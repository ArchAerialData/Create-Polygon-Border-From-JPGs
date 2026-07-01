from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from shapely.geometry import Polygon

from tests.geometry_test_utils import synthetic_point

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from jpg_boundary_kmz_core import (  # noqa: E402
    BoundaryError,
    format_summary,
    generate_boundary,
    generate_boundary_from_input,
    generate_boundary_from_kmz,
    _strict_single_polygon,
)
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
            self.assertTrue(all(section.polygon_projected.is_valid for section in result.sections))

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
