from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

from shapely.geometry import Polygon, box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from section_ordering import (  # noqa: E402
    order_parts_for_human_view,
    orient_parallel_parts_for_human_view,
)


class NaturalPairOrientationTests(TestCase):
    def test_side_by_side_pairs_are_oriented_west_to_east(self) -> None:
        west = box(0, 0, 2, 2)
        middle = box(2, 0, 4, 2)
        east = box(4, 0, 6, 2)
        west_output = box(0, -0.1, 2, 2.1)
        middle_output = box(2, -0.1, 4, 2.1)
        east_output = box(4, -0.1, 6, 2.1)

        bases, outputs = orient_parallel_parts_for_human_view(
            [east, middle, west],
            [east_output, middle_output, west_output],
            split_boundary_direction_deg=90.0,
        )

        _assert_same_objects(self, bases, [west, middle, east])
        _assert_same_objects(
            self,
            outputs,
            [west_output, middle_output, east_output],
        )

    def test_stacked_pairs_are_oriented_north_to_south(self) -> None:
        south = box(0, 0, 2, 2)
        middle = box(0, 2, 2, 4)
        north = box(0, 4, 2, 6)
        south_output = box(-0.1, 0, 2.1, 2)
        middle_output = box(-0.1, 2, 2.1, 4)
        north_output = box(-0.1, 4, 2.1, 6)

        bases, outputs = orient_parallel_parts_for_human_view(
            [south, middle, north],
            [south_output, middle_output, north_output],
            split_boundary_direction_deg=0.0,
        )

        _assert_same_objects(self, bases, [north, middle, south])
        _assert_same_objects(
            self,
            outputs,
            [north_output, middle_output, south_output],
        )

    def test_diagonal_pairs_use_left_to_right_as_the_visual_tie_break(self) -> None:
        northwest = box(-2, 1, -1, 2)
        southeast = box(1, -2, 2, -1)
        southwest = box(-2, -2, -1, -1)
        northeast = box(1, 1, 2, 2)

        cases = (
            (45.0, [southeast, northwest], [northwest, southeast]),
            (135.0, [northeast, southwest], [southwest, northeast]),
        )
        for direction, construction_order, expected in cases:
            with self.subTest(direction=direction):
                bases, outputs = orient_parallel_parts_for_human_view(
                    construction_order,
                    construction_order,
                    split_boundary_direction_deg=direction,
                )

                _assert_same_objects(self, bases, expected)
                _assert_same_objects(self, outputs, expected)


