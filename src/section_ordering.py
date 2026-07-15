from __future__ import annotations

import heapq
import math
from collections.abc import Sequence

from shapely.geometry import GeometryCollection, LineString, MultiLineString, Polygon


VISUAL_CHORD_SAMPLE_COUNT = 129
AXIS_CHORD_SAMPLE_COUNT = 33
AXIS_DIRECTION_BIN_DEGREES = 5.0
MAX_BOUNDARY_AXIS_CANDIDATES = 12
ADJACENCY_DISTANCE_RATIO = 1e-8
MIN_SHARED_BOUNDARY_RATIO = 1e-6
AREA_LIKE_MIN_FILL_RATIO = 0.8


def orient_parallel_parts_for_human_view(
    base_parts: Sequence[Polygon],
    output_parts: Sequence[Polygon],
    split_boundary_direction_deg: float,
) -> tuple[list[Polygon], list[Polygon]]:
    """Orient parallel slices for a north-up, human-readable map view.

    Horizontal-dominant runs read left-to-right. Vertically dominant runs read
    top-to-bottom. Base and output polygons always move as atomic pairs.
    """
    if len(base_parts) != len(output_parts):
        raise ValueError("Base and output section counts must match.")

    direction_rad = math.radians(split_boundary_direction_deg)
    construction_axis = (-math.sin(direction_rad), math.cos(direction_rad))
    if _axis_opposes_human_reading(*construction_axis):
        return list(reversed(base_parts)), list(reversed(output_parts))
    return list(base_parts), list(output_parts)


def order_parts_for_human_view(
    parent_polygon: Polygon,
    parts: Sequence[Polygon],
) -> list[Polygon]:
    """Return the same polygons in deterministic visual reading order.

    The longest visual run is ordered first. Remaining connected groups are
    treated as branches, ordered by their attachment to that run, and walked
    from each junction outward. This function never modifies polygon geometry.
    """
    source_parts = list(parts)
    if len(source_parts) <= 1:
        return source_parts

    scale = _geometry_scale(parent_polygon)
    tolerance = max(scale * ADJACENCY_DISTANCE_RATIO, 1e-9)
    adjacency = _build_adjacency(source_parts, scale, tolerance)
    if _uses_visual_sweep(parent_polygon, adjacency, tolerance):
        sweep_order = sorted(
            range(len(source_parts)),
            key=lambda index: _visual_node_key(source_parts[index], tolerance),
        )
        return [source_parts[index] for index in sweep_order]

    axis_direction_deg = _major_visual_axis_deg(
        parent_polygon,
        source_parts,
        scale,
        tolerance,
    )
    axis = _human_reading_axis(axis_direction_deg)
    chain_order = _simple_chain_or_cycle_order(
        source_parts,
        adjacency,
        axis,
        tolerance,
    )
    if chain_order is not None:
        return [source_parts[index] for index in chain_order]

    main_run = _main_run_indices(
        parent_polygon,
        source_parts,
        adjacency,
        axis,
        scale,
        tolerance,
    )
    ordered_indices = _order_main_run_and_branches(
        source_parts,
        adjacency,
        main_run,
        axis,
        tolerance,
    )

    # A disconnected or numerically ambiguous adjacency graph must not make a
    # previously valid split fail. Any unvisited pieces retain deterministic
    # top-to-bottom, then left-to-right visual ordering at the end.
    seen = set(ordered_indices)
    missing = [index for index in range(len(source_parts)) if index not in seen]
    missing.sort(key=lambda index: _visual_node_key(source_parts[index], tolerance))
    ordered_indices.extend(missing)
    return [source_parts[index] for index in ordered_indices]


def _axis_opposes_human_reading(dx: float, dy: float) -> bool:
    if abs(dx) >= abs(dy):
        return dx < 0.0
    return dy > 0.0


def _human_reading_axis(direction_deg: float) -> tuple[float, float]:
    direction_rad = math.radians(direction_deg)
    dx = math.cos(direction_rad)
    dy = math.sin(direction_rad)
    if _axis_opposes_human_reading(dx, dy):
        return -dx, -dy
    return dx, dy


def _major_visual_axis_deg(
    parent_polygon: Polygon,
    parts: Sequence[Polygon],
    scale: float,
    tolerance: float,
) -> float:
    candidates = _candidate_visual_axis_directions(parent_polygon, tolerance)
    best_direction = 0.0
    best_key: tuple[int, int, int] | None = None
    for direction in candidates:
        direction_rad = math.radians(direction)
        axis = (math.cos(direction_rad), math.sin(direction_rad))
        chord = _longest_visual_chord(
            parent_polygon,
            parts,
            axis,
            scale,
            tolerance,
            sample_count=AXIS_CHORD_SAMPLE_COUNT,
        )
        chord_length = chord.length if chord is not None else 0.0
        key = (
            round(chord_length / tolerance),
            round(abs(axis[0]) / tolerance),
            -round(direction / AXIS_DIRECTION_BIN_DEGREES),
        )
        if best_key is None or key > best_key:
            best_key = key
            best_direction = direction
    return best_direction


