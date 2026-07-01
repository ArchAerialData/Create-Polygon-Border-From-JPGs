from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from pyproj import Transformer
from shapely.affinity import rotate
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box
from shapely.ops import transform as transform_geometry
from shapely.validation import make_valid

from geometry_hardening import densify_projected_geometry, fill_polygon_interiors


ACRES_PER_SQUARE_METER = 0.000247105381467
AUTO_SPLIT_PRIMARY_STEP_DEG = 15.0
AUTO_SPLIT_FALLBACK_STEP_DEG = 5.0
OVERLAP_DISCONNECTED_SLIVER_AREA_RATIO = 0.001


class NaturalSplitError(ValueError):
    """Raised when a clean same-direction section split cannot be produced."""


@dataclass(frozen=True)
class NaturalSection:
    index: int
    total: int
    display_name: str
    base_area_acres: float
    polygon_projected: Polygon
    polygon_wgs84: Polygon


@dataclass(frozen=True)
class NaturalSplitDiagnostics:
    selected_split_direction_deg: float
    section_count: int
    area_min_acres: float
    area_max_acres: float
    area_average_acres: float
    area_variance_pct: float
    split_strategy: str


@dataclass(frozen=True)
class _NaturalSplitCandidate:
    direction: float
    center: tuple[float, float]
    base_parts: list[Polygon]
    output_parts: list[Polygon]
    area_variance_ratio: float


def build_natural_sections(
    parent_polygon: Polygon,
    section_count: int,
    overlap_m: float,
    shape_label: str,
    to_wgs84: Transformer,
    *,
    split_direction_deg: float | None = None,
    axis_hint_deg: float | None = None,
    max_area_variance_ratio: float = 0.20,
) -> tuple[list[NaturalSection], NaturalSplitDiagnostics]:
    if section_count < 1:
        raise NaturalSplitError("Section count must be at least 1.")
    if overlap_m < 0:
        raise NaturalSplitError("Section overlap must be 0 or greater.")
    if parent_polygon.is_empty or parent_polygon.area <= 0:
        raise NaturalSplitError("Parent polygon is empty.")

    candidate = _select_split_candidate(
        parent_polygon,
        section_count,
        overlap_m,
        split_direction_deg,
        axis_hint_deg,
        max_area_variance_ratio,
    )
    direction = candidate.direction

    sections: list[NaturalSection] = []
    for index, (base_part, output_part) in enumerate(
        zip(candidate.base_parts, candidate.output_parts),
        start=1,
    ):
        projected = _strict_single_polygon(
            rotate(output_part, direction, origin=candidate.center, use_radians=False),
            "Natural split produced a disconnected section after rotation.",
        )
        projected = _strict_single_polygon(
            densify_projected_geometry(projected),
            "Natural split section could not be densified.",
        )
        polygon_wgs84 = transform_geometry(
            lambda x, y, z=None: to_wgs84.transform(x, y),
            projected,
        )
        polygon_wgs84 = _strict_single_polygon(
            fill_polygon_interiors(polygon_wgs84),
            "Natural split section could not be transformed to WGS84.",
        )
        sections.append(
            NaturalSection(
                index=index,
                total=section_count,
                display_name=f"{shape_label} ({index} of {section_count})",
                base_area_acres=base_part.area * ACRES_PER_SQUARE_METER,
                polygon_projected=projected,
                polygon_wgs84=polygon_wgs84,
            )
        )

    base_area_acres = [section.base_area_acres for section in sections]
    diagnostics = NaturalSplitDiagnostics(
        selected_split_direction_deg=direction,
        section_count=section_count,
        area_min_acres=min(base_area_acres),
        area_max_acres=max(base_area_acres),
        area_average_acres=sum(base_area_acres) / len(base_area_acres),
        area_variance_pct=candidate.area_variance_ratio * 100.0,
        split_strategy=(
            f"Natural same-direction ({section_count} sections, "
            f"{direction:.1f} deg split boundaries)"
        ),
    )
    return sections, diagnostics