class BranchedSectionOrderingTests(TestCase):
    def test_curved_chain_walks_end_to_end_without_branch_jumps(self) -> None:
        chain = [
            box(0, 2, 1, 3),
            box(0, 1, 1, 2),
            box(0, 0, 1, 1),
            box(1, 0, 2, 1),
            box(2, 0, 3, 1),
            box(2, 1, 3, 2),
            box(2, 2, 3, 3),
        ]
        shuffled = [chain[index] for index in (3, 6, 1, 4, 0, 5, 2)]

        ordered = order_parts_for_human_view(
            unary_union(chain),
            shuffled,
        )

        _assert_same_objects(self, ordered, chain)
        self.assertTrue(
            all(
                first.boundary.intersection(second.boundary).length > 0
                for first, second in zip(ordered, ordered[1:])
            )
        )

    def test_compact_grid_uses_top_to_bottom_left_to_right_visual_sweep(self) -> None:
        visual_order = [
            box(x, y, x + 1, y + 1)
            for y in reversed(range(3))
            for x in range(3)
        ]
        shuffled = [visual_order[index] for index in (8, 3, 5, 0, 7, 2, 4, 1, 6)]

        ordered = order_parts_for_human_view(
            unary_union(visual_order),
            shuffled,
        )

        _assert_same_objects(self, ordered, visual_order)

    def test_elongated_grid_still_uses_visual_row_order(self) -> None:
        visual_order = [
            box(x, y, x + 1, y + 1)
            for y in reversed(range(3))
            for x in range(5)
        ]
        permutation = (14, 5, 9, 0, 12, 2, 7, 4, 10, 1, 13, 6, 3, 11, 8)
        shuffled = [visual_order[index] for index in permutation]

        ordered = order_parts_for_human_view(
            unary_union(visual_order),
            shuffled,
        )

        _assert_same_objects(self, ordered, visual_order)

    def test_compact_t_shape_remains_trunk_then_branch(self) -> None:
        trunk = _horizontal_trunk(3, size=1)
        branch_inner = box(0.5, 1, 2.5, 2)
        branch_outer = box(1, 2, 2, 3)
        parts = [branch_outer, trunk[2], branch_inner, trunk[0], trunk[1]]

        ordered = order_parts_for_human_view(
            unary_union(parts),
            parts,
        )

        _assert_same_objects(
            self,
            ordered,
            [*trunk, branch_inner, branch_outer],
        )

    def test_t_shape_numbers_the_complete_trunk_before_its_branch(self) -> None:
        west, junction, east = _horizontal_trunk(3)
        branch = box(2, 2, 4, 4)
        parts = [branch, east, west, junction]

        ordered = order_parts_for_human_view(
            unary_union(parts),
            parts,
        )

        _assert_same_objects(self, ordered, [west, junction, east, branch])

    def test_comb_numbers_branches_by_trunk_attachment_then_outward(self) -> None:
        trunk = _horizontal_trunk(4)
        near_branch_inner = box(2, 2, 4, 4)
        near_branch_outer = box(2, 4, 4, 6)
        far_branch = box(6, 2, 8, 4)
        parts = [
            far_branch,
            trunk[2],
            near_branch_outer,
            trunk[0],
            near_branch_inner,
            trunk[3],
            trunk[1],
        ]

        ordered = order_parts_for_human_view(
            unary_union(parts),
            parts,
        )

        _assert_same_objects(
            self,
            ordered,
            [*trunk, near_branch_inner, near_branch_outer, far_branch],
        )

    def test_cross_branches_at_one_junction_read_top_to_bottom(self) -> None:
        trunk = _horizontal_trunk(5)
        north_inner = box(4, 2, 6, 4)
        north_outer = box(4, 4, 6, 6)
        south_inner = box(4, -2, 6, 0)
        south_outer = box(4, -4, 6, -2)
        branches = [north_inner, north_outer, south_inner, south_outer]
        parts = [south_outer, trunk[3], north_outer, trunk[0], south_inner]
        parts += [trunk[4], north_inner, trunk[2], trunk[1]]

        ordered = order_parts_for_human_view(
            unary_union([*trunk, *branches]),
            parts,
        )

        _assert_same_objects(
            self,
            ordered,
            [*trunk, north_inner, north_outer, south_inner, south_outer],
        )

    def test_order_is_stable_across_input_and_ring_order(self) -> None:
        trunk = _horizontal_trunk(4)
        branches = [box(2, 2, 4, 4), box(2, 4, 4, 6), box(6, 2, 8, 4)]
        canonical_parts = [*trunk, *branches]
        canonical_parent = unary_union(canonical_parts)
        expected_centroids = _centroid_keys(canonical_parts)
        permutations = (
            [0, 1, 2, 3, 4, 5, 6],
            [6, 2, 5, 0, 4, 3, 1],
            [3, 4, 1, 6, 0, 5, 2],
        )

        for reverse_rings in (False, True):
            rebuilt_parts = [
                _reverse_polygon_ring(part) if reverse_rings else part
                for part in canonical_parts
            ]
            parent = (
                _reverse_polygon_ring(canonical_parent)
                if reverse_rings
                else canonical_parent
            )
            for permutation in permutations:
                with self.subTest(
                    reverse_rings=reverse_rings,
                    permutation=permutation,
                ):
                    shuffled = [rebuilt_parts[index] for index in permutation]

                    ordered = order_parts_for_human_view(
                        parent,
                        shuffled,
                    )

                    self.assertEqual(_centroid_keys(ordered), expected_centroids)

    def test_returned_polygons_are_the_exact_input_objects(self) -> None:
        trunk = _horizontal_trunk(3)
        branch = box(2, 2, 4, 4)
        parts = [branch, trunk[2], trunk[0], trunk[1]]

        ordered = order_parts_for_human_view(
            unary_union(parts),
            parts,
        )

        self.assertEqual({id(part) for part in ordered}, {id(part) for part in parts})
        _assert_same_objects(self, ordered, [*trunk, branch])

    def test_point_only_contacts_do_not_change_branch_attachment_order(self) -> None:
        trunk = _horizontal_trunk(4)
        earlier_branch = box(2, -2, 4, 0)
        later_branch = box(4, 2, 6, 4)
        parts = [later_branch, trunk[3], earlier_branch, trunk[1], trunk[0], trunk[2]]

        # The later branch shares an edge only with trunk[2]. Its corner contact
        # with trunk[1] must not make it look like an earlier-attached branch.
        self.assertEqual(later_branch.intersection(trunk[1]).geom_type, "Point")
        self.assertGreater(later_branch.intersection(trunk[2]).length, 0.0)

        ordered = order_parts_for_human_view(
            unary_union(parts),
            parts,
        )

        _assert_same_objects(
            self,
            ordered,
            [*trunk, earlier_branch, later_branch],
        )


def _horizontal_trunk(count: int, *, size: float = 2) -> list[Polygon]:
    return [
        box(index * size, 0, (index + 1) * size, size)
        for index in range(count)
    ]


def _reverse_polygon_ring(polygon: Polygon) -> Polygon:
    shell = list(polygon.exterior.coords)[::-1]
    holes = [list(interior.coords)[::-1] for interior in polygon.interiors]
    return Polygon(shell, holes)


def _centroid_keys(parts: list[Polygon]) -> list[tuple[float, float]]:
    return [
        (round(part.centroid.x, 9), round(part.centroid.y, 9))
        for part in parts
    ]


def _assert_same_objects(
    test_case: TestCase,
    actual: list[Polygon],
    expected: list[Polygon],
) -> None:
    test_case.assertEqual(len(actual), len(expected))
    for position, (actual_part, expected_part) in enumerate(zip(actual, expected)):
        test_case.assertIs(
            actual_part,
            expected_part,
            f"Unexpected polygon object at visual position {position}",
        )