def _candidate_visual_axis_directions(
    parent_polygon: Polygon,
    tolerance: float,
) -> list[float]:
    candidates = {0.0, 90.0}
    rectangle = parent_polygon.minimum_rotated_rectangle
    coordinates = list(rectangle.exterior.coords[:-1])
    for start, end in zip(coordinates, coordinates[1:] + coordinates[:1]):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        if math.hypot(dx, dy) <= tolerance:
            continue
        candidates.add(math.degrees(math.atan2(dy, dx)) % 180.0)

    bin_count = round(180.0 / AXIS_DIRECTION_BIN_DEGREES)
    direction_bins: dict[int, tuple[float, float, float]] = {}
    exterior = list(parent_polygon.exterior.coords)
    for start, end in zip(exterior, exterior[1:]):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        if length <= tolerance:
            continue
        direction = math.degrees(math.atan2(dy, dx)) % 180.0
        bin_index = round(direction / AXIS_DIRECTION_BIN_DEGREES) % bin_count
        doubled = math.radians(direction * 2.0)
        total, cosine, sine = direction_bins.get(bin_index, (0.0, 0.0, 0.0))
        direction_bins[bin_index] = (
            total + length,
            cosine + length * math.cos(doubled),
            sine + length * math.sin(doubled),
        )

    strongest_bins = sorted(
        direction_bins.items(),
        key=lambda item: (-item[1][0], item[0]),
    )[:MAX_BOUNDARY_AXIS_CANDIDATES]
    for _bin_index, (_total, cosine, sine) in strongest_bins:
        direction = math.degrees(math.atan2(sine, cosine)) / 2.0
        candidates.add(direction % 180.0)
    return sorted(candidates)


def _geometry_scale(geometry: Polygon) -> float:
    minx, miny, maxx, maxy = geometry.bounds
    return max(maxx - minx, maxy - miny, 1.0)


def _build_adjacency(
    parts: Sequence[Polygon],
    scale: float,
    tolerance: float,
) -> list[set[int]]:
    adjacency = [set() for _part in parts]
    boundary_buffers = [part.boundary.buffer(tolerance) for part in parts]
    minimum_shared_length = max(
        scale * MIN_SHARED_BOUNDARY_RATIO,
        tolerance * 8.0,
    )

    for first_index, first in enumerate(parts):
        first_minx, first_miny, first_maxx, first_maxy = first.bounds
        for second_index in range(first_index + 1, len(parts)):
            second = parts[second_index]
            second_minx, second_miny, second_maxx, second_maxy = second.bounds
            if (
                first_maxx + tolerance < second_minx
                or second_maxx + tolerance < first_minx
                or first_maxy + tolerance < second_miny
                or second_maxy + tolerance < first_miny
            ):
                continue
            if first.distance(second) > tolerance:
                continue

            first_near_second = first.boundary.intersection(
                boundary_buffers[second_index]
            ).length
            second_near_first = second.boundary.intersection(
                boundary_buffers[first_index]
            ).length
            if min(first_near_second, second_near_first) <= minimum_shared_length:
                continue
            adjacency[first_index].add(second_index)
            adjacency[second_index].add(first_index)
    return adjacency


def _simple_chain_or_cycle_order(
    parts: Sequence[Polygon],
    adjacency: Sequence[set[int]],
    axis: tuple[float, float],
    tolerance: float,
) -> list[int] | None:
    if not _graph_is_connected(adjacency):
        return None
    if any(len(neighbors) > 2 for neighbors in adjacency):
        return None

    endpoints = [
        index for index, neighbors in enumerate(adjacency) if len(neighbors) == 1
    ]
    if len(parts) > 1 and len(endpoints) not in {0, 2}:
        return None
    if endpoints:
        start = min(
            endpoints,
            key=lambda index: _axis_node_key(parts[index], axis, tolerance),
        )
    else:
        start = min(
            range(len(parts)),
            key=lambda index: _visual_node_key(parts[index], tolerance),
        )

    ordered: list[int] = []
    visited: set[int] = set()
    current = start
    while current not in visited:
        ordered.append(current)
        visited.add(current)
        candidates = [
            neighbor for neighbor in adjacency[current] if neighbor not in visited
        ]
        if not candidates:
            break
        current = min(
            candidates,
            key=lambda index: _visual_node_key(parts[index], tolerance),
        )
    return ordered if len(ordered) == len(parts) else None


