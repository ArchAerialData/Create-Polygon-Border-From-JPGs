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
