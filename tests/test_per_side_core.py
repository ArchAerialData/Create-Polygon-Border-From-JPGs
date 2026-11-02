from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from pyproj import Transformer
from shapely.geometry import Polygon
from shapely.ops import unary_union

from tests.test_polyline_compatibility import LINE, write_kmz
from buffer_settings import BufferSettings
from jpg_boundary_kmz_core import (
    BoundaryError, GENERATION_PROFILE_EXPORT, GENERATION_PROFILE_PREVIEW,
    buffer_settings_from_metadata, format_summary, generate_boundary_from_input, save_kmz,
)


class PerSideCoreTests(TestCase):
    def test_equal_sides_preserve_unified_preview_and_explicit_width(self):
        with TemporaryDirectory() as tmp:
            path = write_kmz(tmp)
            unified = generate_boundary_from_input(path, 350, generation_profile=GENERATION_PROFILE_PREVIEW)
            side = generate_boundary_from_input(path, 999, buffer_settings=BufferSettings.per_side(350, 350),
                                                generation_profile=GENERATION_PROFILE_PREVIEW)
            self.assertTrue(unified.final_polygon_projected.equals(side.final_polygon_projected))
            self.assertIsNone(side.metadata.buffer_ft)
            self.assertEqual(buffer_settings_from_metadata(side.metadata), BufferSettings.per_side(350, 350))
            self.assertEqual(side.metadata.polyline_buffer_candidate_count, 0)
            self.assertIn("Left 350 ft / Right 350 ft", format_summary(side.metadata))

    def test_sections_and_saved_exports_preserve_parent_width_and_source(self):
        with TemporaryDirectory() as tmp:
            path = write_kmz(tmp)
            settings = BufferSettings.per_side(350, 150)
            parent = generate_boundary_from_input(path, 0, buffer_settings=settings,
                                                  generation_profile=GENERATION_PROFILE_PREVIEW).final_polygon_projected
            for count in (1, 3, 4, 8, 12):
                for overlap in (0, 50):
                    for profile in (GENERATION_PROFILE_PREVIEW, GENERATION_PROFILE_EXPORT):
                        with self.subTest(count=count, overlap=overlap, profile=profile):
                            result = generate_boundary_from_input(
                                path, 0, buffer_settings=settings, section_count=count, overlap_ft=overlap,
                                shape_label="Survey", generation_profile=profile)
                            self.assertEqual(buffer_settings_from_metadata(result.metadata), settings)
                            polygons = [s.polygon_projected for s in result.sections] or [result.final_polygon_projected]
                            self.assertEqual(len(polygons), count)
                            self.assertTrue(all(p.is_valid and p.geom_type == "Polygon" and p.area > 0 for p in polygons))
                            output_union = unary_union(polygons)
                            source = unary_union(result.source_lines_projected)
                            self.assertTrue(output_union.buffer(2e-6).covers(source))
                            if profile == GENERATION_PROFILE_PREVIEW:
                                self.assertLess(output_union.symmetric_difference(parent).area / parent.area, 1e-8)
                                self.assertTrue(result.final_polygon_projected.equals(parent))
                            else:
                                self.assertLessEqual(result.metadata.vector_simplification_max_deviation_ft, 5.0001)
                                self.assertLessEqual(result.metadata.vector_simplification_area_delta_pct, 1.0001)
                                output = save_kmz(result, Path(tmp) / "output.kmz")
                                with ZipFile(output) as archive:
                                    xml = archive.read("doc.kml")
                                self.assertIn(b"Left 350 ft / Right 150 ft", xml)
                                root = ET.fromstring(xml)
                                rings = root.findall(".//{*}Polygon/{*}outerBoundaryIs/{*}LinearRing/{*}coordinates")
                                self.assertEqual(len(rings), count)
                                transform = Transformer.from_crs(4326, result.metadata.epsg, always_xy=True)
                                saved = [Polygon([transform.transform(*map(float, token.split(",")[:2]))
                                                  for token in ring.text.split()]) for ring in rings]
                                # Nanometre projection round-off can merge or separate
                                # zero-overlap seams, changing a union's *internal*
                                # boundaries without changing any exported crop.
                                # Check every crop, then the complete covered area.
                                for original, restored in zip(polygons, saved):
                                    self.assertLess(original.boundary.hausdorff_distance(restored.boundary), 0.002)
                                self.assertLess(unary_union(saved).symmetric_difference(output_union).area / output_union.area, 1e-8)

    def test_zero_side_export_keeps_source_even_when_simplified(self):
        # Bends put source vertices directly on the output edge when a side is zero.
        body = "<LineString><coordinates>-80,35 -79.995,35 -79.995,35.003 -79.99,35.003</coordinates></LineString>"
        with TemporaryDirectory() as tmp:
            path = write_kmz(tmp, body)
            for count in (1, 4):
                for left, right in ((0, 100), (100, 0)):
                    with self.subTest(count=count, left=left):
                        result = generate_boundary_from_input(path, 0, section_count=count,
                            buffer_settings=BufferSettings.per_side(left, right), generation_profile=GENERATION_PROFILE_EXPORT)
                        polygons = [s.polygon_projected for s in result.sections] or [result.final_polygon_projected]
                        self.assertTrue(unary_union(polygons).buffer(2e-6).covers(unary_union(result.source_lines_projected)))

    def test_backend_rejects_ineligible_inputs_and_disconnected_explicit_buffers(self):
        with TemporaryDirectory() as tmp:
            side = BufferSettings.per_side(10, 20)
            paths = [Path(tmp), write_kmz(tmp, name="line.kml"),
                     write_kmz(tmp, LINE + "<Point/>", "mixed.kmz")]
            for path in paths:
                with self.subTest(path=path), self.assertRaises(BoundaryError):
                    generate_boundary_from_input(path, 0, buffer_settings=side)
            far_line = "<LineString><coordinates>-79.9,35 -79.89,35</coordinates></LineString>"
            path = write_kmz(tmp, LINE + far_line)
            for settings in (side, BufferSettings.per_side(10, 10)):
                with self.subTest(settings=settings), self.assertRaises(BoundaryError):
                    generate_boundary_from_input(path, 999, buffer_settings=settings)
