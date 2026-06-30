from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
from scipy.spatial import cKDTree


PATTERN_BOUNDARY_TRACE = "boundary_trace"
PATTERN_LAWNMOWER = "lawnmower"
PATTERN_MIXED = "mixed"
PATTERN_SCATTER_UNKNOWN = "scatter_unknown"

ORDER_EXIF_DATETIME = "exif_datetime"
ORDER_FILENAME = "filename"
ORDER_INPUT_SORT = "input_sort"


@dataclass(frozen=True)
class CameraOrder:
    ordered_indices: list[int]
    order_source: str


@dataclass(frozen=True)
class CameraPreflightMetrics:
    point_count: int
    median_nearest_spacing_m: float
    median_ordered_spacing_m: float
    max_ordered_gap_m: float
    gap_threshold_m: float
    dominant_heading_deg: float
    dominant_heading_ratio: float
    heading_change_median_deg: float
    turn_ratio: float
    row_count: int
    row_spacing_m: float
    row_spacing_cv: float
    closure_ratio: float


@dataclass(frozen=True)
class CameraPreflightResult:
    pattern: str
    confidence: float
    order_source: str
    metrics: CameraPreflightMetrics
    section_breaks: list[int]
    warnings: list[str]
    ordered_indices: list[int]


def analyze_camera_preflight(
    gps_points: Sequence[object],
    projected_points: np.ndarray,
) -> CameraPreflightResult:
    points = np.asarray(projected_points, dtype=float)
    if len(gps_points) != len(points):
        raise ValueError("GPS point count must match projected point count.")

    order = determine_camera_order(gps_points)
    ordered = points[order.ordered_indices]
    metrics, section_breaks = compute_preflight_metrics(ordered)
    pattern, confidence, warnings = classify_camera_pattern(metrics, section_breaks)

    if order.order_source != ORDER_EXIF_DATETIME:
        warnings.append(f"Capture order uses {order.order_source} fallback.")

    return CameraPreflightResult(
        pattern=pattern,
        confidence=confidence,
        order_source=order.order_source,
        metrics=metrics,
        section_breaks=section_breaks,
        warnings=warnings,
        ordered_indices=order.ordered_indices,
    )


def determine_camera_order(gps_points: Sequence[object]) -> CameraOrder:
    indexed = list(enumerate(gps_points))
    capture_times = [getattr(point, "capture_time", None) for point in gps_points]
    if capture_times and all(capture_time is not None for capture_time in capture_times):
        ordered = sorted(
            indexed,
            key=lambda item: (
                getattr(item[1], "capture_time"),
                _path_sort_key(getattr(item[1], "path", Path(str(item[0])))),
                item[0],
            ),
        )
        return CameraOrder([index for index, _point in ordered], ORDER_EXIF_DATETIME)

    if all(hasattr(point, "path") for point in gps_points):
        ordered = sorted(
            indexed,
            key=lambda item: (_path_sort_key(getattr(item[1], "path")), item[0]),
        )
        return CameraOrder([index for index, _point in ordered], ORDER_FILENAME)

    return CameraOrder([index for index, _point in indexed], ORDER_INPUT_SORT)


def compute_preflight_metrics(
    ordered_points: np.ndarray,
) -> tuple[CameraPreflightMetrics, list[int]]:
    point_count = len(ordered_points)
    if point_count < 2:
        metrics = CameraPreflightMetrics(
            point_count=point_count,
            median_nearest_spacing_m=0.0,
            median_ordered_spacing_m=0.0,
            max_ordered_gap_m=0.0,
            gap_threshold_m=0.0,
            dominant_heading_deg=0.0,
            dominant_heading_ratio=0.0,
            heading_change_median_deg=0.0,
            turn_ratio=0.0,
            row_count=0,
            row_spacing_m=0.0,
            row_spacing_cv=0.0,
            closure_ratio=math.inf,
        )
        return metrics, []

    segment_vectors = np.diff(ordered_points, axis=0)
    segment_distances = np.linalg.norm(segment_vectors, axis=1)
    positive_distances = segment_distances[segment_distances > 0]
    median_ordered = _safe_median(positive_distances)
    median_nearest = _median_nearest_neighbor_distance(ordered_points)
    max_gap = float(np.max(segment_distances)) if len(segment_distances) else 0.0
    gap_threshold = max(median_ordered * 4.0, median_nearest * 6.0)
    section_breaks = [
        int(index + 1)
        for index, distance in enumerate(segment_distances)
        if gap_threshold > 0 and distance > gap_threshold
    ]

    headings = _segment_headings(segment_vectors, positive_only=True)
    dominant_heading, dominant_ratio = _dominant_heading(headings)
    heading_changes = _heading_changes(headings)
    heading_change_median = _safe_median(heading_changes)
    turn_ratio = (
        float(np.count_nonzero(heading_changes > 45.0) / len(heading_changes))
        if len(heading_changes)
        else 0.0
    )
    row_count, row_spacing, row_spacing_cv = _estimate_rows(
        ordered_points,
        dominant_heading,
        median_nearest,
    )
    closure_distance = float(np.linalg.norm(ordered_points[-1] - ordered_points[0]))
    closure_base = median_ordered or median_nearest or 1.0
    closure_ratio = closure_distance / closure_base

    metrics = CameraPreflightMetrics(
        point_count=point_count,
        median_nearest_spacing_m=median_nearest,
        median_ordered_spacing_m=median_ordered,
        max_ordered_gap_m=max_gap,
        gap_threshold_m=gap_threshold,
        dominant_heading_deg=dominant_heading,
        dominant_heading_ratio=dominant_ratio,
        heading_change_median_deg=heading_change_median,
        turn_ratio=turn_ratio,
        row_count=row_count,
        row_spacing_m=row_spacing,
        row_spacing_cv=row_spacing_cv,
        closure_ratio=closure_ratio,
    )
    return metrics, section_breaks