def _uses_visual_sweep(
    parent_polygon: Polygon,
    adjacency: Sequence[set[int]],
    tolerance: float,
) -> bool:
    if not _graph_is_connected(adjacency):
        return False
    edge_count = sum(len(neighbors) for neighbors in adjacency) // 2
    if edge_count < len(adjacency):
        return False

    rectangle = parent_polygon.minimum_rotated_rectangle
    coordinates = list(rectangle.exterior.coords[:-1])
    if len(coordinates) < 3 or rectangle.area <= tolerance * tolerance:
        return False

    # A nearly filled visual envelope reads as a 2D layout even when it is
    # elongated. Sparse T/cross/comb outlines remain trunk-and-branch layouts.
    fill_ratio = parent_polygon.area / rectangle.area
    return fill_ratio >= AREA_LIKE_MIN_FILL_RATIO


def _graph_is_connected(adjacency: Sequence[set[int]]) -> bool:
    if not adjacency:
        return True
    visited: set[int] = set()
    stack = [0]
    while stack:
        node = stack.pop()
        if node in visited:
            continue
        visited.add(node)
        stack.extend(adjacency[node] - visited)
    return len(visited) == len(adjacency)


def _main_run_indices(
    parent_polygon: Polygon,
    parts: Sequence[Polygon],
    adjacency: Sequence[set[int]],
    axis: tuple[float, float],
    scale: float,
    tolerance: float,
) -> list[int]:
    main_segment = _longest_visual_chord(
        parent_polygon,
        parts,
        axis,
        scale,
        tolerance,
    )
    if main_segment is not None:
        main_indices = [
            index
            for index, part in enumerate(parts)
            if part.intersection(main_segment).length > tolerance * 4.0
        ]
        main_indices.sort(
            key=lambda index: _axis_node_key(parts[index], axis, tolerance)
        )
        if len(main_indices) >= 2:
            return _repair_main_run_adjacency(
                main_indices,
                parts,
                adjacency,
                axis,
                tolerance,
            )

    visually_sorted = sorted(
        range(len(parts)),
        key=lambda index: _axis_node_key(parts[index], axis, tolerance),
    )
    start = visually_sorted[0]
    end = visually_sorted[-1]
    fallback_path = _shortest_path(
        start,
        end,
        set(range(len(parts))),
        parts,
        adjacency,
        axis,
        tolerance,
    )
    return fallback_path or [start]


def _longest_visual_chord(
    parent_polygon: Polygon,
    parts: Sequence[Polygon],
    axis: tuple[float, float],
    scale: float,
    tolerance: float,
    *,
    sample_count: int = VISUAL_CHORD_SAMPLE_COUNT,
) -> LineString | None:
    dx, dy = axis
    normal = (-dy, dx)
    normal_values = [
        (x * normal[0]) + (y * normal[1])
        for x, y in parent_polygon.exterior.coords
    ]
    minimum_normal = min(normal_values)
    maximum_normal = max(normal_values)
    if maximum_normal - minimum_normal <= tolerance:
        return None

    offsets = [
        minimum_normal
        + (maximum_normal - minimum_normal)
        * ((index + 0.5) / sample_count)
        for index in range(sample_count)
    ]
    for part in parts:
        representative = part.representative_point()
        offsets.append(
            (representative.x * normal[0]) + (representative.y * normal[1])
        )
    center = parent_polygon.centroid
    center_normal = (center.x * normal[0]) + (center.y * normal[1])
    half_length = scale * 3.0 + 1.0
    best_segment: LineString | None = None
    best_key: tuple[int, int, int] | None = None
    seen_offsets: set[int] = set()

    for offset in offsets:
        offset_key = round(offset / tolerance)
        if offset_key in seen_offsets:
            continue
        seen_offsets.add(offset_key)
        anchor_x = center.x + normal[0] * (offset - center_normal)
        anchor_y = center.y + normal[1] * (offset - center_normal)
        scan_line = LineString(
            [
                (anchor_x - dx * half_length, anchor_y - dy * half_length),
                (anchor_x + dx * half_length, anchor_y + dy * half_length),
            ]
        )
        segment = _longest_line_component(parent_polygon.intersection(scan_line))
        if segment is None or segment.length <= tolerance:
            continue
        midpoint = segment.interpolate(0.5, normalized=True)
        key = (
            round(segment.length / tolerance),
            round(midpoint.y / tolerance),
            -round(midpoint.x / tolerance),
        )
        if best_key is None or key > best_key:
            best_key = key
            best_segment = segment
    return best_segment


