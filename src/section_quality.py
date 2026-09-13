"""Scale-independent safeguards for automatic ortho crop partitions."""

from collections.abc import Sequence
import math

from shapely.geometry import LineString, Point, Polygon


# 2A/P approximates a long corridor's width (and a circle's radius). A normal
# cross-cut is near 1 for a corridor and at most 2 for a circle/square. Leave
# room for bends and junctions, but reject long cuts down a corridor's side.
MAX_AUTO_CUT_WIDTH_RATIO = 2.5
MIN_AUTO_CROSSING_ANGLE_DEG = 60.0


def minimum_crossing_angle(parent: Polygon, cut) -> float:
    """Smallest angle at which a cut meets the surrounding boundary.

    Sample a short arc on either side of each endpoint to avoid sensitivity to
    dense buffer vertices. An oblique cut beside a bend creates a pointed crop
    end even when the total seam is short. Perpendicular crossings score 90.
    """
    segments = [cut] if isinstance(cut, LineString) else list(getattr(cut, "geoms", ()))
    ring = parent.exterior
    probe = 0.05 * 2.0 * parent.area / ring.length
    angles = []
    for segment in segments:
        if not isinstance(segment, LineString) or segment.length <= 1e-6:
            continue
        start, end = segment.coords[0], segment.coords[-1]
        dx, dy = end[0] - start[0], end[1] - start[1]
        cut_length = math.hypot(dx, dy)
        for xy in (start, end):
            position = ring.project(Point(xy))
            before = ring.interpolate((position - probe) % ring.length)
            after = ring.interpolate((position + probe) % ring.length)
            tx, ty = after.x - before.x, after.y - before.y
            denominator = cut_length * math.hypot(tx, ty)
            if denominator <= 0:
                return 0.0
            cosine = min(1.0, abs(dx * tx + dy * ty) / denominator)
            angles.append(math.degrees(math.acos(cosine)))
    return min(angles, default=0.0)


def cut_width_ratio(parent: Polygon, cut_length: float) -> float:
    if parent.area <= 0 or parent.length <= 0:
        return float("inf")
    return max(0.0, cut_length) * parent.length / (2.0 * parent.area)


def introduced_cut_length(parent: Polygon, parts: Sequence[Polygon]) -> float:
    """Measure cuts before overlap; each new edge belongs to two children.

    Perimeters avoid requiring independently rotated edges to coincide exactly.
    Callers must supply a complete, non-overlapping partition of the parent.
    """
    return max(0.0, (sum(part.length for part in parts) - parent.length) / 2.0)
