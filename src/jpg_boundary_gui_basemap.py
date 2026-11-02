"""Bounded Esri World Imagery support for the preview GUI.

This module deliberately has no dependency on Tk, the GUI controller, or the
boundary-processing core.  It accepts immutable view descriptions, performs
all provider I/O and raster work away from the GUI thread, and returns immutable
frames or categorized failures for the GUI to apply.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from io import BytesIO
import json
import math
import os
import queue
import socket
import threading
import time
import unicodedata
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)

import matplotlib.image
import numpy
from pyproj import CRS, Transformer
from scipy.ndimage import map_coordinates


SERVICE_ROOT = (
    "https://wi.maptiles.arcgis.com/arcgis/rest/services/"
    "World_Imagery/MapServer"
)
METADATA_URL = f"{SERVICE_ROOT}?f=pjson"
ALLOWED_HOST = "wi.maptiles.arcgis.com"
USER_AGENT = "JPG-Boundary-to-KMZ-GUI/1.0"

EXPECTED_WKID = 4326
EXPECTED_TILE_SIZE = 256
EXPECTED_FORMAT = "JPEG"
EXPECTED_ORIGIN_X = -180.0
EXPECTED_ORIGIN_Y = 90.0
EXPECTED_LEVELS = tuple(range(23))

ORIGIN_ABS_TOLERANCE = 1e-12
LOD_REL_TOLERANCE = 1e-12
LOD_ABS_TOLERANCE = 1e-18
MAX_TILES_PER_VIEW = 24
MAX_OUTPUT_PIXELS = 1_500_000
MAX_OUTPUT_DIMENSION = 1_600
MAX_METADATA_BYTES = 1024 * 1024
MAX_TILE_BYTES = 2 * 1024 * 1024
MAX_CACHE_TILES = 128
MAX_CACHE_DECODED_BYTES = 32 * 1024 * 1024
MAX_RESPONSE_ITEMS = 4
WARP_CHUNK_ROWS = 128
REQUEST_TIMEOUT_SECONDS = 4
MAX_TRANSIENT_RETRIES = 1
VIEW_DEBOUNCE_MS = 300
METADATA_RETRY_COOLDOWN = 30.0
RETRY_DELAY_SECONDS = 0.250
METADATA_WAIT_SECONDS = 0.050

_INITIAL_EDGE_POINTS = 33
_INTERIOR_GRID_POINTS = 9
_MAX_ADAPTIVE_DEPTH = 8
_MAX_EDGE_POINTS = 4_097
_MAX_LOD_PASSES = 3
_SOURCE_PIXEL_ERROR_FRACTION = 0.25


@dataclass(frozen=True)
class ArcGisTileService:
    root_url: str
    metadata_url: str
    expected_wkid: int
    tile_size: int
    image_format: str
    origin_x: float
    origin_y: float
    lod_resolutions: tuple[float, ...]
    copyright_text: str


@dataclass(frozen=True)
class ProjectedView:
    surface_id: str
    generation: int
    result_generation: int
    epsg: int
    xlim: tuple[float, float]
    ylim: tuple[float, float]
    pixel_width: int
    pixel_height: int


@dataclass(frozen=True)
class TileAddress:
    level: int
    row: int
    request_column: int
    display_column: int


@dataclass(frozen=True)
class ServiceMetadataError:
    code: str
    message: str


@dataclass(frozen=True)
class BasemapFrame:
    surface_id: str
    generation: int
    result_generation: int
    epsg: int
    xlim: tuple[float, float]
    ylim: tuple[float, float]
    pixel_width: int
    pixel_height: int
    rgba: numpy.ndarray
    copyright_text: str
    requested_tile_count: int
    valid_tile_count: int
    missing_tile_count: int
    is_partial: bool

    def __post_init__(self) -> None:
        if self.requested_tile_count != (
            self.valid_tile_count + self.missing_tile_count
        ):
            raise ValueError("Basemap frame tile accounting is inconsistent.")
        if self.valid_tile_count <= 0:
            raise ValueError("A basemap frame must contain a valid tile.")
        if self.is_partial != (self.missing_tile_count > 0):
            raise ValueError("Basemap frame partial state is inconsistent.")


@dataclass(frozen=True)
class BasemapFailure:
    surface_id: str
    generation: int
    result_generation: int
    category: str
    user_message: str
    retryable: bool


_METADATA_ERRORS = {
    "invalid_root": "Imagery service metadata is incompatible.",
    "invalid_cache": "Imagery service metadata is incompatible.",
    "invalid_capabilities": "Imagery service metadata is incompatible.",
    "invalid_spatial_reference": "Imagery service metadata is incompatible.",
    "invalid_tile_schema": "Imagery service metadata is incompatible.",
    "invalid_origin": "Imagery service metadata is incompatible.",
    "invalid_lods": "Imagery service metadata is incompatible.",
    "invalid_attribution": "Imagery service attribution is unavailable.",
    "invalid_export_policy": "Imagery service metadata is incompatible.",
}


def _metadata_error(code: str) -> ServiceMetadataError:
    return ServiceMetadataError(code=code, message=_METADATA_ERRORS[code])


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _wkid(value: Any) -> int | None:
    if not isinstance(value, Mapping):
        return None
    result = value.get("wkid")
    if not isinstance(result, int) or isinstance(result, bool):
        return None
    return result


def _normalize_attribution(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    for character in value:
        category = unicodedata.category(character)
        if category == "Cc" and character not in "\t\r\n":
            return None
        if category in {"Cf", "Cs"}:
            return None
    normalized = " ".join(value.split())
    if not 1 <= len(normalized) <= 500:
        return None
    return normalized


def parse_service_metadata(
    value: Any,
) -> ArcGisTileService | ServiceMetadataError:
    """Validate the fixed WGS84 World Imagery service schema without raising."""

    try:
        if not isinstance(value, Mapping):
            return _metadata_error("invalid_root")

        fused = value.get("singleFusedMapCache")
        if not isinstance(fused, bool) or fused is not True:
            return _metadata_error("invalid_cache")

        capabilities = value.get("capabilities")
        if not isinstance(capabilities, str) or not capabilities.strip():
            return _metadata_error("invalid_capabilities")
        tokens = [token.strip().casefold() for token in capabilities.split(",")]
        if "tilesonly" not in tokens:
            return _metadata_error("invalid_capabilities")

        tile_info = value.get("tileInfo")
        if not isinstance(tile_info, Mapping):
            return _metadata_error("invalid_tile_schema")
        if (
            _wkid(value.get("spatialReference")) != EXPECTED_WKID
            or _wkid(tile_info.get("spatialReference")) != EXPECTED_WKID
        ):
            return _metadata_error("invalid_spatial_reference")

        rows = tile_info.get("rows")
        columns = tile_info.get("cols")
        if (
            not isinstance(rows, int)
            or isinstance(rows, bool)
            or not isinstance(columns, int)
            or isinstance(columns, bool)
            or rows != EXPECTED_TILE_SIZE
            or columns != EXPECTED_TILE_SIZE
        ):
            return _metadata_error("invalid_tile_schema")

        image_format = tile_info.get("format")
        if not isinstance(image_format, str):
            return _metadata_error("invalid_tile_schema")
        if image_format.strip().casefold() not in {"jpeg", "jpg"}:
            return _metadata_error("invalid_tile_schema")

        origin = tile_info.get("origin")
        if not isinstance(origin, Mapping):
            return _metadata_error("invalid_origin")
        origin_x = origin.get("x")
        origin_y = origin.get("y")
        if not _is_number(origin_x) or not _is_number(origin_y):
            return _metadata_error("invalid_origin")
        if not math.isclose(
            float(origin_x),
            EXPECTED_ORIGIN_X,
            rel_tol=0.0,
            abs_tol=ORIGIN_ABS_TOLERANCE,
        ) or not math.isclose(
            float(origin_y),
            EXPECTED_ORIGIN_Y,
            rel_tol=0.0,
            abs_tol=ORIGIN_ABS_TOLERANCE,
        ):
            return _metadata_error("invalid_origin")

        lod_values = tile_info.get("lods")
        if not isinstance(lod_values, (list, tuple)):
            return _metadata_error("invalid_lods")
        levels: list[int] = []
        resolutions: list[float] = []
        for item in lod_values:
            if not isinstance(item, Mapping):
                return _metadata_error("invalid_lods")
            level = item.get("level")
            resolution = item.get("resolution")
            if (
                not isinstance(level, int)
                or isinstance(level, bool)
                or not _is_number(resolution)
            ):
                return _metadata_error("invalid_lods")
            numeric_resolution = float(resolution)
            if numeric_resolution <= 0.0:
                return _metadata_error("invalid_lods")
            levels.append(level)
            resolutions.append(numeric_resolution)

        if tuple(levels) != EXPECTED_LEVELS or len(set(levels)) != len(levels):
            return _metadata_error("invalid_lods")
        if any(
            resolutions[index] >= resolutions[index - 1]
            for index in range(1, len(resolutions))
        ):
            return _metadata_error("invalid_lods")
        for level, resolution in zip(levels, resolutions, strict=True):
            expected = 0.703125 / (2**level)
            if not math.isclose(
                resolution,
                expected,
                rel_tol=LOD_REL_TOLERANCE,
                abs_tol=LOD_ABS_TOLERANCE,
            ):
                return _metadata_error("invalid_lods")

        attribution = _normalize_attribution(value.get("copyrightText"))
        if attribution is None:
            return _metadata_error("invalid_attribution")

        if "exportTilesAllowed" in value:
            export_allowed = value["exportTilesAllowed"]
            if not isinstance(export_allowed, bool) or export_allowed is not False:
                return _metadata_error("invalid_export_policy")

        return ArcGisTileService(
            root_url=SERVICE_ROOT,
            metadata_url=METADATA_URL,
            expected_wkid=EXPECTED_WKID,
            tile_size=EXPECTED_TILE_SIZE,
            image_format=EXPECTED_FORMAT,
            origin_x=EXPECTED_ORIGIN_X,
            origin_y=EXPECTED_ORIGIN_Y,
            lod_resolutions=tuple(resolutions),
            copyright_text=attribution,
        )
    except (ArithmeticError, TypeError, ValueError):
        return _metadata_error("invalid_root")


def tile_resolution(level: int) -> float:
    if (
        not isinstance(level, int)
        or isinstance(level, bool)
        or level not in EXPECTED_LEVELS
    ):
        raise ValueError("Tile level must be an integer from 0 through 22.")
    return 0.703125 / (2**level)


def tile_span(level: int) -> float:
    return EXPECTED_TILE_SIZE * tile_resolution(level)


def tile_matrix_shape(level: int) -> tuple[int, int]:
    """Return ``(row_count, column_count)`` for the WGS84 tile matrix."""

    tile_resolution(level)
    return 2**level, 2 ** (level + 1)


def _finite_extent(
    extent: Sequence[float],
) -> tuple[float, float, float, float] | None:
    if len(extent) != 4:
        return None
    try:
        west, south, east, north = (float(item) for item in extent)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(item) for item in (west, south, east, north)):
        return None
    if east == west:
        return None
    if east < west:
        difference = west - east
        if not math.isfinite(difference):
            return None
        turns = math.floor(difference / 360.0) + 1
        east += 360.0 * turns
    if (
        not math.isfinite(east)
        or east <= west
        or max(abs(west), abs(east)) > 1_000_000_000.0
    ):
        return None
    if east - west > 360.0 + 1e-10:
        return None
    clipped_south = max(-90.0, south)
    clipped_north = min(90.0, north)
    if clipped_north <= clipped_south or east <= west:
        return None
    return west, clipped_south, east, clipped_north


def select_tile_addresses(
    extent: Sequence[float],
    level: int,
) -> tuple[TileAddress, ...]:
    """Select intersecting WGS84 tiles using east/south half-open bounds."""

    bounds = _tile_index_bounds(extent, level)
    if bounds is None:
        return ()
    first_row, last_row, first_column, last_column, column_count = bounds
    selected_count = (last_row - first_row + 1) * (
        last_column - first_column + 1
    )
    if selected_count > MAX_TILES_PER_VIEW:
        return ()

    return tuple(
        TileAddress(
            level=level,
            row=row,
            request_column=display_column % column_count,
            display_column=display_column,
        )
        for row in range(first_row, last_row + 1)
        for display_column in range(first_column, last_column + 1)
    )


def _tile_index_bounds(
    extent: Sequence[float],
    level: int,
) -> tuple[int, int, int, int, int] | None:
    normalized = _finite_extent(extent)
    if normalized is None:
        return None
    west, south, east, north = normalized
    row_count, column_count = tile_matrix_shape(level)
    span = tile_span(level)
    first_column = math.floor((west + 180.0) / span)
    last_column = math.ceil((east + 180.0) / span) - 1
    first_row = math.floor((90.0 - north) / span)
    last_row = math.ceil((90.0 - south) / span) - 1
    first_row = min(max(first_row, 0), row_count - 1)
    last_row = min(max(last_row, 0), row_count - 1)
    if first_row > last_row or first_column > last_column:
        return None
    return (
        first_row,
        last_row,
        first_column,
        last_column,
        column_count,
    )


def _tile_address_count(
    extent: Sequence[float],
    level: int,
) -> int | None:
    bounds = _tile_index_bounds(extent, level)
    if bounds is None:
        return None
    first_row, last_row, first_column, last_column, _column_count = bounds
    return (last_row - first_row + 1) * (
        last_column - first_column + 1
    )


def _bounded_output_dimensions(view: ProjectedView) -> tuple[int, int] | None:
    if (
        not isinstance(view.pixel_width, int)
        or isinstance(view.pixel_width, bool)
        or not isinstance(view.pixel_height, int)
        or isinstance(view.pixel_height, bool)
        or view.pixel_width < 2
        or view.pixel_height < 2
    ):
        return None
    width = float(view.pixel_width)
    height = float(view.pixel_height)
    scale = min(
        1.0,
        MAX_OUTPUT_DIMENSION / width,
        MAX_OUTPUT_DIMENSION / height,
        math.sqrt(MAX_OUTPUT_PIXELS / (width * height)),
    )
    output_width = max(2, int(math.floor(width * scale)))
    output_height = max(2, int(math.floor(height * scale)))
    while output_width * output_height > MAX_OUTPUT_PIXELS:
        if output_width >= output_height:
            output_width -= 1
        else:
            output_height -= 1
    if (
        output_width < 2
        or output_height < 2
        or output_width > MAX_OUTPUT_DIMENSION
        or output_height > MAX_OUTPUT_DIMENSION
    ):
        return None
    return output_width, output_height


def _valid_view_limits(view: ProjectedView) -> bool:
    try:
        values = (
            float(view.xlim[0]),
            float(view.xlim[1]),
            float(view.ylim[0]),
            float(view.ylim[1]),
        )
    except (IndexError, TypeError, ValueError):
        return False
    return (
        all(math.isfinite(value) for value in values)
        and values[0] != values[1]
        and values[2] != values[3]
        and _bounded_output_dimensions(view) is not None
        and isinstance(view.epsg, int)
        and not isinstance(view.epsg, bool)
        and view.epsg > 0
    )


def _unwrap_longitude(longitude: float, reference: float) -> float:
    return reference + ((longitude - reference + 180.0) % 360.0) - 180.0


@dataclass(frozen=True)
class _GeographicExtent:
    west: float
    south: float
    east: float
    north: float
    unwrap_reference: float
    maximum_midpoint_deviation: float

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return self.west, self.south, self.east, self.north


class _ExtentConvergenceError(RuntimeError):
    pass


def _transform_point(
    transformer: Transformer,
    x_value: float,
    y_value: float,
    reference: float,
) -> tuple[float, float]:
    longitude, latitude = transformer.transform(x_value, y_value)
    longitude = float(longitude)
    latitude = float(latitude)
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        raise _ExtentConvergenceError
    return _unwrap_longitude(longitude, reference), latitude


def _sample_projected_perimeter_impl(
    view: ProjectedView,
    *,
    source_resolution: float | None,
    transformer: Transformer | None,
    max_depth: int,
    max_points_per_edge: int,
) -> _GeographicExtent:
    if not _valid_view_limits(view):
        raise _ExtentConvergenceError
    if source_resolution is not None and (
        not math.isfinite(source_resolution) or source_resolution <= 0.0
    ):
        raise _ExtentConvergenceError
    try:
        active_transformer = transformer or Transformer.from_crs(
            CRS.from_epsg(view.epsg),
            CRS.from_epsg(EXPECTED_WKID),
            always_xy=True,
        )
        x0, x1 = (float(item) for item in view.xlim)
        y0, y1 = (float(item) for item in view.ylim)
        center_x = (x0 + x1) * 0.5
        center_y = (y0 + y1) * 0.5
        center_longitude, center_latitude = active_transformer.transform(
            center_x,
            center_y,
        )
        reference = float(center_longitude)
        if not math.isfinite(reference) or not math.isfinite(float(center_latitude)):
            raise _ExtentConvergenceError

        fractions = numpy.linspace(0.0, 1.0, _INITIAL_EDGE_POINTS)
        edge_projected = (
            [(x0 + (x1 - x0) * fraction, y0) for fraction in fractions],
            [(x1, y0 + (y1 - y0) * fraction) for fraction in fractions],
            [(x1 + (x0 - x1) * fraction, y1) for fraction in fractions],
            [(x0, y1 + (y0 - y1) * fraction) for fraction in fractions],
        )
        transformed_edges: list[list[tuple[float, float, float, float]]] = []
        for edge in edge_projected:
            transformed_edge: list[tuple[float, float, float, float]] = []
            for x_value, y_value in edge:
                longitude, latitude = _transform_point(
                    active_transformer,
                    x_value,
                    y_value,
                    reference,
                )
                transformed_edge.append(
                    (x_value, y_value, longitude, latitude)
                )
            transformed_edges.append(transformed_edge)

        maximum_deviation = 0.0
        if source_resolution is not None:
            tolerance = source_resolution * _SOURCE_PIXEL_ERROR_FRACTION

            def refine(
                left: tuple[float, float, float, float],
                right: tuple[float, float, float, float],
                depth: int,
                point_counter: list[int],
            ) -> list[tuple[float, float, float, float]]:
                nonlocal maximum_deviation
                midpoint_x = (left[0] + right[0]) * 0.5
                midpoint_y = (left[1] + right[1]) * 0.5
                midpoint_longitude, midpoint_latitude = _transform_point(
                    active_transformer,
                    midpoint_x,
                    midpoint_y,
                    (left[2] + right[2]) * 0.5,
                )
                expected_longitude = (left[2] + right[2]) * 0.5
                expected_latitude = (left[3] + right[3]) * 0.5
                deviation = max(
                    abs(midpoint_longitude - expected_longitude),
                    abs(midpoint_latitude - expected_latitude),
                )
                midpoint = (
                    midpoint_x,
                    midpoint_y,
                    midpoint_longitude,
                    midpoint_latitude,
                )
                if deviation <= tolerance:
                    maximum_deviation = max(maximum_deviation, deviation)
                    return [left, right]
                if depth >= max_depth or point_counter[0] + 1 > max_points_per_edge:
                    raise _ExtentConvergenceError
                point_counter[0] += 1
                left_points = refine(
                    left,
                    midpoint,
                    depth + 1,
                    point_counter,
                )
                right_points = refine(
                    midpoint,
                    right,
                    depth + 1,
                    point_counter,
                )
                return left_points[:-1] + right_points

            adaptive_edges: list[list[tuple[float, float, float, float]]] = []
            for edge in transformed_edges:
                counter = [len(edge)]
                adaptive: list[tuple[float, float, float, float]] = [edge[0]]
                for left, right in zip(edge, edge[1:]):
                    segment = refine(left, right, 0, counter)
                    adaptive.extend(segment[1:])
                if len(adaptive) > max_points_per_edge:
                    raise _ExtentConvergenceError
                adaptive_edges.append(adaptive)
            transformed_edges = adaptive_edges

        all_geographic: list[tuple[float, float]] = [
            (item[2], item[3])
            for edge in transformed_edges
            for item in edge
        ]
        interior_fractions = numpy.linspace(0.0, 1.0, _INTERIOR_GRID_POINTS)
        for x_fraction in interior_fractions:
            for y_fraction in interior_fractions:
                longitude, latitude = _transform_point(
                    active_transformer,
                    x0 + (x1 - x0) * float(x_fraction),
                    y0 + (y1 - y0) * float(y_fraction),
                    reference,
                )
                all_geographic.append((longitude, latitude))

        longitudes = [item[0] for item in all_geographic]
        latitudes = [item[1] for item in all_geographic]
        west = min(longitudes)
        east = max(longitudes)
        south = max(-90.0, min(latitudes))
        north = min(90.0, max(latitudes))
        if (
            not all(
                math.isfinite(value)
                for value in (west, south, east, north)
            )
            or east <= west
            or north <= south
            or east - west > 360.0 + 1e-10
        ):
            raise _ExtentConvergenceError
        return _GeographicExtent(
            west=west,
            south=south,
            east=east,
            north=north,
            unwrap_reference=reference,
            maximum_midpoint_deviation=maximum_deviation,
        )
    except _ExtentConvergenceError:
        raise
    except Exception:
        raise _ExtentConvergenceError from None


def sample_projected_perimeter(
    view: ProjectedView,
    *,
    source_resolution: float | None = None,
    transformer: Transformer | None = None,
    max_depth: int = _MAX_ADAPTIVE_DEPTH,
    max_points_per_edge: int = _MAX_EDGE_POINTS,
) -> _GeographicExtent | None:
    """Transform and, when requested, adaptively bound a projected view."""

    try:
        return _sample_projected_perimeter_impl(
            view,
            source_resolution=source_resolution,
            transformer=transformer,
            max_depth=max_depth,
            max_points_per_edge=max_points_per_edge,
        )
    except _ExtentConvergenceError:
        return None


def _geodesic_distance(
    geod: Any,
    first: tuple[float, float],
    second: tuple[float, float],
) -> float:
    _azimuth_1, _azimuth_2, distance = geod.inv(
        first[0],
        first[1],
        second[0],
        second[1],
    )
    return abs(float(distance))


def select_lod(
    service: ArcGisTileService,
    view: ProjectedView,
    *,
    transformer: Transformer | None = None,
    geographic_extent: Sequence[float] | _GeographicExtent | None = None,
) -> int | None:
    """Choose the coarsest advertised LOD meeting the ground-resolution bound."""

    if not _valid_view_limits(view) or not service.lod_resolutions:
        return None
    dimensions = _bounded_output_dimensions(view)
    if dimensions is None:
        return None
    output_width, output_height = dimensions
    x0, x1 = (float(item) for item in view.xlim)
    y0, y1 = (float(item) for item in view.ylim)
    center_x = (x0 + x1) * 0.5
    center_y = (y0 + y1) * 0.5
    step_x = abs(x1 - x0) / output_width
    step_y = abs(y1 - y0) / output_height

    try:
        display_crs = CRS.from_epsg(view.epsg)
        active_transformer = transformer or Transformer.from_crs(
            display_crs,
            CRS.from_epsg(EXPECTED_WKID),
            always_xy=True,
        )
        center = active_transformer.transform(center_x, center_y)
        horizontal = active_transformer.transform(center_x + step_x, center_y)
        vertical = active_transformer.transform(center_x, center_y + step_y)
        geographic_points = tuple(
            (float(point[0]), float(point[1]))
            for point in (center, horizontal, vertical)
        )
        if not all(
            math.isfinite(component)
            for point in geographic_points
            for component in point
        ):
            raise ValueError
        geod = display_crs.get_geod()
        requested_horizontal = _geodesic_distance(
            geod,
            geographic_points[0],
            geographic_points[1],
        )
        requested_vertical = _geodesic_distance(
            geod,
            geographic_points[0],
            geographic_points[2],
        )
        if requested_horizontal <= 0.0 or requested_vertical <= 0.0:
            raise ValueError
        longitude, latitude = geographic_points[0]
        selected_level = len(service.lod_resolutions) - 1
        for level, resolution in enumerate(service.lod_resolutions):
            sample_latitude = min(90.0, latitude + resolution)
            if sample_latitude == latitude:
                sample_latitude = max(-90.0, latitude - resolution)
            service_horizontal = _geodesic_distance(
                geod,
                (longitude, latitude),
                (longitude + resolution, latitude),
            )
            service_vertical = _geodesic_distance(
                geod,
                (longitude, latitude),
                (longitude, sample_latitude),
            )
            if (
                service_horizontal <= 1.25 * requested_horizontal
                and service_vertical <= 1.25 * requested_vertical
            ):
                selected_level = level
                break
        return _back_off_lod_for_extent(selected_level, geographic_extent)
    except Exception:
        degree_per_output_pixel = max(
            abs(x1 - x0) / output_width,
            abs(y1 - y0) / output_height,
        )
        if view.epsg != EXPECTED_WKID or not math.isfinite(
            degree_per_output_pixel
        ) or degree_per_output_pixel <= 0.0:
            return None
        selected_level = len(service.lod_resolutions) - 1
        for level, resolution in enumerate(service.lod_resolutions):
            if resolution <= 1.25 * degree_per_output_pixel:
                selected_level = level
                break
        return _back_off_lod_for_extent(selected_level, geographic_extent)


def _back_off_lod_for_extent(
    selected_level: int,
    geographic_extent: Sequence[float] | _GeographicExtent | None,
) -> int:
    if geographic_extent is None:
        return selected_level
    if isinstance(geographic_extent, _GeographicExtent):
        raw_extent = geographic_extent.bounds
    else:
        raw_extent = geographic_extent
    level = selected_level
    while level > 0:
        resolution = tile_resolution(level)
        normalized = _finite_extent(raw_extent)
        if normalized is None:
            return level
        west, south, east, north = normalized
        padded = (
            west - resolution,
            max(-90.0, south - resolution),
            east + resolution,
            min(90.0, north + resolution),
        )
        if padded[2] - padded[0] >= 360.0:
            center = (west + east) * 0.5
            padded = (
                center - 180.0,
                padded[1],
                center + 180.0,
                padded[3],
            )
        address_count = _tile_address_count(padded, level)
        if address_count is None:
            return level
        if address_count <= MAX_TILES_PER_VIEW:
            return level
        level -= 1
    return 0


class MemoryTileCache:
    """A deterministic, memory-only, lock-protected decoded-tile LRU."""

    def __init__(
        self,
        max_items: int = MAX_CACHE_TILES,
        max_bytes: int = MAX_CACHE_DECODED_BYTES,
        lock: threading.RLock | None = None,
    ) -> None:
        if max_items <= 0 or max_bytes <= 0:
            raise ValueError("Cache bounds must be positive.")
        self._max_items = int(max_items)
        self._max_bytes = int(max_bytes)
        self._lock = lock or threading.RLock()
        self._items: OrderedDict[Any, numpy.ndarray] = OrderedDict()
        self._decoded_bytes = 0

    @property
    def item_count(self) -> int:
        with self._lock:
            return len(self._items)

    @property
    def decoded_bytes(self) -> int:
        with self._lock:
            return self._decoded_bytes

    @property
    def keys(self) -> tuple[Any, ...]:
        with self._lock:
            return tuple(self._items.keys())

    def get(self, key: Any) -> numpy.ndarray | None:
        with self._lock:
            value = self._items.get(key)
            if value is None:
                return None
            self._items.move_to_end(key)
            return value

    def put(self, key: Any, value: numpy.ndarray) -> bool:
        if not isinstance(value, numpy.ndarray):
            return False
        stored = numpy.array(value, copy=True, order="C")
        stored.setflags(write=False)
        byte_count = int(stored.nbytes)
        if byte_count > self._max_bytes:
            return False
        with self._lock:
            old = self._items.get(key)
            old_bytes = int(old.nbytes) if old is not None else 0
            prospective_count = len(self._items) if old is not None else (
                len(self._items) + 1
            )
            prospective_bytes = self._decoded_bytes - old_bytes + byte_count
            if (
                prospective_count > self._max_items
                or prospective_bytes > self._max_bytes
            ):
                while self._items and (
                    prospective_count > self._max_items
                    or prospective_bytes > self._max_bytes
                ):
                    oldest_key = next(iter(self._items))
                    if old is not None and oldest_key == key:
                        candidates = [
                            candidate
                            for candidate in self._items
                            if candidate != key
                        ]
                        if not candidates:
                            break
                        oldest_key = candidates[0]
                    removed = self._items[oldest_key]
                    prospective_count -= 1
                    prospective_bytes -= int(removed.nbytes)
                    self._decoded_bytes -= int(removed.nbytes)
                    del self._items[oldest_key]
                if (
                    prospective_count > self._max_items
                    or prospective_bytes > self._max_bytes
                ):
                    return False
            if old is not None and key in self._items:
                self._decoded_bytes -= int(self._items[key].nbytes)
                del self._items[key]
            self._items[key] = stored
            self._decoded_bytes += byte_count
            return True

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._decoded_bytes = 0


@dataclass(frozen=True)
class _TileMosaic:
    rgb: numpy.ndarray
    validity: numpy.ndarray
    west: float
    north: float
    resolution: float
    unwrap_reference: float
    addresses: tuple[TileAddress, ...]
    valid_tile_count: int
    missing_tile_count: int


@dataclass(frozen=True)
class _WarpedRaster:
    rgba: numpy.ndarray
    extent: tuple[float, float, float, float]


def assemble_tile_mosaic(
    addresses: Sequence[TileAddress],
    tiles: Mapping[Any, numpy.ndarray],
    level: int,
    *,
    unwrap_reference: float | None = None,
) -> _TileMosaic | None:
    """Assemble a bounded north-up WGS84 RGB mosaic and validity mask."""

    address_tuple = tuple(addresses)
    if (
        not address_tuple
        or len(address_tuple) > MAX_TILES_PER_VIEW
        or any(address.level != level for address in address_tuple)
    ):
        return None
    rows = sorted({address.row for address in address_tuple})
    columns = sorted({address.display_column for address in address_tuple})
    if len(rows) * len(columns) != len(address_tuple):
        return None
    expected = {
        (row, column)
        for row in range(rows[0], rows[-1] + 1)
        for column in range(columns[0], columns[-1] + 1)
    }
    actual = {(address.row, address.display_column) for address in address_tuple}
    if expected != actual:
        return None

    height = len(rows) * EXPECTED_TILE_SIZE
    width = len(columns) * EXPECTED_TILE_SIZE
    rgb = numpy.zeros((height, width, 3), dtype=numpy.uint8)
    validity = numpy.zeros((height, width), dtype=numpy.float32)
    row_offsets = {row: index for index, row in enumerate(rows)}
    column_offsets = {
        column: index for index, column in enumerate(columns)
    }
    valid_count = 0
    for address in address_tuple:
        tile = tiles.get(address)
        if tile is None:
            tile = tiles.get(
                (address.level, address.row, address.request_column)
            )
        if tile is None:
            continue
        if (
            not isinstance(tile, numpy.ndarray)
            or tile.shape != (
                EXPECTED_TILE_SIZE,
                EXPECTED_TILE_SIZE,
                3,
            )
            or tile.dtype != numpy.uint8
        ):
            return None
        row_start = row_offsets[address.row] * EXPECTED_TILE_SIZE
        column_start = (
            column_offsets[address.display_column] * EXPECTED_TILE_SIZE
        )
        rgb[
            row_start : row_start + EXPECTED_TILE_SIZE,
            column_start : column_start + EXPECTED_TILE_SIZE,
        ] = tile
        validity[
            row_start : row_start + EXPECTED_TILE_SIZE,
            column_start : column_start + EXPECTED_TILE_SIZE,
        ] = 1.0
        valid_count += 1
    rgb.setflags(write=False)
    validity.setflags(write=False)
    resolution = tile_resolution(level)
    west = EXPECTED_ORIGIN_X + columns[0] * tile_span(level)
    north = EXPECTED_ORIGIN_Y - rows[0] * tile_span(level)
    reference = (
        float(unwrap_reference)
        if unwrap_reference is not None
        else west + width * resolution * 0.5
    )
    return _TileMosaic(
        rgb=rgb,
        validity=validity,
        west=west,
        north=north,
        resolution=resolution,
        unwrap_reference=reference,
        addresses=address_tuple,
        valid_tile_count=valid_count,
        missing_tile_count=len(address_tuple) - valid_count,
    )


def warp_mosaic_to_projected_view(
    mosaic: _TileMosaic,
    view: ProjectedView,
    *,
    transformer: Transformer | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> _WarpedRaster | None:
    """Inverse-warp a WGS84 mosaic into the view's signed projected extent."""

    if not _valid_view_limits(view):
        return None
    dimensions = _bounded_output_dimensions(view)
    if dimensions is None:
        return None
    cancelled = is_cancelled or (lambda: False)
    output_width, output_height = dimensions
    try:
        active_transformer = transformer or Transformer.from_crs(
            CRS.from_epsg(view.epsg),
            CRS.from_epsg(EXPECTED_WKID),
            always_xy=True,
        )
        x0, x1 = (float(item) for item in view.xlim)
        y0, y1 = (float(item) for item in view.ylim)
        x_coordinates = x0 + (
            numpy.arange(output_width, dtype=numpy.float64) + 0.5
        ) * ((x1 - x0) / output_width)
        y_coordinates = y1 + (
            numpy.arange(output_height, dtype=numpy.float64) + 0.5
        ) * ((y0 - y1) / output_height)
        rgba = numpy.zeros(
            (output_height, output_width, 4),
            dtype=numpy.uint8,
        )
        source_height, source_width = mosaic.validity.shape
        for row_start in range(0, output_height, WARP_CHUNK_ROWS):
            if cancelled():
                return None
            row_stop = min(output_height, row_start + WARP_CHUNK_ROWS)
            chunk_y = y_coordinates[row_start:row_stop]
            projected_x = numpy.broadcast_to(
                x_coordinates[numpy.newaxis, :],
                (len(chunk_y), output_width),
            )
            projected_y = numpy.broadcast_to(
                chunk_y[:, numpy.newaxis],
                (len(chunk_y), output_width),
            )
            longitude, latitude = active_transformer.transform(
                projected_x,
                projected_y,
            )
            longitude = numpy.asarray(longitude, dtype=numpy.float64)
            latitude = numpy.asarray(latitude, dtype=numpy.float64)
            finite = numpy.isfinite(longitude) & numpy.isfinite(latitude)
            unwrapped = mosaic.unwrap_reference + numpy.mod(
                longitude - mosaic.unwrap_reference + 180.0,
                360.0,
            ) - 180.0
            source_column = (
                (unwrapped - mosaic.west) / mosaic.resolution - 0.5
            )
            source_row = (
                (mosaic.north - latitude) / mosaic.resolution - 0.5
            )
            in_range = (
                finite
                & (source_column >= 0.0)
                & (source_column <= source_width - 1)
                & (source_row >= 0.0)
                & (source_row <= source_height - 1)
            )
            safe_column = numpy.where(in_range, source_column, -1.0)
            safe_row = numpy.where(in_range, source_row, -1.0)
            coordinates = numpy.vstack(
                (safe_row.ravel(), safe_column.ravel())
            )
            for channel in range(3):
                sampled = map_coordinates(
                    mosaic.rgb[:, :, channel],
                    coordinates,
                    output=numpy.float32,
                    order=1,
                    mode="constant",
                    cval=0.0,
                    prefilter=False,
                ).reshape(len(chunk_y), output_width)
                rgba[row_start:row_stop, :, channel] = numpy.clip(
                    numpy.rint(sampled),
                    0,
                    255,
                ).astype(numpy.uint8)
            if cancelled():
                return None
            sampled_validity = map_coordinates(
                mosaic.validity,
                coordinates,
                order=1,
                mode="constant",
                cval=0.0,
                prefilter=False,
            ).reshape(len(chunk_y), output_width)
            alpha = numpy.clip(
                numpy.rint(sampled_validity * 255.0),
                0,
                255,
            ).astype(numpy.uint8)
            alpha[~in_range] = 0
            rgba[row_start:row_stop, :, 3] = alpha
        rgba.setflags(write=False)
        return _WarpedRaster(
            rgba=rgba,
            extent=(x0, x1, y0, y1),
        )
    except Exception:
        return None


