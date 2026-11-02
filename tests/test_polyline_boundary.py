from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from polyline_boundary import (  # noqa: E402
    PolylineBoundaryError,
    build_polyline_boundary,
    build_polyline_boundary_with_recommended_buffer,
)


class PolylineBoundaryTests(TestCase):
    def test_line_buffer_returns_exterior_only_polygon(self) -> None:
        line = LineString([(-80.0, 35.0), (-79.999, 35.001), (-79.998, 35.0)])

        result = build_polyline_boundary([line], 100.0)

        self.assertTrue(result.final_polygon_projected.is_valid)
        self.assertGreater(result.final_polygon_projected.area, 0)
        self.assertEqual(len(result.final_polygon_projected.interiors), 0)
        self.assertEqual(result.source_line_count, 1)
        self.assertEqual(result.source_point_count, 3)
        self.assertIsNotNone(result.source_axis_hint_deg)

    def test_zero_buffer_line_input_is_rejected(self) -> None:
        line = LineString([(-80.0, 35.0), (-79.999, 35.001)])

        with self.assertRaisesRegex(PolylineBoundaryError, "greater than 0 ft"):
            build_polyline_boundary([line], 0.0)

    def test_closed_line_hole_is_filled(self) -> None:
        line = LineString(
            [
                (-80.0000, 35.0000),
                (-79.9980, 35.0000),
                (-79.9980, 35.0020),
                (-80.0000, 35.0020),
                (-80.0000, 35.0000),
            ]
        )

        result = build_polyline_boundary([line], 30.0)

        self.assertEqual(len(result.final_polygon_projected.interiors), 0)
        self.assertGreaterEqual(
            int(result.diagnostics["ignored_interior_ring_count"]),
            1,
        )

    def test_disconnected_line_buffer_is_rejected(self) -> None:
        lines = [
            LineString([(-80.0, 35.0), (-79.999, 35.0)]),
            LineString([(-79.95, 35.0), (-79.949, 35.0)]),
        ]

        with self.assertRaisesRegex(PolylineBoundaryError, "disconnected"):
            build_polyline_boundary(lines, 25.0)

    def test_close_parallel_lines_can_dissolve_to_one_polygon(self) -> None:
        lines = [
            LineString([(-80.0, 35.0), (-79.999, 35.0)]),
            LineString([(-79.9998, 35.00005), (-79.9988, 35.00005)]),
        ]

        result = build_polyline_boundary(lines, 50.0)

        self.assertTrue(result.final_polygon_projected.is_valid)
        self.assertEqual(len(result.final_polygon_projected.interiors), 0)

    def test_auto_preserves_concave_corridor_at_explicit_distances(self) -> None:
        line = LineString([(-80, 35), (-80, 35.03), (-79.99, 35.03),
                           (-79.99, 35.01), (-79.98, 35.01), (-79.98, 35.04)])
        for distance in (0.25, 50, 350, 2500):
            with self.subTest(distance=distance):
                direct = build_polyline_boundary([line], distance)
                auto = build_polyline_boundary_with_recommended_buffer([line], distance)
                self.assertEqual(auto.diagnostics["selected_buffer_ft"], distance)
                self.assertFalse(auto.diagnostics["adjustment_reason"])
                self.assertTrue(auto.final_polygon_projected.equals(direct.final_polygon_projected))
        self.assertGreater(build_polyline_boundary([line], 350).diagnostics["regularity_ratio"], 1.55)

    def test_auto_uses_minimum_connected_whole_foot_buffer(self) -> None:
        lines = [LineString([(-80, 35), (-79.999, 35)]),
                 LineString([(-79.9988, 35), (-79.997, 35)])]
        for requested in (0, 1, 5):
            with self.subTest(requested=requested):
                result = build_polyline_boundary_with_recommended_buffer(lines, requested)
                selected = result.diagnostics["selected_buffer_ft"]
                self.assertEqual(selected, result.diagnostics["minimum_connected_buffer_ft"])
                self.assertGreater(selected, requested)
                self.assertTrue(result.final_polygon_projected.is_valid)
                with self.assertRaises(PolylineBoundaryError):
                    build_polyline_boundary(lines, selected - 1)

    def test_auto_search_expands_beyond_old_500_foot_limit(self) -> None:
        lines = [LineString([(-80, 35), (-79.999, 35)]),
                 LineString([(-79.994, 35), (-79.993, 35)])]
        result = build_polyline_boundary_with_recommended_buffer(lines, 0)
        selected = result.diagnostics["selected_buffer_ft"]
        self.assertGreater(selected, 500)
        self.assertLess(selected, 2000)
        with self.assertRaises(PolylineBoundaryError):
            build_polyline_boundary(lines, selected - 1)

    def test_auto_rejects_invalid_distances_and_unbridgeable_lines(self) -> None:
        line = LineString([(-80, 35), (-79.999, 35)])
        for requested in (-1, float("nan"), float("inf")):
            with self.subTest(requested=requested), self.assertRaises(PolylineBoundaryError):
                build_polyline_boundary_with_recommended_buffer([line], requested)
        with self.assertRaisesRegex(PolylineBoundaryError, "within 2000 ft"):
            build_polyline_boundary_with_recommended_buffer(
                [line, LineString([(-79.9, 35), (-79.899, 35)])], 0)


