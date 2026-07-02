from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from pyproj import CRS, Transformer
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Polygon
from shapely.ops import transform as transform_geometry
from shapely.ops import unary_union
from shapely.validation import make_valid

from geometry_hardening import (
    buffer_projected_geometry,
    densify_projected_geometry,
    fill_polygon_interiors,
)


FEET_PER_METER = 3.280839895
METERS_PER_FOOT = 0.3048
POLYLINE_REGULARITY_MAX_PERIMETER_RATIO = 1.55
POLYLINE_AUTO_BUFFER_MAX_FT = 500
POLYLINE_AUTO_BUFFER_EXTRA_SEARCH_FT = 200
POLYLINE_AUTO_BUFFER_FALLBACK_EXTRA_FT = 40
POLYLINE_AUTO_BUFFER_HARD_MAX_FT = 2000
POLYLINE_AUTO_BUFFER_MIN_MATERIAL_IMPROVEMENT = 0.10


class PolylineBoundaryError(ValueError):
    """Raised when source linework cannot produce one clean boundary polygon."""


@dataclass(frozen=True)
class PolylineBoundaryResult:
    base_polygon_projected: Polygon
    final_polygon_projected: Polygon
    final_polygon_wgs84: Polygon
    epsg: int
    crs_name: str
    source_line_count: int
    source_point_count: int
    source_axis_hint_deg: float | None
    diagnostics: dict[str, float | int | str]


@dataclass(frozen=True)
class _ProjectedPolylineInput:
    projected_linework: LineString | MultiLineString
    projected_lines: tuple[LineString, ...]
    to_wgs84: Transformer
    epsg: int
    crs_name: str
    source_line_count: int
    source_point_count: int
    source_axis_hint_deg: float | None
    projected_length_m: float


@dataclass(frozen=True)
class _PolylineBufferCandidate:
    buffer_ft: float
    polygon_projected: Polygon
    ignored_interiors: int
    regularity_ratio: float


def build_polyline_boundary(
    lines_wgs84: Sequence[LineString],
    buffer_ft: float,
) -> PolylineBoundaryResult:
    if buffer_ft <= 0:
        raise PolylineBoundaryError("LineString input requires a buffer greater than 0 ft.")
    if not lines_wgs84:
        raise PolylineBoundaryError("LineString input does not contain any usable lines.")

    projected_input = _project_linework(lines_wgs84)
    candidate = _build_buffer_candidate(projected_input, buffer_ft)
    return _build_result_from_candidate(projected_input, candidate)