def _select_split_candidate(
    parent_polygon: Polygon,
    section_count: int,
    overlap_m: float,
    split_direction_deg: float | None,
    axis_hint_deg: float | None,
    max_area_variance_ratio: float,
) -> _NaturalSplitCandidate:
    if split_direction_deg is not None:
        return _build_natural_split_candidate(
            parent_polygon,
            section_count,
            overlap_m,
            split_direction_deg % 180.0,
            max_area_variance_ratio,
        )

    errors: list[str] = []
    for directions in _auto_split_direction_groups(parent_polygon, axis_hint_deg):
        candidates: list[_NaturalSplitCandidate] = []
        for direction in directions:
            try:
                candidates.append(
                    _build_natural_split_candidate(
                        parent_polygon,
                        section_count,
                        overlap_m,
                        direction,
                        max_area_variance_ratio,
                    )
                )
            except NaturalSplitError as exc:
                errors.append(str(exc))
        if candidates:
            return min(candidates, key=_auto_split_candidate_score)

    detail = f" Last failure: {errors[-1]}" if errors else ""
    raise NaturalSplitError(
        "Auto split could not find a connected section direction. "
        "Try a custom split direction or fewer shapes."
        f"{detail}"
    )


def _build_natural_split_candidate(
    parent_polygon: Polygon,
    section_count: int,
    overlap_m: float,
    direction: float,
    max_area_variance_ratio: float,
) -> _NaturalSplitCandidate:
    center = (parent_polygon.centroid.x, parent_polygon.centroid.y)
    rotated_parent = _strict_single_polygon(
        rotate(parent_polygon, -direction, origin=center, use_radians=False),
        "Parent polygon could not be prepared for natural sectioning.",
    )
    minx, miny, maxx, maxy = rotated_parent.bounds
    if math.isclose(miny, maxy):
        raise NaturalSplitError("Parent polygon is too narrow to split.")

    cut_values = _equal_area_cut_values(rotated_parent, section_count, miny, maxy)
    margin = max(maxx - minx, maxy - miny) * 2.0 + max(overlap_m, 1.0)
    base_parts: list[Polygon] = []
    output_parts: list[Polygon] = []
    half_overlap = overlap_m / 2.0

    for index in range(section_count):
        base_min_y = cut_values[index]
        base_max_y = cut_values[index + 1]
        base_part = _slice_rotated_polygon(
            rotated_parent,
            minx - margin,
            maxx + margin,
            base_min_y,
            base_max_y,
            "Natural split produced a disconnected base section.",
        )
        expanded_min_y = miny if index == 0 else base_min_y - half_overlap
        expanded_max_y = maxy if index == section_count - 1 else base_max_y + half_overlap
        output_part = _slice_rotated_polygon(
            rotated_parent,
            minx - margin,
            maxx + margin,
            expanded_min_y,
            expanded_max_y,
            "Natural split overlap produced a disconnected section.",
            discard_minor_disconnected_parts=True,
        )
        base_parts.append(base_part)
        output_parts.append(output_part)

    area_average = rotated_parent.area / section_count
    if area_average <= 0:
        raise NaturalSplitError("Natural split produced zero-area sections.")
    area_variance_ratio = max(
        abs((base_part.area - area_average) / area_average) for base_part in base_parts
    )
    if area_variance_ratio > max_area_variance_ratio + 1e-6:
        raise NaturalSplitError(
            "Natural split could not keep section areas within "
            f"{max_area_variance_ratio:.0%} of average."
        )

    return _NaturalSplitCandidate(
        direction=direction,
        center=center,
        base_parts=base_parts,
        output_parts=output_parts,
        area_variance_ratio=area_variance_ratio,
    )


def _slice_rotated_polygon(
    rotated_parent: Polygon,
    minx: float,
    maxx: float,
    miny: float,
    maxy: float,
    error_message: str,
    *,
    discard_minor_disconnected_parts: bool = False,
) -> Polygon:
    if maxy <= miny:
        raise NaturalSplitError(error_message)
    max_discarded_area_ratio = (
        OVERLAP_DISCONNECTED_SLIVER_AREA_RATIO
        if discard_minor_disconnected_parts
        else 0.0
    )
    return _strict_single_polygon(
        rotated_parent.intersection(box(minx, miny, maxx, maxy)),
        error_message,
        max_discarded_area_ratio=max_discarded_area_ratio,
    )


