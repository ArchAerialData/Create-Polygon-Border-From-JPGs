from __future__ import annotations

import contextlib
import html
import io
import math
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import exifread
import numpy as np
import simplekml
from pyproj import CRS, Transformer
from scipy.spatial import cKDTree
from shapely import concave_hull
from shapely.affinity import rotate
from shapely.geometry import box
from shapely.geometry import GeometryCollection, MultiPoint, MultiPolygon, Polygon
from shapely.ops import transform as transform_geometry
from shapely.ops import unary_union
from shapely.validation import make_valid


FEET_PER_METER = 3.280839895
METERS_PER_FOOT = 0.3048
DEFAULT_CONCAVE_RATIO = 0.15
DEFAULT_SIMPLIFY_FACTOR = 0.25
BUFFER_JOIN_STYLE = "round"
BUFFER_QUAD_SEGS = 8
BUFFER_MITRE_LIMIT = 3.0
MAX_SECTION_COUNT = 100
ACRES_PER_SQUARE_METER = 0.000247105381467
KML_LINE_WIDTH = 6.0


class BoundaryError(RuntimeError):
    """Raised when the input photos cannot produce a usable boundary."""


@dataclass(frozen=True)
class GpsPoint:
    path: Path
    lat: float
    lon: float


@dataclass(frozen=True)
class BoundaryMetadata:
    source_folder: Path
    input_type: str
    jpg_count: int
    gps_count: int
    skipped_count: int
    epsg: int
    crs_name: str
    buffer_ft: float
    median_spacing_ft: float
    smoothing_ft: float
    containment_padding_ft: float
    concave_ratio: float
    vertex_count: int
    section_count: int
    overlap_ft: float
    shape_label: str
    split_strategy: str
    section_area_min_acres: float
    section_area_max_acres: float
    sections_connected: bool


@dataclass
class BoundarySection:
    index: int
    total: int
    display_name: str
    base_area_acres: float
    polygon_projected: Polygon
    polygon_wgs84: Polygon


@dataclass
class BoundaryResult:
    metadata: BoundaryMetadata
    gps_points: list[GpsPoint]
    projected_points: np.ndarray
    base_polygon_projected: Polygon
    final_polygon_projected: Polygon
    final_polygon_wgs84: Polygon
    sections: list[BoundarySection]


def find_jpgs(parent_folder: Path) -> list[Path]:
    parent_folder = Path(parent_folder)
    if not parent_folder.exists():
        raise BoundaryError(f"Input folder does not exist: {parent_folder}")
    if not parent_folder.is_dir():
        raise BoundaryError(f"Input path is not a folder: {parent_folder}")

    jpgs: list[Path] = []
    for path in parent_folder.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg"}:
            jpgs.append(path)
    return sorted(jpgs, key=lambda p: str(p).lower())


def read_gps_points(paths: Iterable[Path]) -> tuple[list[GpsPoint], int]:
    points: list[GpsPoint] = []
    skipped_count = 0

    for path in paths:
        point = _read_gps_point(Path(path))
        if point is None:
            skipped_count += 1
        else:
            points.append(point)

    return points, skipped_count