def build_polyline_boundary_with_recommended_buffer(
    lines_wgs84: Sequence[LineString],
    requested_buffer_ft: float,
) -> PolylineBoundaryResult:
    if not lines_wgs84:
        raise PolylineBoundaryError("LineString input does not contain any usable lines.")

    projected_input = _project_linework(lines_wgs84)
    requested_buffer_ft = float(requested_buffer_ft)
    search_limit_ft = _auto_buffer_search_limit(requested_buffer_ft)
    candidates_tested = 0
    candidate_cache: dict[float, _PolylineBufferCandidate | None] = {}

    def candidate_for(buffer_ft: float) -> _PolylineBufferCandidate | None:
        nonlocal candidates_tested
        key = round(float(buffer_ft), 6)
        if key not in candidate_cache:
            candidates_tested += 1
            try:
                candidate_cache[key] = _build_buffer_candidate(projected_input, key)
            except PolylineBoundaryError:
                candidate_cache[key] = None
        return candidate_cache[key]

    requested_candidate = (
        candidate_for(requested_buffer_ft) if requested_buffer_ft > 0 else None
    )
    minimum_connected_ft = _find_minimum_connected_buffer_ft(
        candidate_for,
        requested_buffer_ft,
        requested_candidate,
        search_limit_ft,
    )
    minimum_candidate = candidate_for(minimum_connected_ft)
    if minimum_candidate is None:
        raise PolylineBoundaryError(
            "Polyline buffer could not produce one connected polygon during auto-buffer analysis."
        )

    selected_candidate: _PolylineBufferCandidate | None = None
    adjustment_reason = ""
    if requested_candidate is not None and _is_regular_buffer_candidate(requested_candidate):
        selected_candidate = requested_candidate
    else:
        start_ft = minimum_connected_ft
        if requested_buffer_ft > 0:
            start_ft = max(start_ft, math.ceil(requested_buffer_ft))
        selected_candidate = _find_first_regular_buffer_candidate(
            candidate_for,
            int(start_ft),
            int(search_limit_ft),
        )
        if selected_candidate is not None:
            adjustment_reason = _auto_buffer_adjustment_reason(
                requested_buffer_ft,
                requested_candidate,
            )

    if selected_candidate is None:
        fallback_ft = minimum_connected_ft + POLYLINE_AUTO_BUFFER_FALLBACK_EXTRA_FT
        fallback_candidate = (
            candidate_for(float(fallback_ft))
            if fallback_ft <= POLYLINE_AUTO_BUFFER_HARD_MAX_FT
            else None
        )
        if (
            fallback_candidate is not None
            and _materially_improves_regularity(minimum_candidate, fallback_candidate)
        ):
            selected_candidate = fallback_candidate
            adjustment_reason = (
                "No candidate reached the regularity target; using fixed fallback "
                "above the minimum connected buffer."
            )
        else:
            best_candidate = _best_connected_candidate(candidate_cache)
            if best_candidate is None:
                raise PolylineBoundaryError(
                    "Polyline buffer could not produce one connected polygon during auto-buffer analysis."
                )
            raise PolylineBoundaryError(
                "Polyline auto-buffer could not find a regular connected boundary. "
                f"Best tested buffer: {best_candidate.buffer_ft:.0f} ft, "
                f"regularity ratio {best_candidate.regularity_ratio:.3f} "
                f"(target <= {POLYLINE_REGULARITY_MAX_PERIMETER_RATIO:.2f})."
            )

    diagnostics = {
        "requested_buffer_ft": requested_buffer_ft,
        "minimum_connected_buffer_ft": float(minimum_connected_ft),
        "selected_buffer_ft": float(selected_candidate.buffer_ft),
        "regularity_ratio": float(selected_candidate.regularity_ratio),
        "regularity_target": float(POLYLINE_REGULARITY_MAX_PERIMETER_RATIO),
        "candidate_count": int(candidates_tested),
        "adjustment_reason": adjustment_reason,
    }
    return _build_result_from_candidate(
        projected_input,
        selected_candidate,
        extra_diagnostics=diagnostics,
    )


def _project_linework(lines_wgs84: Sequence[LineString]) -> _ProjectedPolylineInput:
    lons, lats = _collect_line_coordinates(lines_wgs84)
    epsg = _detect_utm_epsg(lats, lons)
    crs_projected = CRS.from_epsg(epsg)
    to_projected = Transformer.from_crs(4326, crs_projected, always_xy=True)
    to_wgs84 = Transformer.from_crs(crs_projected, 4326, always_xy=True)

    projected_lines = [
        transform_geometry(lambda x, y, z=None: to_projected.transform(x, y), line)
        for line in lines_wgs84
    ]
    dissolved = unary_union(projected_lines)
    if isinstance(dissolved, (LineString, MultiLineString)):
        projected_linework = dissolved
    else:
        raise PolylineBoundaryError("LineString input did not produce linework after projection.")

    return _ProjectedPolylineInput(
        projected_linework=projected_linework,
        projected_lines=tuple(projected_lines),
        to_wgs84=to_wgs84,
        epsg=epsg,
        crs_name=crs_projected.name,
        source_line_count=len(lines_wgs84),
        source_point_count=len(lons),
        source_axis_hint_deg=_source_axis_hint_deg(projected_lines),
        projected_length_m=float(sum(line.length for line in projected_lines)),
    )


def _build_buffer_candidate(
    projected_input: _ProjectedPolylineInput,
    buffer_ft: float,
) -> _PolylineBufferCandidate:
    if buffer_ft <= 0:
        raise PolylineBoundaryError("LineString input requires a buffer greater than 0 ft.")

    buffered = buffer_projected_geometry(
        projected_input.projected_linework,
        buffer_ft * METERS_PER_FOOT,
    )
    exterior_only = fill_polygon_interiors(buffered)
    base_polygon = _require_single_polygon(
        exterior_only,
        "Polyline buffer produced disconnected polygons. Process disconnected areas separately.",
    )
    base_polygon = _require_single_polygon(fill_polygon_interiors(make_valid(base_polygon)))
    return _PolylineBufferCandidate(
        buffer_ft=float(buffer_ft),
        polygon_projected=base_polygon,
        ignored_interiors=_count_interiors(buffered),
        regularity_ratio=_regularity_ratio(base_polygon),
    )


