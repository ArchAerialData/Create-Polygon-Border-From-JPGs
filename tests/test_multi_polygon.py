from __future__ import annotations

import hashlib
import sys
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from zipfile import ZipFile

import numpy as np
from pyproj import Transformer
from shapely.geometry import Polygon
from shapely.ops import transform, unary_union

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from jpg_boundary_kmz_core import (
    BOUNDARY_COLORS, BoundaryCollectionResult, BoundaryError, BoundaryResult,
    GENERATION_PROFILE_PREVIEW, generate_boundary_from_input,
    generate_boundary_from_vector_geometry, format_summary, save_kmz,
)
from kml_vector_input import VectorInputError, load_vector_input

FIXTURE = Path(__file__).parent / "fixtures/kmz/wwm_station_facilities_37_polygons.kmz"
NS = {"k": "http://www.opengis.net/kml/2.2"}
EXPECTED_NAMES = (
    "ADCC EFM MS", "ABP Brazos Fuel Tap", "ABP Summit Double E MS", "ABP Targa Falcon II MS",
    "ABP Western Bone Spring MS", "ABP Western N. Loving Cryo MS", "GCX Interconnect", "PHP Interconnect",
    "Secretariat MS", "BXM Pembrook East MS", "BXP Targa Blending MS", "BFP Batson CS-3",
    "BFP CS-1 Burleigh", "BFP Evadale CS-4", "BFP PHP MS", "BFP to MXP Crossover MS",
    "BFP Tres Palacios MS", "BFP VG CPX MS", "ABP Devon Lea Co. Fuel Tap", "Atmos Marble Falls",
    "MXP Aspen Draft Horse MS", "MXP Aspen Midstream MS", "MXP CS-1 Waha", "MXP CS-3 Barnhart",
    "MXP CS-5 San Saba", "MXP CS-7 Lincoln", "MXP ENB Tres P MS", "MXP Midkiff Booster CS",
    "MXP TETCO", "MXP WMB Transco Clarks Branch MS", "Stanton Junction", "10C Injection Well",
    "4C Injection Well Pad", "ETC Mustang Draw", "WHL CS-1 Waha", "WHL EPD Orion MS", "WHL ETC Cotulla MS",
)


def outputs(result):
    return [section.polygon_projected for section in result.sections] or [result.final_polygon_projected]


def polygon_xml(coords="-97,32 -96.99,32 -96.99,32.01 -97,32.01 -97,32", hole=""):
    inner = f"<innerBoundaryIs><LinearRing><coordinates>{hole}</coordinates></LinearRing></innerBoundaryIs>" if hole else ""
    return f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{coords}</coordinates></LinearRing></outerBoundaryIs>{inner}</Polygon>"


def write_kml(directory, body):
    path = Path(directory) / "input.kml"
    path.write_text(f'<kml xmlns="{NS["k"]}"><Document>{body}</Document></kml>', encoding="utf-8")
    return path


class MultiPolygonFixtureTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parsed = load_vector_input(FIXTURE)
        cls.results = {
            (buffer, count, simplify): generate_boundary_from_input(
                FIXTURE, buffer, section_count=count, simplify_vector_output=simplify,
            )
            for buffer in (0, 100) for count in (1, 2) for simplify in (False, True)
        }

    def test_fixture_integrity_and_inventory(self):
        self.assertEqual(FIXTURE.stat().st_size, 115041)
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
                         "61bffe0f3a5aedb2318d21bb68e3eb17c277627177c0df9ccdd138c83aa679e1")
        with ZipFile(FIXTURE) as archive:
            root = ET.fromstring(archive.read("doc.kml"))
        self.assertEqual(len(root.findall(".//k:Placemark", NS)), 37)
        self.assertEqual(len(root.findall(".//k:Polygon", NS)), 37)
        self.assertEqual(root.findall(".//k:LineString", NS), [])
        self.assertEqual(root.findall(".//k:innerBoundaryIs", NS), [])
        for ring in root.findall(".//k:outerBoundaryIs/k:LinearRing/k:coordinates", NS):
            points = ring.text.split()
            self.assertEqual(points[0], points[-1])
        self.assertEqual(tuple(s.name for s in self.parsed.polygon_sources), EXPECTED_NAMES)

    def test_matrix_matches_standalone_processing_and_limits(self):
        for (buffer, count, simplify), collection in self.results.items():
            with self.subTest(buffer=buffer, count=count, simplify=simplify):
                self.assertIsInstance(collection, BoundaryCollectionResult)
                self.assertEqual(len(collection.children), 37)
                self.assertEqual(collection.metadata.output_polygon_count, 37 * count)
                self.assertEqual({c.result.metadata.epsg for c in collection.children}, {32613, 32614, 32615})
                total_before = total_after = 0
                for index, child in enumerate(collection.children):
                    self.assertEqual(child.source_name, EXPECTED_NAMES[index])
                    self.assertEqual(child.source_id, f"polygon-{index + 1}")
                    standalone = generate_boundary_from_vector_geometry(
                        replace(self.parsed, polygons_wgs84=(self.parsed.polygons_wgs84[index],),
                                polygon_sources=(self.parsed.polygon_sources[index],)),
                        buffer, section_count=count, shape_label=child.source_name,
                        simplify_vector_output=simplify,
                    )
                    self.assertIsInstance(standalone, BoundaryResult)
                    raw = self.results[buffer, count, False].children[index].result
                    self.assertEqual(len(outputs(child.result)), count)
                    for actual, expected, original in zip(outputs(child.result), outputs(standalone), outputs(raw)):
                        self.assertTrue(actual.is_valid and not actual.is_empty)
                        self.assertTrue(actual.equals_exact(expected, 1e-7))
                        self.assertLessEqual(original.hausdorff_distance(actual), 5 * .3048 + 1e-8)
                        self.assertLessEqual(original.symmetric_difference(actual).area / original.area, .01 + 1e-9)
                        total_before += len(original.exterior.coords)
                        total_after += len(actual.exterior.coords)
                    if count > 1:
                        protected = unary_union(outputs(raw)).buffer(-5 * .3048)
                        self.assertTrue(unary_union(outputs(child.result)).buffer(1e-7).covers(protected))
                if simplify:
                    self.assertLess(total_after, total_before * .5)
                else:
                    self.assertEqual(total_after, total_before)

    def test_export_round_trip_folder_names_styles_and_geometry(self):
        for settings, collection in self.results.items():
            with self.subTest(settings=settings), TemporaryDirectory() as tmp:
                output = save_kmz(collection, Path(tmp) / "facilities.kmz")
                with ZipFile(output) as archive:
                    root = ET.fromstring(archive.read("doc.kml"))
                document = root.find("k:Document", NS)
                self.assertEqual(document.findtext("k:name", namespaces=NS), "facilities")
                self.assertEqual(document.findall("k:Placemark", NS), [])
                folders = document.findall("k:Folder", NS)
                self.assertEqual(len(folders), 37)
                styles = {s.attrib["id"]: s for s in root.findall(".//k:Style", NS)}
                color_index = 0
                for folder, child in zip(folders, collection.children):
                    self.assertEqual(folder.findtext("k:name", namespaces=NS), child.source_name)
                    placemarks = folder.findall("k:Placemark", NS)
                    self.assertEqual(len(placemarks), settings[1])
                    names = ([s.display_name for s in child.result.sections] or [child.source_name])
                    self.assertEqual(names, [child.source_name] if settings[1] == 1 else
                                     [f"{child.source_name} ({i} of {settings[1]})" for i in range(1, settings[1] + 1)])
                    for placemark, expected, name in zip(placemarks, outputs(child.result), names):
                        self.assertEqual(placemark.findtext("k:name", namespaces=NS), name)
                        node = placemark.find("k:Polygon", NS)
                        self.assertEqual(node.findtext("k:altitudeMode", namespaces=NS), "clampToGround")
                        coordinates = node.findtext("k:outerBoundaryIs/k:LinearRing/k:coordinates", namespaces=NS)
                        coords = [tuple(map(float, token.split(","))) for token in coordinates.split()]
                        self.assertEqual(coords[0], coords[-1])
                        self.assertTrue(all(-180 <= x <= 180 and -90 <= y <= 90 and z == 0 for x, y, z in coords))
                        restored = transform(Transformer.from_crs(4326, child.result.metadata.epsg, always_xy=True).transform,
                                             Polygon([(x, y) for x, y, _ in coords]))
                        self.assertTrue(restored.is_valid)
                        self.assertLess(restored.hausdorff_distance(expected), 1e-5)
                        style = styles[placemark.findtext("k:styleUrl", namespaces=NS).lstrip("#")]
                        self.assertEqual(style.findtext("k:PolyStyle/k:fill", namespaces=NS), "0")
                        self.assertEqual(style.findtext("k:PolyStyle/k:outline", namespaces=NS), "1")
                        self.assertEqual(float(style.findtext("k:LineStyle/k:width", namespaces=NS)), 5)
                        color = BOUNDARY_COLORS[color_index % len(BOUNDARY_COLORS)][1:]
                        self.assertEqual(style.findtext("k:LineStyle/k:color", namespaces=NS),
                                         "ff" + color[4:6] + color[2:4] + color[:2])
                        color_index += 1

    def test_display_projection_and_summary_are_collection_wide(self):
        collection = self.results[100, 2, True]
        for child, display in zip(collection.children, collection.display_results):
            self.assertEqual(display.metadata.epsg, collection.metadata.epsg)
            transformer = Transformer.from_crs(4326, collection.metadata.epsg, always_xy=True)
            for local, shown in zip(child.result.sections, display.sections):
                expected = transform(transformer.transform, local.polygon_wgs84)
                self.assertLess(expected.hausdorff_distance(shown.polygon_projected), 1e-5)
            self.assertFalse(np.shares_memory(child.result.projected_points, display.projected_points))
        summary = format_summary(collection.metadata)
        self.assertIn("Source polygons: 37", summary)
        self.assertIn("Output polygons: 74", summary)
        self.assertTrue(all(name in summary for name in EXPECTED_NAMES))
        self.assertEqual(collection.metadata.vertex_count, sum(c.result.metadata.vertex_count for c in collection.children))
        self.assertEqual(collection.metadata.vector_simplification_max_deviation_ft,
                         max(c.result.metadata.vector_simplification_max_deviation_ft for c in collection.children))