def generate_boundary(
    parent_folder: Path,
    buffer_ft: float,
    section_count: int = 1,
    overlap_ft: float = 50.0,
    shape_label: str = "",
    concave_ratio: float = DEFAULT_CONCAVE_RATIO,
    simplify_factor: float = DEFAULT_SIMPLIFY_FACTOR,
) -> BoundaryResult:
    if buffer_ft < 0:
        raise BoundaryError("Buffer distance must be 0 or greater.")
    if not 0 <= concave_ratio <= 1:
        raise BoundaryError("Concave hull ratio must be between 0 and 1.")
    if simplify_factor < 0:
        raise BoundaryError("Simplify factor must be 0 or greater.")
    if section_count < 1 or section_count > MAX_SECTION_COUNT:
        raise BoundaryError(f"# of Shapes must be between 1 and {MAX_SECTION_COUNT}.")
    if overlap_ft < 0:
        raise BoundaryError("Overlap distance must be 0 or greater.")

    parent_folder = Path(parent_folder)
    jpgs = find_jpgs(parent_folder)
    if not jpgs:
        raise BoundaryError("No JPG or JPEG files were found in the selected folder.")

    gps_points, skipped_count = read_gps_points(jpgs)
    if len(gps_points) < 3:
        raise BoundaryError(
            f"At least 3 geotagged JPGs are required; found {len(gps_points)}."
        )

    lats = np.array([point.lat for point in gps_points], dtype=float)
    lons = np.array([point.lon for point in gps_points], dtype=float)
    epsg = detect_utm_epsg(lats, lons)
    crs_projected = CRS.from_epsg(epsg)
    to_projected = Transformer.from_crs(4326, crs_projected, always_xy=True)
    to_wgs84 = Transformer.from_crs(crs_projected, 4326, always_xy=True)

    xs, ys = to_projected.transform(lons, lats)
    projected_points = np.column_stack([xs, ys])
    unique_points = np.unique(np.round(projected_points, 6), axis=0)
    if len(unique_points) < 3:
        raise BoundaryError("The geotagged JPGs do not contain 3 unique positions.")

    point_geometry = MultiPoint(unique_points)
    raw_hull = concave_hull(point_geometry, ratio=concave_ratio, allow_holes=False)
    hull = _ensure_polygon(raw_hull, point_geometry)
    if hull.area <= 0:
        raise BoundaryError("The camera positions did not produce a usable polygon.")

    median_spacing_m = _median_nearest_neighbor_distance(unique_points)
    base_polygon, smoothing_m, containment_padding_m = _simplify_with_containment(
        hull,
        point_geometry,
        median_spacing_m,
        simplify_factor,
    )

    buffer_m = buffer_ft * METERS_PER_FOOT
    if buffer_m > 0:
        final_projected = base_polygon.buffer(
            buffer_m,
            join_style=BUFFER_JOIN_STYLE,
            quad_segs=BUFFER_QUAD_SEGS,
            mitre_limit=BUFFER_MITRE_LIMIT,
        )
        final_projected = _ensure_polygon(final_projected, point_geometry)
    else:
        final_projected = base_polygon

    final_wgs84 = transform_geometry(
        lambda x, y, z=None: to_wgs84.transform(x, y),
        final_projected,
    )
    final_wgs84 = _ensure_polygon(final_wgs84)

    sections: list[BoundarySection] = []
    split_strategy = "Single polygon"
    section_area_min_acres = 0.0
    section_area_max_acres = 0.0
    sections_connected = True
    section_label = shape_label.strip()

    if section_count > 1:
        section_label = section_label or "JPG Camera Boundary"
        sections, split_angles = _build_sections(
            final_projected,
            section_count,
            overlap_ft * METERS_PER_FOOT,
            section_label,
            to_wgs84,
        )
        base_areas = [section.base_area_acres for section in sections]
        section_area_min_acres = min(base_areas)
        section_area_max_acres = max(base_areas)
        split_strategy = _format_split_strategy(split_angles)

    metadata = BoundaryMetadata(
        source_folder=parent_folder.resolve(),
        input_type="JPG folder",
        jpg_count=len(jpgs),
        gps_count=len(gps_points),
        skipped_count=skipped_count,
        epsg=epsg,
        crs_name=crs_projected.name,
        buffer_ft=buffer_ft,
        median_spacing_ft=median_spacing_m * FEET_PER_METER,
        smoothing_ft=smoothing_m * FEET_PER_METER,
        containment_padding_ft=containment_padding_m * FEET_PER_METER,
        concave_ratio=concave_ratio,
        vertex_count=len(final_wgs84.exterior.coords),
        section_count=section_count,
        overlap_ft=overlap_ft if section_count > 1 else 0.0,
        shape_label=section_label if section_count > 1 else "",
        split_strategy=split_strategy,
        section_area_min_acres=section_area_min_acres,
        section_area_max_acres=section_area_max_acres,
        sections_connected=sections_connected,
    )

    return BoundaryResult(
        metadata=metadata,
        gps_points=gps_points,
        projected_points=projected_points,
        base_polygon_projected=base_polygon,
        final_polygon_projected=final_projected,
        final_polygon_wgs84=final_wgs84,
        sections=sections,
    )


