from __future__ import annotations

import contextlib
import html
import io
import math
import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Iterable

import exifread
import numpy as np
import simplekml
from pyproj import CRS, Transformer
from scipy.spatial import cKDTree
from shapely.affinity import rotate
from shapely.geometry import box
from shapely.geometry import GeometryCollection, LineString, MultiPoint, MultiPolygon, Polygon
from shapely.ops import transform as transform_geometry
from shapely.ops import unary_union
from shapely.validation import make_valid

from buffer_settings import BufferSettings
from polyline_compatibility import classify_per_side_input
from camera_preflight import analyze_camera_preflight
from geometry_hardening import (
    DEFAULT_BUFFER_QUAD_SEGS,
    buffer_projected_geometry,
    densify_projected_geometry,
    fill_polygon_interiors,
)
from kml_vector_input import PolygonSource, VectorInputError, VectorInputGeometry, load_vector_input
from natural_sectioning import (
    NaturalSplitDiagnostics,
    NaturalSplitError,
    build_natural_sections,
)
from outline_strategies import (
    OUTLINE_MODE_AUTO,
    OUTLINE_MODES,
    select_outline,
    summarize_candidates,
)
from polyline_boundary import (
    PolylineBoundaryError,
    build_polyline_boundary_with_recommended_buffer,
    build_per_side_polyline_boundary,
)
from section_ordering import order_parts_for_human_view
from section_quality import (
    MAX_AUTO_CUT_WIDTH_RATIO, MIN_AUTO_CROSSING_ANGLE_DEG,
    cut_width_ratio, introduced_cut_length, minimum_crossing_angle,
)


FEET_PER_METER = 3.280839895
METERS_PER_FOOT = 0.3048
DEFAULT_CONCAVE_RATIO = 0.15
DEFAULT_SIMPLIFY_FACTOR = 0.25
BUFFER_JOIN_STYLE = "round"
BUFFER_QUAD_SEGS = DEFAULT_BUFFER_QUAD_SEGS
BUFFER_MITRE_LIMIT = 3.0
MAX_SECTION_COUNT = 100
ACRES_PER_SQUARE_METER = 0.000247105381467
KML_LINE_WIDTH = 5.0
VECTOR_SIMPLIFY_MAX_DEVIATION_FT = 5.0
VECTOR_SIMPLIFY_MAX_AREA_DELTA_RATIO = 0.01
VECTOR_SIMPLIFY_SEARCH_ITERATIONS = 14
GENERATION_PROFILE_EXPORT = "export"
GENERATION_PROFILE_PREVIEW = "preview"
BOUNDARY_COLORS = (
    "#d62728", "#2ca02c", "#1f77b4", "#9467bd", "#ff7f0e",
    "#17becf", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22",
)


class BoundaryError(RuntimeError):
    """Raised when the input photos cannot produce a usable boundary."""


@dataclass(frozen=True)
class GpsPoint:
    path: Path
    lat: float
    lon: float
    capture_time: datetime | None = None


@dataclass(frozen=True)
class BoundaryMetadata:
    source_folder: Path
    input_type: str
    jpg_count: int
    gps_count: int
    skipped_count: int
    epsg: int
    crs_name: str
    buffer_ft: float | None
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
    preflight_pattern: str = ""
    preflight_confidence: float = 0.0
    order_source: str = ""
    preflight_warnings: str = ""
    outline_mode: str = ""
    selected_strategy: str = ""
    strategy_confidence: float = 0.0
    fallback_reason: str = ""
    candidate_summary: str = ""
    source_line_count: int = 0
    source_point_count: int = 0
    ignored_polygon_count: int = 0
    ignored_interior_ring_count: int = 0
    source_axis_hint_deg: float | None = None
    requested_split_direction_deg: float | None = None
    selected_split_direction_deg: float | None = None
    split_area_variance_pct: float = 0.0
    exterior_cleanup: str = ""
    vector_simplification_before_vertices: int = 0
    vector_simplification_after_vertices: int = 0
    vector_simplification_tolerance_ft: float = 0.0
    vector_simplification_max_deviation_ft: float = 0.0
    vector_simplification_area_delta_pct: float = 0.0
    vector_simplification_enabled: bool = True
    polyline_requested_buffer_ft: float = 0.0
    polyline_minimum_connected_buffer_ft: float = 0.0
    polyline_selected_buffer_ft: float = 0.0
    polyline_buffer_regularity_ratio: float = 0.0
    polyline_buffer_regularity_target: float = 0.0
    polyline_buffer_candidate_count: int = 0
    polyline_buffer_adjustment_reason: str = ""
    generation_profile: str = GENERATION_PROFILE_EXPORT
    buffer_mode: str = "unified"
    left_buffer_ft: float | None = None
    right_buffer_ft: float | None = None


@dataclass(frozen=True)
class VectorSimplificationStats:
    before_vertices: int = 0
    after_vertices: int = 0
    tolerance_m: float = 0.0
    max_deviation_m: float = 0.0
    area_delta_ratio: float = 0.0


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
    source_lines_projected: tuple[LineString, ...] = ()


@dataclass(frozen=True)
class BoundaryCollectionMetadata(BoundaryMetadata):
    source_polygon_count: int = 0
    output_polygon_count: int = 0
    facility_summaries: tuple[str, ...] = ()


@dataclass(frozen=True)
class NamedBoundaryResult:
    source_id: str
    source_name: str
    result: BoundaryResult


@dataclass
class BoundaryCollectionResult:
    metadata: BoundaryCollectionMetadata
    children: tuple[NamedBoundaryResult, ...]
    # Rendering copies share one CRS; children retain their local processing CRS.
    display_results: tuple[BoundaryResult, ...]


