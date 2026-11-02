from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from pyproj import Transformer
from shapely.geometry import Polygon, box
from shapely.ops import transform
from tests.test_polyline_compatibility import write_kmz
from jpg_boundary_kmz_core import BoundaryError, generate_boundary_from_input, save_kmz, _polygon_to_kml_coords


NS = {'k': 'http://www.opengis.net/kml/2.2'}


class KmzExportContractTests(TestCase):
    def test_exports_use_unfilled_colored_outlines_and_wgs84_in_both_hemispheres(self):
        for lon, lat in ((-80, 35), (151, -33)):
            for count in (1, 3):
                with self.subTest(lon=lon, lat=lat, count=count), TemporaryDirectory() as tmp:
                    body = f'<LineString><coordinates>{lon},{lat} {lon+.02},{lat} {lon+.02},{lat+.01}</coordinates></LineString>'
                    result = generate_boundary_from_input(write_kmz(tmp, body), 100, section_count=count)
                    output = save_kmz(result, Path(tmp)/'output.kmz')
                    with ZipFile(output) as archive:
                        root = ET.fromstring(archive.read('doc.kml'))
                    styles = root.findall('.//k:Style', NS)
                    self.assertEqual(len(styles), count)
                    colors = []
                    for style in styles:
                        self.assertEqual(style.findtext('k:PolyStyle/k:fill', namespaces=NS), '0')
                        self.assertEqual(style.findtext('k:PolyStyle/k:outline', namespaces=NS), '1')
                        self.assertEqual(float(style.findtext('k:LineStyle/k:width', namespaces=NS)), 5)
                        colors.append(style.findtext('k:LineStyle/k:color', namespaces=NS))
                    self.assertEqual(len(set(colors)), count)
                    original = [s.polygon_projected for s in result.sections] or [result.final_polygon_projected]
                    polygons = root.findall('.//k:Polygon', NS)
                    for node, expected in zip(polygons, original):
                        self.assertEqual(node.findtext('k:altitudeMode', namespaces=NS), 'clampToGround')
                        text = node.findtext('k:outerBoundaryIs/k:LinearRing/k:coordinates', namespaces=NS)
                        coords = [tuple(map(float, value.split(','))) for value in text.split()]
                        self.assertEqual(coords[0], coords[-1])
                        self.assertTrue(all(abs(x-lon)<.1 and abs(y-lat)<.1 and z==0 for x,y,z in coords))
                        polygon = Polygon([(x,y) for x,y,z in coords])
                        self.assertTrue(polygon.is_valid)
                        projected = transform(Transformer.from_crs(4326, result.metadata.epsg, always_xy=True).transform, polygon)
                        self.assertLess(projected.hausdorff_distance(expected), 1e-5)

    def test_export_rejects_projected_or_invalid_coordinates(self):
        for polygon in (box(400000, 3800000, 400100, 3800100),
                        Polygon([(0, 0), (1, 1), (1, 0), (0, 1)]), Polygon()):
            with self.subTest(polygon=polygon.wkt), self.assertRaises(BoundaryError):
                _polygon_to_kml_coords(polygon)
