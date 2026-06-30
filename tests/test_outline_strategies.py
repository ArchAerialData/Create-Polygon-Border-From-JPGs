from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

import numpy as np
from shapely.geometry import MultiPoint, Point, Polygon

from tests.geometry_test_utils import lawnmower_xy, points_from_xy

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from camera_preflight import analyze_camera_preflight  # noqa: E402
from outline_strategies import (  # noqa: E402
    OUTLINE_MODE_AUTO,
    OUTLINE_MODE_LAWNMOWER,
    OUTLINE_MODE_ROUTE_AWARE,
    STRATEGY_CONCAVE,
    STRATEGY_LAWNMOWER,
    STRATEGY_ROUTE_AWARE,
    OutlineCandidate,
    evaluate_candidate,
    select_outline,
)


class OutlineStrategyTests(TestCase):
    def test_lawnmower_uses_outermost_cameras(self) -> None:
        gps_points, projected = points_from_xy(lawnmower_xy(rows=5, columns=9))
        preflight = analyze_camera_preflight(gps_points, projected)

        selection = select_outline(
            mode=OUTLINE_MODE_LAWNMOWER,
            projected_points=projected,
            preflight=preflight,
            concave_ratio=0.15,
            section_count=1,
        )

        self.assertEqual(selection.selected.strategy, STRATEGY_LAWNMOWER)
        self.assertTrue(selection.selected.accepted)
        self.assertLessEqual(len(selection.selected.polygon_projected.exterior.coords), 70)

    def test_lawnmower_rejects_low_confidence_rows(self) -> None:
        coordinates = [(0, 0), (30, 5), (5, 80), (90, 70), (35, 35), (80, 5)]
        gps_points, projected = points_from_xy(coordinates)
        preflight = analyze_camera_preflight(gps_points, projected)

        selection = select_outline(
            mode=OUTLINE_MODE_LAWNMOWER,
            projected_points=projected,
            preflight=preflight,
            concave_ratio=0.15,
            section_count=1,
        )

        self.assertEqual(selection.selected.strategy, STRATEGY_CONCAVE)
        self.assertIn("rejected", selection.fallback_reason)

    def test_route_trace_preserves_l_shape_corner(self) -> None:
        coordinates = [
            (0, 0),
            (20, 0),
            (40, 0),
            (60, 0),
            (60, 20),
            (60, 40),
            (60, 60),
            (60, 80),
        ]
        gps_points, projected = points_from_xy(coordinates)
        preflight = analyze_camera_preflight(gps_points, projected)

        selection = select_outline(
            mode=OUTLINE_MODE_ROUTE_AWARE,
            projected_points=projected,
            preflight=preflight,
            concave_ratio=0.15,
            section_count=1,
        )

        self.assertEqual(selection.selected.strategy, STRATEGY_ROUTE_AWARE)
        self.assertFalse(selection.selected.polygon_projected.covers(Point(20, 40)))

    def test_route_trace_rejects_bad_order(self) -> None:
        coordinates = [(0, 0), (60, 0), (0, 80), (60, 80), (0, 40), (60, 40)]
        gps_points, projected = points_from_xy(coordinates)
        preflight = analyze_camera_preflight(gps_points, projected)

        selection = select_outline(
            mode=OUTLINE_MODE_ROUTE_AWARE,
            projected_points=projected,
            preflight=preflight,
            concave_ratio=0.15,
            section_count=1,
        )

        self.assertEqual(selection.selected.strategy, STRATEGY_CONCAVE)
        self.assertIn("route_aware rejected", selection.fallback_reason)

    def test_auto_falls_back_to_concave_when_uncertain(self) -> None:
        coordinates = [(0, 0), (30, 5), (5, 80), (90, 70), (35, 35), (80, 5)]
        gps_points, projected = points_from_xy(coordinates)
        preflight = analyze_camera_preflight(gps_points, projected)

        selection = select_outline(
            mode=OUTLINE_MODE_AUTO,
            projected_points=projected,
            preflight=preflight,
            concave_ratio=0.15,
            section_count=1,
        )

        self.assertEqual(selection.selected.strategy, STRATEGY_CONCAVE)
        self.assertTrue(selection.fallback_reason)

    def test_candidate_rejected_when_area_ratio_is_implausible(self) -> None:
        fallback = Polygon([(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)])
        candidate = OutlineCandidate(
            STRATEGY_LAWNMOWER,
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]),
            0.9,
            1.0,
        )

        evaluate_candidate(candidate, fallback, MultiPoint([(0, 0), (1, 1)]), 1)

        self.assertFalse(candidate.accepted)
        self.assertIn("area ratio is implausible", candidate.rejection_reasons)

    def test_candidate_rejected_when_required_points_are_not_covered(self) -> None:
        fallback = Polygon([(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)])
        candidate = OutlineCandidate(
            STRATEGY_ROUTE_AWARE,
            Polygon([(0, 0), (50, 0), (50, 50), (0, 50), (0, 0)]),
            0.9,
            1.0,
        )

        evaluate_candidate(candidate, fallback, MultiPoint([(10, 10), (90, 90)]), 1)

        self.assertFalse(candidate.accepted)
        self.assertIn("required camera points are not covered", candidate.rejection_reasons)

    def test_candidate_rejected_when_geometry_is_disconnected_for_sections(self) -> None:
        fallback = Polygon([(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)])
        disconnected = MultiPoint([(0, 0), (1, 0), (50, 50), (51, 50)]).buffer(1)
        candidate = OutlineCandidate(STRATEGY_ROUTE_AWARE, disconnected, 0.9, 1.0)

        evaluate_candidate(candidate, fallback, MultiPoint([(0, 0), (50, 50)]), 2)

        self.assertFalse(candidate.accepted)
        self.assertIn("geometry is disconnected", candidate.rejection_reasons)
