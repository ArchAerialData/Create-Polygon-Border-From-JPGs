from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from shapely import concave_hull
from shapely.geometry import LineString, MultiPoint, MultiPolygon, Polygon
from shapely.ops import unary_union

from camera_preflight import (
    PATTERN_BOUNDARY_TRACE,
    PATTERN_LAWNMOWER,
    PATTERN_MIXED,
    CameraPreflightResult,
)
from geometry_hardening import buffer_projected_geometry, clean_geometry


OUTLINE_MODE_AUTO = "auto"
OUTLINE_MODE_CONCAVE = "concave_hull"
OUTLINE_MODE_ROUTE_AWARE = "route_aware"
OUTLINE_MODE_LAWNMOWER = "lawnmower_envelope"
OUTLINE_MODES = {
    OUTLINE_MODE_AUTO,
    OUTLINE_MODE_CONCAVE,
    OUTLINE_MODE_ROUTE_AWARE,
    OUTLINE_MODE_LAWNMOWER,
}

STRATEGY_CONCAVE = "concave_hull"
STRATEGY_ROUTE_AWARE = "route_aware"
STRATEGY_LAWNMOWER = "lawnmower_envelope"
STRATEGY_MIXED = "mixed_sections"

MIN_AREA_RATIO = 0.05
MAX_AREA_RATIO = 5.0


@dataclass
class OutlineCandidate:
    strategy: str
    polygon_projected: object
    confidence: float
    score: float
    accepted: bool = False
    rejection_reasons: list[str] | None = None
    diagnostics: dict[str, float | int | str | bool] | None = None

    def __post_init__(self) -> None:
        if self.rejection_reasons is None:
            self.rejection_reasons = []
        if self.diagnostics is None:
            self.diagnostics = {}


@dataclass(frozen=True)
class OutlineSelection:
    selected: OutlineCandidate
    fallback: OutlineCandidate
    candidates: list[OutlineCandidate]
    fallback_reason: str


def select_outline(
    *,
    mode: str,
    projected_points: np.ndarray,
    preflight: CameraPreflightResult,
    concave_ratio: float,
    section_count: int,
) -> OutlineSelection:
    point_geometry = MultiPoint(np.asarray(projected_points, dtype=float))
    fallback = build_concave_candidate(point_geometry, concave_ratio)
    evaluate_candidate(fallback, fallback.polygon_projected, point_geometry, section_count)
    fallback.accepted = True

    if mode == OUTLINE_MODE_CONCAVE:
        return OutlineSelection(fallback, fallback, [fallback], "")

    candidates = [fallback]
    ordered_points = np.asarray(projected_points, dtype=float)[preflight.ordered_indices]

    if mode in {OUTLINE_MODE_AUTO, OUTLINE_MODE_ROUTE_AWARE}:
        route = build_route_aware_candidate(ordered_points, preflight)
        evaluate_candidate(route, fallback.polygon_projected, point_geometry, section_count)
        candidates.append(route)

    if mode in {OUTLINE_MODE_AUTO, OUTLINE_MODE_LAWNMOWER}:
        lawnmower = build_lawnmower_candidate(projected_points, preflight)
        evaluate_candidate(lawnmower, fallback.polygon_projected, point_geometry, section_count)
        candidates.append(lawnmower)

    if mode == OUTLINE_MODE_AUTO and preflight.pattern == PATTERN_MIXED:
        mixed = build_mixed_candidate(ordered_points, preflight)
        evaluate_candidate(mixed, fallback.polygon_projected, point_geometry, section_count)
        candidates.append(mixed)

    non_fallback = [
        candidate
        for candidate in candidates
        if candidate.strategy != STRATEGY_CONCAVE and candidate.accepted
    ]
    if mode == OUTLINE_MODE_AUTO:
        high_confidence = [
            candidate for candidate in non_fallback if candidate.confidence >= 0.65
        ]
        if high_confidence:
            selected = max(high_confidence, key=lambda candidate: candidate.score)
            return OutlineSelection(selected, fallback, candidates, "")
        return OutlineSelection(
            fallback,
            fallback,
            candidates,
            _fallback_reason(candidates),
        )

    explicit = candidates[-1]
    if explicit.accepted:
        return OutlineSelection(explicit, fallback, candidates, "")
    return OutlineSelection(
        fallback,
        fallback,
        candidates,
        f"{explicit.strategy} rejected: {', '.join(explicit.rejection_reasons)}",
    )