def generate_boundary_from_input(
    input_path: Path,
    buffer_ft: float,
    section_count: int = 1,
    overlap_ft: float = 50.0,
    shape_label: str = "",
) -> BoundaryResult:
    input_path = Path(input_path)
    if input_path.is_dir():
        return generate_boundary(
            input_path,
            buffer_ft,
            section_count=section_count,
            overlap_ft=overlap_ft,
            shape_label=shape_label,
        )
    if input_path.is_file() and input_path.suffix.lower() == ".kmz":
        return generate_boundary_from_kmz(
            input_path,
            buffer_ft,
            section_count=section_count,
            overlap_ft=overlap_ft,
            shape_label=shape_label,
        )
    raise BoundaryError("Choose a folder of JPGs or an existing KMZ file.")


def generate_boundary_from_kmz(
    kmz_path: Path,
    buffer_ft: float,
    section_count: int = 1,
    overlap_ft: float = 50.0,
    shape_label: str = "",
) -> BoundaryResult:
    if buffer_ft < 0:
        raise BoundaryError("Buffer distance must be 0 or greater.")
    if section_count < 1 or section_count > MAX_SECTION_COUNT:
        raise BoundaryError(f"# of Shapes must be between 1 and {MAX_SECTION_COUNT}.")
    if overlap_ft < 0:
        raise BoundaryError("Overlap distance must be 0 or greater.")

    kmz_path = Path(kmz_path)
    if not kmz_path.exists():
        raise BoundaryError(f"Input KMZ does not exist: {kmz_path}")
    if not kmz_path.is_file() or kmz_path.suffix.lower() != ".kmz":
        raise BoundaryError(f"Input path is not a KMZ file: {kmz_path}")

    source_polygon_wgs84 = _read_single_polygon_from_kmz(kmz_path)
    lon_values = np.array([lon for lon, _lat in source_polygon_wgs84.exterior.coords])
    lat_values = np.array([lat for _lon, lat in source_polygon_wgs84.exterior.coords])
    epsg = detect_utm_epsg(lat_values, lon_values)
    crs_projected = CRS.from_epsg(epsg)
    to_projected = Transformer.from_crs(4326, crs_projected, always_xy=True)
    to_wgs84 = Transformer.from_crs(crs_projected, 4326, always_xy=True)

    source_projected = transform_geometry(
        lambda x, y, z=None: to_projected.transform(x, y),
        source_polygon_wgs84,
    )
    source_projected = _ensure_polygon(source_projected)

    buffer_m = buffer_ft * METERS_PER_FOOT
    if buffer_m > 0:
        final_projected = source_projected.buffer(
            buffer_m,
            join_style=BUFFER_JOIN_STYLE,
            quad_segs=BUFFER_QUAD_SEGS,
            mitre_limit=BUFFER_MITRE_LIMIT,
        )
        final_projected = _ensure_polygon(final_projected)
    else:
        final_projected = source_projected

    final_wgs84 = transform_geometry(
        lambda x, y, z=None: to_wgs84.transform(x, y),
        final_projected,
    )
    final_wgs84 = _ensure_polygon(final_wgs84)
    projected_points = np.array(final_projected.exterior.coords[:-1], dtype=float)

    sections: list[BoundarySection] = []
    split_strategy = "Single polygon"
    section_area_min_acres = 0.0
    section_area_max_acres = 0.0
    section_label = shape_label.strip()
    if section_count > 1:
        section_label = section_label or kmz_path.stem
        sections, split_angles = _build_sections(
            final_projected,
            section_count,
            overlap_ft * METERS_PER_FOOT,
            section_label,
            to_wgs84,
        )
        base_areas = [section.base_area_acres for section in sections]
        section_area_min_acres = min(base_areas)
        section_area_max_acres = max(base_areas)
        split_strategy = _format_split_strategy(split_angles)

    metadata = BoundaryMetadata(
        source_folder=kmz_path.resolve(),
        input_type="KMZ polygon",
        jpg_count=0,
        gps_count=0,
        skipped_count=0,
        epsg=epsg,
        crs_name=crs_projected.name,
        buffer_ft=buffer_ft,
        median_spacing_ft=0.0,
        smoothing_ft=0.0,
        containment_padding_ft=0.0,
        concave_ratio=0.0,
        vertex_count=len(final_wgs84.exterior.coords),
        section_count=section_count,
        overlap_ft=overlap_ft if section_count > 1 else 0.0,
        shape_label=section_label if section_count > 1 else "",
        split_strategy=split_strategy,
        section_area_min_acres=section_area_min_acres,
        section_area_max_acres=section_area_max_acres,
        sections_connected=True,
    )

    return BoundaryResult(
        metadata=metadata,
        gps_points=[],
        projected_points=projected_points,
        base_polygon_projected=source_projected,
        final_polygon_projected=final_projected,
        final_polygon_wgs84=final_wgs84,
        sections=sections,
    )


