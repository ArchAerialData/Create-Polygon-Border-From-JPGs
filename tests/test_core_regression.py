from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from tests.geometry_test_utils import synthetic_point

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from jpg_boundary_kmz_core import (  # noqa: E402
    BoundaryError,
    generate_boundary,
    generate_boundary_from_kmz,
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


def _write_test_kmz(path: Path) -> None:
    kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              -80.0000,35.0000,0 -79.9990,35.0000,0 -79.9990,35.0010,0 -80.0000,35.0010,0 -80.0000,35.0000,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>
"""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("doc.kml", kml)
