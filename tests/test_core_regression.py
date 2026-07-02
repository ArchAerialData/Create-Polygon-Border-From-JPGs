from __future__ import annotations

import math
import sys
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from pyproj import CRS, Transformer
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from tests.geometry_test_utils import synthetic_point

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from jpg_boundary_kmz_core import (  # noqa: E402
    BoundaryError,
    GENERATION_PROFILE_EXPORT,
    GENERATION_PROFILE_PREVIEW,
    format_summary,
    generate_boundary,
    generate_boundary_from_input,
    generate_boundary_from_kmz,
    save_kmz,
    _strict_single_polygon,
)
from natural_sectioning import NaturalSplitError, build_natural_sections  # noqa: E402
from outline_strategies import OUTLINE_MODE_CONCAVE  # noqa: E402


class CoreRegressionTests(TestCase):
    def test_kmz_input_still_works(self) -> None:
        with TemporaryDirectory() as tmp:
            kmz_path = Path(tmp) / "source.kmz"
            _write_test_kmz(kmz_path)

            result = generate_boundary_from_kmz(kmz_path, buffer_ft=0.0)

            self.assertEqual(result.metadata.input_type, "KMZ polygon")
            self.assertTrue(result.final_polygon_projected.is_valid)

    def test_kml_polyline_input_routes_to_linework_buffer(self) -> None:
        with TemporaryDirectory() as tmp:
            kml_path = Path(tmp) / "source_lines.kml"
            _write_text_kml(kml_path, _line_kml_body())

            result = generate_boundary_from_input(kml_path, buffer_ft=100.0)

            self.assertEqual(result.metadata.input_type, "KML polyline")
            self.assertEqual(result.metadata.source_line_count, 1)
            self.assertGreater(result.metadata.source_point_count, 1)
            self.assertEqual(len(result.final_polygon_projected.interiors), 0)

    def test_kmz_polyline_input_routes_to_linework_buffer(self) -> None:
        with TemporaryDirectory() as tmp:
            kmz_path = Path(tmp) / "source_lines.kmz"
            _write_test_kmz(kmz_path, body=_line_kml_body())

            result = generate_boundary_from_input(kmz_path, buffer_ft=100.0)

            self.assertEqual(result.metadata.input_type, "KMZ polyline")
            self.assertEqual(result.metadata.source_line_count, 1)
            self.assertEqual(len(result.final_polygon_projected.interiors), 0)

    def test_linestring_input_zero_buffer_auto_selects_positive_buffer(self) -> None:
        with TemporaryDirectory() as tmp:
            kml_path = Path(tmp) / "source_lines.kml"
            _write_text_kml(kml_path, _line_kml_body())

            result = generate_boundary_from_input(kml_path, buffer_ft=0.0)

            self.assertEqual(result.metadata.input_type, "KML polyline")
            self.assertEqual(result.metadata.polyline_requested_buffer_ft, 0.0)
            self.assertGreater(result.metadata.buffer_ft, 0.0)
            self.assertEqual(
                result.metadata.buffer_ft,
                result.metadata.polyline_selected_buffer_ft,
            )
            self.assertEqual(len(result.final_polygon_projected.interiors), 0)

    def test_mixed_vector_input_uses_lines_and_reports_ignored_polygon(self) -> None:
        with TemporaryDirectory() as tmp:
            kml_path = Path(tmp) / "mixed.kml"
            _write_text_kml(kml_path, _line_kml_body() + _polygon_kml_body())

            result = generate_boundary_from_input(kml_path, buffer_ft=100.0)
            summary = format_summary(result.metadata)

            self.assertEqual(result.metadata.input_type, "KML polyline")
            self.assertEqual(result.metadata.ignored_polygon_count, 1)
            self.assertIn("Using source LineStrings; polygons ignored", summary)

    def test_single_polygon_kml_input_works(self) -> None:
        with TemporaryDirectory() as tmp:
            kml_path = Path(tmp) / "source_polygon.kml"
            _write_text_kml(kml_path, _polygon_kml_body())

            result = generate_boundary_from_input(kml_path, buffer_ft=0.0)

            self.assertEqual(result.metadata.input_type, "KML polygon")
            self.assertTrue(result.final_polygon_projected.is_valid)

    def test_holed_polygon_kml_input_is_exterior_only(self) -> None:
        with TemporaryDirectory() as tmp:
            kml_path = Path(tmp) / "holed_polygon.kml"
            _write_text_kml(kml_path, _polygon_kml_body(hole=True))

            result = generate_boundary_from_input(kml_path, buffer_ft=0.0)

            self.assertEqual(result.metadata.input_type, "KML polygon")
            self.assertEqual(result.metadata.ignored_interior_ring_count, 1)
            self.assertEqual(len(result.final_polygon_projected.interiors), 0)

    def test_dense_polygon_kml_input_is_automatically_simplified(self) -> None:
        with TemporaryDirectory() as tmp:
            kml_path = Path(tmp) / "dense_polygon.kml"
            _write_text_kml(kml_path, _dense_polygon_kml_body())

            result = generate_boundary_from_input(kml_path, buffer_ft=0.0)
            summary = format_summary(result.metadata)

            self.assertLess(
                result.metadata.vector_simplification_after_vertices,
                result.metadata.vector_simplification_before_vertices,
            )
            self.assertEqual(
                result.metadata.vector_simplification_after_vertices,
                len(result.final_polygon_wgs84.exterior.coords),
            )
            self.assertLessEqual(
                result.metadata.vector_simplification_max_deviation_ft,
                5.001,
            )
            self.assertLessEqual(
                result.metadata.vector_simplification_area_delta_pct,
                1.001,
            )
            self.assertEqual(len(result.final_polygon_projected.interiors), 0)
            self.assertIn("Vector simplification:", summary)

    def test_dense_polyline_kml_buffer_is_automatically_simplified(self) -> None:
        with TemporaryDirectory() as tmp:
            kml_path = Path(tmp) / "dense_line.kml"
            _write_text_kml(kml_path, _dense_line_kml_body())

            result = generate_boundary_from_input(kml_path, buffer_ft=120.0)

            self.assertEqual(result.metadata.input_type, "KML polyline")
            self.assertLess(
                result.metadata.vector_simplification_after_vertices,
                result.metadata.vector_simplification_before_vertices,
            )
            self.assertLessEqual(
                result.metadata.vector_simplification_max_deviation_ft,
                5.001,
            )
            self.assertLessEqual(
                result.metadata.vector_simplification_area_delta_pct,
                1.001,
            )
            self.assertEqual(len(result.final_polygon_projected.interiors), 0)

    def test_problem_polyline_kml_auto_selects_regular_buffer(self) -> None:
        kml_path = (
            ROOT
            / "test_data"
            / "new-failures-debugging"
            / "input-kml"
            / "photo_polylines_20260702_095008.kml"
        )
        self.assertTrue(kml_path.exists())

        for requested_buffer_ft in (0.0, 80.0, 84.0, 85.0):
            with self.subTest(requested_buffer_ft=requested_buffer_ft):
                result = generate_boundary_from_input(
                    kml_path,
                    buffer_ft=requested_buffer_ft,
                    generation_profile=GENERATION_PROFILE_PREVIEW,
                )

                self.assertEqual(result.metadata.input_type, "KML polyline")
                self.assertAlmostEqual(
                    result.metadata.polyline_requested_buffer_ft,
                    requested_buffer_ft,
                )
                self.assertGreaterEqual(
                    result.metadata.buffer_ft,
                    result.metadata.polyline_minimum_connected_buffer_ft,
                )
                self.assertEqual(
                    result.metadata.buffer_ft,
                    result.metadata.polyline_selected_buffer_ft,
                )
                self.assertLessEqual(
                    result.metadata.polyline_buffer_regularity_ratio,
                    result.metadata.polyline_buffer_regularity_target,
                )
                self.assertGreater(result.metadata.polyline_buffer_candidate_count, 0)
                self.assertTrue(result.metadata.polyline_buffer_adjustment_reason)
                self.assertTrue(result.final_polygon_projected.is_valid)
                self.assertEqual(len(result.final_polygon_projected.interiors), 0)

    def test_regular_explicit_polyline_buffer_is_not_adjusted(self) -> None:
        with TemporaryDirectory() as tmp:
            kml_path = Path(tmp) / "source_lines.kml"
            _write_text_kml(kml_path, _line_kml_body())

            result = generate_boundary_from_input(kml_path, buffer_ft=100.0)

            self.assertEqual(result.metadata.input_type, "KML polyline")
            self.assertEqual(result.metadata.buffer_ft, 100.0)
            self.assertEqual(result.metadata.polyline_requested_buffer_ft, 100.0)
            self.assertEqual(result.metadata.polyline_selected_buffer_ft, 100.0)
            self.assertFalse(result.metadata.polyline_buffer_adjustment_reason)
            self.assertLessEqual(
                result.metadata.polyline_buffer_regularity_ratio,
                result.metadata.polyline_buffer_regularity_target,
            )

    def test_vector_sections_are_simplified_and_export_outer_boundaries(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            kml_path = tmp_path / "dense_polygon.kml"
            output_path = tmp_path / "sections.kmz"
            _write_text_kml(kml_path, _dense_polygon_kml_body())

            result = generate_boundary_from_input(
                kml_path,
                buffer_ft=0.0,
                section_count=3,
                overlap_ft=0.0,
                shape_label="Crop",
                split_direction_deg=90.0,
            )
            to_wgs84 = Transformer.from_crs(
                CRS.from_epsg(result.metadata.epsg),
                4326,
                always_xy=True,
            )
            raw_sections, _diagnostics = build_natural_sections(
                result.final_polygon_projected,
                3,
                0.0,
                "Crop",
                to_wgs84,
                split_direction_deg=90.0,
            )

            self.assertEqual(len(result.sections), 3)
            self.assertLess(
                result.metadata.vector_simplification_after_vertices,
                result.metadata.vector_simplification_before_vertices,
            )
            self.assertEqual(
                result.metadata.vertex_count,
                sum(len(section.polygon_wgs84.exterior.coords) for section in result.sections),
            )
            for raw_section, simplified_section in zip(raw_sections, result.sections):
                self.assertLess(
                    len(simplified_section.polygon_projected.exterior.coords),
                    len(raw_section.polygon_projected.exterior.coords),
                )
                self.assertTrue(simplified_section.polygon_projected.is_valid)
                self.assertEqual(len(simplified_section.polygon_projected.interiors), 0)
                self.assertEqual(
                    simplified_section.display_name,
                    f"Crop ({simplified_section.index} of 3)",
                )

            save_kmz(result, output_path)
            with zipfile.ZipFile(output_path) as archive:
                kml_text = archive.read("doc.kml").decode("utf-8")
            self.assertEqual(kml_text.count("<Polygon"), 3)
            self.assertNotIn("innerBoundaryIs", kml_text)

    def test_vector_preview_profile_skips_export_simplification(self) -> None:
        with TemporaryDirectory() as tmp:
            kml_path = Path(tmp) / "dense_polygon.kml"
            _write_text_kml(kml_path, _dense_polygon_kml_body())

            result = generate_boundary_from_input(
                kml_path,
                buffer_ft=0.0,
                section_count=3,
                overlap_ft=0.0,
                shape_label="Crop",
                split_direction_deg=90.0,
                generation_profile=GENERATION_PROFILE_PREVIEW,
            )

            self.assertEqual(
                result.metadata.generation_profile,
                GENERATION_PROFILE_PREVIEW,
            )
            self.assertEqual(len(result.sections), 3)
            self.assertEqual(
                result.metadata.vector_simplification_before_vertices,
                result.metadata.vector_simplification_after_vertices,
            )
            self.assertTrue(
                all(section.polygon_projected.is_valid for section in result.sections)
            )
            with self.assertRaisesRegex(BoundaryError, "Preview-quality"):
                save_kmz(result, Path(tmp) / "preview_output.kmz")

    def test_invalid_generation_profile_is_rejected_for_vector_input(self) -> None:
        with TemporaryDirectory() as tmp:
            kml_path = Path(tmp) / "dense_polygon.kml"
            _write_text_kml(kml_path, _dense_polygon_kml_body())

            with self.assertRaisesRegex(BoundaryError, "Unknown generation profile"):
                generate_boundary_from_input(
                    kml_path,
                    buffer_ft=0.0,
                    generation_profile="fast",
                )

    def test_export_profile_after_preview_still_simplifies_and_saves(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            kml_path = tmp_path / "dense_polygon.kml"
            output_path = tmp_path / "export_output.kmz"
            _write_text_kml(kml_path, _dense_polygon_kml_body())

            preview_result = generate_boundary_from_input(
                kml_path,
                buffer_ft=0.0,
                section_count=3,
                overlap_ft=0.0,
                shape_label="Crop",
                split_direction_deg=90.0,
                generation_profile=GENERATION_PROFILE_PREVIEW,
            )
            export_result = generate_boundary_from_input(
                kml_path,
                buffer_ft=0.0,
                section_count=3,
                overlap_ft=0.0,
                shape_label="Crop",
                split_direction_deg=90.0,
                generation_profile=GENERATION_PROFILE_EXPORT,
            )

            self.assertEqual(
                preview_result.metadata.generation_profile,
                GENERATION_PROFILE_PREVIEW,
            )
            self.assertEqual(
                export_result.metadata.generation_profile,
                GENERATION_PROFILE_EXPORT,
            )
            self.assertLess(
                export_result.metadata.vector_simplification_after_vertices,
                export_result.metadata.vector_simplification_before_vertices,
            )
            save_kmz(export_result, output_path)
            with zipfile.ZipFile(output_path) as archive:
                kml_text = archive.read("doc.kml").decode("utf-8")
            self.assertEqual(kml_text.count("<Polygon"), 3)
            self.assertNotIn("innerBoundaryIs", kml_text)

    def test_existing_concave_mode_still_generates_polygon(self) -> None:
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            result = _generate_with_synthetic_jpgs(folder, section_count=1)

            self.assertEqual(result.metadata.selected_strategy, "concave_hull")
            self.assertTrue(result.final_polygon_projected.is_valid)
            self.assertGreater(result.final_polygon_projected.area, 0)

    def test_sections_still_split_connected_polygon(self) -> None:
        with TemporaryDirectory() as tmp:
            kmz_path = Path(tmp) / "source.kmz"
            _write_test_kmz(kmz_path)

            result = generate_boundary_from_kmz(kmz_path, buffer_ft=0.0, section_count=2)

            self.assertEqual(len(result.sections), 2)

    def test_polygon_kmz_sections_ignore_minor_overlap_slivers(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            kmz_path = tmp_path / "source.kmz"
            output_path = tmp_path / "sections.kmz"
            _write_test_kmz(
                kmz_path,
                body=_projected_polygon_kml_body(
                    _minor_overlap_sliver_projected_parent()
                ),
            )

            result = generate_boundary_from_input(
                kmz_path,
                buffer_ft=0.0,
                section_count=2,
                overlap_ft=70.0,
                shape_label="Crop",
                split_direction_deg=0.0,
            )

            self.assertEqual(len(result.sections), 2)
            self.assertEqual(result.metadata.input_type, "KMZ polygon")
            self.assertTrue(
                all(
                    not section.polygon_projected.interiors
                    for section in result.sections
                )
            )
            save_kmz(result, output_path)
            with zipfile.ZipFile(output_path) as archive:
                kml_text = archive.read("doc.kml").decode("utf-8")
            self.assertEqual(kml_text.count("<Polygon"), 2)
            self.assertNotIn("innerBoundaryIs", kml_text)
            self.assertTrue(
                all(section.polygon_projected.is_valid for section in result.sections)
            )

    def test_polygon_kmz_auto_sections_retry_candidate_directions(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            kmz_path = tmp_path / "auto_sections.kmz"
            output_path = tmp_path / "auto_sections_output.kmz"
            _write_test_kmz(
                kmz_path,
                body=_projected_polygon_kml_body(
                    _auto_retry_corridor_projected_parent()
                ),
            )

            result = generate_boundary_from_input(
                kmz_path,
                buffer_ft=0.0,
                section_count=2,
                overlap_ft=50.0,
                shape_label="Auto Crop",
                split_direction_deg=None,
            )

            self.assertEqual(len(result.sections), 2)
            self.assertEqual(result.metadata.input_type, "KMZ polygon")
            self.assertIsNotNone(result.metadata.selected_split_direction_deg)
            save_kmz(result, output_path)
            with zipfile.ZipFile(output_path) as archive:
                kml_text = archive.read("doc.kml").decode("utf-8")
            self.assertEqual(kml_text.count("<Polygon"), 2)
            self.assertNotIn("innerBoundaryIs", kml_text)

    def test_polygon_kmz_auto_sections_fall_back_to_recursive_connected_split(self) -> None:
        parent = _elevon_like_projected_parent()
        with self.assertRaises(NaturalSplitError):
            build_natural_sections(
                parent,
                10,
                50.0 * 0.3048,
                "Elevon",
                Transformer.from_crs(3857, 3857, always_xy=True),
                split_direction_deg=None,
                densify_sections=False,
            )

        with TemporaryDirectory() as tmp:
            kmz_path = Path(tmp) / "elevon_like.kmz"
            _write_test_kmz(kmz_path, body=_projected_polygon_kml_body(parent))

            result = generate_boundary_from_input(
                kmz_path,
                buffer_ft=0.0,
                section_count=10,
                overlap_ft=50.0,
                shape_label="Elevon",
                split_direction_deg=None,
                generation_profile=GENERATION_PROFILE_PREVIEW,
            )

        self.assertEqual(len(result.sections), 10)
        self.assertEqual(result.metadata.input_type, "KMZ polygon")
        self.assertIn("Auto connected equal-area", result.metadata.split_strategy)
        self.assertIsNone(result.metadata.selected_split_direction_deg)
        self.assertLessEqual(result.metadata.split_area_variance_pct, 0.01)
        for section in result.sections:
            self.assertEqual(section.display_name, f"Elevon ({section.index} of 10)")
            self.assertTrue(section.polygon_projected.is_valid)
            self.assertEqual(len(section.polygon_projected.interiors), 0)

    def test_unknown_outline_mode_raises_boundary_error(self) -> None:
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            jpgs, gps_points = _synthetic_jpg_inputs(folder)

            with patch("jpg_boundary_kmz_core.find_jpgs", return_value=jpgs), patch(
                "jpg_boundary_kmz_core.read_gps_points",
                return_value=(gps_points, 0),
            ):
                with self.assertRaises(BoundaryError):
                    generate_boundary(folder, 0.0, outline_mode="bad-mode")

    def test_holed_section_geometry_is_rejected(self) -> None:
        holed = Polygon(
            [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)],
            holes=[[(4, 4), (6, 4), (6, 6), (4, 6), (4, 4)]],
        )

        self.assertIsNone(_strict_single_polygon(holed))


def _generate_with_synthetic_jpgs(folder: Path, section_count: int):
    jpgs, gps_points = _synthetic_jpg_inputs(folder)
    with patch("jpg_boundary_kmz_core.find_jpgs", return_value=jpgs), patch(
        "jpg_boundary_kmz_core.read_gps_points",
        return_value=(gps_points, 0),
    ):
        return generate_boundary(
            folder,
            0.0,
            section_count=section_count,
            outline_mode=OUTLINE_MODE_CONCAVE,
        )


def _synthetic_jpg_inputs(folder: Path):
    jpgs = [folder / f"img_{index:03d}.jpg" for index in range(5)]
    gps_points = [
        synthetic_point(str(jpgs[0]), -80.0000, 35.0000),
        synthetic_point(str(jpgs[1]), -79.9990, 35.0000),
        synthetic_point(str(jpgs[2]), -79.9990, 35.0010),
        synthetic_point(str(jpgs[3]), -80.0000, 35.0010),
        synthetic_point(str(jpgs[4]), -80.0005, 35.0005),
    ]
    return jpgs, gps_points


def _write_test_kmz(path: Path, body: str | None = None) -> None:
    kml = _kml_document(body or _polygon_kml_body())
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("doc.kml", kml)


def _write_text_kml(path: Path, body: str) -> None:
    path.write_text(_kml_document(body), encoding="utf-8")


def _kml_document(body: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>{body}</Document>
</kml>
"""


def _line_kml_body() -> str:
    return """
    <Placemark>
      <LineString>
        <coordinates>
          -80.0000,35.0000,0 -79.9990,35.0005,0 -79.9980,35.0000,0
        </coordinates>
      </LineString>
    </Placemark>
"""


def _polygon_kml_body(*, hole: bool = False) -> str:
    inner = ""
    if hole:
        inner = """
        <innerBoundaryIs>
          <LinearRing>
            <coordinates>
              -79.9998,35.0002,0 -79.9994,35.0002,0 -79.9994,35.0006,0 -79.9998,35.0002,0
            </coordinates>
          </LinearRing>
        </innerBoundaryIs>
"""
    return f"""
    <Placemark>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              -80.0000,35.0000,0 -79.9990,35.0000,0 -79.9990,35.0010,0 -80.0000,35.0010,0 -80.0000,35.0000,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
        {inner}
      </Polygon>
    </Placemark>
"""


def _dense_polygon_kml_body(point_count: int = 240) -> str:
    center_lon = -80.0000
    center_lat = 35.0000
    radius_lon = 0.0022
    radius_lat = 0.0017
    coords: list[str] = []
    for index in range(point_count):
        angle = 2.0 * math.pi * index / point_count
        ripple = 1.0 + 0.015 * math.sin(angle * 12.0)
        lon = center_lon + radius_lon * ripple * math.cos(angle)
        lat = center_lat + radius_lat * ripple * math.sin(angle)
        coords.append(f"{lon:.8f},{lat:.8f},0")
    coords.append(coords[0])
    coordinate_text = " ".join(coords)
    return f"""
    <Placemark>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>{coordinate_text}</coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
"""


def _dense_line_kml_body(point_count: int = 180) -> str:
    coords: list[str] = []
    for index in range(point_count):
        t = index / (point_count - 1)
        lon = -80.0030 + 0.0060 * t
        lat = 35.0000 + 0.0020 * t + 0.00012 * math.sin(t * math.pi * 10.0)
        coords.append(f"{lon:.8f},{lat:.8f},0")
    coordinate_text = " ".join(coords)
    return f"""
    <Placemark>
      <LineString>
        <coordinates>{coordinate_text}</coordinates>
      </LineString>
    </Placemark>
"""


def _minor_overlap_sliver_projected_parent() -> Polygon:
    x_offset = 365000.0
    y_offset = 3315000.0
    geometry = unary_union(
        [
            box(x_offset, y_offset, x_offset + 100, y_offset + 1000),
            box(x_offset + 100, y_offset + 488, x_offset + 120, y_offset + 488.5),
            box(x_offset + 119, y_offset + 488.5, x_offset + 123, y_offset + 493.5),
        ]
    )
    if not isinstance(geometry, Polygon):
        raise AssertionError(f"Expected one polygon, got {geometry.geom_type}.")
    return geometry


def _auto_retry_corridor_projected_parent() -> Polygon:
    x_offset = 365000.0
    y_offset = 3315000.0
    return LineString(
        [
            (x_offset, y_offset),
            (x_offset + 2000, y_offset + 2000),
            (x_offset + 4000, y_offset + 1000),
            (x_offset + 6000, y_offset + 3000),
        ]
    ).buffer(100, cap_style="flat", join_style="mitre")


def _elevon_like_projected_parent() -> Polygon:
    return Polygon(
        [
            (740578.2785485019, 3657276.734508307),
            (740543.2265492795, 3657174.1938875355),
            (740440.2998483776, 3657107.0072762445),
            (740414.048488486, 3657038.141530687),
            (740368.365597078, 3657009.233901303),
            (740278.9462869853, 3656998.1346497918),
            (740114.6932378816, 3657020.160649015),
            (740082.8598346503, 3657043.7332881493),
            (740036.1581446131, 3657421.7985511124),
            (739148.1075686364, 3657137.216196941),
            (739113.1606973477, 3657139.6718816655),
            (739083.6533513693, 3657184.6516223387),
            (739090.6164225528, 3657941.860588608),
            (739129.3627916266, 3657982.0028616805),
            (739348.2951142194, 3657982.044540039),
            (739389.1589479134, 3658006.7614384512),
            (740029.4009488369, 3657989.399388557),
            (740062.4276658338, 3657953.9885697374),
            (740126.4967698716, 3657592.0103452513),
            (740576.2539884133, 3657721.8671521246),
            (740584.3024851172, 3658293.524694843),
            (740626.3597449723, 3658330.5688985866),
            (740852.5828532177, 3658327.348940606),
            (740878.2214802892, 3659025.3088657013),
            (740915.117289514, 3659069.543801735),
            (741462.9341661165, 3659056.95759068),
            (741499.789245071, 3659037.928409264),
            (741518.4407594701, 3659063.962519228),
            (741549.615129691, 3659073.438155178),
            (741722.609304006, 3659058.85219365),
            (741754.7077143717, 3659039.691383985),
            (741784.0265487153, 3658499.3491066145),
            (741721.5279347416, 3658382.1768521713),
            (741709.6426218947, 3658324.227596481),
            (741764.9294559546, 3658313.365590721),
            (741817.1410172447, 3658235.191837204),
            (741809.1766970268, 3657898.324021027),
            (743630.6752526576, 3658174.1414192813),
            (743664.5969350551, 3658166.285507786),
            (743685.6135138081, 3658137.0975693814),
            (743668.2355192639, 3656573.060631179),
            (743623.6322271723, 3656542.5759945405),
            (742678.6412409012, 3656535.124749036),
            (742678.0970207443, 3655755.0408131997),
            (742623.8549604833, 3655628.562802689),
            (742593.5572991936, 3655605.135130498),
            (742402.2822419485, 3655604.4590563355),
            (742231.4766899262, 3655678.0161680044),
            (741576.0444247085, 3655680.785439517),
            (741546.62448982, 3655719.601402635),
            (741554.3706811109, 3655833.315440783),
            (741522.4354107179, 3655874.5703753936),
            (741528.9693392839, 3656090.602283642),
            (741199.9542193864, 3656097.13236949),
            (741191.1001749987, 3655791.791291353),
            (741158.8946716781, 3655751.0703841117),
            (740695.3452741973, 3655763.5268161884),
            (740666.0046435593, 3655775.216428569),
            (740648.0592674671, 3655813.1095454474),
            (740659.7872819789, 3656622.5464156843),
            (740703.8804165701, 3656658.636306041),
            (741149.6520165637, 3656663.20119695),
            (741163.2617790209, 3657480.8744315812),
            (740966.7487864748, 3657492.9504395933),
            (740761.7068907617, 3657338.358741389),
            (740703.427461543, 3657329.676723441),
            (740578.2785485019, 3657276.734508307),
        ]
    )


def _projected_polygon_kml_body(polygon: Polygon, epsg: int = 32615) -> str:
    to_wgs84 = Transformer.from_crs(CRS.from_epsg(epsg), 4326, always_xy=True)
    coords = []
    for x, y in polygon.exterior.coords:
        lon, lat = to_wgs84.transform(x, y)
        coords.append(f"{lon:.8f},{lat:.8f},0")
    coordinate_text = " ".join(coords)
    return f"""
    <Placemark>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>{coordinate_text}</coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
"""