def detect_utm_epsg(lats: np.ndarray, lons: np.ndarray) -> int:
    if len(lats) == 0 or len(lons) == 0:
        raise BoundaryError("No coordinates are available for CRS detection.")

    avg_lat = float(np.mean(lats))
    avg_lon = float(np.mean(lons))
    zone = math.floor((avg_lon + 180.0) / 6.0) + 1
    zone = max(1, min(60, zone))
    return (32600 if avg_lat >= 0 else 32700) + zone


def save_kmz(result: BoundaryResult, output_path: Path) -> Path:
    output_path = Path(output_path)
    if output_path.suffix.lower() != ".kmz":
        output_path = output_path.with_suffix(".kmz")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    kml = simplekml.Kml()
    output_stem = output_path.stem
    kml.document.name = output_stem

    if result.sections:
        folder = kml.newfolder(name=output_stem)
        for section in result.sections:
            coords = _polygon_to_kml_coords(section.polygon_wgs84)
            polygon = folder.newpolygon(
                name=section.display_name,
                outerboundaryis=coords,
            )
            polygon.description = _build_kml_description(result.metadata, section)
            _style_polygon(polygon, section.index - 1)
    else:
        coords = _polygon_to_kml_coords(result.final_polygon_wgs84)
        polygon = kml.newpolygon(
            name="JPG Camera Boundary",
            outerboundaryis=coords,
        )
        polygon.description = _build_kml_description(result.metadata)
        _style_polygon(polygon, 0)

    kml.savekmz(str(output_path))
    return output_path


def format_summary(metadata: BoundaryMetadata) -> str:
    lines = [
        f"Input type: {metadata.input_type}",
        f"Source input: {metadata.source_folder}",
    ]
    if metadata.input_type == "JPG folder":
        lines.extend(
            [
                f"JPG/JPEG files found: {metadata.jpg_count:,}",
                f"Usable GPS points: {metadata.gps_count:,}",
                f"Skipped files without GPS: {metadata.skipped_count:,}",
                f"Median camera spacing: {metadata.median_spacing_ft:,.1f} ft",
                f"Auto smoothing distance: {metadata.smoothing_ft:,.1f} ft",
                f"Auto containment padding: {metadata.containment_padding_ft:,.1f} ft",
            ]
        )
    else:
        lines.append("Source polygon: 1")
    lines.extend(
        [
            f"Detected projected CRS: EPSG:{metadata.epsg} ({metadata.crs_name})",
            f"Buffer distance: {metadata.buffer_ft:,.1f} ft",
            f"Output polygon vertices: {metadata.vertex_count:,}",
        ]
    )
    if metadata.section_count > 1:
        lines.extend(
            [
                f"Sections: {metadata.section_count}",
                f"Section overlap: {metadata.overlap_ft:,.1f} ft",
                f"Shape label: {metadata.shape_label}",
                f"Split strategy: {metadata.split_strategy}",
                "Sections connected: Yes",
                (
                    "Base section area range: "
                    f"{metadata.section_area_min_acres:,.1f} - "
                    f"{metadata.section_area_max_acres:,.1f} acres"
                ),
            ]
        )
    else:
        lines.append("Sections: 1")
    return "\n".join(lines)