BoundaryOutput = BoundaryResult | BoundaryCollectionResult


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
    outline_mode: str = OUTLINE_MODE_AUTO,
    split_direction_deg: float | None = None,
) -> BoundaryResult:
    if not math.isfinite(buffer_ft) or buffer_ft < 0:
        raise BoundaryError("Buffer distance must be finite and 0 or greater.")
    if not 0 <= concave_ratio <= 1:
        raise BoundaryError("Concave hull ratio must be between 0 and 1.")
    if not math.isfinite(simplify_factor) or simplify_factor < 0:
        raise BoundaryError("Simplify factor must be finite and 0 or greater.")
    _validate_section_settings(section_count, overlap_ft, split_direction_deg)
    if outline_mode not in OUTLINE_MODES:
        raise BoundaryError(f"Unknown outline mode: {outline_mode}")

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
    preflight = analyze_camera_preflight(gps_points, projected_points)
    unique_points = np.unique(np.round(projected_points, 6), axis=0)
    if len(unique_points) < 3:
        raise BoundaryError("The geotagged JPGs do not contain 3 unique positions.")

    point_geometry = MultiPoint(unique_points)
    outline_selection = select_outline(
        mode=outline_mode,
        projected_points=projected_points,
        preflight=preflight,
        concave_ratio=concave_ratio,
        section_count=section_count,
    )
    hull = _ensure_polygon(outline_selection.selected.polygon_projected, point_geometry)
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
        final_projected = buffer_projected_geometry(
            base_polygon,
            buffer_m,
            join_style=BUFFER_JOIN_STYLE,
            mitre_limit=BUFFER_MITRE_LIMIT,
        )
        final_projected = _ensure_polygon(final_projected, point_geometry)
    else:
        final_projected = base_polygon

    final_projected = _ensure_polygon(densify_projected_geometry(final_projected))
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
    selected_split_direction_deg: float | None = None
    split_area_variance_pct = 0.0

    if section_count > 1:
        section_label = section_label or "JPG Camera Boundary"
        sections, split_diagnostics = _build_sections(
            final_projected,
            section_count,
            overlap_ft * METERS_PER_FOOT,
            section_label,
            to_wgs84,
            split_direction_deg=split_direction_deg,
        )
        base_areas = [section.base_area_acres for section in sections]
        section_area_min_acres = min(base_areas)
        section_area_max_acres = max(base_areas)
        split_strategy = split_diagnostics.split_strategy
        selected_split_direction_deg = split_diagnostics.selected_split_direction_deg
        split_area_variance_pct = split_diagnostics.area_variance_pct

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
        preflight_pattern=preflight.pattern,
        preflight_confidence=preflight.confidence,
        order_source=preflight.order_source,
        preflight_warnings="; ".join(preflight.warnings),
        outline_mode=outline_mode,
        selected_strategy=outline_selection.selected.strategy,
        strategy_confidence=outline_selection.selected.confidence,
        fallback_reason=outline_selection.fallback_reason,
        candidate_summary=summarize_candidates(outline_selection.candidates),
        requested_split_direction_deg=split_direction_deg if section_count > 1 else None,
        selected_split_direction_deg=selected_split_direction_deg,
        split_area_variance_pct=split_area_variance_pct,
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
    outline_mode: str = OUTLINE_MODE_AUTO,
    split_direction_deg: float | None = None,
    generation_profile: str = GENERATION_PROFILE_EXPORT,
    simplify_vector_output: bool = True,
    *,
    buffer_settings: BufferSettings | None = None,
) -> BoundaryOutput:
    if buffer_settings is not None and buffer_settings.mode == "unified":
        buffer_ft = buffer_settings.unified_ft
    input_path = Path(input_path)
    if input_path.is_dir():
        if buffer_settings is not None and buffer_settings.mode == "per_side":
            raise BoundaryError("Per-side buffers require a polyline-only KMZ.")
        return generate_boundary(
            input_path,
            buffer_ft,
            section_count=section_count,
            overlap_ft=overlap_ft,
            shape_label=shape_label,
            outline_mode=outline_mode,
            split_direction_deg=split_direction_deg,
        )
    generation_profile = _validate_generation_profile(generation_profile)
    if input_path.is_file() and input_path.suffix.lower() == ".kmz":
        return generate_boundary_from_kmz(
            input_path,
            buffer_ft,
            section_count=section_count,
            overlap_ft=overlap_ft,
            shape_label=shape_label,
            split_direction_deg=split_direction_deg,
            generation_profile=generation_profile,
            simplify_vector_output=simplify_vector_output,
            buffer_settings=buffer_settings,
        )
    if input_path.is_file() and input_path.suffix.lower() == ".kml":
        return generate_boundary_from_vector_file(
            input_path,
            buffer_ft,
            section_count=section_count,
            overlap_ft=overlap_ft,
            shape_label=shape_label,
            split_direction_deg=split_direction_deg,
            generation_profile=generation_profile,
            simplify_vector_output=simplify_vector_output,
            buffer_settings=buffer_settings,
        )
    raise BoundaryError("Choose a folder of JPGs, KML file, or KMZ file.")


def generate_boundary_from_kmz(
    kmz_path: Path,
    buffer_ft: float,
    section_count: int = 1,
    overlap_ft: float = 50.0,
    shape_label: str = "",
    split_direction_deg: float | None = None,
    generation_profile: str = GENERATION_PROFILE_EXPORT,
    simplify_vector_output: bool = True,
    *,
    buffer_settings: BufferSettings | None = None,
) -> BoundaryOutput:
    kmz_path = Path(kmz_path)
    if kmz_path.suffix.lower() != ".kmz":
        raise BoundaryError(f"Input path is not a KMZ file: {kmz_path}")
    return generate_boundary_from_vector_file(
        kmz_path,
        buffer_ft,
        section_count=section_count,
        overlap_ft=overlap_ft,
        shape_label=shape_label,
        split_direction_deg=split_direction_deg,
        generation_profile=generation_profile,
        simplify_vector_output=simplify_vector_output,
        buffer_settings=buffer_settings,
    )


def generate_boundary_from_vector_file(
    vector_path: Path,
    buffer_ft: float,
    section_count: int = 1,
    overlap_ft: float = 50.0,
    shape_label: str = "",
    split_direction_deg: float | None = None,
    generation_profile: str = GENERATION_PROFILE_EXPORT,
    simplify_vector_output: bool = True,
    *,
    buffer_settings: BufferSettings | None = None,
) -> BoundaryOutput:
    try:
        vector_geometry = load_vector_input(Path(vector_path))
    except VectorInputError as exc:
        raise BoundaryError(str(exc)) from exc
    return generate_boundary_from_vector_geometry(
        vector_geometry, buffer_ft, section_count, overlap_ft, shape_label,
        split_direction_deg, generation_profile, simplify_vector_output,
        buffer_settings=buffer_settings,
    )


def generate_boundary_from_vector_geometry(
    vector_geometry: VectorInputGeometry,
    buffer_ft: float,
    section_count: int = 1,
    overlap_ft: float = 50.0,
    shape_label: str = "",
    split_direction_deg: float | None = None,
    generation_profile: str = GENERATION_PROFILE_EXPORT,
    simplify_vector_output: bool = True,
    *,
    buffer_settings: BufferSettings | None = None,
) -> BoundaryOutput:
    try:
        settings = buffer_settings or BufferSettings(unified_ft=buffer_ft)
    except ValueError as exc:
        raise BoundaryError(str(exc)) from exc
    if settings.mode == "per_side":
        compatibility = classify_per_side_input(vector_geometry)
        if not compatibility.eligible:
            raise BoundaryError(compatibility.explanation)
        buffer_ft = 0.0  # Legacy scalar is inactive in this mode.
    else:
        buffer_ft = settings.unified_ft
    if buffer_ft < 0:
        raise BoundaryError("Buffer distance must be 0 or greater.")
    _validate_section_settings(section_count, overlap_ft, split_direction_deg)
    generation_profile = _validate_generation_profile(generation_profile)

    if vector_geometry.lines_wgs84:
        return _generate_boundary_from_polyline_vector(
            vector_geometry,
            buffer_ft=buffer_ft,
            section_count=section_count,
            overlap_ft=overlap_ft,
            shape_label=shape_label,
            split_direction_deg=split_direction_deg,
            generation_profile=generation_profile,
            simplify_vector_output=simplify_vector_output,
            buffer_settings=settings,
        )
    if not vector_geometry.polygons_wgs84:
        raise BoundaryError("No source polygons are available.")
    polygon_generator = (
        _generate_boundary_collection if len(vector_geometry.polygons_wgs84) > 1
        else _generate_boundary_from_polygon_vector
    )
    return polygon_generator(
        vector_geometry,
        buffer_ft=buffer_ft,
        section_count=section_count,
        overlap_ft=overlap_ft,
        shape_label=shape_label,
        split_direction_deg=split_direction_deg,
        generation_profile=generation_profile,
        simplify_vector_output=simplify_vector_output,
    )


def _generate_boundary_collection(
    vector_geometry: VectorInputGeometry, **options,
) -> BoundaryCollectionResult:
    sources = vector_geometry.polygon_sources or tuple(
        PolygonSource(f"polygon-{i}", f"Polygon {i}", "")
        for i in range(1, len(vector_geometry.polygons_wgs84) + 1)
    )
    if len(sources) != len(vector_geometry.polygons_wgs84):
        raise BoundaryError("Polygon source metadata does not match the geometry count.")
    children = []
    for polygon, source in zip(vector_geometry.polygons_wgs84, sources):
        try:
            if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
                raise BoundaryError("Source polygon must be valid and have positive area.")
            child_input = replace(
                vector_geometry, polygons_wgs84=(polygon,), polygon_sources=(source,),
                source_name=source.name,
                ignored_interior_ring_count=source.ignored_interior_ring_count,
            )
            child = _generate_boundary_from_polygon_vector(
                child_input, **{**options, "shape_label": source.name},
            )
        except Exception as exc:
            raise BoundaryError(f"Polygon {source.name!r} ({source.source_id}): {exc}") from exc
        children.append(NamedBoundaryResult(source.source_id, source.name, child))

    coords = np.concatenate([np.asarray(p.exterior.coords) for p in vector_geometry.polygons_wgs84])
    display_epsg = detect_utm_epsg(coords[:, 1], coords[:, 0])
    display_crs_name = CRS.from_epsg(display_epsg).name
    display_results = tuple(_boundary_in_display_crs(child.result, display_epsg) for child in children)
    metas = [child.result.metadata for child in children]
    aggregate = replace(
        metas[0], epsg=display_epsg, crs_name=display_crs_name,
        shape_label=options["shape_label"], split_strategy="Independent source polygons",
        selected_split_direction_deg=None,
        vertex_count=sum(m.vertex_count for m in metas),
        ignored_interior_ring_count=sum(m.ignored_interior_ring_count for m in metas),
        section_area_min_acres=min(m.section_area_min_acres for m in metas),
        section_area_max_acres=max(m.section_area_max_acres for m in metas),
        split_area_variance_pct=max(m.split_area_variance_pct for m in metas),
        vector_simplification_before_vertices=sum(m.vector_simplification_before_vertices for m in metas),
        vector_simplification_after_vertices=sum(m.vector_simplification_after_vertices for m in metas),
        vector_simplification_tolerance_ft=max(m.vector_simplification_tolerance_ft for m in metas),
        vector_simplification_max_deviation_ft=max(m.vector_simplification_max_deviation_ft for m in metas),
        vector_simplification_area_delta_pct=max(m.vector_simplification_area_delta_pct for m in metas),
    )
    metadata = BoundaryCollectionMetadata(
        **vars(aggregate), source_polygon_count=len(children),
        output_polygon_count=sum(len(child.result.sections) or 1 for child in children),
        facility_summaries=tuple(
            f"{child.source_name} [{child.source_id}]\n{format_summary(child.result.metadata)}"
            for child in children
        ),
    )
    return BoundaryCollectionResult(metadata, tuple(children), display_results)


