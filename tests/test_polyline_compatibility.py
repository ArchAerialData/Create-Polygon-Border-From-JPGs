import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kml_vector_input import load_vector_input
from polyline_compatibility import classify_per_side_input


LINE = "<LineString><coordinates>-80,35 -79.99,35 -79.99,35.01</coordinates></LineString>"


def write_kmz(folder, body=LINE, name="input.kmz"):
    path = Path(folder) / name
    xml = f'<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark>{body}</Placemark></Document></kml>'
    if path.suffix == ".kmz":
        with ZipFile(path, "w") as archive:
            archive.writestr("doc.kml", xml)
    else:
        path.write_text(xml, encoding="utf-8")
    return path


class PolylineCompatibilityTests(TestCase):
    def test_pure_open_lines_and_nested_branches_are_eligible(self):
        with TemporaryDirectory() as tmp:
            path = write_kmz(tmp, f"<MultiGeometry>{LINE}{LINE}</MultiGeometry>")
            source = load_vector_input(path)
            before = [line.wkb for line in source.lines_wgs84]
            result = classify_per_side_input(source)
            self.assertTrue(result.eligible)
            self.assertEqual(result.line_count, 2)
            self.assertEqual([line.wkb for line in source.lines_wgs84], before)

    def test_mixed_geometry_stays_valid_for_unified_but_is_ineligible(self):
        for tag in ("Polygon", "Point", "LinearRing", "Track", "MultiTrack", "Model",
                    "NetworkLink", "GroundOverlay", "PhotoOverlay"):
            with self.subTest(tag=tag), TemporaryDirectory() as tmp:
                source = load_vector_input(write_kmz(tmp, LINE + f"<{tag}/>"))
                self.assertEqual(len(source.lines_wgs84), 1)
                self.assertIn(tag, source.geometry_inventory)
                self.assertEqual(classify_per_side_input(source).reason_code, "mixed_geometry")

    def test_kml_closed_and_self_crossing_are_ineligible(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(classify_per_side_input(load_vector_input(write_kmz(tmp, name="input.kml"))).reason_code, "not_kmz")
            for coords, reason in [
                ("-80,35 -79.99,35 -79.99,35.01 -80,35", "closed_line"),
                ("-80,35 -79.99,35.01 -80,35.01 -79.99,35", "self_crossing"),
            ]:
                source = load_vector_input(write_kmz(tmp, f"<LineString><coordinates>{coords}</coordinates></LineString>"))
                self.assertEqual(classify_per_side_input(source).reason_code, reason)

    def test_cli_uses_same_classifier_and_handles_read_failure(self):
        script = Path(__file__).resolve().parents[1] / "src/polyline_compatibility.py"
        with TemporaryDirectory() as tmp:
            path = write_kmz(tmp)
            good = subprocess.run([sys.executable, "-B", str(script), str(path)], capture_output=True, text=True)
            self.assertEqual(good.returncode, 0)
            self.assertTrue(json.loads(good.stdout)["eligible"])
            path.unlink()
            bad = subprocess.run([sys.executable, "-B", str(script), str(path)], capture_output=True, text=True)
            self.assertEqual(bad.returncode, 1)
            self.assertEqual(json.loads(bad.stdout)["reason_code"], "read_error")