def _longest_line_component(geometry) -> LineString | None:
    if isinstance(geometry, LineString):
        return geometry if geometry.length > 0 else None
    if isinstance(geometry, (MultiLineString, GeometryCollection)):
        candidates = [
            candidate
            for part in geometry.geoms
            if (candidate := _longest_line_component(part)) is not None
        ]
        if candidates:
            return max(
                candidates,
                key=lambda candidate: (
                    candidate.length,
                    candidate.interpolate(0.5, normalized=True).y,
                    -candidate.interpolate(0.5, normalized=True).x,
                ),
            )
    return None


def _repair_main_run_adjacency(
    main_indices: Sequence[int],
    parts: Sequence[Polygon],
    adjacency: Sequence[set[int]],
    axis: tuple[float, float],
    tolerance: float,
) -> list[int]:
    repaired = [main_indices[0]]
    for target in main_indices[1:]:
        if target in repaired:
            continue
        current = repaired[-1]
        if target in adjacency[current]:
            repaired.append(target)
            continue

        current_projection = _axis_projection(parts[current], axis)
        target_projection = _axis_projection(parts[target], axis)
        allowed = {
            index
            for index, part in enumerate(parts)
            if index not in repaired
            and current_projection - tolerance
            <= _axis_projection(part, axis)
            <= target_projection + tolerance
        }
        allowed.add(current)
        path = _shortest_path(
            current,
            target,
            allowed,
            parts,
            adjacency,
            axis,
            tolerance,
        )
        if path:
            repaired.extend(index for index in path[1:] if index not in repaired)
        else:
            repaired.append(target)
    return repaired


def _order_main_run_and_branches(
    parts: Sequence[Polygon],
    adjacency: Sequence[set[int]],
    main_run: Sequence[int],
    axis: tuple[float, float],
    tolerance: float,
) -> list[int]:
    ordered = list(dict.fromkeys(main_run))
    remaining = set(range(len(parts))) - set(ordered)
    ordered.extend(
        _order_attached_components(
            remaining,
            ordered,
            parts,
            adjacency,
            axis,
            tolerance,
        )
    )
    return ordered


def _order_attached_components(
    nodes: set[int],
    parent_order: Sequence[int],
    parts: Sequence[Polygon],
    adjacency: Sequence[set[int]],
    axis: tuple[float, float],
    tolerance: float,
) -> list[int]:
    if not nodes:
        return []
    parent_positions = {node: position for position, node in enumerate(parent_order)}
    components = _connected_components(nodes, adjacency)
    components.sort(
        key=lambda component: _component_order_key(
            component,
            parent_positions,
            parts,
            adjacency,
            tolerance,
        )
    )

    result: list[int] = []
    for component in components:
        root = _component_root(
            component,
            parent_positions,
            parts,
            adjacency,
            tolerance,
        )
        spine = _rooted_component_spine(
            component,
            root,
            parts,
            adjacency,
            axis,
            tolerance,
        )
        result.extend(spine)
        subnodes = component - set(spine)
        result.extend(
            _order_attached_components(
                subnodes,
                spine,
                parts,
                adjacency,
                axis,
                tolerance,
            )
        )
    return result


def _component_order_key(
    component: set[int],
    parent_positions: dict[int, int],
    parts: Sequence[Polygon],
    adjacency: Sequence[set[int]],
    tolerance: float,
) -> tuple:
    attachment_positions = [
        parent_positions[neighbor]
        for node in component
        for neighbor in adjacency[node]
        if neighbor in parent_positions
    ]
    attachment = min(attachment_positions) if attachment_positions else math.inf
    visual = min(_visual_node_key(parts[node], tolerance) for node in component)
    return attachment, visual


def _component_root(
    component: set[int],
    parent_positions: dict[int, int],
    parts: Sequence[Polygon],
    adjacency: Sequence[set[int]],
    tolerance: float,
) -> int:
    attached = [
        (
            min(
                parent_positions[neighbor]
                for neighbor in adjacency[node]
                if neighbor in parent_positions
            ),
            node,
        )
        for node in component
        if any(neighbor in parent_positions for neighbor in adjacency[node])
    ]
    if attached:
        first_attachment = min(position for position, _node in attached)
        candidates = [node for position, node in attached if position == first_attachment]
    else:
        candidates = list(component)
    return min(candidates, key=lambda node: _visual_node_key(parts[node], tolerance))