def _build_sections(
    parent_polygon: Polygon,
    section_count: int,
    overlap_m: float,
    shape_label: str,
    to_wgs84: Transformer,
) -> tuple[list[BoundarySection], list[float]]:
    base_parts, split_angles = _partition_connected_polygon(
        parent_polygon,
        section_count,
    )
    sorted_parts = sorted(
        base_parts,
        key=lambda polygon: (polygon.centroid.x, -polygon.centroid.y),
    )

    sections: list[BoundarySection] = []
    half_overlap_m = overlap_m / 2.0
    for index, base_part in enumerate(sorted_parts, start=1):
        output_part = base_part
        if half_overlap_m > 0:
            output_part = base_part.buffer(
                half_overlap_m,
                join_style=BUFFER_JOIN_STYLE,
                quad_segs=BUFFER_QUAD_SEGS,
                mitre_limit=BUFFER_MITRE_LIMIT,
            ).intersection(parent_polygon)

        output_part = _strict_single_polygon(output_part)
        if output_part is None:
            raise BoundaryError(
                "Could not create connected overlapped sections. "
                "Try fewer shapes or a smaller overlap distance."
            )

        polygon_wgs84 = transform_geometry(
            lambda x, y, z=None: to_wgs84.transform(x, y),
            output_part,
        )
        polygon_wgs84 = _ensure_polygon(polygon_wgs84)
        sections.append(
            BoundarySection(
                index=index,
                total=section_count,
                display_name=f"{shape_label} ({index} of {section_count})",
                base_area_acres=base_part.area * ACRES_PER_SQUARE_METER,
                polygon_projected=output_part,
                polygon_wgs84=polygon_wgs84,
            )
        )

    return sections, split_angles


def _partition_connected_polygon(
    polygon: Polygon,
    target_count: int,
) -> tuple[list[Polygon], list[float]]:
    if target_count == 1:
        return [polygon], []

    left_count = target_count // 2
    right_count = target_count - left_count
    cut = _find_connected_cut(polygon, left_count / target_count)
    if cut is None:
        raise BoundaryError(
            "Could not split the outline into the requested number of connected "
            "sections. Try fewer shapes."
        )

    left_polygon, right_polygon, angle = cut
    left_parts, left_angles = _partition_connected_polygon(left_polygon, left_count)
    right_parts, right_angles = _partition_connected_polygon(right_polygon, right_count)
    return left_parts + right_parts, [angle] + left_angles + right_angles


def _find_connected_cut(
    polygon: Polygon,
    left_fraction: float,
) -> tuple[Polygon, Polygon, float] | None:
    coords = np.array(polygon.exterior.coords[:-1])
    center = tuple(coords.mean(axis=0))
    best: tuple[float, int, int, float, Polygon, Polygon] | None = None

    for priority, angle in enumerate(_candidate_split_angles(polygon)):
        rotated = rotate(polygon, -angle, origin=center, use_radians=False)
        minx, miny, maxx, maxy = rotated.bounds
        margin = max(maxx - minx, maxy - miny) * 2.0
        target_area = rotated.area * left_fraction
        cut_x = _find_equal_area_x(
            rotated,
            minx - margin,
            maxx + margin,
            miny - margin,
            maxy + margin,
            target_area,
        )
        left_rotated = _strict_single_polygon(
            rotated.intersection(box(minx - margin, miny - margin, cut_x, maxy + margin))
        )
        right_rotated = _strict_single_polygon(
            rotated.intersection(box(cut_x, miny - margin, maxx + margin, maxy + margin))
        )
        if left_rotated is None or right_rotated is None:
            continue

        left_polygon = _strict_single_polygon(
            rotate(left_rotated, angle, origin=center, use_radians=False)
        )
        right_polygon = _strict_single_polygon(
            rotate(right_rotated, angle, origin=center, use_radians=False)
        )
        if left_polygon is None or right_polygon is None:
            continue

        area_error = abs((left_polygon.area / polygon.area) - left_fraction)
        vertex_count = len(left_polygon.exterior.coords) + len(right_polygon.exterior.coords)
        candidate = (area_error, vertex_count, priority, angle, left_polygon, right_polygon)
        if best is None or candidate[:3] < best[:3]:
            best = candidate

    if best is None:
        return None
    return best[4], best[5], best[3]