def _boundary_in_display_crs(result: BoundaryResult, epsg: int) -> BoundaryResult:
    """Create a rendering view without changing processing geometry or its metrics."""
    transformer = Transformer.from_crs(result.metadata.epsg, epsg, always_xy=True)
    def project(polygon: Polygon) -> Polygon:
        return transform_geometry(transformer.transform, polygon)
    base = project(result.base_polygon_projected)
    return replace(
        result,
        metadata=replace(result.metadata, epsg=epsg, crs_name=CRS.from_epsg(epsg).name),
        projected_points=np.asarray(base.exterior.coords[:-1]),
        base_polygon_projected=base,
        final_polygon_projected=project(result.final_polygon_projected),
        sections=[replace(s, polygon_projected=project(s.polygon_projected)) for s in result.sections],
    )


def _generate_boundary_from_polygon_vector(
    vector_geometry: VectorInputGeometry,
    *,
    buffer_ft: float,
    section_count: int,
    overlap_ft: float,
    shape_label: str,
    split_direction_deg: float | None,
    generation_profile: str,
    simplify_vector_output: bool,
) -> BoundaryResult:
    source_polygon_wgs84 = _ensure_polygon(
        fill_polygon_interiors(vector_geometry.polygons_wgs84[0])
    )
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
    source_projected = _ensure_polygon(fill_polygon_interiors(source_projected))

    buffer_m = buffer_ft * METERS_PER_FOOT
    ignored_generated_interiors = 0
    if buffer_m > 0:
        buffered_projected = buffer_projected_geometry(
            source_projected,
            buffer_m,
            join_style=BUFFER_JOIN_STYLE,
            mitre_limit=BUFFER_MITRE_LIMIT,
        )
        ignored_generated_interiors = _count_polygon_interiors(buffered_projected)
        final_projected = _ensure_polygon(fill_polygon_interiors(buffered_projected))
    else:
        final_projected = source_projected

    final_projected = _require_single_exterior_polygon(
        fill_polygon_interiors(final_projected),
        "KML/KMZ polygon input did not produce one exterior-only polygon.",
    )

    sections: list[BoundarySection] = []
    split_strategy = "Single polygon"
    section_area_min_acres = 0.0
    section_area_max_acres = 0.0
    section_label = shape_label.strip()
    selected_split_direction_deg: float | None = None
    split_area_variance_pct = 0.0
    export_quality = (
        generation_profile == GENERATION_PROFILE_EXPORT and simplify_vector_output
    )
    simplification_stats = VectorSimplificationStats(
        before_vertices=_polygon_vertex_count(final_projected),
        after_vertices=_polygon_vertex_count(final_projected),
    )
    if section_count > 1:
        section_label = section_label or vector_geometry.source_path.stem
        sections, split_diagnostics = _build_sections(
            final_projected,
            section_count,
            overlap_ft * METERS_PER_FOOT,
            section_label,
            to_wgs84,
            split_direction_deg=split_direction_deg,
            densify_sections=False,
        )
        if export_quality:
            sections, simplification_stats = _simplify_vector_sections(
                sections,
                to_wgs84,
            )
        else:
            simplification_stats = _unsimplified_vector_section_stats(sections)
        base_areas = [section.base_area_acres for section in sections]
        section_area_min_acres = min(base_areas)
        section_area_max_acres = max(base_areas)
        split_strategy = split_diagnostics.split_strategy
        selected_split_direction_deg = split_diagnostics.selected_split_direction_deg
        split_area_variance_pct = split_diagnostics.area_variance_pct
        final_wgs84 = _project_polygon_to_wgs84(final_projected, to_wgs84)
    else:
        if export_quality:
            final_projected, simplification_stats = _simplify_vector_output_polygon(
                final_projected
            )
        final_wgs84 = _project_polygon_to_wgs84(final_projected, to_wgs84)
    projected_points = np.array(final_projected.exterior.coords[:-1], dtype=float)

    ignored_interior_count = (
        vector_geometry.ignored_interior_ring_count + ignored_generated_interiors
    )
    metadata = BoundaryMetadata(
        source_folder=vector_geometry.source_path,
        input_type=_input_type_label(vector_geometry.input_kind),
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
        vertex_count=_export_vertex_count(final_wgs84, sections),
        section_count=section_count,
        overlap_ft=overlap_ft if section_count > 1 else 0.0,
        shape_label=section_label if section_count > 1 else "",
        split_strategy=split_strategy,
        section_area_min_acres=section_area_min_acres,
        section_area_max_acres=section_area_max_acres,
        sections_connected=True,
        outline_mode="source_polygon",
        selected_strategy="source_polygon",
        strategy_confidence=1.0,
        ignored_interior_ring_count=ignored_interior_count,
        requested_split_direction_deg=split_direction_deg if section_count > 1 else None,
        selected_split_direction_deg=selected_split_direction_deg,
        split_area_variance_pct=split_area_variance_pct,
        exterior_cleanup=_format_exterior_cleanup(ignored_interior_count),
        vector_simplification_before_vertices=simplification_stats.before_vertices,
        vector_simplification_after_vertices=simplification_stats.after_vertices,
        vector_simplification_tolerance_ft=(
            simplification_stats.tolerance_m * FEET_PER_METER
        ),
        vector_simplification_max_deviation_ft=(
            simplification_stats.max_deviation_m * FEET_PER_METER
        ),
        vector_simplification_area_delta_pct=(
            simplification_stats.area_delta_ratio * 100.0
        ),
        vector_simplification_enabled=simplify_vector_output,
        generation_profile=generation_profile,
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


def _generate_boundary_from_polyline_vector(
    vector_geometry: VectorInputGeometry,
    *,
    buffer_ft: float,
    section_count: int,
    overlap_ft: float,
    shape_label: str,
    split_direction_deg: float | None,
    generation_profile: str,
    simplify_vector_output: bool,
    buffer_settings: BufferSettings | None = None,
) -> BoundaryResult:
    per_side = buffer_settings is not None and buffer_settings.mode == "per_side"
    try:
        if per_side:
            line_boundary = build_per_side_polyline_boundary(
                vector_geometry.lines_wgs84, buffer_settings.left_ft, buffer_settings.right_ft,
            )
        else:
            line_boundary = build_polyline_boundary_with_recommended_buffer(
                vector_geometry.lines_wgs84, buffer_ft,
            )
    except PolylineBoundaryError as exc:
        raise BoundaryError(str(exc)) from exc

    effective_buffer_ft = float(line_boundary.diagnostics.get("buffer_ft", buffer_ft))
    to_projected = Transformer.from_crs(4326, line_boundary.epsg, always_xy=True)
    final_projected = _require_single_exterior_polygon(
        fill_polygon_interiors(line_boundary.final_polygon_projected),
        "Polyline buffer did not produce one exterior-only polygon.",
    )
    to_wgs84 = Transformer.from_crs(
        CRS.from_epsg(line_boundary.epsg),
        4326,
        always_xy=True,
    )

    source_lines = tuple(transform_geometry(to_projected.transform, line)
                         for line in vector_geometry.lines_wgs84)
    source_union = unary_union(source_lines)
    sections: list[BoundarySection] = []
    split_strategy = "Single polygon"
    section_area_min_acres = 0.0
    section_area_max_acres = 0.0
    section_label = shape_label.strip()
    selected_split_direction_deg: float | None = None
    split_area_variance_pct = 0.0
    export_quality = (
        generation_profile == GENERATION_PROFILE_EXPORT and simplify_vector_output
    )
    simplification_stats = VectorSimplificationStats(
        before_vertices=_polygon_vertex_count(final_projected),
        after_vertices=_polygon_vertex_count(final_projected),
    )
    if section_count > 1:
        section_label = section_label or vector_geometry.source_path.stem
        sections, split_diagnostics = _build_sections(
            final_projected,
            section_count,
            overlap_ft * METERS_PER_FOOT,
            section_label,
            to_wgs84,
            split_direction_deg=split_direction_deg,
            axis_hint_deg=line_boundary.source_axis_hint_deg,
            densify_sections=False,
        )
        if export_quality:
            original_sections = sections
            sections, simplification_stats = _simplify_vector_sections(sections, to_wgs84)
            if per_side and not unary_union([s.polygon_projected for s in sections]).buffer(2e-6).covers(source_union):
                sections = original_sections
                simplification_stats = _unsimplified_vector_section_stats(sections)
        else:
            simplification_stats = _unsimplified_vector_section_stats(sections)
        base_areas = [section.base_area_acres for section in sections]
        section_area_min_acres = min(base_areas)
        section_area_max_acres = max(base_areas)
        split_strategy = split_diagnostics.split_strategy
        selected_split_direction_deg = split_diagnostics.selected_split_direction_deg
        split_area_variance_pct = split_diagnostics.area_variance_pct
        final_wgs84 = _project_polygon_to_wgs84(final_projected, to_wgs84)
    else:
        if export_quality:
            original = final_projected
            final_projected, simplification_stats = _simplify_vector_output_polygon(original)
            if per_side and not final_projected.buffer(2e-6).covers(source_union):
                final_projected = original
                count = _polygon_vertex_count(original)
                simplification_stats = VectorSimplificationStats(count, count)
        final_wgs84 = _project_polygon_to_wgs84(final_projected, to_wgs84)
    projected_points = np.array(final_projected.exterior.coords[:-1], dtype=float)

    ignored_interior_count = int(
        line_boundary.diagnostics.get("ignored_interior_ring_count", 0)
    )
    metadata = BoundaryMetadata(
        source_folder=vector_geometry.source_path,
        input_type=_input_type_label(vector_geometry.input_kind),
        jpg_count=0,
        gps_count=0,
        skipped_count=0,
        epsg=line_boundary.epsg,
        crs_name=line_boundary.crs_name,
        buffer_ft=None if per_side else effective_buffer_ft,
        buffer_mode="per_side" if per_side else "unified",
        left_buffer_ft=buffer_settings.left_ft if per_side else None,
        right_buffer_ft=buffer_settings.right_ft if per_side else None,
        median_spacing_ft=0.0,
        smoothing_ft=0.0,
        containment_padding_ft=0.0,
        concave_ratio=0.0,
        vertex_count=_export_vertex_count(final_wgs84, sections),
        section_count=section_count,
        overlap_ft=overlap_ft if section_count > 1 else 0.0,
        shape_label=section_label if section_count > 1 else "",
        split_strategy=split_strategy,
        section_area_min_acres=section_area_min_acres,
        section_area_max_acres=section_area_max_acres,
        sections_connected=True,
        outline_mode="source_linework",
        selected_strategy="source_linework_buffer",
        strategy_confidence=1.0,
        source_line_count=line_boundary.source_line_count,
        source_point_count=line_boundary.source_point_count,
        ignored_polygon_count=vector_geometry.ignored_polygon_count,
        ignored_interior_ring_count=ignored_interior_count,
        source_axis_hint_deg=line_boundary.source_axis_hint_deg,
        requested_split_direction_deg=split_direction_deg if section_count > 1 else None,
        selected_split_direction_deg=selected_split_direction_deg,
        split_area_variance_pct=split_area_variance_pct,
        exterior_cleanup=_format_exterior_cleanup(ignored_interior_count),
        vector_simplification_before_vertices=simplification_stats.before_vertices,
        vector_simplification_after_vertices=simplification_stats.after_vertices,
        vector_simplification_tolerance_ft=(
            simplification_stats.tolerance_m * FEET_PER_METER
        ),
        vector_simplification_max_deviation_ft=(
            simplification_stats.max_deviation_m * FEET_PER_METER
        ),
        vector_simplification_area_delta_pct=(
            simplification_stats.area_delta_ratio * 100.0
        ),
        vector_simplification_enabled=simplify_vector_output,
        polyline_requested_buffer_ft=float(
            line_boundary.diagnostics.get("requested_buffer_ft", buffer_ft)
        ),
        polyline_minimum_connected_buffer_ft=float(
            line_boundary.diagnostics.get("minimum_connected_buffer_ft", 0.0)
        ),
        polyline_selected_buffer_ft=float(
            line_boundary.diagnostics.get("selected_buffer_ft", effective_buffer_ft)
        ),
        polyline_buffer_regularity_ratio=float(
            line_boundary.diagnostics.get("regularity_ratio", 0.0)
        ),
        polyline_buffer_regularity_target=float(
            line_boundary.diagnostics.get("regularity_target", 0.0)
        ),
        polyline_buffer_candidate_count=int(
            line_boundary.diagnostics.get("candidate_count", 0)
        ),
        polyline_buffer_adjustment_reason=str(
            line_boundary.diagnostics.get("adjustment_reason", "")
        ),
        generation_profile=generation_profile,
    )

    return BoundaryResult(
        metadata=metadata,
        gps_points=[],
        projected_points=projected_points,
        base_polygon_projected=line_boundary.base_polygon_projected,
        final_polygon_projected=final_projected,
        final_polygon_wgs84=final_wgs84,
        sections=sections,
        source_lines_projected=source_lines,
    )


def detect_utm_epsg(lats: np.ndarray, lons: np.ndarray) -> int:
    if len(lats) == 0 or len(lons) == 0:
        raise BoundaryError("No coordinates are available for CRS detection.")

    avg_lat = float(np.mean(lats))
    avg_lon = float(np.mean(lons))
    zone = math.floor((avg_lon + 180.0) / 6.0) + 1
    zone = max(1, min(60, zone))
    return (32600 if avg_lat >= 0 else 32700) + zone


def _validate_section_settings(section_count: int, overlap_ft: float, split_direction_deg: float | None) -> None:
    if (isinstance(section_count, bool) or not isinstance(section_count, (int, np.integer))
            or not 1 <= section_count <= MAX_SECTION_COUNT):
        raise BoundaryError(f"# of Shapes must be a whole number between 1 and {MAX_SECTION_COUNT}.")
    if not math.isfinite(overlap_ft) or overlap_ft < 0:
        raise BoundaryError("Overlap distance must be finite and 0 or greater.")
    if split_direction_deg is not None and not math.isfinite(split_direction_deg):
        raise BoundaryError("Split direction must be finite.")


def save_kmz(result: BoundaryOutput, output_path: Path) -> Path:
    results = (
        [child.result for child in result.children]
        if isinstance(result, BoundaryCollectionResult) else [result]
    )
    if any(item.metadata.generation_profile != GENERATION_PROFILE_EXPORT for item in [result, *results]):
        raise BoundaryError(
            "Preview-quality boundaries must be regenerated before KMZ export."
        )
    output_path = Path(output_path)
    if output_path.suffix.lower() != ".kmz":
        output_path = output_path.with_suffix(".kmz")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    kml = simplekml.Kml()
    output_stem = output_path.stem
    kml.document.name = output_stem

    if isinstance(result, BoundaryCollectionResult):
        color_index = 0
        for child in result.children:
            folder = kml.newfolder(name=child.source_name)
            folder.description = format_summary(child.result.metadata)
            outputs = (
                [(section.display_name, section.polygon_wgs84, section) for section in child.result.sections]
                or [(child.source_name, child.result.final_polygon_wgs84, None)]
            )
            for name, geometry, section in outputs:
                polygon = folder.newpolygon(name=name, outerboundaryis=_polygon_to_kml_coords(geometry))
                polygon.description = _build_kml_description(child.result.metadata, section)
                _style_polygon(polygon, color_index)
                color_index += 1
    elif result.sections:
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

    # Finish writing beside the destination before replacing an existing export.
    # Closing the handle first also lets ZipFile reopen it on Windows.
    with tempfile.NamedTemporaryFile(dir=output_path.parent, prefix=".boundary-", suffix=".kmz", delete=False) as pending:
        temporary_path = Path(pending.name)
    try:
        kml.savekmz(str(temporary_path))
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return output_path


def format_summary(metadata: BoundaryMetadata) -> str:
    if isinstance(metadata, BoundaryCollectionMetadata):
        lines = [
            f"Input type: {metadata.input_type} collection",
            f"Source input: {metadata.source_folder}",
            f"Source polygons: {metadata.source_polygon_count}",
            f"Sections per polygon: {metadata.section_count}",
            f"Output polygons: {metadata.output_polygon_count}",
            "Additional buffer: " + buffer_settings_from_metadata(metadata).description,
            f"Section overlap: {metadata.overlap_ft:,.1f} ft",
            f"Preview CRS: EPSG:{metadata.epsg} ({metadata.crs_name})",
            "Processing CRS: selected independently per facility",
            f"Output polygon vertices: {metadata.vertex_count:,}",
            f"Interior rings ignored/filled: {metadata.ignored_interior_ring_count:,}",
            *_format_vector_simplification_lines(metadata),
            "Simplification deviation and area-change values are maxima across facilities.",
        ]
        return "\n".join(lines) + "\n\n" + "\n\n".join(metadata.facility_summaries)
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
                f"Preflight pattern: {metadata.preflight_pattern or 'Not evaluated'}",
                f"Preflight confidence: {metadata.preflight_confidence:.2f}",
                f"Camera order source: {metadata.order_source or 'Not evaluated'}",
                f"Outline mode: {metadata.outline_mode or 'Not evaluated'}",
                f"Selected strategy: {metadata.selected_strategy or 'Not evaluated'}",
                f"Strategy confidence: {metadata.strategy_confidence:.2f}",
                f"Median camera spacing: {metadata.median_spacing_ft:,.1f} ft",
                f"Auto smoothing distance: {metadata.smoothing_ft:,.1f} ft",
                f"Auto containment padding: {metadata.containment_padding_ft:,.1f} ft",
            ]
        )
        if metadata.preflight_warnings:
            lines.append(f"Preflight warnings: {metadata.preflight_warnings}")
        if metadata.fallback_reason:
            lines.append(f"Fallback reason: {metadata.fallback_reason}")
        if metadata.candidate_summary:
            lines.append(f"Candidate summary: {metadata.candidate_summary}")
    else:
        if metadata.source_line_count:
            lines.extend(
                [
                    f"Source LineStrings: {metadata.source_line_count:,}",
                    f"Source line coordinates: {metadata.source_point_count:,}",
                ]
            )
            if metadata.source_axis_hint_deg is not None:
                lines.append(
                    f"Source line orientation hint: {metadata.source_axis_hint_deg:.1f} deg"
                )
            if metadata.ignored_polygon_count:
                lines.append(
                    "Using source LineStrings; polygons ignored: "
                    f"{metadata.ignored_polygon_count:,}"
                )
            lines.extend(_format_polyline_auto_buffer_lines(metadata))
        else:
            lines.append("Source polygon: 1")
        if metadata.ignored_interior_ring_count:
            lines.append(
                f"Interior rings ignored/filled: {metadata.ignored_interior_ring_count:,}"
            )
        if metadata.exterior_cleanup:
            lines.append(f"Exterior cleanup: {metadata.exterior_cleanup}")
        lines.extend(_format_vector_simplification_lines(metadata))
    lines.extend(
        [
            f"Detected projected CRS: EPSG:{metadata.epsg} ({metadata.crs_name})",
            "Buffer distance: " + buffer_settings_from_metadata(metadata).description,
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
                    "Selected split direction: Auto"
                    if metadata.selected_split_direction_deg is None
                    else f"Selected split direction: {metadata.selected_split_direction_deg:.1f} deg"
                ),
                f"Section area variance: {metadata.split_area_variance_pct:.1f}%",
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
    *,
    split_direction_deg: float | None = None,
    axis_hint_deg: float | None = None,
    densify_sections: bool = True,
):
    try:
        natural_sections, diagnostics = build_natural_sections(
            parent_polygon,
            section_count,
            overlap_m,
            shape_label,
            to_wgs84,
            split_direction_deg=split_direction_deg,
            axis_hint_deg=axis_hint_deg,
            densify_sections=densify_sections,
        )
    except NaturalSplitError as exc:
        if split_direction_deg is None:
            try:
                return _build_recursive_connected_sections(
                    parent_polygon,
                    section_count,
                    overlap_m,
                    shape_label,
                    to_wgs84,
                    densify_sections=densify_sections,
                )
            except BoundaryError as fallback_exc:
                raise BoundaryError(
                    f"{exc} Connected fallback also failed: {fallback_exc}"
                ) from fallback_exc
        raise BoundaryError(str(exc)) from exc

    sections = [
        BoundarySection(
            index=section.index,
            total=section.total,
            display_name=section.display_name,
            base_area_acres=section.base_area_acres,
            polygon_projected=section.polygon_projected,
            polygon_wgs84=section.polygon_wgs84,
        )
        for section in natural_sections
    ]
    return sections, diagnostics


