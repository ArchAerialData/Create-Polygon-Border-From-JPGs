from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

from shapely.geometry import LineString, Polygon


class VectorInputError(ValueError):
    """Raised when KML/KMZ vector input cannot be parsed safely."""


@dataclass(frozen=True)
class VectorInputGeometry:
    source_path: Path
    input_kind: str
    lines_wgs84: tuple[LineString, ...]
    polygons_wgs84: tuple[Polygon, ...]
    source_name: str
    ignored_polygon_count: int = 0
    ignored_interior_ring_count: int = 0
    geometry_inventory: tuple[str, ...] | None = None


def load_vector_input(path: Path) -> VectorInputGeometry:
    source_path = Path(path)
    suffix = source_path.suffix.lower()
    if suffix not in {".kml", ".kmz"}:
        raise VectorInputError("Vector input must be a KML or KMZ file.")
    if not source_path.exists():
        raise VectorInputError(f"Input file does not exist: {source_path}")
    if not source_path.is_file():
        raise VectorInputError(f"Input path is not a file: {source_path}")

    root = _read_kml_root(source_path)
    # Inventory before line precedence drops polygons or other spatial objects.
    spatial_tags = {
        "LineString", "LinearRing", "Polygon", "Point", "MultiGeometry", "Model",
        "Track", "MultiTrack", "NetworkLink", "GroundOverlay", "PhotoOverlay", "ScreenOverlay",
    }
    inventory = tuple(sorted({_local_name(e.tag) for e in root.iter()
                              if _local_name(e.tag) in spatial_tags}))
    line_strings = _extract_line_strings(root)
    polygon_elements = [
        element for element in root.iter() if _local_name(element.tag) == "Polygon"
    ]

    kind_suffix = "kml" if suffix == ".kml" else "kmz"
    if line_strings:
        return VectorInputGeometry(
            source_path=source_path.resolve(),
            input_kind=f"polyline_{kind_suffix}",
            lines_wgs84=tuple(line_strings),
            polygons_wgs84=(),
            source_name=source_path.stem,
            ignored_polygon_count=len(polygon_elements),
            geometry_inventory=inventory,
        )

    if not polygon_elements:
        raise VectorInputError("The KML/KMZ file does not contain LineString or Polygon geometry.")
    if len(polygon_elements) > 1:
        raise VectorInputError(
            "KML/KMZ polygon input must contain exactly one polygon when no LineStrings are present; "
            f"found {len(polygon_elements)}."
        )

    polygon, ignored_interiors = _parse_polygon(polygon_elements[0])
    return VectorInputGeometry(
        source_path=source_path.resolve(),
        input_kind=f"polygon_{kind_suffix}",
        lines_wgs84=(),
        polygons_wgs84=(polygon,),
        source_name=source_path.stem,
        ignored_interior_ring_count=ignored_interiors,
        geometry_inventory=inventory,
    )


def _read_kml_root(path: Path) -> ET.Element:
    suffix = path.suffix.lower()
    if suffix == ".kml":
        kml_data = path.read_bytes()
    else:
        try:
            with zipfile.ZipFile(path) as archive:
                kml_names = [
                    name for name in archive.namelist() if name.lower().endswith(".kml")
                ]
                if not kml_names:
                    raise VectorInputError("The KMZ does not contain a KML document.")
                kml_data = archive.read(_preferred_kml_name(kml_names))
        except zipfile.BadZipFile as exc:
            raise VectorInputError(f"Input file is not a valid KMZ archive: {path}") from exc

    try:
        return ET.fromstring(kml_data)
    except ET.ParseError as exc:
        raise VectorInputError("The KML/KMZ file contains invalid XML.") from exc


def _preferred_kml_name(kml_names: list[str]) -> str:
    return next(
        (name for name in kml_names if Path(name).name.lower() == "doc.kml"),
        kml_names[0],
    )


def _extract_line_strings(root: ET.Element) -> list[LineString]:
    lines: list[LineString] = []
    for element in root.iter():
        if _local_name(element.tag) != "LineString":
            continue
        coordinates_text = _find_coordinates_text(element)
        if not coordinates_text:
            raise VectorInputError("A LineString is missing coordinates.")
        coordinates = _parse_kml_coordinates(coordinates_text)
        if len(coordinates) < 2 or len(set(coordinates)) < 2:
            raise VectorInputError("A LineString must contain at least 2 unique coordinates.")
        lines.append(LineString(coordinates))
    return lines


def _parse_polygon(polygon_element: ET.Element) -> tuple[Polygon, int]:
    coordinates_text = _find_outer_boundary_coordinates_text(polygon_element)
    if not coordinates_text:
        raise VectorInputError("The KML/KMZ polygon does not contain outer boundary coordinates.")
    coordinates = _parse_kml_coordinates(coordinates_text)
    if len(coordinates) < 4:
        raise VectorInputError("The KML/KMZ polygon must contain at least 4 coordinates.")
    if coordinates[0] != coordinates[-1]:
        coordinates.append(coordinates[0])
    if len(set(coordinates)) < 3:
        raise VectorInputError("The KML/KMZ polygon must contain at least 3 unique coordinates.")

    ignored_interiors = sum(
        1 for element in polygon_element.iter() if _local_name(element.tag) == "innerBoundaryIs"
    )
    return Polygon(coordinates), ignored_interiors


def _find_outer_boundary_coordinates_text(polygon_element: ET.Element) -> str:
    outer_boundary = _find_first_descendant(polygon_element, "outerBoundaryIs")
    if outer_boundary is None:
        return ""
    linear_ring = _find_first_descendant(outer_boundary, "LinearRing")
    if linear_ring is None:
        return ""
    return _find_coordinates_text(linear_ring)


def _find_coordinates_text(element: ET.Element) -> str:
    coordinates = _find_first_descendant(element, "coordinates")
    if coordinates is None or not coordinates.text:
        return ""
    return coordinates.text.strip()


def _find_first_descendant(element: ET.Element, local_name: str) -> ET.Element | None:
    for descendant in element.iter():
        if _local_name(descendant.tag) == local_name:
            return descendant
    return None


def _parse_kml_coordinates(coordinates_text: str) -> list[tuple[float, float]]:
    coordinates: list[tuple[float, float]] = []
    for token in coordinates_text.replace("\n", " ").split():
        parts = token.split(",")
        if len(parts) < 2:
            raise VectorInputError(f"KML coordinate is malformed: {token}")
        try:
            lon = float(parts[0])
            lat = float(parts[1])
        except ValueError as exc:
            raise VectorInputError(f"KML coordinate is malformed: {token}") from exc
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise VectorInputError(f"KML coordinate is outside WGS84 bounds: {token}")
        coordinates.append((lon, lat))
    return coordinates


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