def _candidate_split_angles(polygon: Polygon) -> list[float]:
    angles: list[float] = []
    coords = np.array(polygon.exterior.coords[:-1])
    if len(coords) >= 2:
        center = coords.mean(axis=0)
        centered = coords - center
        _, _, vh = np.linalg.svd(centered, full_matrices=False)
        principal_angle = math.degrees(math.atan2(vh[0][1], vh[0][0]))
    else:
        principal_angle = 0.0

    for angle in [0.0, 90.0, principal_angle, principal_angle + 90.0]:
        _append_unique_angle(angles, angle)
    for angle in range(0, 180, 15):
        _append_unique_angle(angles, float(angle))
    return angles


def _append_unique_angle(angles: list[float], angle: float) -> None:
    normalized = angle % 180.0
    if all(abs(normalized - existing) > 1e-6 for existing in angles):
        angles.append(normalized)


def _find_equal_area_x(
    polygon: Polygon,
    minx: float,
    maxx: float,
    miny: float,
    maxy: float,
    target_area: float,
) -> float:
    low = minx
    high = maxx
    for _ in range(52):
        midpoint = (low + high) / 2.0
        left_area = polygon.intersection(box(minx, miny, midpoint, maxy)).area
        if left_area < target_area:
            low = midpoint
        else:
            high = midpoint
    return (low + high) / 2.0


def _strict_single_polygon(geometry, min_area: float = 1e-6) -> Polygon | None:
    if geometry.is_empty:
        return None
    if not geometry.is_valid:
        geometry = make_valid(geometry)
    if isinstance(geometry, Polygon) and geometry.area > min_area:
        return geometry
    if isinstance(geometry, GeometryCollection):
        polygons = [
            part
            for part in geometry.geoms
            if isinstance(part, Polygon) and part.area > min_area
        ]
        if len(polygons) == 1:
            return polygons[0]
    return None


def _format_split_strategy(split_angles: list[float]) -> str:
    if not split_angles:
        return "Single polygon"
    rounded = [f"{angle:.1f} deg" for angle in split_angles[:6]]
    suffix = "" if len(split_angles) <= 6 else f", +{len(split_angles) - 6} more"
    return f"Auto connected equal-area ({len(split_angles)} cuts: {', '.join(rounded)}{suffix})"


def _polygon_to_kml_coords(polygon: Polygon) -> list[tuple[float, float, int]]:
    return [(lon, lat, 0) for lon, lat in polygon.exterior.coords]


def _style_polygon(polygon, color_index: int) -> None:
    palette = [
        (214, 39, 40),
        (44, 160, 44),
        (31, 119, 180),
        (148, 103, 189),
        (255, 127, 14),
        (23, 190, 207),
        (140, 86, 75),
        (227, 119, 194),
        (127, 127, 127),
        (188, 189, 34),
    ]
    red, green, blue = palette[color_index % len(palette)]
    polygon.style.linestyle.color = simplekml.Color.rgb(red, green, blue)
    polygon.style.linestyle.width = KML_LINE_WIDTH
    polygon.style.polystyle.color = simplekml.Color.rgb(red, green, blue, 45)
    polygon.style.polystyle.fill = 1
    polygon.style.polystyle.outline = 1


def _read_single_polygon_from_kmz(kmz_path: Path) -> Polygon:
    try:
        with zipfile.ZipFile(kmz_path) as archive:
            kml_names = [
                name
                for name in archive.namelist()
                if name.lower().endswith(".kml")
            ]
            if not kml_names:
                raise BoundaryError("The KMZ does not contain a KML document.")
            kml_name = _preferred_kml_name(kml_names)
            kml_data = archive.read(kml_name)
    except zipfile.BadZipFile as exc:
        raise BoundaryError(f"Input file is not a valid KMZ archive: {kmz_path}") from exc

    try:
        root = ET.fromstring(kml_data)
    except ET.ParseError as exc:
        raise BoundaryError("The KMZ contains invalid KML XML.") from exc

    polygon_elements = [
        element for element in root.iter() if _local_name(element.tag) == "Polygon"
    ]
    if not polygon_elements:
        raise BoundaryError("The KMZ does not contain a polygon.")
    if len(polygon_elements) > 1:
        raise BoundaryError(
            f"The KMZ must contain exactly one polygon; found {len(polygon_elements)}."
        )

    polygon_element = polygon_elements[0]
    if any(
        _local_name(element.tag) == "innerBoundaryIs"
        for element in polygon_element.iter()
    ):
        raise BoundaryError("KMZ polygons with holes are not supported for splitting.")

    coordinates_text = _find_outer_boundary_coordinates_text(polygon_element)
    if not coordinates_text:
        raise BoundaryError("The KMZ polygon does not contain outer boundary coordinates.")

    coordinates = _parse_kml_coordinates(coordinates_text)
    if len(coordinates) < 4:
        raise BoundaryError("The KMZ polygon must contain at least 4 coordinates.")
    if len(set(coordinates)) < 3:
        raise BoundaryError(
            "The KMZ polygon must contain at least 3 unique coordinates."
        )

    polygon = Polygon(coordinates)
    polygon = _strict_single_polygon(polygon, min_area=0.0)
    if polygon is None:
        raise BoundaryError("The KMZ polygon is invalid or disconnected.")
    return polygon