def _build_recursive_connected_sections(
    parent_polygon: Polygon,
    section_count: int,
    overlap_m: float,
    shape_label: str,
    to_wgs84: Transformer,
    *,
    densify_sections: bool,
) -> tuple[list[BoundarySection], NaturalSplitDiagnostics]:
    base_parts, split_angles = _partition_connected_polygon(parent_polygon, section_count)
    base_parts = order_parts_for_human_view(parent_polygon, base_parts)
    sections: list[BoundarySection] = []
    base_area_acres: list[float] = []

    for index, base_part in enumerate(base_parts, start=1):
        projected = _recursive_section_output_polygon(
            parent_polygon,
            base_part,
            overlap_m,
        )
        if densify_sections:
            projected = _require_single_exterior_polygon(
                densify_projected_geometry(projected),
                "Connected fallback section could not be densified.",
            )
        polygon_wgs84 = _project_polygon_to_wgs84(projected, to_wgs84)
        base_area_acres.append(base_part.area * ACRES_PER_SQUARE_METER)
        sections.append(
            BoundarySection(
                index=index,
                total=section_count,
                display_name=f"{shape_label} ({index} of {section_count})",
                base_area_acres=base_area_acres[-1],
                polygon_projected=projected,
                polygon_wgs84=polygon_wgs84,
            )
        )

    average_area_acres = sum(base_area_acres) / len(base_area_acres)
    area_variance_pct = 0.0
    if average_area_acres > 0:
        area_variance_pct = (
            max(abs(area - average_area_acres) for area in base_area_acres)
            / average_area_acres
            * 100.0
        )

    diagnostics = NaturalSplitDiagnostics(
        selected_split_direction_deg=None,
        section_count=section_count,
        area_min_acres=min(base_area_acres),
        area_max_acres=max(base_area_acres),
        area_average_acres=average_area_acres,
        area_variance_pct=area_variance_pct,
        split_strategy=_format_split_strategy(split_angles, area_variance_pct=area_variance_pct),
    )
    return sections, diagnostics