def build_concave_candidate(point_geometry: MultiPoint, concave_ratio: float) -> OutlineCandidate:
    polygon = _coerce_polygon(
        concave_hull(point_geometry, ratio=concave_ratio, allow_holes=False),
        point_geometry,
    )
    return OutlineCandidate(
        strategy=STRATEGY_CONCAVE,
        polygon_projected=polygon,
        confidence=1.0,
        score=10.0,
        diagnostics={"area_m2": float(polygon.area)},
    )


def build_route_aware_candidate(
    ordered_points: np.ndarray,
    preflight: CameraPreflightResult,
) -> OutlineCandidate:
    diagnostics = {
        "preflight_pattern": preflight.pattern,
        "preflight_confidence": float(preflight.confidence),
        "median_ordered_spacing_m": preflight.metrics.median_ordered_spacing_m,
    }
    rejections: list[str] = []
    if preflight.pattern != PATTERN_BOUNDARY_TRACE:
        rejections.append(f"preflight pattern is {preflight.pattern}")
    if preflight.confidence < 0.65:
        rejections.append("preflight confidence is below route threshold")
    if (
        preflight.metrics.turn_ratio > 0.45
        and preflight.metrics.heading_change_median_deg > 30.0
    ):
        rejections.append("ordered route has excessive heading alternation")
    if len(ordered_points) < 3:
        rejections.append("fewer than 3 ordered points")

    if rejections:
        polygon: object = Polygon()
    else:
        width_m = max(
            preflight.metrics.median_nearest_spacing_m,
            preflight.metrics.median_ordered_spacing_m * 0.75,
            1.0,
        )
        diagnostics["route_buffer_m"] = float(width_m)
        line = LineString(ordered_points)
        polygon = buffer_projected_geometry(line, width_m)

    return OutlineCandidate(
        strategy=STRATEGY_ROUTE_AWARE,
        polygon_projected=polygon,
        confidence=preflight.confidence,
        score=70.0 + preflight.confidence * 20.0,
        rejection_reasons=rejections,
        diagnostics=diagnostics,
    )


def build_lawnmower_candidate(
    projected_points: np.ndarray,
    preflight: CameraPreflightResult,
) -> OutlineCandidate:
    diagnostics = {
        "preflight_pattern": preflight.pattern,
        "preflight_confidence": float(preflight.confidence),
        "row_count": preflight.metrics.row_count,
        "row_spacing_cv": preflight.metrics.row_spacing_cv,
    }
    rejections: list[str] = []
    if preflight.pattern != PATTERN_LAWNMOWER:
        rejections.append(f"preflight pattern is {preflight.pattern}")
    if preflight.confidence < 0.65:
        rejections.append("preflight confidence is below lawnmower threshold")
    if preflight.metrics.row_count < 3:
        rejections.append("fewer than 3 detected rows")

    if rejections:
        polygon: object = Polygon()
    else:
        point_geometry = MultiPoint(np.asarray(projected_points, dtype=float))
        polygon = _coerce_polygon(point_geometry.convex_hull, point_geometry)
        diagnostics["envelope_padding_m"] = 0.0

    return OutlineCandidate(
        strategy=STRATEGY_LAWNMOWER,
        polygon_projected=polygon,
        confidence=preflight.confidence,
        score=75.0 + preflight.confidence * 20.0,
        rejection_reasons=rejections,
        diagnostics=diagnostics,
    )


def build_mixed_candidate(
    ordered_points: np.ndarray,
    preflight: CameraPreflightResult,
) -> OutlineCandidate:
    diagnostics = {
        "preflight_pattern": preflight.pattern,
        "gap_count": len(preflight.section_breaks),
    }
    if not preflight.section_breaks:
        return OutlineCandidate(
            strategy=STRATEGY_MIXED,
            polygon_projected=Polygon(),
            confidence=0.0,
            score=0.0,
            rejection_reasons=["no section breaks were detected"],
            diagnostics=diagnostics,
        )

    boundaries = [0, *preflight.section_breaks, len(ordered_points)]
    pieces = []
    width_m = max(preflight.metrics.median_nearest_spacing_m, 1.0)
    for start, stop in zip(boundaries, boundaries[1:]):
        segment = ordered_points[start:stop]
        if len(segment) < 2:
            continue
        pieces.append(buffer_projected_geometry(LineString(segment), width_m))

    if not pieces:
        polygon: object = Polygon()
        rejections = ["no usable mixed sections were created"]
    else:
        polygon = clean_geometry(unary_union(pieces))
        rejections = []

    return OutlineCandidate(
        strategy=STRATEGY_MIXED,
        polygon_projected=polygon,
        confidence=min(0.65, preflight.confidence),
        score=60.0 + preflight.confidence * 10.0,
        rejection_reasons=rejections,
        diagnostics=diagnostics,
    )


