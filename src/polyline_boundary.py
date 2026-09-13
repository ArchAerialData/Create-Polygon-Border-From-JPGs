from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from shapely import union_all
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
from buffer_settings import BufferSettings


FEET_PER_METER = 3.280839895
METERS_PER_FOOT = 0.3048
POLYLINE_AUTO_BUFFER_HARD_MAX_FT = 2000


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
    if not math.isfinite(buffer_ft) or buffer_ft <= 0:
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
    if not math.isfinite(requested_buffer_ft) or requested_buffer_ft < 0:
        raise PolylineBoundaryError("Polyline buffer must be finite and 0 ft or greater.")
    search_limit_ft = POLYLINE_AUTO_BUFFER_HARD_MAX_FT
    candidates_tested = 0
    candidate_cache: dict[float, _PolylineBufferCandidate | None] = {}

    def candidate_for(buffer_ft: float) -> _PolylineBufferCandidate | None:
        nonlocal candidates_tested
        key = float(buffer_ft)
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

    # Concavity is expected in flight corridors. A perimeter/convex-hull ratio
    # measures shape complexity, not whether a buffer is geometrically usable.
    # Preserve every valid explicit distance; Auto only resolves connectivity.
    selected_candidate = requested_candidate or minimum_candidate
    adjustment_reason = ""
    if requested_candidate is None:
        if requested_buffer_ft == 0:
            adjustment_reason = (
                "LineString input needs positive width; selected the smallest "
                "connected buffer in whole feet."
            )
        else:
            adjustment_reason = (
                "Requested buffer produced disconnected geometry; selected the "
                "smallest connected buffer in whole feet."
            )

    diagnostics = {
        "requested_buffer_ft": requested_buffer_ft,
        "minimum_connected_buffer_ft": float(minimum_connected_ft),
        "selected_buffer_ft": float(selected_candidate.buffer_ft),
        "regularity_ratio": float(selected_candidate.regularity_ratio),
        "regularity_target": 0.0,  # Legacy diagnostic: no shape-complexity gate.
        "candidate_count": int(candidates_tested),
        "adjustment_reason": adjustment_reason,
    }
    return _build_result_from_candidate(
        projected_input,
        selected_candidate,
        extra_diagnostics=diagnostics,
    )


def build_per_side_polyline_boundary(
    lines_wgs84: Sequence[LineString], left_ft: float, right_ft: float,
) -> PolylineBoundaryResult:
    try:
        settings = BufferSettings.per_side(left_ft, right_ft)
    except ValueError as exc:
        raise PolylineBoundaryError(str(exc)) from exc
    if not lines_wgs84 or any(
        line.is_empty or line.is_closed or not line.is_simple or line.length <= 0
        for line in lines_wgs84
    ):
        raise PolylineBoundaryError("Per-side buffers require usable open, simple polylines.")
    left_ft, right_ft = settings.left_ft, settings.right_ft
    projected = _project_linework(lines_wgs84)
    if left_ft == right_ft:
        # Exact parity with ordinary buffering, without Auto changing the width.
        candidate = _build_buffer_candidate(projected, left_ft)
    else:
        left, right = left_ft * METERS_PER_FOOT, right_ft * METERS_PER_FOOT
        radius, shift = (left + right) / 2, (left - right) / 2
        grid = min(1e-6, min(v for v in (left, right) if v > 0) / 10000)
        pieces = []
        for line in projected.projected_lines:
            if left:
                pieces.append(line.buffer(left, single_sided=True, quad_segs=64))
            if right:
                pieces.append(line.buffer(-right, single_sided=True, quad_segs=64))
            coordinates = np.asarray(line.coords)
            # Consecutive duplicate vertices must not create a zero-length tangent.
            nonzero = np.linalg.norm(np.diff(coordinates, axis=0), axis=1) > 0
            segments = np.diff(coordinates, axis=0)[nonzero]
            for point, tangent, sign in (
                (coordinates[0], segments[0], -1),
                (coordinates[-1], segments[-1], 1),
            ):
                segment_length = np.linalg.norm(tangent)
                tangent = tangent / segment_length
                normal = np.array([-tangent[1], tangent[0]])
                arc = [
                    point + normal * (shift + radius * math.sin(angle))
                    + sign * tangent * radius * max(0, math.cos(angle))
                    for angle in np.linspace(-math.pi / 2, math.pi / 2, 129)
                ]
                # Overlap the cap seam inward by a bounded numerical tolerance.
                # At millimetre widths, independently rounded offset/cap endpoints
                # can otherwise meet at only a point after fixed-grid union.
                seam = min(segment_length / 4, max(4 * grid, 4 * abs(np.spacing(np.max(np.abs(point))))))
                inward = -sign * tangent * seam
                pieces.append(Polygon(arc + [arc[-1] + inward, arc[0] + inward]))
        buffered = union_all(pieces, grid_size=grid)
        polygon = _require_single_polygon(
            fill_polygon_interiors(buffered),
            "These side buffers produce separate areas. Increase the left or right buffer.",
        )
        # Tolerance covers only cap-union rounding, including a zero-width side.
        if not polygon.buffer(max(2 * grid, 1e-8)).covers(projected.projected_linework):
            raise PolylineBoundaryError("Per-side buffer did not retain all source linework.")
        candidate = _PolylineBufferCandidate(
            radius / METERS_PER_FOOT, polygon, _count_interiors(buffered), _regularity_ratio(polygon),
        )
    return _build_result_from_candidate(projected, candidate, extra_diagnostics={
        "buffer_mode": "per_side", "left_buffer_ft": left_ft, "right_buffer_ft": right_ft,
    })


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
    if not math.isfinite(buffer_ft) or buffer_ft <= 0:
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
    if not base_polygon.is_valid or base_polygon.area <= 0:
        raise PolylineBoundaryError("Polyline buffer did not produce a valid positive-area polygon.")
    if not base_polygon.covers(projected_input.projected_linework):
        raise PolylineBoundaryError("Polyline buffer did not retain all source linework.")
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


def _regularity_ratio(polygon: Polygon) -> float:
    hull_length = float(polygon.convex_hull.length)
    if hull_length <= 0:
        return math.inf
    return float(polygon.exterior.length) / hull_length


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