def _build_result_from_candidate(
    projected_input: _ProjectedPolylineInput,
    candidate: _PolylineBufferCandidate,
    *,
    extra_diagnostics: dict[str, float | int | str] | None = None,
) -> PolylineBoundaryResult:
    final_projected = _require_single_polygon(
        densify_projected_geometry(candidate.polygon_projected),
        "Polyline buffer could not be densified into one polygon.",
    )
    final_wgs84 = transform_geometry(
        lambda x, y, z=None: projected_input.to_wgs84.transform(x, y),
        final_projected,
    )
    final_wgs84 = _require_single_polygon(fill_polygon_interiors(final_wgs84))

    diagnostics: dict[str, float | int | str] = {
        "buffer_ft": float(candidate.buffer_ft),
        "buffer_m": float(candidate.buffer_ft * METERS_PER_FOOT),
        "source_line_count": projected_input.source_line_count,
        "source_point_count": projected_input.source_point_count,
        "ignored_interior_ring_count": candidate.ignored_interiors,
        "projected_area_sq_m": float(final_projected.area),
        "projected_length_m": projected_input.projected_length_m,
        "regularity_ratio": float(candidate.regularity_ratio),
    }
    if extra_diagnostics:
        diagnostics.update(extra_diagnostics)
    return PolylineBoundaryResult(
        base_polygon_projected=candidate.polygon_projected,
        final_polygon_projected=final_projected,
        final_polygon_wgs84=final_wgs84,
        epsg=projected_input.epsg,
        crs_name=projected_input.crs_name,
        source_line_count=projected_input.source_line_count,
        source_point_count=projected_input.source_point_count,
        source_axis_hint_deg=projected_input.source_axis_hint_deg,
        diagnostics=diagnostics,
    )


def _auto_buffer_search_limit(requested_buffer_ft: float) -> int:
    requested_limit = math.ceil(max(requested_buffer_ft, 0.0)) + POLYLINE_AUTO_BUFFER_EXTRA_SEARCH_FT
    return int(
        min(
            POLYLINE_AUTO_BUFFER_HARD_MAX_FT,
            max(POLYLINE_AUTO_BUFFER_MAX_FT, requested_limit),
        )
    )


def _find_minimum_connected_buffer_ft(
    candidate_for,
    requested_buffer_ft: float,
    requested_candidate: _PolylineBufferCandidate | None,
    search_limit_ft: int,
) -> int:
    if requested_candidate is not None:
        high = max(1, math.ceil(requested_buffer_ft))
    else:
        high = max(1, math.ceil(max(requested_buffer_ft, 1.0)))
        while high <= search_limit_ft and candidate_for(float(high)) is None:
            high = max(high + 1, high * 2)
        if high > search_limit_ft:
            high = search_limit_ft

    if candidate_for(float(high)) is None:
        raise PolylineBoundaryError(
            "Polyline auto-buffer could not find one connected polygon within "
            f"{search_limit_ft} ft."
        )

    low = 1
    while low < high:
        mid = (low + high) // 2
        if candidate_for(float(mid)) is None:
            low = mid + 1
        else:
            high = mid
    return low


def _find_first_regular_buffer_candidate(
    candidate_for,
    start_ft: int,
    search_limit_ft: int,
) -> _PolylineBufferCandidate | None:
    if start_ft > search_limit_ft:
        return None

    upper_candidate = candidate_for(float(search_limit_ft))
    if upper_candidate is None or not _is_regular_buffer_candidate(upper_candidate):
        return None

    low = start_ft
    high = search_limit_ft
    selected_candidate = upper_candidate
    while low <= high:
        mid = (low + high) // 2
        candidate = candidate_for(float(mid))
        if candidate is not None and _is_regular_buffer_candidate(candidate):
            selected_candidate = candidate
            high = mid - 1
        else:
            low = mid + 1
    return selected_candidate


def _regularity_ratio(polygon: Polygon) -> float:
    hull_length = float(polygon.convex_hull.length)
    if hull_length <= 0:
        return math.inf
    return float(polygon.exterior.length) / hull_length


