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
from natural_sectioning import build_natural_sections  # noqa: E402
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

    def test_linestring_input_requires_positive_buffer(self) -> None:
        with TemporaryDirectory() as tmp:
            kml_path = Path(tmp) / "source_lines.kml"
            _write_text_kml(kml_path, _line_kml_body())

            with self.assertRaisesRegex(BoundaryError, "greater than 0 ft"):
                generate_boundary_from_input(kml_path, buffer_ft=0.0)

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