def _recursive_section_output_polygon(
    parent_polygon: Polygon,
    base_part: Polygon,
    overlap_m: float,
) -> Polygon:
    if overlap_m <= 0:
        return _require_single_exterior_polygon(
            fill_polygon_interiors(base_part),
            "Connected fallback produced a disconnected section.",
        )

    expanded = buffer_projected_geometry(
        base_part,
        overlap_m / 2.0,
        join_style=BUFFER_JOIN_STYLE,
        mitre_limit=BUFFER_MITRE_LIMIT,
    )
    return _require_single_exterior_polygon(
        fill_polygon_interiors(expanded.intersection(parent_polygon)),
        "Connected fallback overlap produced a disconnected section.",
    )


def _simplify_vector_output_polygon(
    polygon: Polygon,
    *,
    max_deviation_ft: float = VECTOR_SIMPLIFY_MAX_DEVIATION_FT,
    max_area_delta_ratio: float = VECTOR_SIMPLIFY_MAX_AREA_DELTA_RATIO,
) -> tuple[Polygon, VectorSimplificationStats]:
    original = _require_single_exterior_polygon(
        fill_polygon_interiors(polygon),
        "Vector output polygon is not one exterior-only polygon.",
    )
    before_vertices = _polygon_vertex_count(original)
    max_deviation_m = max_deviation_ft * METERS_PER_FOOT
    if max_deviation_m <= 0 or original.area <= 0:
        return original, VectorSimplificationStats(before_vertices, before_vertices)

    best_polygon = original
    best_tolerance_m = 0.0
    best_deviation_m = 0.0
    best_area_delta_ratio = 0.0
    low = 0.0
    high = max_deviation_m
    candidate_result = _evaluate_vector_simplification_candidate(
        original,
        high,
        before_vertices,
        max_deviation_m,
        max_area_delta_ratio,
    )
    if candidate_result is not None:
        return candidate_result
    high = max_deviation_m

    for _index in range(VECTOR_SIMPLIFY_SEARCH_ITERATIONS):
        tolerance_m = (low + high) / 2.0
        candidate = _strict_vector_simplification_candidate(
            original.simplify(tolerance_m, preserve_topology=True)
        )
        if candidate is None:
            high = tolerance_m
            continue

        after_vertices = _polygon_vertex_count(candidate)
        if after_vertices >= before_vertices:
            low = tolerance_m
            continue

        deviation_m = float(original.hausdorff_distance(candidate))
        area_delta_ratio = _polygon_area_delta_ratio(original, candidate)
        if (
            deviation_m <= max_deviation_m + 1e-9
            and area_delta_ratio <= max_area_delta_ratio + 1e-9
        ):
            best_polygon = candidate
            best_tolerance_m = tolerance_m
            best_deviation_m = deviation_m
            best_area_delta_ratio = area_delta_ratio
            low = tolerance_m
        else:
            high = tolerance_m

    after_vertices = _polygon_vertex_count(best_polygon)
    if after_vertices >= before_vertices:
        return original, VectorSimplificationStats(before_vertices, before_vertices)

    return best_polygon, VectorSimplificationStats(
        before_vertices=before_vertices,
        after_vertices=after_vertices,
        tolerance_m=best_tolerance_m,
        max_deviation_m=best_deviation_m,
        area_delta_ratio=best_area_delta_ratio,
    )


