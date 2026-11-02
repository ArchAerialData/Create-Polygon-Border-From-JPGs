from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from kml_vector_input import VectorInputError, load_vector_input  # noqa: E402


class KmlVectorInputTests(TestCase):
    def test_plain_kml_linestring_parses(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "lines.kml"
            path.write_text(_kml(_linestring("-80,35,0 -79.9,35.1,0")), encoding="utf-8")

            result = load_vector_input(path)

            self.assertEqual(result.input_kind, "polyline_kml")
            self.assertEqual(len(result.lines_wgs84), 1)
            self.assertEqual(len(result.lines_wgs84[0].coords), 2)
            self.assertEqual(result.ignored_polygon_count, 0)

    def test_kmz_doc_kml_linestring_parses(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "lines.kmz"
            _write_kmz(path, _kml(_linestring("-80,35,0 -79.9,35.1,0")))

            result = load_vector_input(path)

            self.assertEqual(result.input_kind, "polyline_kmz")
            self.assertEqual(len(result.lines_wgs84), 1)

    def test_mixed_linestring_polygon_prefers_lines_and_reports_ignored_polygon(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "mixed.kml"
            path.write_text(
                _kml(
                    _linestring("-80,35,0 -79.9,35.1,0")
                    + _polygon("-80,35,0 -79.9,35,0 -79.9,35.1,0 -80,35,0")
                ),
                encoding="utf-8",
            )

            result = load_vector_input(path)

            self.assertEqual(result.input_kind, "polyline_kml")
            self.assertEqual(len(result.lines_wgs84), 1)
            self.assertEqual(result.polygons_wgs84, ())
            self.assertEqual(result.ignored_polygon_count, 1)

    def test_single_polygon_kml_with_hole_reports_ignored_interior(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "polygon.kml"
            path.write_text(
                _kml(
                    _polygon(
                        "-80,35,0 -79.9,35,0 -79.9,35.1,0 -80,35.1,0 -80,35,0",
                        hole="-79.98,35.02,0 -79.95,35.02,0 -79.95,35.05,0 -79.98,35.02,0",
                    )
                ),
                encoding="utf-8",
            )

            result = load_vector_input(path)

            self.assertEqual(result.input_kind, "polygon_kml")
            self.assertEqual(len(result.polygons_wgs84), 1)
            self.assertEqual(result.ignored_interior_ring_count, 1)

    def test_multiple_polygons_without_lines_are_preserved(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "polygons.kml"
            polygon = _polygon("-80,35,0 -79.9,35,0 -79.9,35.1,0 -80,35,0")
            path.write_text(_kml(polygon + polygon), encoding="utf-8")

            result = load_vector_input(path)
            self.assertEqual(len(result.polygons_wgs84), 2)
            self.assertEqual([source.name for source in result.polygon_sources], ["Polygon 1", "Polygon 2"])

    def test_malformed_coordinate_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.kml"
            path.write_text(_kml(_linestring("-80,35,0 bad")), encoding="utf-8")

            with self.assertRaisesRegex(VectorInputError, "malformed"):
                load_vector_input(path)


def _kml(body: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>{body}</Document>
</kml>
"""


def _linestring(coordinates: str) -> str:
    return f"""
<Placemark>
  <LineString>
    <coordinates>{coordinates}</coordinates>
  </LineString>
</Placemark>
"""


def _polygon(coordinates: str, *, hole: str = "") -> str:
    inner = ""
    if hole:
        inner = f"""
    <innerBoundaryIs>
      <LinearRing><coordinates>{hole}</coordinates></LinearRing>
    </innerBoundaryIs>
"""
    return f"""
<Placemark>
  <Polygon>
    <outerBoundaryIs>
      <LinearRing><coordinates>{coordinates}</coordinates></LinearRing>
    </outerBoundaryIs>
    {inner}
  </Polygon>
</Placemark>
"""


def _write_kmz(path: Path, kml: str) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("doc.kml", kml)
