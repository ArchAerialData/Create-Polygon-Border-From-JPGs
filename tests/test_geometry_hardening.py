from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

from shapely.geometry import Polygon

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from geometry_hardening import (  # noqa: E402
    EXPORT_MAX_SEGMENT_M,
    buffer_projected_geometry,
    densify_projected_geometry,
    max_exterior_segment_length,
)


class GeometryHardeningTests(TestCase):
    def test_segmentize_caps_projected_segments(self) -> None:
        polygon = Polygon([(0, 0), (125, 0), (125, 20), (0, 20), (0, 0)])

        densified = densify_projected_geometry(polygon, EXPORT_MAX_SEGMENT_M)

        self.assertLessEqual(
            max_exterior_segment_length(densified),
            EXPORT_MAX_SEGMENT_M + 1e-9,
        )
        self.assertAlmostEqual(densified.area, polygon.area, places=6)

    def test_buffer_cleanup_returns_valid_polygon(self) -> None:
        bowtie = Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)])

        cleaned = buffer_projected_geometry(bowtie, 5.0)

        self.assertFalse(cleaned.is_empty)
        self.assertTrue(cleaned.is_valid)
        self.assertGreater(cleaned.area, 0)

    def test_zero_buffer_does_not_create_extra_shape(self) -> None:
        polygon = Polygon([(0, 0), (10, 0), (10, 5), (0, 5), (0, 0)])

        result = buffer_projected_geometry(polygon, 0.0)

        self.assertTrue(result.equals_exact(polygon, 0.0))
        self.assertAlmostEqual(result.area, polygon.area, places=9)