def _preferred_kml_name(kml_names: list[str]) -> str:
    return next(
        (name for name in kml_names if Path(name).name.lower() == "doc.kml"),
        kml_names[0],
    )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_outer_boundary_coordinates_text(polygon_element: ET.Element) -> str:
    outer_boundary = _find_first_descendant(polygon_element, "outerBoundaryIs")
    if outer_boundary is None:
        return ""

    linear_ring = _find_first_descendant(outer_boundary, "LinearRing")
    if linear_ring is None:
        return ""

    coordinates = _find_first_descendant(linear_ring, "coordinates")
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
            raise BoundaryError(f"KMZ coordinate is malformed: {token}")
        try:
            lon = float(parts[0])
            lat = float(parts[1])
        except ValueError as exc:
            raise BoundaryError(f"KMZ coordinate is malformed: {token}") from exc
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise BoundaryError(f"KMZ coordinate is outside WGS84 bounds: {token}")
        coordinates.append((lon, lat))
    return coordinates


def _read_gps_point(path: Path) -> GpsPoint | None:
    try:
        with path.open("rb") as image_file:
            with contextlib.redirect_stderr(io.StringIO()):
                tags = exifread.process_file(
                    image_file,
                    details=False,
                    stop_tag="GPSLongitude",
                )
    except Exception:
        return None

    lat_tag = tags.get("GPS GPSLatitude")
    lat_ref = tags.get("GPS GPSLatitudeRef")
    lon_tag = tags.get("GPS GPSLongitude")
    lon_ref = tags.get("GPS GPSLongitudeRef")
    if not lat_tag or not lat_ref or not lon_tag or not lon_ref:
        return None

    try:
        lat = _dms_to_decimal(lat_tag.values, str(lat_ref))
        lon = _dms_to_decimal(lon_tag.values, str(lon_ref))
    except Exception:
        return None

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return GpsPoint(path=path, lat=lat, lon=lon)


def _dms_to_decimal(values: list[object], ref: str) -> float:
    degrees, minutes, seconds = [_ratio_to_float(value) for value in values[:3]]
    decimal = degrees + (minutes / 60.0) + (seconds / 3600.0)
    if ref.strip().upper() in {"S", "W"}:
        decimal *= -1.0
    return decimal


def _ratio_to_float(value: object) -> float:
    if hasattr(value, "num") and hasattr(value, "den"):
        denominator = float(value.den)
        if denominator == 0:
            raise ValueError("EXIF ratio denominator is zero.")
        return float(value.num) / denominator
    return float(value)


def _median_nearest_neighbor_distance(points: np.ndarray) -> float:
    if len(points) < 2:
        return 0.0
    distances, _ = cKDTree(points).query(points, k=2)
    nearest = distances[:, 1]
    nearest = nearest[np.isfinite(nearest) & (nearest > 0)]
    if len(nearest) == 0:
        return 0.0
    return float(np.median(nearest))


