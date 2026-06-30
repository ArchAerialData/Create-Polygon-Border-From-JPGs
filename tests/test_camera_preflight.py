from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys
from unittest import TestCase

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tests.geometry_test_utils import (
    lawnmower_xy,
    points_from_xy,
    rectangle_trace_xy,
    synthetic_point,
)

from camera_preflight import (  # noqa: E402
    ORDER_EXIF_DATETIME,
    ORDER_FILENAME,
    PATTERN_BOUNDARY_TRACE,
    PATTERN_LAWNMOWER,
    PATTERN_SCATTER_UNKNOWN,
    analyze_camera_preflight,
)


class CameraPreflightTests(TestCase):
    def test_detects_lawnmower_parallel_rows(self) -> None:
        gps_points, projected = points_from_xy(lawnmower_xy(rows=5, columns=10))

        result = analyze_camera_preflight(gps_points, projected)

        self.assertEqual(result.pattern, PATTERN_LAWNMOWER)
        self.assertGreaterEqual(result.confidence, 0.70)
        self.assertGreaterEqual(result.metrics.row_count, 5)

    def test_detects_boundary_trace(self) -> None:
        gps_points, projected = points_from_xy(rectangle_trace_xy())

        result = analyze_camera_preflight(gps_points, projected)

        self.assertEqual(result.pattern, PATTERN_BOUNDARY_TRACE)
        self.assertGreaterEqual(result.confidence, 0.70)

    def test_detects_scatter_unknown(self) -> None:
        coordinates = [
            (0, 0),
            (50, 10),
            (5, 80),
            (90, 70),
            (35, 35),
            (80, 5),
            (15, 45),
        ]
        gps_points, projected = points_from_xy(coordinates)

        result = analyze_camera_preflight(gps_points, projected)

        self.assertEqual(result.pattern, PATTERN_SCATTER_UNKNOWN)
        self.assertLess(result.confidence, 0.60)

    def test_identifies_large_gap_candidates(self) -> None:
        coordinates = [(0, 0), (10, 0), (20, 0), (500, 0), (510, 0), (520, 0)]
        gps_points, projected = points_from_xy(coordinates)

        result = analyze_camera_preflight(gps_points, projected)

        self.assertIn(3, result.section_breaks)
        self.assertTrue(result.warnings)

    def test_missing_capture_order_uses_filename_fallback(self) -> None:
        gps_points = [
            synthetic_point("b.jpg", 10, 0),
            synthetic_point("a.jpg", 0, 0),
            synthetic_point("c.jpg", 20, 0),
        ]
        projected = np.array([(10, 0), (0, 0), (20, 0)], dtype=float)

        result = analyze_camera_preflight(gps_points, projected)

        self.assertEqual(result.order_source, ORDER_FILENAME)
        self.assertEqual(result.ordered_indices, [1, 0, 2])

    def test_complete_capture_times_use_exif_order(self) -> None:
        start = datetime(2026, 6, 30, 12, 0, 0)
        gps_points = [
            synthetic_point("b.jpg", 10, 0, start + timedelta(seconds=10)),
            synthetic_point("a.jpg", 0, 0, start),
            synthetic_point("c.jpg", 20, 0, start + timedelta(seconds=20)),
        ]
        projected = np.array([(10, 0), (0, 0), (20, 0)], dtype=float)

        result = analyze_camera_preflight(gps_points, projected)

        self.assertEqual(result.order_source, ORDER_EXIF_DATETIME)
        self.assertEqual(result.ordered_indices, [1, 0, 2])