def _simplify_vector_sections(
    sections: list[BoundarySection],
    to_wgs84: Transformer,
) -> tuple[list[BoundarySection], VectorSimplificationStats]:
    simplified_sections: list[BoundarySection] = []
    stats: list[VectorSimplificationStats] = []
    for section in sections:
        simplified_projected, section_stats = _simplify_vector_output_polygon(
            section.polygon_projected
        )
        simplified_wgs84 = _project_polygon_to_wgs84(simplified_projected, to_wgs84)
        simplified_sections.append(
            BoundarySection(
                index=section.index,
                total=section.total,
                display_name=section.display_name,
                base_area_acres=section.base_area_acres,
                polygon_projected=simplified_projected,
                polygon_wgs84=simplified_wgs84,
            )
        )
        stats.append(section_stats)
    if any(stat.after_vertices < stat.before_vertices for stat in stats):
        # Independent simplification can move opposite sides of a shared cut
        # differently, even when each polygon passes its own deviation/area
        # checks. Permit the usual outer-edge tolerance, but no new interior
        # gaps. Keep the original partition if the simplified set loses coverage.
        original_union = unary_union([section.polygon_projected for section in sections])
        required_interior = original_union.buffer(
            -VECTOR_SIMPLIFY_MAX_DEVIATION_FT * METERS_PER_FOOT
        )
        simplified_union = unary_union(
            [section.polygon_projected for section in simplified_sections]
        )
        if required_interior.difference(simplified_union.buffer(2e-6)).area > 1e-6:
            return sections, _unsimplified_vector_section_stats(sections)
    return simplified_sections, _combine_vector_simplification_stats(stats)


def _unsimplified_vector_section_stats(
    sections: list[BoundarySection],
) -> VectorSimplificationStats:
    vertex_count = sum(
        _polygon_vertex_count(section.polygon_projected) for section in sections
    )
    return VectorSimplificationStats(
        before_vertices=vertex_count,
        after_vertices=vertex_count,
    )


def _evaluate_vector_simplification_candidate(
    original: Polygon,
    tolerance_m: float,
    before_vertices: int,
    max_deviation_m: float,
    max_area_delta_ratio: float,
) -> tuple[Polygon, VectorSimplificationStats] | None:
    candidate = _strict_vector_simplification_candidate(
        original.simplify(tolerance_m, preserve_topology=True)
    )
    if candidate is None:
        return None
    after_vertices = _polygon_vertex_count(candidate)
    if after_vertices >= before_vertices:
        return None

    deviation_m = float(original.hausdorff_distance(candidate))
    area_delta_ratio = _polygon_area_delta_ratio(original, candidate)
    if (
        deviation_m > max_deviation_m + 1e-9
        or area_delta_ratio > max_area_delta_ratio + 1e-9
    ):
        return None

    return candidate, VectorSimplificationStats(
        before_vertices=before_vertices,
        after_vertices=after_vertices,
        tolerance_m=tolerance_m,
        max_deviation_m=deviation_m,
        area_delta_ratio=area_delta_ratio,
    )


def _combine_vector_simplification_stats(
    stats: list[VectorSimplificationStats],
) -> VectorSimplificationStats:
    if not stats:
        return VectorSimplificationStats()
    return VectorSimplificationStats(
        before_vertices=sum(item.before_vertices for item in stats),
        after_vertices=sum(item.after_vertices for item in stats),
        tolerance_m=max(item.tolerance_m for item in stats),
        max_deviation_m=max(item.max_deviation_m for item in stats),
        area_delta_ratio=max(item.area_delta_ratio for item in stats),
    )


def _validate_generation_profile(generation_profile: str) -> str:
    if generation_profile in {
        GENERATION_PROFILE_EXPORT,
        GENERATION_PROFILE_PREVIEW,
    }:
        return generation_profile
    raise BoundaryError(f"Unknown generation profile: {generation_profile}")


def _project_polygon_to_wgs84(polygon: Polygon, to_wgs84: Transformer) -> Polygon:
    polygon_wgs84 = transform_geometry(
        lambda x, y, z=None: to_wgs84.transform(x, y),
        polygon,
    )
    return _require_single_exterior_polygon(
        fill_polygon_interiors(polygon_wgs84),
        "Vector output polygon could not be transformed to WGS84.",
    )


def _strict_vector_simplification_candidate(geometry) -> Polygon | None:
    if geometry.is_empty:
        return None
    if not geometry.is_valid:
        geometry = make_valid(geometry)
    geometry = fill_polygon_interiors(geometry)
    if isinstance(geometry, Polygon) and geometry.area > 0 and not geometry.interiors:
        return geometry
    if isinstance(geometry, MultiPolygon):
        polygons = [
            part
            for part in geometry.geoms
            if isinstance(part, Polygon)
            and part.area > 0
            and not part.interiors
            and not part.is_empty
        ]
        if len(polygons) == 1:
            return polygons[0]
    if isinstance(geometry, GeometryCollection):
        polygons = [
            part
            for part in geometry.geoms
            if isinstance(part, Polygon)
            and part.area > 0
            and not part.interiors
            and not part.is_empty
        ]
        if len(polygons) == 1:
            return polygons[0]
    return None