def evaluate_candidate(
    candidate: OutlineCandidate,
    fallback_polygon,
    required_points: MultiPoint,
    section_count: int,
) -> OutlineCandidate:
    reasons = list(candidate.rejection_reasons or [])
    geometry = clean_geometry(candidate.polygon_projected)

    if geometry.is_empty:
        reasons.append("geometry is empty")
    if not geometry.is_valid:
        reasons.append("geometry is invalid")
    if isinstance(geometry, MultiPolygon):
        reasons.append("geometry is disconnected")

    polygon = _coerce_polygon(geometry, required_points)
    if polygon is None or polygon.is_empty:
        reasons.append("geometry is not polygonal")
    else:
        candidate.polygon_projected = polygon
        if polygon.interiors:
            reasons.append("geometry contains holes")
        if not _covers_required_points(polygon, required_points):
            reasons.append("required camera points are not covered")
        area_ratio = _area_ratio(polygon, fallback_polygon)
        candidate.diagnostics = candidate.diagnostics or {}
        candidate.diagnostics["area_ratio_to_fallback"] = float(area_ratio)
        if area_ratio < MIN_AREA_RATIO or area_ratio > MAX_AREA_RATIO:
            reasons.append("area ratio is implausible")
        if section_count > 1 and not isinstance(geometry, Polygon):
            reasons.append("geometry is not section-compatible")

    candidate.rejection_reasons = _dedupe_reasons(reasons)
    candidate.accepted = len(candidate.rejection_reasons) == 0
    if candidate.accepted:
        candidate.score += _score_area_ratio(
            float(candidate.diagnostics.get("area_ratio_to_fallback", 1.0))
        )
    return candidate


def summarize_candidates(candidates: Sequence[OutlineCandidate]) -> str:
    parts = []
    for candidate in candidates:
        status = "accepted" if candidate.accepted else "rejected"
        if candidate.rejection_reasons:
            status = f"{status} ({', '.join(candidate.rejection_reasons)})"
        parts.append(f"{candidate.strategy}: {status}")
    return "; ".join(parts)


def _coerce_polygon(geometry, fallback_points: MultiPoint | None = None) -> Polygon | None:
    if geometry is None or geometry.is_empty:
        if fallback_points is not None and not fallback_points.is_empty:
            convex = fallback_points.convex_hull
            return convex if isinstance(convex, Polygon) else None
        return None

    geometry = clean_geometry(geometry)
    if isinstance(geometry, Polygon):
        return geometry
    if isinstance(geometry, MultiPolygon):
        merged = unary_union(geometry)
        if isinstance(merged, Polygon):
            return merged
        convex = merged.convex_hull
        return convex if isinstance(convex, Polygon) else None
    convex = geometry.convex_hull
    return convex if isinstance(convex, Polygon) else None


def _covers_required_points(polygon: Polygon, points: MultiPoint) -> bool:
    return polygon.buffer(1e-6).covers(points)


def _area_ratio(polygon: Polygon, fallback_polygon) -> float:
    fallback_area = getattr(fallback_polygon, "area", 0.0)
    if fallback_area <= 0:
        return math.inf
    return float(polygon.area / fallback_area)


def _score_area_ratio(area_ratio: float) -> float:
    if not math.isfinite(area_ratio):
        return -100.0
    return max(-25.0, -abs(math.log(max(area_ratio, 1e-9))) * 5.0)


def _fallback_reason(candidates: Sequence[OutlineCandidate]) -> str:
    rejected = [
        candidate
        for candidate in candidates
        if candidate.strategy != STRATEGY_CONCAVE and not candidate.accepted
    ]
    if not rejected:
        return "Auto did not find a higher-confidence candidate than concave hull."
    reason_text = "; ".join(
        f"{candidate.strategy}: {', '.join(candidate.rejection_reasons)}"
        for candidate in rejected
    )
    return f"Auto fell back to concave hull because {reason_text}."


def _dedupe_reasons(reasons: Sequence[str]) -> list[str]:
    result: list[str] = []
    for reason in reasons:
        if reason and reason not in result:
            result.append(reason)
    return result