def classify_camera_pattern(
    metrics: CameraPreflightMetrics,
    section_breaks: Sequence[int],
) -> tuple[str, float, list[str]]:
    warnings: list[str] = []
    if metrics.point_count < 3:
        return PATTERN_SCATTER_UNKNOWN, 0.0, ["Fewer than 3 camera points."]

    if section_breaks:
        warnings.append(f"Detected {len(section_breaks)} large ordered gap(s).")

    row_regular = metrics.row_count >= 3 and metrics.row_spacing_cv <= 0.75
    if (
        row_regular
        and metrics.dominant_heading_ratio >= 0.58
        and metrics.closure_ratio > 3.0
    ):
        confidence = 0.70
        confidence += min(0.20, (metrics.dominant_heading_ratio - 0.58) * 0.5)
        confidence += 0.05 if metrics.row_spacing_cv <= 0.35 else 0.0
        confidence -= min(0.20, len(section_breaks) * 0.05)
        return PATTERN_LAWNMOWER, _clamp_confidence(confidence), warnings

    if (
        metrics.point_count >= 8
        and metrics.closure_ratio <= 2.5
        and metrics.turn_ratio >= 0.18
        and metrics.dominant_heading_ratio <= 0.70
    ):
        confidence = 0.72
        confidence += min(0.15, metrics.turn_ratio * 0.2)
        confidence -= min(0.20, len(section_breaks) * 0.05)
        return PATTERN_BOUNDARY_TRACE, _clamp_confidence(confidence), warnings

    ordered_quality_ratio = (
        metrics.median_ordered_spacing_m / metrics.median_nearest_spacing_m
        if metrics.median_nearest_spacing_m > 0
        else math.inf
    )
    if (
        not section_breaks
        and metrics.point_count >= 5
        and ordered_quality_ratio <= 1.8
    ):
        confidence = 0.68
        if metrics.turn_ratio >= 0.10:
            confidence += 0.07
        return PATTERN_BOUNDARY_TRACE, _clamp_confidence(confidence), warnings

    if section_breaks:
        warnings.append("Large gaps suggest multiple capture sections.")
        return PATTERN_MIXED, 0.55, warnings

    warnings.append("Camera pattern is ambiguous; conservative fallback is recommended.")
    return PATTERN_SCATTER_UNKNOWN, 0.30, warnings


def _path_sort_key(path: Path) -> str:
    return str(Path(path)).lower()


def _safe_median(values: np.ndarray) -> float:
    if len(values) == 0:
        return 0.0
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return 0.0
    return float(np.median(values))


def _median_nearest_neighbor_distance(points: np.ndarray) -> float:
    if len(points) < 2:
        return 0.0
    distances, _ = cKDTree(points).query(points, k=2)
    nearest = distances[:, 1]
    nearest = nearest[np.isfinite(nearest) & (nearest > 0)]
    return _safe_median(nearest)


def _segment_headings(vectors: np.ndarray, *, positive_only: bool) -> np.ndarray:
    if len(vectors) == 0:
        return np.array([], dtype=float)
    distances = np.linalg.norm(vectors, axis=1)
    if positive_only:
        vectors = vectors[distances > 0]
    if len(vectors) == 0:
        return np.array([], dtype=float)
    headings = np.degrees(np.arctan2(vectors[:, 1], vectors[:, 0]))
    return headings % 180.0


def _dominant_heading(headings: np.ndarray) -> tuple[float, float]:
    if len(headings) == 0:
        return 0.0, 0.0
    bins = np.arange(0.0, 181.0, 10.0)
    counts, edges = np.histogram(headings, bins=bins)
    best_index = int(np.argmax(counts))
    dominant = float((edges[best_index] + edges[best_index + 1]) / 2.0)
    ratio = float(counts[best_index] / len(headings))
    return dominant, ratio


def _heading_changes(headings: np.ndarray) -> np.ndarray:
    if len(headings) < 2:
        return np.array([], dtype=float)
    diffs = np.abs(np.diff(headings))
    return np.minimum(diffs, 180.0 - diffs)


def _estimate_rows(
    points: np.ndarray,
    dominant_heading_deg: float,
    median_nearest_m: float,
) -> tuple[int, float, float]:
    if len(points) < 3:
        return 0, 0.0, 0.0

    theta = math.radians(dominant_heading_deg + 90.0)
    normal = np.array([math.cos(theta), math.sin(theta)])
    offsets = np.sort(points @ normal)
    span = float(offsets[-1] - offsets[0])
    if span <= 0:
        return 1, 0.0, 0.0

    tolerance = max(median_nearest_m * 0.6, span * 0.03, 1.0)
    rows: list[list[float]] = []
    for value in offsets:
        if not rows or abs(value - np.mean(rows[-1])) > tolerance:
            rows.append([float(value)])
        else:
            rows[-1].append(float(value))

    centers = np.array([float(np.mean(row)) for row in rows], dtype=float)
    if len(centers) < 2:
        return len(centers), 0.0, 0.0
    spacings = np.diff(centers)
    median_spacing = _safe_median(spacings)
    spacing_cv = (
        float(np.std(spacings) / median_spacing)
        if median_spacing > 0 and len(spacings) > 1
        else 0.0
    )
    return len(centers), median_spacing, spacing_cv


def _clamp_confidence(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