def _require_single_exterior_polygon(geometry, message: str) -> Polygon:
    polygon = _strict_vector_simplification_candidate(geometry)
    if polygon is None:
        raise BoundaryError(message)
    return polygon


def _polygon_vertex_count(polygon: Polygon) -> int:
    return len(polygon.exterior.coords)


def _polygon_area_delta_ratio(original: Polygon, candidate: Polygon) -> float:
    if original.area <= 0:
        return 0.0
    return float(original.symmetric_difference(candidate).area / original.area)


def _export_vertex_count(
    final_polygon_wgs84: Polygon,
    sections: list[BoundarySection],
) -> int:
    if sections:
        return sum(_polygon_vertex_count(section.polygon_wgs84) for section in sections)
    return _polygon_vertex_count(final_polygon_wgs84)


def _partition_connected_polygon(
    polygon: Polygon,
    target_count: int,
) -> tuple[list[Polygon], list[float]]:
    # Prefer short cross-cuts over long, equal-area slices down a corridor.
    # Keep every leaf within the ORIGINAL target area, avoiding cumulative drift
    # through recursive cuts. Try nearby allocations at each node before
    # backtracking, so exact equality cannot force an irregular crop downstream.
    target_area = polygon.area / target_count
    remaining_attempts = 0
    area_tolerance = 0.20

    def partition(part: Polygon, count: int) -> tuple[list[Polygon], list[float]] | None:
        nonlocal remaining_attempts
        if count == 1:
            if abs(part.area / target_area - 1.0) <= area_tolerance + 1e-6:
                return [part], []
            return None
        if remaining_attempts <= 0:
            return None
        remaining_attempts -= 1
        balanced = count // 2
        # Finish an end/branch section first. Repeatedly forcing a network into
        # halves can exhaust the search before trying these clean cross-cuts.
        allocations = list(dict.fromkeys((1, count - 1, balanced, count - balanced)))
        for left_count in allocations:
            fraction = left_count / count
            right_count = count - left_count
            low = max(
                (1.0 - area_tolerance) * left_count * target_area / part.area,
                1.0 - (1.0 + area_tolerance) * right_count * target_area / part.area,
            )
            high = min(
                (1.0 + area_tolerance) * left_count * target_area / part.area,
                1.0 - (1.0 - area_tolerance) * right_count * target_area / part.area,
            )
            for bounds in (None, (low, high)):
                for left, right, angle in _connected_cut_candidates(
                    part, fraction, fraction_bounds=bounds,
                ):
                    if remaining_attempts <= 0:
                        return None
                    remaining_attempts -= 1
                    left_result = partition(left, left_count)
                    if left_result is None:
                        continue
                    right_result = partition(right, count - left_count)
                    if right_result is not None:
                        return (
                            left_result[0] + right_result[0],
                            [angle] + left_result[1] + right_result[1],
                        )
        return None

    # Keep the usual balance where feasible. At a bend, a moderately larger
    # crop is preferable to a pointed end or an unusable partition. Each pass
    # has its own bounded search budget and still uses the original mean area.
    for area_tolerance in (0.20, 0.35):
        remaining_attempts = max(64, min(1024, target_count * 24))
        result = partition(polygon, target_count)
        if result is not None:
            return result
    raise BoundaryError(
        "Auto could not find connected crop sections with short cross-cuts and "
        "areas within 35% of average. Try fewer shapes or choose a custom split direction."
    )


def _connected_cut_candidates(
    polygon: Polygon,
    left_fraction: float,
    *,
    fraction_bounds: tuple[float, float] | None = None,
) -> Iterable[tuple[Polygon, Polygon, float]]:
    center = (polygon.centroid.x, polygon.centroid.y)
    angles = _candidate_split_angles(polygon)
    for angle in range(0, 180, 5):
        _append_unique_angle(angles, float(angle))
    # This outline supplies SEARCH POSITIONS only. Every accepted cut clips the
    # original polygon, so simplification cannot change the exported footprint.
    width_scale = 2.0 * polygon.area / polygon.length
    landmarks = (
        polygon.simplify(width_scale * 0.05, preserve_topology=True)
        if fraction_bounds is not None else None
    )
    candidates = []
    for priority, angle in enumerate(angles):
        rotated = rotate(polygon, -angle, origin=center, use_radians=False)
        minx, miny, maxx, maxy = rotated.bounds
        margin = max(maxx - minx, maxy - miny) * 2.0
        cut_x = _find_equal_area_x(
            rotated, minx - margin, maxx + margin,
            miny - margin, maxy + margin, rotated.area * left_fraction,
        )
        positions = [cut_x]
        if landmarks is not None:
            landmark_xs = sorted({
                x for x, _y in rotate(landmarks, -angle, origin=center).exterior.coords
            })
            # Midpoints and positions just inside each bend find narrow feasible
            # windows that fixed 5% area steps can jump over completely.
            inset = width_scale * 0.05
            positions.extend((a + b) / 2.0 for a, b in zip(landmark_xs, landmark_xs[1:]))
            positions.extend(x + shift for x in landmark_xs for shift in (-inset, inset))
            positions = sorted(
                {x for x in positions if minx < x < maxx},
                key=lambda x: abs(x - cut_x),
            )[:256]
        angle_candidates = []
        for position in positions:
            left_geometry = rotated.intersection(box(minx - margin, miny - margin, position, maxy + margin))
            actual_fraction = left_geometry.area / polygon.area
            area_error = abs(actual_fraction - left_fraction)
            if fraction_bounds is not None and (
                not fraction_bounds[0] - 1e-8 <= actual_fraction <= fraction_bounds[1] + 1e-8
                or area_error < 1e-8
            ):
                continue
            left_rotated = _strict_single_polygon(left_geometry)
            if left_rotated is None:
                continue
            right_rotated = _strict_single_polygon(
                rotated.intersection(box(position, miny - margin, maxx + margin, maxy + margin))
            )
            if right_rotated is None:
                continue
            quality = cut_width_ratio(
                rotated, introduced_cut_length(rotated, (left_rotated, right_rotated))
            )
            if quality > MAX_AUTO_CUT_WIDTH_RATIO:
                continue
            seam = rotated.intersection(LineString([
                (position, miny - margin), (position, maxy + margin),
            ]))
            if minimum_crossing_angle(rotated, seam) < MIN_AUTO_CROSSING_ANGLE_DEG - 1e-6:
                continue
            left = _strict_single_polygon(rotate(left_rotated, angle, origin=center))
            right = _strict_single_polygon(rotate(right_rotated, angle, origin=center))
            if left is None or right is None:
                continue
            angle_candidates.append((round(quality, 6), round(area_error, 8), priority, angle, left, right))
        candidates.extend(sorted(angle_candidates, key=lambda item: item[:3])[:4])
    for candidate in sorted(candidates, key=lambda item: item[:3]):
        yield candidate[4], candidate[5], candidate[3]


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
        return geometry if not geometry.interiors else None
    if isinstance(geometry, GeometryCollection):
        polygons = [
            part
            for part in geometry.geoms
            if isinstance(part, Polygon)
            and part.area > min_area
            and not part.interiors
        ]
        if len(polygons) == 1:
            return polygons[0]
    return None


def _format_split_strategy(split_angles: list[float], *, area_variance_pct: float = 0.0) -> str:
    if not split_angles:
        return "Single polygon"
    rounded = [f"{angle:.1f} deg" for angle in split_angles[:6]]
    suffix = "" if len(split_angles) <= 6 else f", +{len(split_angles) - 6} more"
    area_mode = "balanced-area" if area_variance_pct > 0.01 else "equal-area"
    return f"Auto connected {area_mode} ({len(split_angles)} cuts: {', '.join(rounded)}{suffix})"


def _polygon_to_kml_coords(polygon: Polygon) -> list[tuple[float, float, int]]:
    if not isinstance(polygon, Polygon) or polygon.is_empty or not polygon.is_valid or polygon.interiors:
        raise BoundaryError("KMZ export requires a valid, exterior-only WGS84 polygon.")
    if any(
        not math.isfinite(lon) or not math.isfinite(lat) or not -180 <= lon <= 180 or not -90 <= lat <= 90
        for lon, lat in polygon.exterior.coords
    ):
        raise BoundaryError("KMZ export coordinates must be finite WGS84 longitude/latitude degrees.")
    return [(lon, lat, 0) for lon, lat in polygon.exterior.coords]


