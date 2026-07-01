from __future__ import annotations

import math

from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.ops import unary_union
from shapely.validation import make_valid


EXPORT_MAX_SEGMENT_M = 10.0
DEFAULT_BUFFER_QUAD_SEGS = 64


def clean_geometry(geometry):
    """Repair constructive geometry output while preserving polygonal shape."""
    if geometry.is_empty:
        return geometry

    repaired = geometry
    if not repaired.is_valid:
        repaired = make_valid(repaired)

    if not repaired.is_valid:
        repaired = repaired.buffer(0)

    if isinstance(repaired, GeometryCollection):
        polygons = [
            part
            for part in repaired.geoms
            if isinstance(part, Polygon) and not part.is_empty and part.area > 0
        ]
        if polygons:
            repaired = unary_union(polygons)

    if not repaired.is_valid:
        repaired = repaired.buffer(0)

    return repaired


def buffer_projected_geometry(
    geometry,
    distance_m: float,
    *,
    join_style: str = "round",
    quad_segs: int = DEFAULT_BUFFER_QUAD_SEGS,
    mitre_limit: float = 3.0,
):
    if distance_m < 0:
        raise ValueError("Buffer distance must be non-negative.")
    if distance_m == 0:
        return clean_geometry(geometry)

    buffered = geometry.buffer(
        distance_m,
        join_style=join_style,
        quad_segs=quad_segs,
        mitre_limit=mitre_limit,
    )
    return clean_geometry(buffered)


def densify_projected_geometry(geometry, max_segment_m: float = EXPORT_MAX_SEGMENT_M):
    if max_segment_m <= 0:
        raise ValueError("Maximum segment length must be greater than zero.")
    if not hasattr(geometry, "segmentize"):
        raise RuntimeError("Shapely >= 2.0 is required for geometry segmentize support.")
    if geometry.is_empty:
        return geometry
    return clean_geometry(geometry.segmentize(max_segment_m))


def fill_polygon_interiors(geometry):
    """Return polygonal geometry with all interior rings removed."""
    cleaned = clean_geometry(geometry)
    if cleaned.is_empty:
        return cleaned

    if isinstance(cleaned, Polygon):
        return clean_geometry(Polygon(cleaned.exterior))

    if isinstance(cleaned, MultiPolygon):
        return clean_geometry(
            MultiPolygon(
                [Polygon(part.exterior) for part in cleaned.geoms if not part.is_empty]
            )
        )

    if isinstance(cleaned, GeometryCollection):
        polygons = [
            Polygon(part.exterior)
            for part in cleaned.geoms
            if isinstance(part, Polygon) and not part.is_empty and part.area > 0
        ]
        if polygons:
            return clean_geometry(unary_union(polygons))

    return cleaned


def is_supported_polygonal_geometry(geometry) -> bool:
    if geometry.is_empty or not geometry.is_valid:
        return False
    return isinstance(geometry, (Polygon, MultiPolygon))


def max_exterior_segment_length(polygon: Polygon) -> float:
    coords = list(polygon.exterior.coords)
    if len(coords) < 2:
        return 0.0
    return max(
        math.hypot(x2 - x1, y2 - y1)
        for (x1, y1), (x2, y2) in zip(coords, coords[1:])
    )
