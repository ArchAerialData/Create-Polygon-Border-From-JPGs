from __future__ import annotations

import sys
import math
from pathlib import Path
from unittest import TestCase

from pyproj import Transformer
from shapely.affinity import rotate, scale, translate
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jpg_boundary_kmz_core import BoundarySection, _build_sections, _simplify_vector_sections  # noqa: E402
from natural_sectioning import build_natural_sections  # noqa: E402


def branched_corridor():
    # A trunk and several unequal branches: exact equal-area cuts used to run
    # lengthwise down the trunk, leaving two long, half-width crop strips.
    paths = [
        [(0, 1300), (0, 0), (1400, 0)],
        [(-800, 1100), (0, 1100)],
        [(0, 900), (450, 900)],
        [(0, 1300), (250, 1300)],
        [(0, 500), (80, 500)],
    ]
    return unary_union([LineString(path) for path in paths]).buffer(60, quad_segs=16)


class OrthoCropSectionTests(TestCase):
    def test_six_crops_avoid_material_pointed_ends_near_branches(self):
        parent = branched_corridor()
        identity = Transformer.from_crs(32617, 32617, always_xy=True)
        for overlap in (0, 15.24):
            with self.subTest(overlap=overlap):
                sections, _ = _build_sections(parent, 6, overlap, "Crop", identity, densify_sections=False)
                for section in sections:
                    ring = list(section.polygon_projected.simplify(0.2, preserve_topology=True).exterior.coords)[:-1]
                    for i, point in enumerate(ring):
                        before, after = ring[i-1], ring[(i+1) % len(ring)]
                        u = (before[0]-point[0], before[1]-point[1])
                        v = (after[0]-point[0], after[1]-point[1])
                        lu, lv = math.hypot(*u), math.hypot(*v)
                        # Tiny rounding intersections at overlap edges are not
                        # the long pointed crop ends visible in the report.
                        if min(lu, lv) < 20:
                            continue
                        cosine = (u[0]*v[0] + u[1]*v[1]) / (lu*lv)
                        angle = math.degrees(math.acos(max(-1, min(1, cosine))))
                        self.assertGreaterEqual(angle, 55)

    def test_export_simplification_cannot_open_an_interior_crop_gap(self):
        # Both polygons pass individual simplification limits, but their unequal
        # areas lead to different retained vertices on the SAME shallow seam.
        left = Polygon([(0, 0), (50, 0), (50.5, 50), (50, 100), (0, 100)])
        right = Polygon([(50.5, 50), (50, 0), (55, 0), (55, 100), (50, 100)])
        sections = [
            BoundarySection(i, 2, f"Crop {i}", part.area, part, part)
            for i, part in enumerate((left, right), 1)
        ]
        simplified, stats = _simplify_vector_sections(
            sections, Transformer.from_crs(32617, 32617, always_xy=True),
        )
        union = unary_union([s.polygon_projected for s in simplified])
        self.assertLess(box(0, 0, 55, 100).difference(union).area, 1e-6)
        self.assertEqual(stats.before_vertices, stats.after_vertices)
        self.assertEqual(stats.max_deviation_m, 0)

    def test_branched_crops_keep_full_trunk_width_at_different_scales_and_rotations(self):
        identity = Transformer.from_crs(32617, 32617, always_xy=True)
        for angle, size in ((0, 1), (35, 1), (0, 0.1), (35, 10)):
            with self.subTest(angle=angle, scale=size):
                def place(geometry):
                    return translate(
                        rotate(scale(geometry, xfact=size, yfact=size, origin=(0, 0)),
                               angle, origin=(0, 0)),
                        xoff=450000, yoff=3800000,
                    )

                parent = place(branched_corridor())
                sections, diagnostics = _build_sections(
                    parent, 4, 0, "Crop", identity, densify_sections=False,
                )
                parts = [section.polygon_projected for section in sections]
                self.assertEqual(len(parts), 4)
                self.assertTrue(all(p.is_valid and not p.interiors for p in parts))
                self.assertLess(unary_union(parts).symmetric_difference(parent).area / parent.area, 1e-8)
                self.assertLess(abs(sum(p.area for p in parts) / parent.area - 1), 1e-8)
                # Clean junctions may use the bounded 35% fallback when 20%
                # balance would force an acute end on this unequal network.
                self.assertLessEqual(diagnostics.area_variance_pct, 35.0001)

                # Measure actual usable crop width, independently of the search
                # score. Short transverse seams may cross a few transects; a
                # longitudinal sliver must not split hundreds of metres of trunk.
                partial_transects = 0
                for y in range(100, 1250, 5):
                    transect = place(LineString([(-59, y), (59, y)]))
                    coverage = max(p.intersection(transect).length for p in parts) / transect.length
                    partial_transects += coverage < 0.99
                self.assertLess(partial_transects * 5, 150)

    def test_overlap_preserves_parent_and_repeatable_section_assignment(self):
        parent = branched_corridor()
        identity = Transformer.from_crs(32617, 32617, always_xy=True)
        first, _ = _build_sections(parent, 4, 0, "Crop", identity, densify_sections=False)
        repeated, _ = _build_sections(parent, 4, 0, "Crop", identity, densify_sections=False)
        overlapped, _ = _build_sections(parent, 4, 15.24, "Crop", identity, densify_sections=False)
        for original, repeat, expanded in zip(first, repeated, overlapped):
            self.assertEqual(original.display_name, repeat.display_name)
            self.assertTrue(original.polygon_projected.equals_exact(repeat.polygon_projected, 1e-8))
            self.assertLess(original.polygon_projected.difference(expanded.polygon_projected).area, 1e-6)
            self.assertLess(expanded.polygon_projected.difference(parent).area, 1e-6)
            self.assertAlmostEqual(original.base_area_acres, expanded.base_area_acres)
        self.assertLess(unary_union([s.polygon_projected for s in overlapped]).symmetric_difference(parent).area, 1e-6)

    def test_auto_cuts_across_long_rectangle_while_explicit_direction_is_respected(self):
        identity = Transformer.from_crs(32617, 32617, always_xy=True)
        parent = box(0, 0, 1200, 100)
        auto, _ = build_natural_sections(parent, 4, 0, "Crop", identity, densify_sections=False)
        for section in auto:
            minx, miny, maxx, maxy = section.polygon_projected.bounds
            self.assertAlmostEqual(maxy - miny, 100)
            self.assertAlmostEqual(maxx - minx, 300)
        manual, _ = build_natural_sections(
            parent, 4, 0, "Crop", identity, split_direction_deg=0,
            densify_sections=False,
        )
        for section in manual:
            minx, miny, maxx, maxy = section.polygon_projected.bounds
            self.assertAlmostEqual(maxx - minx, 1200)
            self.assertAlmostEqual(maxy - miny, 25)