class MultiPolygonEdgeTests(TestCase):
    def test_nested_geometry_names_identity_and_holes(self):
        with TemporaryDirectory() as tmp:
            body = (f"<Placemark><name>Site</name><MultiGeometry><MultiGeometry>{polygon_xml()}</MultiGeometry>"
                    f"{polygon_xml(hole='-96.998,32.002 -96.997,32.002 -96.997,32.003 -96.998,32.002')}"
                    f"</MultiGeometry></Placemark><Placemark><name>Site</name>{polygon_xml()}</Placemark>"
                    f"<Placemark>{polygon_xml()}</Placemark><Placemark><name>Site (2)</name>{polygon_xml()}</Placemark>")
            parsed = load_vector_input(write_kml(tmp, body))
            names = [source.name for source in parsed.polygon_sources]
            self.assertEqual(names, ["Site", "Site (2)", "Site (3)", "Polygon 4", "Site (2) (2)"])
            self.assertEqual(len({s.source_id for s in parsed.polygon_sources}), 5)
            self.assertEqual(parsed.ignored_interior_ring_count, 1)
            result = generate_boundary_from_vector_geometry(parsed, 100)
            self.assertEqual(len(result.children), 5)  # Identical/overlapping shapes remain distinct.
            self.assertEqual([c.result.metadata.ignored_interior_ring_count for c in result.children], [0, 1, 0, 0, 0])
            self.assertTrue(all(len(c.result.final_polygon_wgs84.interiors) == 0 for c in result.children))

    def test_later_invalid_facility_fails_with_name_and_preserves_existing_export(self):
        with TemporaryDirectory() as tmp:
            source = write_kml(tmp, f"<Placemark><name>Good</name>{polygon_xml()}</Placemark>"
                               f"<Placemark><name>Bad facility</name>{polygon_xml('-97,32 -96.99,32.01 -96.99,32 -97,32.01 -97,32')}</Placemark>")
            destination = Path(tmp) / "existing.kmz"
            destination.write_bytes(b"existing export")
            with self.assertRaisesRegex(BoundaryError, "Bad facility"):
                save_kmz(generate_boundary_from_input(source, 100), destination)
            self.assertEqual(destination.read_bytes(), b"existing export")
            self.assertEqual(list(Path(tmp).glob(".boundary-*")), [])

    def test_malformed_later_coordinates_report_facility(self):
        with TemporaryDirectory() as tmp:
            source = write_kml(tmp, f"<Placemark>{polygon_xml()}</Placemark>"
                               f"<Placemark><name>Broken</name>{polygon_xml('bad')}</Placemark>")
            with self.assertRaisesRegex(VectorInputError, "Broken.*malformed"):
                load_vector_input(source)

    def test_preview_collection_and_invalid_export_do_not_replace_destination(self):
        with TemporaryDirectory() as tmp:
            source = write_kml(tmp, f"<Placemark>{polygon_xml()}</Placemark>" * 2)
            result = generate_boundary_from_input(source, 0, generation_profile=GENERATION_PROFILE_PREVIEW)
            destination = Path(tmp) / "existing.kmz"
            destination.write_bytes(b"existing export")
            with self.assertRaisesRegex(BoundaryError, "Preview-quality"):
                save_kmz(result, destination)
            result = generate_boundary_from_input(source, 0)
            result.children[-1].result.final_polygon_wgs84 = Polygon()
            with self.assertRaises(BoundaryError):
                save_kmz(result, destination)
            self.assertEqual(destination.read_bytes(), b"existing export")

    def test_mixed_input_keeps_linestring_precedence(self):
        with TemporaryDirectory() as tmp:
            source = write_kml(tmp, f"<Placemark>{polygon_xml()}</Placemark>" * 2
                               + "<Placemark><LineString><coordinates>-97,32 -96.99,32</coordinates></LineString></Placemark>")
            parsed = load_vector_input(source)
            self.assertEqual(parsed.ignored_polygon_count, 2)
            self.assertEqual(parsed.polygons_wgs84, ())
            self.assertIsInstance(generate_boundary_from_vector_geometry(parsed, 100), BoundaryResult)