_SOF_MARKERS = frozenset(
    {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
)
_STANDALONE_MARKERS = frozenset(
    {0xD8, 0xD9, 0x01, *range(0xD0, 0xD8)}
)


def _jpeg_dimensions_are_safe(data: bytes) -> bool:
    if not isinstance(data, bytes) or len(data) < 4 or data[:2] != b"\xff\xd8":
        return False
    position = 2
    dimensions: tuple[int, int, int] | None = None
    while position < len(data):
        if data[position] != 0xFF:
            return False
        while position < len(data) and data[position] == 0xFF:
            position += 1
        if position >= len(data):
            return False
        marker = data[position]
        position += 1
        if marker == 0x00:
            return False
        if marker in _STANDALONE_MARKERS:
            if marker == 0xD9:
                return dimensions is not None
            continue
        if marker == 0xDA:
            return dimensions is not None
        if position + 2 > len(data):
            return False
        segment_length = int.from_bytes(data[position : position + 2], "big")
        if segment_length < 2:
            return False
        segment_end = position + segment_length
        if segment_end < position or segment_end > len(data):
            return False
        if marker in _SOF_MARKERS:
            payload = data[position + 2 : segment_end]
            if len(payload) < 6:
                return False
            height = int.from_bytes(payload[1:3], "big")
            width = int.from_bytes(payload[3:5], "big")
            components = payload[5]
            if (
                not 1 <= components <= 4
                or segment_length < 8 + 3 * components
                or height != EXPECTED_TILE_SIZE
                or width != EXPECTED_TILE_SIZE
            ):
                return False
            found = (height, width, components)
            if dimensions is not None and dimensions != found:
                return False
            dimensions = found
        position = segment_end
    return dimensions is not None


def decode_jpeg_tile(
    data: bytes,
    *,
    decoder: Callable[..., numpy.ndarray] | None = None,
) -> numpy.ndarray | None:
    """Validate a bounded JPEG header, decode it, and normalize to read-only RGB."""

    if not _jpeg_dimensions_are_safe(data):
        return None
    active_decoder = decoder or matplotlib.image.imread
    try:
        decoded = numpy.asarray(
            active_decoder(BytesIO(data), format="jpeg")
        )
    except Exception:
        return None
    if decoded.ndim == 2:
        decoded = numpy.repeat(decoded[:, :, numpy.newaxis], 3, axis=2)
    elif decoded.ndim == 3 and decoded.shape[2] == 1:
        decoded = numpy.repeat(decoded, 3, axis=2)
    elif decoded.ndim == 3 and decoded.shape[2] == 4:
        decoded = decoded[:, :, :3]
    elif decoded.ndim != 3 or decoded.shape[2] != 3:
        return None
    if decoded.shape != (
        EXPECTED_TILE_SIZE,
        EXPECTED_TILE_SIZE,
        3,
    ):
        return None
    if decoded.dtype == numpy.uint8:
        normalized = numpy.ascontiguousarray(decoded)
    elif numpy.issubdtype(decoded.dtype, numpy.floating):
        if not numpy.isfinite(decoded).all():
            return None
        normalized = numpy.ascontiguousarray(
            numpy.rint(numpy.clip(decoded, 0.0, 1.0) * 255.0).astype(
                numpy.uint8
            )
        )
    else:
        return None
    normalized.setflags(write=False)
    return normalized


@dataclass(frozen=True)
class _ViewRequest:
    level: int
    extent: _GeographicExtent
    padded_extent: tuple[float, float, float, float]
    addresses: tuple[TileAddress, ...]
    output_dimensions: tuple[int, int]


def _padded_extent(
    extent: _GeographicExtent,
    resolution: float,
) -> tuple[float, float, float, float]:
    west = extent.west - resolution
    east = extent.east + resolution
    south = max(-90.0, extent.south - resolution)
    north = min(90.0, extent.north + resolution)
    if east - west >= 360.0:
        west = extent.unwrap_reference - 180.0
        east = extent.unwrap_reference + 180.0
    return west, south, east, north


def _prepare_view_request(
    service: ArcGisTileService,
    view: ProjectedView,
) -> _ViewRequest | None:
    """Create the converged, padded, resource-bounded request for a view."""

    dimensions = _bounded_output_dimensions(view)
    if dimensions is None:
        return None
    initial_extent = sample_projected_perimeter(view)
    if initial_extent is None:
        return None
    level = select_lod(
        service,
        view,
        geographic_extent=initial_extent,
    )
    if level is None:
        return None
    for _pass_index in range(_MAX_LOD_PASSES):
        if not 0 <= level < len(service.lod_resolutions):
            return None
        converged = sample_projected_perimeter(
            view,
            source_resolution=service.lod_resolutions[level],
        )
        if converged is None:
            return None
        padded = _padded_extent(converged, service.lod_resolutions[level])
        address_count = _tile_address_count(padded, level)
        if address_count is None:
            return None
        backed_off_level = level
        while (
            address_count > MAX_TILES_PER_VIEW
            and backed_off_level > 0
        ):
            backed_off_level -= 1
            padded = _padded_extent(
                converged,
                service.lod_resolutions[backed_off_level],
            )
            address_count = _tile_address_count(
                padded,
                backed_off_level,
            )
            if address_count is None:
                return None
        if address_count > MAX_TILES_PER_VIEW:
            return None
        addresses = select_tile_addresses(padded, backed_off_level)
        if not addresses:
            return None
        if backed_off_level != level:
            level = backed_off_level
            continue
        return _ViewRequest(
            level=level,
            extent=converged,
            padded_extent=padded,
            addresses=addresses,
            output_dimensions=dimensions,
        )
    return None


def _tile_url(address: TileAddress) -> str:
    return (
        f"{SERVICE_ROOT}/tile/{address.level}/{address.row}/"
        f"{address.request_column}"
    )


def _url_is_allowed(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return (
            parsed.scheme.casefold() == "https"
            and parsed.hostname is not None
            and parsed.hostname.casefold() == ALLOWED_HOST
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
        )
    except (TypeError, ValueError):
        return False


class _StrictRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        request: Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> Request | None:
        if not _url_is_allowed(new_url):
            raise URLError("Redirect target rejected.")
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )


@dataclass(frozen=True)
class _HttpBytes:
    data: bytes
    content_type: str


@dataclass(frozen=True)
class _HttpProblem:
    kind: str
    status: int | None
    retryable: bool
    permanent: bool
    missing: bool = False


_CANCELLED = object()


def _status_problem(status: int) -> _HttpProblem:
    if status == 404:
        return _HttpProblem(
            kind="http_status",
            status=status,
            retryable=False,
            permanent=True,
            missing=True,
        )
    if status in {408, 429} or 500 <= status <= 599:
        return _HttpProblem(
            kind="http_status",
            status=status,
            retryable=True,
            permanent=False,
        )
    return _HttpProblem(
        kind="http_status",
        status=status,
        retryable=False,
        permanent=True,
    )


def _exception_problem(error: BaseException) -> _HttpProblem:
    if isinstance(error, HTTPError):
        return _status_problem(int(error.code))
    if isinstance(error, (TimeoutError, socket.timeout, ConnectionError)):
        return _HttpProblem(
            kind="timeout",
            status=None,
            retryable=True,
            permanent=False,
        )
    if isinstance(error, URLError):
        reason = error.reason
        if isinstance(
            reason,
            (TimeoutError, socket.timeout, ConnectionError, socket.gaierror),
        ):
            return _HttpProblem(
                kind="url_error",
                status=None,
                retryable=True,
                permanent=False,
            )
        return _HttpProblem(
            kind="url_error",
            status=None,
            retryable=False,
            permanent=True,
        )
    return _HttpProblem(
        kind="transport",
        status=None,
        retryable=False,
        permanent=True,
    )


def _response_status(response: Any) -> int | None:
    status = getattr(response, "status", None)
    if status is None:
        getter = getattr(response, "getcode", None)
        if callable(getter):
            status = getter()
    if not isinstance(status, int) or isinstance(status, bool):
        return None
    return status


def _response_url(response: Any, fallback: str) -> str:
    getter = getattr(response, "geturl", None)
    if callable(getter):
        result = getter()
        if isinstance(result, str):
            return result
    url = getattr(response, "url", None)
    return url if isinstance(url, str) else fallback


def _response_content_type(response: Any) -> str:
    headers = getattr(response, "headers", None)
    if headers is None:
        info = getattr(response, "info", None)
        if callable(info):
            headers = info()
    if headers is None:
        return ""
    get_content_type = getattr(headers, "get_content_type", None)
    if callable(get_content_type):
        value = get_content_type()
    else:
        getter = getattr(headers, "get", None)
        value = getter("Content-Type", "") if callable(getter) else ""
    if not isinstance(value, str):
        return ""
    return value.split(";", 1)[0].strip().casefold()


def _read_bounded_body(response: Any, maximum_bytes: int) -> bytes | None:
    read = getattr(response, "read", None)
    if not callable(read):
        return None
    body = bytearray()
    while len(body) <= maximum_bytes:
        requested = min(65_536, maximum_bytes + 1 - len(body))
        if requested <= 0:
            break
        chunk = read(requested)
        if not isinstance(chunk, (bytes, bytearray, memoryview)):
            return None
        if not chunk:
            break
        body.extend(chunk)
    if len(body) > maximum_bytes:
        return None
    return bytes(body)


@dataclass(frozen=True)
class _JobContext:
    slot_key: str
    surface_id: str
    generation: int
    registration_epoch: int
    cache_epoch: int


@dataclass(frozen=True)
class _AttemptReservation:
    token: int
    slot_key: str
    surface_id: str
    generation: int
    registration_epoch: int
    cache_epoch: int
    purpose: str
    metadata_token: tuple[int, int] | None


@dataclass(frozen=True)
class _PendingJob:
    view: ProjectedView
    registration_epoch: int
    cache_epoch: int


@dataclass
class _WorkerSlot:
    key: str
    condition: threading.Condition
    surface_id: str | None = None
    registration_epoch: int = 0
    pending: _PendingJob | None = None
    thread: threading.Thread | None = None


@dataclass(frozen=True)
class _TileFetch:
    state: str
    tile: numpy.ndarray | None = None


class ArcGisBasemapClient:
    """Latest-only, two-slot basemap client with bounded process-memory state."""

    def __init__(
        self,
        *,
        opener: Any | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
        retry_wait: Callable[[float, Callable[[], bool]], bool] | None = None,
        metadata_fixture: Any | None = None,
        cache: MemoryTileCache | None = None,
        response_queue: queue.Queue[
            BasemapFrame | BasemapFailure
        ] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._metadata_condition = threading.Condition(self._lock)
        self._slots = {
            key: _WorkerSlot(
                key=key,
                condition=threading.Condition(self._lock),
            )
            for key in ("main", "inspector")
        }
        self._latest_generation: dict[str, int] = {}
        self._surface_slots: dict[str, str] = {}
        self._cache_epoch = 0
        self._cache = cache or MemoryTileCache(lock=self._lock)
        self._responses = response_queue or queue.Queue(
            maxsize=MAX_RESPONSE_ITEMS
        )
        self._response_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._stopping = False

        self._opener = opener or build_opener(_StrictRedirectHandler())
        self._clock = monotonic_clock
        self._retry_wait = retry_wait
        self._metadata_fixture = metadata_fixture

        self._metadata_state = "EMPTY"
        self._metadata_service: ArcGisTileService | None = None
        self._metadata_cooldown_started: float | None = None
        self._metadata_epoch = 0
        self._metadata_token_counter = 0
        self._active_metadata_token: tuple[int, int] | None = None

        self._reservation_counter = 0
        self._reservations: dict[str, _AttemptReservation] = {}

    @property
    def metadata_state(self) -> str:
        with self._lock:
            return self._metadata_state

    @property
    def active_reservations(self) -> tuple[_AttemptReservation, ...]:
        with self._lock:
            return tuple(self._reservations.values())

    @property
    def cache_epoch(self) -> int:
        with self._lock:
            return self._cache_epoch

    def submit(self, view: ProjectedView) -> None:
        if not isinstance(view, ProjectedView):
            return
        if view.surface_id == "main":
            slot_key = "main"
        elif (
            view.surface_id.startswith("inspector:")
            and len(view.surface_id) > len("inspector:")
        ):
            slot_key = "inspector"
        else:
            return
        with self._lock:
            if self._stopping:
                return
            slot = self._slots[slot_key]
            if slot.surface_id != view.surface_id:
                if slot.surface_id is not None:
                    self._latest_generation.pop(slot.surface_id, None)
                    self._surface_slots.pop(slot.surface_id, None)
                slot.registration_epoch += 1
                slot.surface_id = view.surface_id
                slot.pending = None
                self._surface_slots[view.surface_id] = slot_key
            current = self._latest_generation.get(view.surface_id)
            if current is not None and view.generation < current:
                return
            self._latest_generation[view.surface_id] = view.generation
            slot.pending = _PendingJob(
                view=view,
                registration_epoch=slot.registration_epoch,
                cache_epoch=self._cache_epoch,
            )
            if slot.thread is None or not slot.thread.is_alive():
                slot.thread = threading.Thread(
                    target=self._worker_loop,
                    args=(slot_key,),
                    name=f"basemap-{slot_key}",
                    daemon=True,
                )
                slot.thread.start()
            slot.condition.notify_all()
            self._metadata_condition.notify_all()

    def cancel_surface(
        self,
        surface_id: str,
        minimum_generation: int,
    ) -> None:
        with self._lock:
            slot_key = self._surface_slots.get(surface_id)
            if slot_key is None:
                return
            current = self._latest_generation.get(surface_id, minimum_generation)
            self._latest_generation[surface_id] = max(
                current,
                minimum_generation,
            )
            slot = self._slots[slot_key]
            slot.pending = None
            slot.condition.notify_all()
            self._metadata_condition.notify_all()

    def deregister_surface(self, surface_id: str) -> None:
        with self._lock:
            slot_key = self._surface_slots.pop(surface_id, None)
            if slot_key is None:
                return
            slot = self._slots[slot_key]
            if slot.surface_id != surface_id:
                return
            self._latest_generation.pop(surface_id, None)
            slot.surface_id = None
            slot.pending = None
            slot.registration_epoch += 1
            slot.condition.notify_all()
            self._metadata_condition.notify_all()

    def poll(self) -> BasemapFrame | BasemapFailure | None:
        with self._response_lock:
            try:
                return self._responses.get_nowait()
            except queue.Empty:
                return None

    def clear_cache(self) -> None:
        with self._lock:
            self._cache_epoch += 1
            self._cache.clear()
            for slot in self._slots.values():
                slot.condition.notify_all()
            self._metadata_condition.notify_all()

    def reset_transient_metadata_failure(self) -> None:
        with self._metadata_condition:
            if self._metadata_state != "COOLDOWN":
                return
            self._metadata_epoch += 1
            self._metadata_state = "EMPTY"
            self._metadata_cooldown_started = None
            self._active_metadata_token = None
            self._metadata_condition.notify_all()

    def shutdown(self) -> None:
        with self._lock:
            if self._stopping:
                return
            self._stopping = True
            self._stop_event.set()
            self._cache_epoch += 1
            self._cache.clear()
            self._metadata_epoch += 1
            self._metadata_state = "SHUTDOWN"
            self._metadata_service = None
            self._active_metadata_token = None
            self._latest_generation.clear()
            self._surface_slots.clear()
            for slot in self._slots.values():
                slot.pending = None
                slot.surface_id = None
                slot.registration_epoch += 1
                slot.condition.notify_all()
            self._metadata_condition.notify_all()

    def _worker_loop(self, slot_key: str) -> None:
        slot = self._slots[slot_key]
        while True:
            with slot.condition:
                while slot.pending is None and not self._stopping:
                    slot.condition.wait()
                if self._stopping:
                    return
                pending = slot.pending
                slot.pending = None
                if pending is None:
                    continue
                view = pending.view
                if slot.surface_id != view.surface_id:
                    continue
                context = _JobContext(
                    slot_key=slot_key,
                    surface_id=view.surface_id,
                    generation=view.generation,
                    registration_epoch=pending.registration_epoch,
                    cache_epoch=pending.cache_epoch,
                )
            try:
                self._process_view(view, context)
            except (Exception, MemoryError):
                self._publish_if_current(
                    context,
                    self._failure(
                        view,
                        "imagery_error",
                        "Imagery is unavailable for this view.",
                        retryable=True,
                    )
                )

    def _is_job_current_locked(self, context: _JobContext) -> bool:
        if self._stopping or self._stop_event.is_set():
            return False
        slot = self._slots[context.slot_key]
        return (
            slot.surface_id == context.surface_id
            and slot.registration_epoch == context.registration_epoch
            and self._surface_slots.get(context.surface_id) == context.slot_key
            and self._latest_generation.get(context.surface_id)
            == context.generation
            and self._cache_epoch == context.cache_epoch
        )

    def _is_job_current(self, context: _JobContext) -> bool:
        with self._lock:
            return self._is_job_current_locked(context)

    def _reserve_http_attempt(
        self,
        context: _JobContext,
        purpose: str,
        metadata_token: tuple[int, int] | None = None,
    ) -> _AttemptReservation | None:
        with self._lock:
            if (
                not self._is_job_current_locked(context)
                or context.slot_key in self._reservations
            ):
                return None
            if metadata_token is not None and (
                self._metadata_state != "FETCHING"
                or self._active_metadata_token != metadata_token
            ):
                return None
            self._reservation_counter += 1
            reservation = _AttemptReservation(
                token=self._reservation_counter,
                slot_key=context.slot_key,
                surface_id=context.surface_id,
                generation=context.generation,
                registration_epoch=context.registration_epoch,
                cache_epoch=context.cache_epoch,
                purpose=purpose,
                metadata_token=metadata_token,
            )
            self._reservations[context.slot_key] = reservation
            return reservation

    def _perform_reserved_open(
        self,
        reservation: _AttemptReservation,
        request: Request,
    ) -> Any:
        del reservation
        open_method = getattr(self._opener, "open", None)
        if callable(open_method):
            return open_method(
                request,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        return self._opener(
            request,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    def _release_http_attempt(
        self,
        reservation: _AttemptReservation,
    ) -> None:
        with self._lock:
            current = self._reservations.get(reservation.slot_key)
            if current is not None and current.token == reservation.token:
                del self._reservations[reservation.slot_key]

    def _reservation_return_is_current(
        self,
        context: _JobContext,
        metadata_token: tuple[int, int] | None,
    ) -> bool:
        with self._lock:
            if not self._is_job_current_locked(context):
                return False
            if metadata_token is None:
                return True
            return (
                self._metadata_state == "FETCHING"
                and self._active_metadata_token == metadata_token
            )

    def _request_bytes(
        self,
        context: _JobContext,
        *,
        url: str,
        maximum_bytes: int,
        purpose: str,
        metadata_token: tuple[int, int] | None = None,
    ) -> _HttpBytes | _HttpProblem | object:
        if not _url_is_allowed(url):
            return _HttpProblem(
                kind="url_policy",
                status=None,
                retryable=False,
                permanent=True,
            )
        reservation = self._reserve_http_attempt(
            context,
            purpose,
            metadata_token,
        )
        if reservation is None:
            return _CANCELLED
        request = Request(url, headers={"User-Agent": USER_AGENT})
        response: Any | None = None
        try:
            response = self._perform_reserved_open(reservation, request)
            status = _response_status(response)
            if status != 200:
                result = _status_problem(status if status is not None else 0)
            elif not _url_is_allowed(_response_url(response, url)):
                result = _HttpProblem(
                    kind="url_policy",
                    status=None,
                    retryable=False,
                    permanent=True,
                )
            else:
                content_type = _response_content_type(response)
                body = _read_bounded_body(response, maximum_bytes)
                if body is None:
                    result = _HttpProblem(
                        kind="body_policy",
                        status=None,
                        retryable=False,
                        permanent=True,
                    )
                else:
                    result = _HttpBytes(
                        data=body,
                        content_type=content_type,
                    )
        except Exception as error:
            result = _exception_problem(error)
            if isinstance(error, HTTPError):
                try:
                    error.close()
                except Exception:
                    pass
        finally:
            if response is not None:
                close = getattr(response, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass
            self._release_http_attempt(reservation)
        if not self._reservation_return_is_current(
            context,
            metadata_token,
        ):
            return _CANCELLED
        return result

    def _failure(
        self,
        view: ProjectedView,
        category: str,
        user_message: str,
        *,
        retryable: bool,
    ) -> BasemapFailure:
        return BasemapFailure(
            surface_id=view.surface_id,
            generation=view.generation,
            result_generation=view.result_generation,
            category=category,
            user_message=user_message,
            retryable=retryable,
        )

    def _metadata_failure_for_state(
        self,
        view: ProjectedView,
    ) -> BasemapFailure:
        if self._metadata_state == "COOLDOWN":
            return self._failure(
                view,
                "metadata_unavailable",
                "Imagery service is temporarily unavailable.",
                retryable=True,
            )
        return self._failure(
            view,
            "metadata_incompatible",
            "Imagery service metadata is incompatible.",
            retryable=False,
        )

    def _acquire_metadata_payload(
        self,
        context: _JobContext,
        metadata_token: tuple[int, int],
    ) -> tuple[str, ArcGisTileService | ServiceMetadataError | None]:
        if self._metadata_fixture is not None:
            try:
                raw_value = (
                    self._metadata_fixture()
                    if callable(self._metadata_fixture)
                    else self._metadata_fixture
                )
                if isinstance(raw_value, ArcGisTileService):
                    return "ready", raw_value
                if isinstance(raw_value, (bytes, bytearray)):
                    try:
                        raw_value = json.loads(bytes(raw_value).decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        return "cooldown", None
                parsed = parse_service_metadata(raw_value)
                if isinstance(parsed, ArcGisTileService):
                    return "ready", parsed
                return "incompatible", parsed
            except Exception:
                return "cooldown", None

        response = self._request_bytes(
            context,
            url=METADATA_URL,
            maximum_bytes=MAX_METADATA_BYTES,
            purpose="metadata",
            metadata_token=metadata_token,
        )
        if response is _CANCELLED:
            return "cancelled", None
        if isinstance(response, _HttpProblem):
            return (
                "cooldown" if response.retryable else "incompatible",
                None,
            )
        assert isinstance(response, _HttpBytes)
        explicit_json = (
            response.content_type == "application/json"
            or response.content_type == "text/json"
            or response.content_type.endswith("+json")
        )
        try:
            decoded = response.data.decode("utf-8")
            raw_metadata = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return (
                "cooldown" if explicit_json or not response.content_type
                else "incompatible",
                None,
            )
        parsed = parse_service_metadata(raw_metadata)
        if isinstance(parsed, ServiceMetadataError):
            return "incompatible", parsed
        return "ready", parsed

    def _get_service(
        self,
        view: ProjectedView,
        context: _JobContext,
    ) -> tuple[ArcGisTileService | None, BasemapFailure | None]:
        owner_token: tuple[int, int] | None = None
        while owner_token is None:
            with self._metadata_condition:
                if not self._is_job_current_locked(context):
                    return None, None
                if self._metadata_state == "READY":
                    return self._metadata_service, None
                if self._metadata_state == "SHUTDOWN":
                    return None, None
                if self._metadata_state == "INCOMPATIBLE":
                    return None, self._metadata_failure_for_state(view)
                if self._metadata_state == "COOLDOWN":
                    started = self._metadata_cooldown_started
                    if (
                        started is not None
                        and self._clock()
                        < started + METADATA_RETRY_COOLDOWN
                    ):
                        return None, self._metadata_failure_for_state(view)
                    self._metadata_state = "EMPTY"
                    self._metadata_cooldown_started = None
                if self._metadata_state == "EMPTY":
                    self._metadata_token_counter += 1
                    owner_token = (
                        self._metadata_epoch,
                        self._metadata_token_counter,
                    )
                    self._active_metadata_token = owner_token
                    self._metadata_state = "FETCHING"
                    break
                self._metadata_condition.wait(METADATA_WAIT_SECONDS)

        outcome, payload = self._acquire_metadata_payload(
            context,
            owner_token,
        )
        with self._metadata_condition:
            owns_fetch = (
                self._metadata_state == "FETCHING"
                and self._active_metadata_token == owner_token
            )
            if not owns_fetch:
                return None, None
            if not self._is_job_current_locked(context) or outcome == "cancelled":
                self._metadata_state = "EMPTY"
                self._active_metadata_token = None
                self._metadata_condition.notify_all()
                return None, None
            if outcome == "ready" and isinstance(payload, ArcGisTileService):
                self._metadata_service = payload
                self._metadata_state = "READY"
                self._active_metadata_token = None
                self._metadata_condition.notify_all()
                return payload, None
            if outcome == "cooldown":
                self._metadata_state = "COOLDOWN"
                self._metadata_cooldown_started = self._clock()
            else:
                self._metadata_state = "INCOMPATIBLE"
                self._metadata_cooldown_started = None
            self._active_metadata_token = None
            self._metadata_condition.notify_all()
            return None, self._metadata_failure_for_state(view)

    def _wait_before_retry(self, context: _JobContext) -> bool:
        if self._retry_wait is not None:
            try:
                elapsed = self._retry_wait(
                    RETRY_DELAY_SECONDS,
                    lambda: self._is_job_current(context),
                )
            except Exception:
                return False
            return bool(elapsed) and self._is_job_current(context)
        deadline = self._clock() + RETRY_DELAY_SECONDS
        condition = self._slots[context.slot_key].condition
        with condition:
            while self._is_job_current_locked(context):
                remaining = deadline - self._clock()
                if remaining <= 0.0:
                    return True
                condition.wait(remaining)
            return False

    def _fetch_tile(
        self,
        context: _JobContext,
        address: TileAddress,
    ) -> _TileFetch:
        key = (
            SERVICE_ROOT,
            address.level,
            address.row,
            address.request_column,
        )
        with self._lock:
            if not self._is_job_current_locked(context):
                return _TileFetch("cancelled")
            cached = self._cache.get(key)
        if cached is not None:
            return _TileFetch("valid", cached)

        for attempt in range(MAX_TRANSIENT_RETRIES + 1):
            response = self._request_bytes(
                context,
                url=_tile_url(address),
                maximum_bytes=MAX_TILE_BYTES,
                purpose="tile",
            )
            if response is _CANCELLED:
                return _TileFetch("cancelled")
            if isinstance(response, _HttpProblem):
                if response.missing:
                    return _TileFetch("missing")
                if (
                    response.retryable
                    and attempt < MAX_TRANSIENT_RETRIES
                    and self._wait_before_retry(context)
                ):
                    continue
                return _TileFetch("failed")
            assert isinstance(response, _HttpBytes)
            if response.content_type not in {"image/jpeg", "image/jpg"}:
                return _TileFetch("failed")
            tile = decode_jpeg_tile(response.data)
            if tile is None:
                return _TileFetch("failed")
            with self._lock:
                if not self._is_job_current_locked(context):
                    return _TileFetch("cancelled")
                self._cache.put(key, tile)
                stored = self._cache.get(key)
            return _TileFetch("valid", stored if stored is not None else tile)
        return _TileFetch("failed")

    def _process_view(
        self,
        view: ProjectedView,
        context: _JobContext,
    ) -> None:
        if not self._is_job_current(context):
            return
        service, metadata_failure = self._get_service(view, context)
        if metadata_failure is not None:
            self._publish_if_current(context, metadata_failure)
            return
        if service is None or not self._is_job_current(context):
            return
        request = _prepare_view_request(service, view)
        if request is None:
            self._publish_if_current(
                context,
                self._failure(
                    view,
                    "invalid_view",
                    "Imagery is unavailable for this view.",
                    retryable=False,
                )
            )
            return

        tiles: dict[TileAddress, numpy.ndarray] = {}
        missing_count = 0
        consecutive_failures = 0
        for address in request.addresses:
            if not self._is_job_current(context):
                return
            result = self._fetch_tile(context, address)
            if result.state == "cancelled":
                return
            if result.state == "valid" and result.tile is not None:
                tiles[address] = result.tile
                consecutive_failures = 0
                continue
            missing_count += 1
            if result.state == "missing":
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    self._publish_if_current(
                        context,
                        self._failure(
                            view,
                            "tile_failures",
                            "Imagery is unavailable for this view.",
                            retryable=True,
                        )
                    )
                    return

        if not tiles:
            self._publish_if_current(
                context,
                self._failure(
                    view,
                    "no_imagery",
                    "No imagery is available for this view.",
                    retryable=True,
                )
            )
            return
        mosaic = assemble_tile_mosaic(
            request.addresses,
            tiles,
            request.level,
            unwrap_reference=request.extent.unwrap_reference,
        )
        if mosaic is None:
            self._publish_if_current(
                context,
                self._failure(
                    view,
                    "raster_error",
                    "Imagery is unavailable for this view.",
                    retryable=False,
                )
            )
            return
        warped = warp_mosaic_to_projected_view(
            mosaic,
            view,
            is_cancelled=lambda: not self._is_job_current(context),
        )
        if warped is None:
            self._publish_if_current(
                context,
                self._failure(
                    view,
                    "raster_error",
                    "Imagery is unavailable for this view.",
                    retryable=False,
                )
            )
            return
        if not self._is_job_current(context):
            return
        requested_count = len(request.addresses)
        valid_count = len(tiles)
        if missing_count != requested_count - valid_count:
            return
        frame = BasemapFrame(
            surface_id=view.surface_id,
            generation=view.generation,
            result_generation=view.result_generation,
            epsg=view.epsg,
            xlim=view.xlim,
            ylim=view.ylim,
            pixel_width=view.pixel_width,
            pixel_height=view.pixel_height,
            rgba=warped.rgba,
            copyright_text=service.copyright_text,
            requested_tile_count=requested_count,
            valid_tile_count=valid_count,
            missing_tile_count=missing_count,
            is_partial=missing_count > 0,
        )
        self._publish_if_current(context, frame)

    def _publish_if_current(
        self,
        context: _JobContext,
        item: BasemapFrame | BasemapFailure,
    ) -> bool:
        with self._lock:
            if not self._is_job_current_locked(context):
                return False
            self._publish(item)
            return True

    def _publish(self, item: BasemapFrame | BasemapFailure) -> None:
        with self._response_lock:
            if (
                self._responses.qsize() >= MAX_RESPONSE_ITEMS
                or self._responses.full()
            ):
                try:
                    self._responses.get_nowait()
                except queue.Empty:
                    pass
            try:
                self._responses.put_nowait(item)
            except queue.Full:
                pass


def _live_service_smoke() -> tuple[ArcGisTileService, numpy.ndarray]:
    """Fetch exactly metadata and one known tile for the opt-in smoke test."""

    if os.environ.get("JPG_BOUNDARY_LIVE_ESRI_TEST") != "1":
        raise RuntimeError("Live Esri smoke is not enabled.")
    opener = build_opener(_StrictRedirectHandler())

    def fetch(url: str, maximum: int, expected_type: str) -> bytes:
        request = Request(url, headers={"User-Agent": USER_AGENT})
        response = opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS)
        try:
            if _response_status(response) != 200:
                raise RuntimeError("Unexpected live response.")
            if not _url_is_allowed(_response_url(response, url)):
                raise RuntimeError("Unexpected live response URL.")
            if _response_content_type(response) != expected_type:
                raise RuntimeError("Unexpected live content type.")
            body = _read_bounded_body(response, maximum)
            if body is None:
                raise RuntimeError("Live response exceeded its bound.")
            return body
        finally:
            response.close()

    metadata_body = fetch(METADATA_URL, MAX_METADATA_BYTES, "application/json")
    metadata = parse_service_metadata(
        json.loads(metadata_body.decode("utf-8"))
    )
    if not isinstance(metadata, ArcGisTileService):
        raise RuntimeError("Live service metadata is incompatible.")
    address = TileAddress(
        level=15,
        row=8283,
        request_column=16493,
        display_column=16493,
    )
    tile_body = fetch(_tile_url(address), MAX_TILE_BYTES, "image/jpeg")
    tile = decode_jpeg_tile(tile_body)
    if tile is None:
        raise RuntimeError("Live tile is invalid.")
    return metadata, tile
