from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

from pyproj import Transformer
from shapely.geometry import Polygon, box

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from natural_sectioning import (  # noqa: E402
    NaturalSplitError,
    build_natural_sections,
)


class NaturalSectioningTests(TestCase):
    def test_selected_east_west_split_direction_creates_stacked_sections(self) -> None:
        parent = box(0, 0, 120, 60)

        sections, diagnostics = build_natural_sections(
            parent,
            3,
            0.0,
            "Crop",
            _identity_transformer(),
            split_direction_deg=0.0,
        )

        self.assertEqual(len(sections), 3)
        self.assertAlmostEqual(diagnostics.selected_split_direction_deg, 0.0)
        self.assertLessEqual(diagnostics.area_variance_pct, 1e-6)
        self.assertLess(sections[0].polygon_projected.centroid.y, sections[1].polygon_projected.centroid.y)
        self.assertLess(sections[1].polygon_projected.centroid.y, sections[2].polygon_projected.centroid.y)
        self.assertTrue(all(not section.polygon_projected.interiors for section in sections))

    def test_selected_north_south_split_direction_creates_side_by_side_sections(self) -> None:
        parent = box(0, 0, 120, 60)

        sections, diagnostics = build_natural_sections(
            parent,
            3,
            0.0,
            "Crop",
            _identity_transformer(),
            split_direction_deg=90.0,
        )

        self.assertEqual(len(sections), 3)
        self.assertAlmostEqual(diagnostics.selected_split_direction_deg, 90.0)
        centroid_xs = sorted(section.polygon_projected.centroid.x for section in sections)
        self.assertLess(centroid_xs[0], centroid_xs[1])
        self.assertLess(centroid_xs[1], centroid_xs[2])

    def test_custom_direction_is_normalized(self) -> None:
        sections, diagnostics = build_natural_sections(
            box(0, 0, 120, 60),
            2,
            0.0,
            "Crop",
            _identity_transformer(),
            split_direction_deg=270.0,
        )

        self.assertEqual(len(sections), 2)
        self.assertAlmostEqual(diagnostics.selected_split_direction_deg, 90.0)

    def test_overlap_expands_adjacent_sections_along_split_normal(self) -> None:
        sections, _diagnostics = build_natural_sections(
            box(0, 0, 120, 60),
            2,
            10.0,
            "Crop",
            _identity_transformer(),
            split_direction_deg=0.0,
        )

        self.assertGreater(
            sections[0].polygon_projected.bounds[3],
            sections[1].polygon_projected.bounds[1],
        )

    def test_disconnected_section_is_rejected(self) -> None:
        u_shape = Polygon(
            [
                (0, 0),
                (10, 0),
                (10, 10),
                (8, 10),
                (8, 2),
                (2, 2),
                (2, 10),
                (0, 10),
                (0, 0),
            ]
        )

        with self.assertRaises(NaturalSplitError):
            build_natural_sections(
                u_shape,
                2,
                0.0,
                "Crop",
                _identity_transformer(),
                split_direction_deg=0.0,
            )


def _identity_transformer() -> Transformer:
    return Transformer.from_crs(3857, 3857, always_xy=True)
