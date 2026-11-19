from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

from tests.test_polyline_compatibility import write_kmz
from export_style import BOUNDARY_COLORS, MAX_LINE_WIDTH, ExportStyle, ExportStyleError
from jpg_boundary_kmz_core import (
    BoundaryError, _polygon_to_kml_coords, format_summary,
    generate_boundary_from_input, save_kmz,
)


NS = {"k": "http://www.opengis.net/kml/2.2"}


def polygon_body(lon=-80):
    return (
        "<Polygon><outerBoundaryIs><LinearRing><coordinates>"
        f"{lon},35 {lon+.01},35 {lon+.01},35.01 {lon},35.01 {lon},35"
        "</coordinates></LinearRing></outerBoundaryIs></Polygon>"
    )


class ExportStyleTests(TestCase):
    def test_invalid_values_are_rejected_before_serialization(self):
        cases = [
            {"line_width": value} for value in (0, -1, float("nan"), float("inf"), True,
                                               MAX_LINE_WIDTH + .1, 1e308, 10**1000)
        ] + [
            {field: value} for field in ("line_opacity", "fill_opacity")
            for value in (-1, 101, float("nan"), float("inf"), False, 10**1000)
        ] + [
            {field: value} for field in ("line_color", "fill_color")
            for value in ("", "red", "#123", "#12345678", "#gggggg", 42)
        ] + [
            {field: value} for field in ("line_width", "line_opacity", "fill_opacity")
            for value in ("", "invalid", "nan", "inf")
        ] + [{"mode": "invalid"}, {"mode": []}]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ExportStyleError) as raised:
                    ExportStyle(**kwargs)
                self.assertIsInstance(raised.exception, ValueError)
                self.assertEqual(raised.exception.field, next(iter(kwargs)))

    def test_colors_palette_and_opacity_are_stable(self):
        default = ExportStyle()
        self.assertEqual(ExportStyle(line_width=MAX_LINE_WIDTH).line_width, MAX_LINE_WIDTH)
        self.assertEqual(default.color_for(1), BOUNDARY_COLORS[1])
        self.assertEqual(default.color_for(len(BOUNDARY_COLORS)), BOUNDARY_COLORS[0])
        custom = ExportStyle(line_color="#1234AB", fill_color="#FEDCBA", line_opacity=50, fill_opacity=25)
        self.assertEqual(custom.color_for(4), "#1234ab")
        self.assertEqual(custom.kml_color_for(4), "80ab3412")
        self.assertEqual(custom.kml_color_for(4, fill=True), "40badcfe")
        self.assertTrue(replace(custom, line_opacity=0).kml_color_for(0).startswith("00"))
        self.assertTrue(replace(custom, line_opacity=100).kml_color_for(0).startswith("ff"))
        with self.assertRaises(FrozenInstanceError):
            custom.line_width = 9


class ExportAppearanceContractTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.folder = Path(cls.tmp.name)
        cls.source = write_kmz(cls.folder, polygon_body())
        cls.single = generate_boundary_from_input(cls.source, 20)
        cls.split = generate_boundary_from_input(cls.source, 20, section_count=2, shape_label="Custom crop")
        collection_path = cls.folder / "facilities.kml"
        collection_path.write_text(
            '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
            f'<Placemark><name>North facility</name>{polygon_body()}</Placemark>'
            f'<Placemark><name>South facility</name>{polygon_body(-79.98)}</Placemark>'
            '</Document></kml>', encoding="utf-8")
        cls.collection = generate_boundary_from_input(collection_path, 20, section_count=2)

    def read_export(self, result, name, style=None):
        path = save_kmz(result, self.folder / name, style=style)
        with ZipFile(path) as archive:
            content = archive.read("doc.kml")
        return ET.fromstring(content), content

    def test_filename_names_single_shape_and_split_labels_remain_custom(self):
        root, _ = self.read_export(self.single, "Chosen Boundary & north.kmz")
        self.assertEqual(root.findtext("k:Document/k:name", namespaces=NS), "Chosen Boundary & north")
        self.assertEqual(root.findtext(".//k:Placemark/k:name", namespaces=NS), "Chosen Boundary & north")
        root, _ = self.read_export(self.split, "Output document.kmz")
        self.assertEqual(root.findtext("k:Document/k:Folder/k:name", namespaces=NS), "Output document")
        self.assertEqual([n.text for n in root.findall(".//k:Placemark/k:name", NS)],
                         ["Custom crop (1 of 2)", "Custom crop (2 of 2)"])

    def test_descriptions_are_absent_and_diagnostics_remain_outside_kmz(self):
        for result in (self.single, self.split, self.collection):
            with self.subTest(result=type(result).__name__):
                root, content = self.read_export(result, "clean.kmz")
                self.assertEqual(root.findall(".//k:description", NS), [])
                self.assertNotIn(str(result.metadata.source_folder).encode(), content)
                summary = format_summary(result.metadata, getattr(result, "sections", ()))
                self.assertIn("Export CRS: WGS84", summary)
                self.assertIn(str(result.metadata.source_folder), summary)
                if result is self.split:
                    self.assertIn("Section name: Custom crop (1 of 2)", summary)
                    self.assertIn("Section index: 1 of 2", summary)
                    self.assertIn("Base section area:", summary)
                if result is self.collection:
                    self.assertIn("Section name: North facility (1 of 2)", summary)

    def test_modes_opacity_colors_and_ground_clamping_roundtrip_for_all_outputs(self):
        for mode, fill, outline in (("outline", "0", "1"), ("fill", "1", "0"), ("both", "1", "1")):
            style = ExportStyle(line_color="#1234ab", fill_color="#fedcba", line_width=2.75,
                                line_opacity=50, fill_opacity=25, mode=mode)
            for result in (self.single, self.split, self.collection):
                with self.subTest(mode=mode, result=type(result).__name__):
                    root, _ = self.read_export(result, "styled.kmz", style)
                    for node in root.findall(".//k:Style", NS):
                        self.assertEqual(node.findtext("k:LineStyle/k:color", namespaces=NS), "80ab3412")
                        self.assertEqual(float(node.findtext("k:LineStyle/k:width", namespaces=NS)), 2.75)
                        self.assertEqual(node.findtext("k:PolyStyle/k:color", namespaces=NS), "40badcfe")
                        self.assertEqual(node.findtext("k:PolyStyle/k:fill", namespaces=NS), fill)
                        self.assertEqual(node.findtext("k:PolyStyle/k:outline", namespaces=NS), outline)
                    for node in root.findall(".//k:Polygon", NS):
                        self.assertEqual(node.findtext("k:altitudeMode", namespaces=NS), "clampToGround")
                        coords = node.findtext("k:outerBoundaryIs/k:LinearRing/k:coordinates", namespaces=NS)
                        values = [tuple(map(float, item.split(","))) for item in coords.split()]
                        self.assertTrue(all(value[2] == 0 for value in values))
                        self.assertTrue(Polygon([value[:2] for value in values]).exterior.is_ccw)
                    if result is self.collection:
                        self.assertEqual([n.text for n in root.findall("k:Document/k:Folder/k:name", NS)],
                                         ["North facility", "South facility"])

    def test_winding_is_normalized_without_mutating_or_moving_geometry(self):
        source = Polygon([(-80, 35), (-79.99, 35), (-79.99, 35.01), (-80, 35.01), (-80, 35)])
        for sign in (-1.0, 1.0):
            polygon = orient(source, sign=sign)
            before = polygon.wkb
            values = _polygon_to_kml_coords(polygon)
            exported = Polygon([value[:2] for value in values])
            self.assertTrue(exported.exterior.is_ccw)
            self.assertTrue(exported.equals(polygon))
            self.assertEqual(exported.hausdorff_distance(polygon), 0)
            self.assertEqual(len(values), len(polygon.exterior.coords))
            self.assertEqual(before, polygon.wkb)

    def test_invalid_style_does_not_replace_existing_file(self):
        path = self.folder / "existing.kmz"
        path.write_bytes(b"Existing export")
        with self.assertRaises(BoundaryError):
            save_kmz(self.single, path, style="invalid")
        self.assertEqual(path.read_bytes(), b"Existing export")

    def test_three_dimensional_geometry_is_ground_clamped_without_mutation(self):
        geometry = orient(Polygon([(-80, 35, 12), (-79.99, 35, 17),
                                  (-79.99, 35.01, 30), (-80, 35.01, 21)]), sign=-1)
        before = geometry.wkb
        result = replace(self.single, final_polygon_wgs84=geometry)
        root, _ = self.read_export(result, "Ground clamped.kmz")
        coordinates = root.findtext(".//k:Polygon/k:outerBoundaryIs/k:LinearRing/k:coordinates", namespaces=NS)
        values = [tuple(map(float, item.split(","))) for item in coordinates.split()]
        restored = Polygon(values)
        self.assertTrue(all(value[2] == 0 for value in values))
        self.assertTrue(restored.exterior.is_ccw)
        self.assertTrue(restored.equals(geometry))
        self.assertEqual(geometry.wkb, before)
        with self.assertRaises(BoundaryError):
            _polygon_to_kml_coords(Polygon([(400000, 3800000, 1), (400100, 3800000, 1),
                                          (400100, 3800100, 1), (400000, 3800100, 1)]))