def _equal_area_cut_values(
    polygon: Polygon,
    section_count: int,
    miny: float,
    maxy: float,
) -> list[float]:
    values = [miny]
    total_area = polygon.area
    minx, _miny, maxx, _maxy = polygon.bounds
    margin = max(maxx - minx, maxy - miny) * 2.0
    for index in range(1, section_count):
        target_area = total_area * (index / section_count)
        low = values[-1]
        high = maxy
        for _ in range(56):
            midpoint = (low + high) / 2.0
            candidate_area = polygon.intersection(
                box(minx - margin, miny - margin, maxx + margin, midpoint)
            ).area
            if candidate_area < target_area:
                low = midpoint
            else:
                high = midpoint
        values.append((low + high) / 2.0)
    values.append(maxy)
    return values


def _auto_split_direction_groups(
    parent_polygon: Polygon,
    axis_hint_deg: float | None,
) -> list[list[float]]:
    dominant_direction = _dominant_polygon_orientation_deg(parent_polygon)
    seed_directions: list[float] = [dominant_direction, dominant_direction + 90.0]
    if axis_hint_deg is not None:
        seed_directions.extend([axis_hint_deg, axis_hint_deg + 90.0])

    primary_grid = _degree_range(AUTO_SPLIT_PRIMARY_STEP_DEG)
    fallback_grid = _degree_range(AUTO_SPLIT_FALLBACK_STEP_DEG)
    primary = _unique_normalized_directions([*seed_directions, *primary_grid])
    fallback = _unique_normalized_directions(fallback_grid)
    return [primary, fallback]


def _degree_range(step: float) -> list[float]:
    if step <= 0:
        raise ValueError("Direction step must be greater than zero.")
    values: list[float] = []
    value = 0.0
    while value < 180.0:
        values.append(value)
        value += step
    return values


def _unique_normalized_directions(values: list[float]) -> list[float]:
    directions: list[float] = []
    seen: set[float] = set()
    for value in values:
        normalized = value % 180.0
        key = round(normalized, 6)
        if key in seen:
            continue
        seen.add(key)
        directions.append(normalized)
    return directions


def _auto_split_candidate_score(candidate: _NaturalSplitCandidate) -> tuple[float, float]:
    return (
        round(candidate.area_variance_ratio, 6),
        sum(_polygon_compactness_score(part) for part in candidate.output_parts),
    )


def _polygon_compactness_score(polygon: Polygon) -> float:
    if polygon.area <= 0:
        return math.inf
    return polygon.length / math.sqrt(polygon.area)


def _dominant_polygon_orientation_deg(polygon: Polygon) -> float:
    coords = np.array(polygon.exterior.coords[:-1], dtype=float)
    if len(coords) < 2:
        return 0.0
    centered = coords - coords.mean(axis=0)
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    return math.degrees(math.atan2(vh[0][1], vh[0][0])) % 180.0


def _strict_single_polygon(
    geometry,
    message: str,
    *,
    max_discarded_area_ratio: float = 0.0,
) -> Polygon:
    if geometry.is_empty:
        raise NaturalSplitError(message)
    if not geometry.is_valid:
        geometry = make_valid(geometry)
    geometry = fill_polygon_interiors(geometry)
    if isinstance(geometry, Polygon) and geometry.area > 0:
        return geometry
    if isinstance(geometry, MultiPolygon):
        polygons = [part for part in geometry.geoms if not part.is_empty and part.area > 0]
        if len(polygons) == 1:
            return polygons[0]
        dominant = _dominant_polygon_if_discarded_parts_are_minor(
            polygons,
            max_discarded_area_ratio,
        )
        if dominant is not None:
            return dominant
        raise NaturalSplitError(message)
    if isinstance(geometry, GeometryCollection):
        polygons = [
            part
            for part in geometry.geoms
            if isinstance(part, Polygon) and not part.is_empty and part.area > 0
        ]
        if len(polygons) == 1:
            return polygons[0]
        dominant = _dominant_polygon_if_discarded_parts_are_minor(
            polygons,
            max_discarded_area_ratio,
        )
        if dominant is not None:
            return dominant
    raise NaturalSplitError(message)


def _dominant_polygon_if_discarded_parts_are_minor(
    polygons: list[Polygon],
    max_discarded_area_ratio: float,
) -> Polygon | None:
    if max_discarded_area_ratio <= 0 or len(polygons) < 2:
        return None
    ordered = sorted(polygons, key=lambda polygon: polygon.area, reverse=True)
    total_area = sum(polygon.area for polygon in ordered)
    if total_area <= 0:
        return None
    discarded_area = total_area - ordered[0].area
    if discarded_area / total_area <= max_discarded_area_ratio:
        return ordered[0]
    return None