def _simplify_with_containment(
    polygon: Polygon,
    points: MultiPoint,
    median_spacing_m: float,
    simplify_factor: float,
) -> tuple[Polygon, float, float]:
    if median_spacing_m <= 0 or simplify_factor == 0:
        return polygon, 0.0, 0.0

    tolerance_m = median_spacing_m * simplify_factor
    candidate = polygon.simplify(tolerance_m, preserve_topology=True)
    candidate = _ensure_polygon(candidate, points)

    padding_m = _max_distance_outside(candidate, points)
    if padding_m > 0:
        candidate = candidate.buffer(
            padding_m + 0.01,
            join_style=BUFFER_JOIN_STYLE,
            quad_segs=BUFFER_QUAD_SEGS,
            mitre_limit=BUFFER_MITRE_LIMIT,
        )
        candidate = _ensure_polygon(candidate, points)

    if not _covers_points(candidate, points):
        return polygon, 0.0, 0.0

    return candidate, tolerance_m, padding_m


def _max_distance_outside(polygon: Polygon, points: MultiPoint) -> float:
    max_distance = 0.0
    covered_polygon = polygon.buffer(1e-6)
    for point in points.geoms:
        if not covered_polygon.covers(point):
            max_distance = max(max_distance, point.distance(polygon))
    return max_distance


def _covers_points(polygon: Polygon, points: MultiPoint) -> bool:
    return polygon.buffer(1e-6).covers(points)


def _ensure_polygon(geometry, fallback_points: MultiPoint | None = None) -> Polygon:
    if geometry.is_empty:
        if fallback_points is not None:
            return _ensure_polygon(fallback_points.convex_hull)
        raise BoundaryError("Generated geometry is empty.")

    if not geometry.is_valid:
        geometry = make_valid(geometry)

    if isinstance(geometry, Polygon):
        return geometry

    if isinstance(geometry, MultiPolygon):
        merged = unary_union(geometry)
        if isinstance(merged, Polygon):
            return merged
        return merged.convex_hull

    if isinstance(geometry, GeometryCollection):
        polygons = [part for part in geometry.geoms if isinstance(part, Polygon)]
        if polygons:
            merged = unary_union(polygons)
            return _ensure_polygon(merged, fallback_points)

    convex = geometry.convex_hull
    if isinstance(convex, Polygon):
        return convex
    if fallback_points is not None:
        fallback = fallback_points.convex_hull
        if isinstance(fallback, Polygon):
            return fallback
    raise BoundaryError("Generated geometry is not polygonal.")


def _build_kml_description(
    metadata: BoundaryMetadata,
    section: BoundarySection | None = None,
) -> str:
    lines = [
        "Generated by JPG Boundary to KMZ.",
        f"Input type: {metadata.input_type}",
        f"Source input: {metadata.source_folder}",
        f"Detected projected CRS: EPSG:{metadata.epsg} ({metadata.crs_name})",
        f"Buffer distance: {metadata.buffer_ft:,.1f} ft",
        f"Output polygon vertices: {metadata.vertex_count:,}",
    ]
    if metadata.input_type == "JPG folder":
        lines[0] = "Generated from geotagged JPG camera positions."
        lines.extend(
            [
                f"JPG/JPEG files found: {metadata.jpg_count:,}",
                f"Usable GPS points: {metadata.gps_count:,}",
                f"Skipped files without GPS: {metadata.skipped_count:,}",
                f"Concave hull ratio: {metadata.concave_ratio}",
                f"Median camera spacing: {metadata.median_spacing_ft:,.1f} ft",
                f"Auto smoothing distance: {metadata.smoothing_ft:,.1f} ft",
                f"Auto containment padding: {metadata.containment_padding_ft:,.1f} ft",
            ]
        )
    else:
        lines.append("Source polygon: 1")
    if metadata.section_count > 1:
        lines.extend(
            [
                f"Sections: {metadata.section_count}",
                f"Section overlap: {metadata.overlap_ft:,.1f} ft",
                f"Shape label: {metadata.shape_label}",
                f"Split strategy: {metadata.split_strategy}",
                f"Sections connected: {'Yes' if metadata.sections_connected else 'No'}",
                (
                    "Base section area range: "
                    f"{metadata.section_area_min_acres:,.1f} - "
                    f"{metadata.section_area_max_acres:,.1f} acres"
                ),
            ]
        )
    if section is not None:
        lines.extend(
            [
                f"Section name: {section.display_name}",
                f"Section index: {section.index} of {section.total}",
                f"Base section area: {section.base_area_acres:,.1f} acres",
            ]
        )
    escaped = "<br/>".join(html.escape(line) for line in lines)
    return f"<![CDATA[{escaped}]]>"
