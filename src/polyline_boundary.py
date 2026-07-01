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


def build_polyline_boundary(
    lines_wgs84: Sequence[LineString],
    buffer_ft: float,
) -> PolylineBoundaryResult:
    if buffer_ft <= 0:
        raise PolylineBoundaryError("LineString input requires a buffer greater than 0 ft.")
    if not lines_wgs84:
        raise PolylineBoundaryError("LineString input does not contain any usable lines.")

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
        buffered = buffer_projected_geometry(dissolved, buffer_ft * METERS_PER_FOOT)
    else:
        raise PolylineBoundaryError("LineString input did not produce linework after projection.")

    exterior_only = fill_polygon_interiors(buffered)
    base_polygon = _require_single_polygon(
        exterior_only,
        "Polyline buffer produced disconnected polygons. Process disconnected areas separately.",
    )
    base_polygon = _require_single_polygon(fill_polygon_interiors(make_valid(base_polygon)))
    final_projected = _require_single_polygon(
        densify_projected_geometry(base_polygon),
        "Polyline buffer could not be densified into one polygon.",
    )
    final_wgs84 = transform_geometry(
        lambda x, y, z=None: to_wgs84.transform(x, y),
        final_projected,
    )
    final_wgs84 = _require_single_polygon(fill_polygon_interiors(final_wgs84))

    ignored_interiors = _count_interiors(buffered)
    diagnostics: dict[str, float | int | str] = {
        "buffer_ft": float(buffer_ft),
        "buffer_m": float(buffer_ft * METERS_PER_FOOT),
        "source_line_count": len(lines_wgs84),
        "source_point_count": len(lons),
        "ignored_interior_ring_count": ignored_interiors,
        "projected_area_sq_m": float(final_projected.area),
        "projected_length_m": float(sum(line.length for line in projected_lines)),
    }
    return PolylineBoundaryResult(
        base_polygon_projected=base_polygon,
        final_polygon_projected=final_projected,
        final_polygon_wgs84=final_wgs84,
        epsg=epsg,
        crs_name=crs_projected.name,
        source_line_count=len(lines_wgs84),
        source_point_count=len(lons),
        source_axis_hint_deg=_source_axis_hint_deg(projected_lines),
        diagnostics=diagnostics,
    )


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