def _style_polygon(polygon, color_index: int) -> None:
    color = BOUNDARY_COLORS[color_index % len(BOUNDARY_COLORS)].lstrip("#")
    red, green, blue = (int(color[i:i + 2], 16) for i in (0, 2, 4))
    polygon.style.linestyle.color = simplekml.Color.rgb(red, green, blue)
    polygon.style.linestyle.width = KML_LINE_WIDTH
    polygon.style.polystyle.color = simplekml.Color.rgb(red, green, blue, 45)
    polygon.style.polystyle.fill = 0
    polygon.style.polystyle.outline = 1
    polygon.altitudemode = simplekml.AltitudeMode.clamptoground


def _input_type_label(input_kind: str) -> str:
    labels = {
        "polyline_kml": "KML polyline",
        "polyline_kmz": "KMZ polyline",
        "polygon_kml": "KML polygon",
        "polygon_kmz": "KMZ polygon",
    }
    return labels.get(input_kind, input_kind)


def _format_exterior_cleanup(ignored_interior_count: int) -> str:
    if ignored_interior_count:
        return "Interior rings filled; exterior boundary only."
    return "Exterior boundary only."


def _format_vector_simplification_lines(metadata: BoundaryMetadata) -> list[str]:
    if metadata.vector_simplification_before_vertices <= 0:
        return []
    if not metadata.vector_simplification_enabled:
        return [
            "Vector simplification: Off",
            (
                "Vector vertices preserved: "
                f"{metadata.vector_simplification_before_vertices:,}"
            ),
        ]
    return [
        (
            "Vector simplification: "
            f"{metadata.vector_simplification_before_vertices:,} -> "
            f"{metadata.vector_simplification_after_vertices:,} vertices"
        ),
        (
            "Vector simplification tolerance: "
            f"{metadata.vector_simplification_tolerance_ft:.2f} ft"
        ),
        (
            "Vector simplification max deviation: "
            f"{metadata.vector_simplification_max_deviation_ft:.2f} ft"
        ),
        (
            "Vector simplification area delta: "
            f"{metadata.vector_simplification_area_delta_pct:.3f}%"
        ),
    ]


def buffer_settings_from_metadata(metadata: BoundaryMetadata) -> BufferSettings:
    if metadata.buffer_mode == "per_side":
        return BufferSettings.per_side(metadata.left_buffer_ft, metadata.right_buffer_ft)
    return BufferSettings(unified_ft=metadata.buffer_ft)


def _format_polyline_auto_buffer_lines(metadata: BoundaryMetadata) -> list[str]:
    if not metadata.source_line_count or metadata.polyline_buffer_candidate_count <= 0:
        return []

    lines = [
        f"Requested polyline buffer: {metadata.polyline_requested_buffer_ft:,.1f} ft",
        (
            "Minimum connected whole-foot buffer: "
            f"{metadata.polyline_minimum_connected_buffer_ft:,.1f} ft"
        ),
        f"Selected polyline buffer: {metadata.polyline_selected_buffer_ft:,.1f} ft",
    ]
    if metadata.polyline_buffer_regularity_target > 0:
        lines.append(
            "Polyline regularity ratio: "
            f"{metadata.polyline_buffer_regularity_ratio:.3f} "
            f"(target <= {metadata.polyline_buffer_regularity_target:.2f})"
        )
    lines.append(
        f"Polyline buffer candidates tested: {metadata.polyline_buffer_candidate_count:,}"
    )
    if metadata.polyline_buffer_adjustment_reason:
        lines.append(
            "Polyline buffer adjustment: "
            f"{metadata.polyline_buffer_adjustment_reason}"
        )
    return lines


def _count_polygon_interiors(geometry) -> int:
    if isinstance(geometry, Polygon):
        return len(geometry.interiors)
    if isinstance(geometry, MultiPolygon):
        return sum(len(part.interiors) for part in geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        return sum(_count_polygon_interiors(part) for part in geometry.geoms)
    return 0


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
    return GpsPoint(path=path, lat=lat, lon=lon, capture_time=_read_capture_time(tags))


def _read_capture_time(tags: dict[str, object]) -> datetime | None:
    for tag_name in ("EXIF DateTimeOriginal", "Image DateTime"):
        tag = tags.get(tag_name)
        if not tag:
            continue
        parsed = _parse_exif_datetime(str(tag))
        if parsed is not None:
            return parsed
    return None


def _parse_exif_datetime(value: str) -> datetime | None:
    value = value.strip()
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


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
        candidate = buffer_projected_geometry(
            candidate,
            padding_m + 0.01,
            join_style=BUFFER_JOIN_STYLE,
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
        "Export CRS: WGS84 (EPSG:4326), longitude/latitude degrees.",
        "Buffer distance: " + buffer_settings_from_metadata(metadata).description,
        f"Output polygon vertices: {metadata.vertex_count:,}",
    ]
    if metadata.input_type == "JPG folder":
        lines[0] = "Generated from geotagged JPG camera positions."
        lines.extend(
            [
                f"JPG/JPEG files found: {metadata.jpg_count:,}",
                f"Usable GPS points: {metadata.gps_count:,}",
                f"Skipped files without GPS: {metadata.skipped_count:,}",
                f"Preflight pattern: {metadata.preflight_pattern or 'Not evaluated'}",
                f"Preflight confidence: {metadata.preflight_confidence:.2f}",
                f"Camera order source: {metadata.order_source or 'Not evaluated'}",
                f"Outline mode: {metadata.outline_mode or 'Not evaluated'}",
                f"Selected strategy: {metadata.selected_strategy or 'Not evaluated'}",
                f"Strategy confidence: {metadata.strategy_confidence:.2f}",
                f"Concave hull ratio: {metadata.concave_ratio}",
                f"Median camera spacing: {metadata.median_spacing_ft:,.1f} ft",
                f"Auto smoothing distance: {metadata.smoothing_ft:,.1f} ft",
                f"Auto containment padding: {metadata.containment_padding_ft:,.1f} ft",
            ]
        )
        if metadata.preflight_warnings:
            lines.append(f"Preflight warnings: {metadata.preflight_warnings}")
        if metadata.fallback_reason:
            lines.append(f"Fallback reason: {metadata.fallback_reason}")
        if metadata.candidate_summary:
            lines.append(f"Candidate summary: {metadata.candidate_summary}")
    else:
        if metadata.source_line_count:
            lines.extend(
                [
                    f"Source LineStrings: {metadata.source_line_count:,}",
                    f"Source line coordinates: {metadata.source_point_count:,}",
                ]
            )
            if metadata.source_axis_hint_deg is not None:
                lines.append(
                    f"Source line orientation hint: {metadata.source_axis_hint_deg:.1f} deg"
                )
            if metadata.ignored_polygon_count:
                lines.append(
                    "Using source LineStrings; polygons ignored: "
                    f"{metadata.ignored_polygon_count:,}"
                )
            lines.extend(_format_polyline_auto_buffer_lines(metadata))
        else:
            lines.append("Source polygon: 1")
        if metadata.ignored_interior_ring_count:
            lines.append(
                f"Interior rings ignored/filled: {metadata.ignored_interior_ring_count:,}"
            )
        if metadata.exterior_cleanup:
            lines.append(f"Exterior cleanup: {metadata.exterior_cleanup}")
        lines.extend(_format_vector_simplification_lines(metadata))
    if metadata.section_count > 1:
        lines.extend(
            [
                f"Sections: {metadata.section_count}",
                f"Section overlap: {metadata.overlap_ft:,.1f} ft",
                f"Shape label: {metadata.shape_label}",
                f"Split strategy: {metadata.split_strategy}",
                f"Sections connected: {'Yes' if metadata.sections_connected else 'No'}",
                (
                    "Selected split direction: Auto"
                    if metadata.selected_split_direction_deg is None
                    else f"Selected split direction: {metadata.selected_split_direction_deg:.1f} deg"
                ),
                f"Section area variance: {metadata.split_area_variance_pct:.1f}%",
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
