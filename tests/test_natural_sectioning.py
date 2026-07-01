from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

from pyproj import Transformer
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from natural_sectioning import (  # noqa: E402
    NaturalSplitError,
    _dominant_polygon_orientation_deg,
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

    def test_minor_disconnected_overlap_sliver_is_discarded(self) -> None:
        parent = _minor_overlap_sliver_parent()

        sections, diagnostics = build_natural_sections(
            parent,
            2,
            20.0,
            "Crop",
            _identity_transformer(),
            split_direction_deg=0.0,
        )

        self.assertEqual(len(sections), 2)
        self.assertLessEqual(diagnostics.area_variance_pct, 1e-6)
        self.assertTrue(
            all(section.polygon_projected.geom_type == "Polygon" for section in sections)
        )
        self.assertLessEqual(sections[1].polygon_projected.bounds[2], 100.0)

    def test_meaningful_disconnected_overlap_is_rejected(self) -> None:
        with self.assertRaisesRegex(NaturalSplitError, "overlap"):
            build_natural_sections(
                _meaningful_overlap_disconnection_parent(),
                2,
                20.0,
                "Crop",
                _identity_transformer(),
                split_direction_deg=0.0,
            )

    def test_auto_split_retries_candidate_directions_for_corridor(self) -> None:
        parent = _auto_retry_corridor_parent()
        dominant_direction = _dominant_polygon_orientation_deg(parent)
        with self.assertRaisesRegex(NaturalSplitError, "base section"):
            build_natural_sections(
                parent,
                2,
                20.0,
                "Crop",
                _identity_transformer(),
                split_direction_deg=dominant_direction,
            )

        sections, diagnostics = build_natural_sections(
            parent,
            2,
            20.0,
            "Crop",
            _identity_transformer(),
            split_direction_deg=None,
        )

        self.assertEqual(len(sections), 2)
        self.assertNotAlmostEqual(
            diagnostics.selected_split_direction_deg,
            dominant_direction,
        )
        self.assertTrue(all(section.polygon_projected.is_valid for section in sections))


def _identity_transformer() -> Transformer:
    return Transformer.from_crs(3857, 3857, always_xy=True)


def _minor_overlap_sliver_parent() -> Polygon:
    return _single_polygon_union(
        [
            box(0, 0, 100, 1000),
            box(100, 488, 120, 488.5),
            box(119, 488.5, 123, 493.5),
        ]
    )


def _meaningful_overlap_disconnection_parent() -> Polygon:
    return _single_polygon_union(
        [
            box(0, 0, 1000, 1000),
            box(1000, 488, 1200, 488.5),
            box(1199, 488.5, 1599, 493.5),
        ]
    )


def _auto_retry_corridor_parent() -> Polygon:
    return LineString(
        [
            (0, 0),
            (2000, 2000),
            (4000, 1000),
            (6000, 3000),
        ]
    ).buffer(100, cap_style="flat", join_style="mitre")


def _single_polygon_union(parts: list[Polygon]) -> Polygon:
    geometry = unary_union(parts)
    if not isinstance(geometry, Polygon):
        raise AssertionError(
            f"Expected test geometry to be one polygon, got {geometry.geom_type}."
        )
    return geometry