def _rooted_component_spine(
    component: set[int],
    root: int,
    parts: Sequence[Polygon],
    adjacency: Sequence[set[int]],
    axis: tuple[float, float],
    tolerance: float,
) -> list[int]:
    distances, previous = _shortest_paths_from(
        root,
        component,
        parts,
        adjacency,
        axis,
        tolerance,
    )
    reachable = [node for node in component if math.isfinite(distances[node])]
    if not reachable:
        return [root]
    farthest = min(
        reachable,
        key=lambda node: (
            -round(distances[node] / tolerance),
            _visual_node_key(parts[node], tolerance),
        ),
    )
    path: list[int] = []
    current: int | None = farthest
    while current is not None:
        path.append(current)
        if current == root:
            break
        current = previous[current]
    path.reverse()
    return path if path and path[0] == root else [root]


def _shortest_path(
    start: int,
    end: int,
    allowed: set[int],
    parts: Sequence[Polygon],
    adjacency: Sequence[set[int]],
    axis: tuple[float, float],
    tolerance: float,
) -> list[int]:
    distances, previous = _shortest_paths_from(
        start,
        allowed,
        parts,
        adjacency,
        axis,
        tolerance,
    )
    if not math.isfinite(distances[end]):
        return []
    path: list[int] = []
    current: int | None = end
    while current is not None:
        path.append(current)
        if current == start:
            break
        current = previous[current]
    path.reverse()
    return path if path and path[0] == start else []


def _shortest_paths_from(
    start: int,
    allowed: set[int],
    parts: Sequence[Polygon],
    adjacency: Sequence[set[int]],
    axis: tuple[float, float],
    tolerance: float,
) -> tuple[list[float], list[int | None]]:
    distances = [math.inf] * len(parts)
    previous: list[int | None] = [None] * len(parts)
    distances[start] = 0.0
    queue: list[tuple[float, tuple, int]] = [
        (0.0, _axis_node_key(parts[start], axis, tolerance), start)
    ]

    while queue:
        distance, _tie_key, node = heapq.heappop(queue)
        if distance > distances[node] + tolerance:
            continue
        for neighbor in sorted(
            adjacency[node],
            key=lambda candidate: _axis_node_key(
                parts[candidate],
                axis,
                tolerance,
            ),
        ):
            if neighbor not in allowed:
                continue
            edge_distance = parts[node].centroid.distance(parts[neighbor].centroid)
            candidate_distance = distance + max(edge_distance, tolerance)
            if candidate_distance >= distances[neighbor] - tolerance:
                continue
            distances[neighbor] = candidate_distance
            previous[neighbor] = node
            heapq.heappush(
                queue,
                (
                    candidate_distance,
                    _axis_node_key(parts[neighbor], axis, tolerance),
                    neighbor,
                ),
            )
    return distances, previous


def _connected_components(
    nodes: set[int],
    adjacency: Sequence[set[int]],
) -> list[set[int]]:
    remaining = set(nodes)
    components: list[set[int]] = []
    while remaining:
        start = min(remaining)
        component: set[int] = set()
        stack = [start]
        while stack:
            node = stack.pop()
            if node not in remaining:
                continue
            remaining.remove(node)
            component.add(node)
            stack.extend(adjacency[node] & remaining)
        components.append(component)
    return components


def _axis_projection(part: Polygon, axis: tuple[float, float]) -> float:
    centroid = part.centroid
    return (centroid.x * axis[0]) + (centroid.y * axis[1])


def _axis_node_key(
    part: Polygon,
    axis: tuple[float, float],
    tolerance: float,
) -> tuple:
    perpendicular = (-axis[1], axis[0])
    centroid = part.centroid
    projection = (centroid.x * axis[0]) + (centroid.y * axis[1])
    lateral = (centroid.x * perpendicular[0]) + (centroid.y * perpendicular[1])
    return (
        round(projection / tolerance),
        round(lateral / tolerance),
        _geometry_tie_key(part, tolerance),
    )


def _visual_node_key(part: Polygon, tolerance: float) -> tuple:
    centroid = part.centroid
    return (
        -round(centroid.y / tolerance),
        round(centroid.x / tolerance),
        _geometry_tie_key(part, tolerance),
    )


def _geometry_tie_key(part: Polygon, tolerance: float) -> tuple[int, ...]:
    minx, miny, maxx, maxy = part.bounds
    area_tolerance = max(tolerance * tolerance, 1e-18)
    return (
        round(minx / tolerance),
        round(miny / tolerance),
        round(maxx / tolerance),
        round(maxy / tolerance),
        round(part.area / area_tolerance),
    )