def _is_regular_buffer_candidate(candidate: _PolylineBufferCandidate) -> bool:
    return candidate.regularity_ratio <= POLYLINE_REGULARITY_MAX_PERIMETER_RATIO


def _auto_buffer_adjustment_reason(
    requested_buffer_ft: float,
    requested_candidate: _PolylineBufferCandidate | None,
) -> str:
    if requested_buffer_ft <= 0:
        return "Requested buffer was zero; auto-selected a connected regular buffer."
    if requested_candidate is None:
        return "Requested buffer produced disconnected geometry; auto-selected a connected regular buffer."
    return "Requested buffer was connected but too irregular; auto-selected a larger regular buffer."


def _materially_improves_regularity(
    baseline: _PolylineBufferCandidate,
    candidate: _PolylineBufferCandidate,
) -> bool:
    improvement = baseline.regularity_ratio - candidate.regularity_ratio
    return improvement >= baseline.regularity_ratio * POLYLINE_AUTO_BUFFER_MIN_MATERIAL_IMPROVEMENT


def _best_connected_candidate(
    candidate_cache: dict[float, _PolylineBufferCandidate | None],
) -> _PolylineBufferCandidate | None:
    candidates = [candidate for candidate in candidate_cache.values() if candidate is not None]
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: candidate.regularity_ratio)


def _collect_line_coordinates(lines: Sequence[LineString]) -> tuple[np.ndarray, np.ndarray]:
    coordinates: list[tuple[float, float]] = []
    for line in lines:
        if line.is_empty:
            continue
        line_coordinates = list(line.coords)
        if len(line_coordinates) < 2 or len(set(line_coordinates)) < 2:
            continue
        coordinates.extend((float(lon), float(lat)) for lon, lat in line_coordinates)
    if len(coordinates) < 2:
        raise PolylineBoundaryError("LineString input must contain at least 2 unique coordinates.")
    lons = np.array([lon for lon, _lat in coordinates], dtype=float)
    lats = np.array([lat for _lon, lat in coordinates], dtype=float)
    return lons, lats


def _detect_utm_epsg(lats: np.ndarray, lons: np.ndarray) -> int:
    avg_lat = float(np.mean(lats))
    avg_lon = float(np.mean(lons))
    zone = math.floor((avg_lon + 180.0) / 6.0) + 1
    zone = max(1, min(60, zone))
    return (32600 if avg_lat >= 0 else 32700) + zone


def _require_single_polygon(
    geometry,
    message: str = "Generated geometry is not one polygon.",
) -> Polygon:
    if geometry.is_empty:
        raise PolylineBoundaryError("Generated geometry is empty.")
    if not geometry.is_valid:
        geometry = make_valid(geometry)
    geometry = fill_polygon_interiors(geometry)
    if isinstance(geometry, Polygon):
        return geometry
    if isinstance(geometry, MultiPolygon):
        polygons = [part for part in geometry.geoms if not part.is_empty and part.area > 0]
        if len(polygons) == 1:
            return polygons[0]
        raise PolylineBoundaryError(message)
    if isinstance(geometry, GeometryCollection):
        polygons = [
            part
            for part in geometry.geoms
            if isinstance(part, Polygon) and not part.is_empty and part.area > 0
        ]
        if len(polygons) == 1:
            return polygons[0]
    raise PolylineBoundaryError(message)


def _count_interiors(geometry) -> int:
    if isinstance(geometry, Polygon):
        return len(geometry.interiors)
    if isinstance(geometry, MultiPolygon):
        return sum(len(part.interiors) for part in geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        return sum(_count_interiors(part) for part in geometry.geoms)
    return 0


def _source_axis_hint_deg(lines_projected: Sequence[LineString]) -> float | None:
    weighted_cos = 0.0
    weighted_sin = 0.0
    total_length = 0.0
    for line in lines_projected:
        coords = list(line.coords)
        for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
            dx = x2 - x1
            dy = y2 - y1
            length = math.hypot(dx, dy)
            if length <= 0:
                continue
            theta = math.atan2(dy, dx)
            weighted_cos += math.cos(2.0 * theta) * length
            weighted_sin += math.sin(2.0 * theta) * length
            total_length += length
    if total_length <= 0:
        return None
    angle = 0.5 * math.atan2(weighted_sin, weighted_cos)
    return math.degrees(angle) % 180.0