class PerSidePolylineTests(TestCase):
    def test_equal_sides_match_unified_and_swapped_reverse_matches(self):
        from polyline_boundary import build_per_side_polyline_boundary
        lines = [LineString([(-80, 35), (-79.99, 35), (-79.99, 35.01)])]
        for distance in (0.005, 50, 350):
            with self.subTest(distance=distance):
                ordinary = build_polyline_boundary(lines, distance).final_polygon_projected
                sides = build_per_side_polyline_boundary(lines, distance, distance).final_polygon_projected
                self.assertTrue(sides.equals(ordinary))
        for left, right in ((350,150), (150,350), (0,100), (100,0), (0.005,0.01)):
            with self.subTest(left=left,right=right):
                forward = build_per_side_polyline_boundary(lines,left,right).final_polygon_projected
                reverse = build_per_side_polyline_boundary([LineString(list(lines[0].coords)[::-1])],right,left).final_polygon_projected
                self.assertTrue(forward.is_valid)
                self.assertEqual(forward.geom_type,'Polygon')
                self.assertLess(forward.symmetric_difference(reverse).area/forward.area,1e-6)

    def test_straight_side_extents_and_rounded_endpoints(self):
        from pyproj import Transformer
        from polyline_boundary import build_per_side_polyline_boundary
        tr = Transformer.from_crs(32617,4326,always_xy=True)
        line = LineString([tr.transform(400000,3800000),tr.transform(400500,3800000)])
        result = build_per_side_polyline_boundary([line],150,50)
        minx,miny,maxx,maxy = result.final_polygon_projected.bounds
        self.assertAlmostEqual(miny,3800000-50*.3048,places=5)
        self.assertAlmostEqual(maxy,3800000+150*.3048,places=5)
        self.assertAlmostEqual(minx,400000-100*.3048,places=5)
        self.assertAlmostEqual(maxx,400500+100*.3048,places=5)

    def test_duplicate_endpoints_hairpins_and_large_ratio(self):
        from polyline_boundary import build_per_side_polyline_boundary, _project_linework
        for coords in [
            [(-80,35),(-80,35),(-79.99,35),(-79.99,35)],
            [(-80,35),(-79.99,35),(-79.99,35.0001),(-80,35.0001)],
        ]:
            lines=[LineString(coords)]
            for left,right in [(1000,1),(1,1000),(100,0)]:
                r=build_per_side_polyline_boundary(lines,left,right)
                self.assertTrue(r.final_polygon_projected.is_valid)
                self.assertTrue(r.final_polygon_projected.buffer(2e-6).covers(_project_linework(lines).projected_linework))
