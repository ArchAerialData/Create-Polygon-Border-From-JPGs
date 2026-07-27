from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from io import BytesIO
import builtins
import json
import math
import os
from pathlib import Path
import queue
import socket
import sys
import threading
import time
from types import SimpleNamespace
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

import matplotlib.image
import numpy as np
from pyproj import CRS, Geod, Transformer


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import jpg_boundary_gui_basemap as basemap  # noqa: E402
from jpg_boundary_gui_basemap import (  # noqa: E402
    ArcGisTileService,
    BasemapFailure,
    BasemapFrame,
    MemoryTileCache,
    ProjectedView,
    ServiceMetadataError,
    TileAddress,
    assemble_tile_mosaic,
    decode_jpeg_tile,
    parse_service_metadata,
    sample_projected_perimeter,
    select_lod,
    select_tile_addresses,
    tile_matrix_shape,
    tile_resolution,
    tile_span,
    warp_mosaic_to_projected_view,
)

ArcGisBasemapClient = getattr(basemap, "ArcGisBasemapClient", None)

_MODULE_NETWORK_GUARDS: list[object] = []
_MODULE_NETWORK_MOCKS: list[Mock] = []


def setUpModule() -> None:
    if os.environ.get("JPG_BOUNDARY_LIVE_ESRI_TEST") == "1":
        return
    for target, attribute, message in (
        (socket.socket, "connect", "network socket opened"),
        (socket, "create_connection", "network connection opened"),
    ):
        guard = patch.object(
            target,
            attribute,
            side_effect=AssertionError(message),
        )
        _MODULE_NETWORK_GUARDS.append(guard)
        _MODULE_NETWORK_MOCKS.append(guard.start())


def tearDownModule() -> None:
    try:
        for network_mock in _MODULE_NETWORK_MOCKS:
            network_mock.assert_not_called()
    finally:
        for guard in reversed(_MODULE_NETWORK_GUARDS):
            guard.stop()
        _MODULE_NETWORK_GUARDS.clear()
        _MODULE_NETWORK_MOCKS.clear()


_ATTRIBUTION = (
    "Source: Esri, Vantor, Earthstar Geographics, "
    "and the GIS User Community"
)


def _metadata_fixture() -> dict[str, object]:
    return {
        "currentVersion": 10.91,
        "singleFusedMapCache": True,
        "capabilities": "Map, Tilemap, TilesOnly",
        "spatialReference": {"wkid": 4326},
        "tileInfo": {
            "rows": 256,
            "cols": 256,
            "format": "JPEG",
            "origin": {"x": -180.0, "y": 90.0},
            "spatialReference": {"wkid": 4326},
            "lods": [
                {
                    "level": level,
                    "resolution": 0.703125 / (2**level),
                }
                for level in range(23)
            ],
        },
        "copyrightText": _ATTRIBUTION,
        "exportTilesAllowed": False,
    }


def _service() -> ArcGisTileService:
    parsed = parse_service_metadata(_metadata_fixture())
    if not isinstance(parsed, ArcGisTileService):
        raise AssertionError(parsed)
    return parsed


def _view(
    *,
    surface_id: str = "main",
    generation: int = 1,
    result_generation: int = 1,
    epsg: int = 4326,
    xlim: tuple[float, float] = (-1.0, 1.0),
    ylim: tuple[float, float] = (-1.0, 1.0),
    pixel_width: int = 256,
    pixel_height: int = 256,
) -> ProjectedView:
    return ProjectedView(
        surface_id=surface_id,
        generation=generation,
        result_generation=result_generation,
        epsg=epsg,
        xlim=xlim,
        ylim=ylim,
        pixel_width=pixel_width,
        pixel_height=pixel_height,
    )


def _solid_tile(red: int, green: int = 0, blue: int = 0) -> np.ndarray:
    tile = np.empty((256, 256, 3), dtype=np.uint8)
    tile[:, :, 0] = red
    tile[:, :, 1] = green
    tile[:, :, 2] = blue
    return tile


def _gradient_tile() -> np.ndarray:
    columns = np.arange(256, dtype=np.uint8)
    rows = np.arange(256, dtype=np.uint8)
    tile = np.empty((256, 256, 3), dtype=np.uint8)
    tile[:, :, 0] = columns[np.newaxis, :]
    tile[:, :, 1] = rows[:, np.newaxis]
    tile[:, :, 2] = 127
    return tile


def _jpeg_header(
    *,
    width: int = 256,
    height: int = 256,
    marker: int = 0xC0,
    components: int = 3,
    tail: bytes = b"\xff\xd9",
) -> bytes:
    payload = (
        bytes([8])
        + int(height).to_bytes(2, "big", signed=False)
        + int(width).to_bytes(2, "big", signed=False)
        + bytes([components])
        + b"\x01\x11\x00" * components
    )
    segment = b"\xff" + bytes([marker]) + (len(payload) + 2).to_bytes(2, "big")
    return b"\xff\xd8" + segment + payload + tail


def _encoded_jpeg(tile: np.ndarray | None = None) -> bytes:
    source = _gradient_tile() if tile is None else tile
    buffer = BytesIO()
    matplotlib.image.imsave(buffer, source, format="jpeg")
    return buffer.getvalue()


class _Headers:
    def __init__(self, content_type: str, content_length: int | None = None):
        self._content_type = content_type
        self._content_length = content_length

    def get_content_type(self) -> str:
        return self._content_type

    def get(self, name: str, default: object = None) -> object:
        if name.casefold() == "content-length" and self._content_length is not None:
            return str(self._content_length)
        return default


class _Response:
    def __init__(
        self,
        body: bytes,
        *,
        url: str,
        status: int = 200,
        content_type: str = "application/json",
        content_length: int | None = None,
    ) -> None:
        self.body = body
        self.url = url
        self.status = status
        self.headers = _Headers(
            content_type,
            len(body) if content_length is None else content_length,
        )
        self._offset = 0

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def geturl(self) -> str:
        return self.url

    def close(self) -> None:
        return None

    def read(self, amount: int = -1) -> bytes:
        if amount is None or amount < 0:
            amount = len(self.body) - self._offset
        result = self.body[self._offset : self._offset + amount]
        self._offset += len(result)
        return result


def _wait_until(predicate: object, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():  # type: ignore[operator]
            return
        time.sleep(0.005)
    raise AssertionError("timed out waiting for worker state")


def _register_context(
    client: object,
    view: ProjectedView,
) -> object:
    slot_key = "main" if view.surface_id == "main" else "inspector"
    with client._lock:  # type: ignore[attr-defined]
        slot = client._slots[slot_key]  # type: ignore[attr-defined]
        if slot.surface_id != view.surface_id:
            if slot.surface_id is not None:
                client._latest_generation.pop(slot.surface_id, None)  # type: ignore[attr-defined]
                client._surface_slots.pop(slot.surface_id, None)  # type: ignore[attr-defined]
            slot.registration_epoch += 1
            slot.surface_id = view.surface_id
        client._surface_slots[view.surface_id] = slot_key  # type: ignore[attr-defined]
        client._latest_generation[view.surface_id] = view.generation  # type: ignore[attr-defined]
        return basemap._JobContext(
            slot_key=slot_key,
            surface_id=view.surface_id,
            generation=view.generation,
            registration_epoch=slot.registration_epoch,
            cache_epoch=client._cache_epoch,  # type: ignore[attr-defined]
        )


def _registered_client(
    *,
    view: ProjectedView | None = None,
    **client_kwargs: object,
) -> tuple[object, ProjectedView, object]:
    if ArcGisBasemapClient is None:
        raise AssertionError("ArcGisBasemapClient is unavailable")
    active_view = view or _view()
    client = ArcGisBasemapClient(**client_kwargs)
    context = _register_context(client, active_view)
    return client, active_view, context


class ServiceMetadataTests(TestCase):
    def test_parse_verified_world_imagery_fixture(self) -> None:
        parsed = parse_service_metadata(_metadata_fixture())

        self.assertIsInstance(parsed, ArcGisTileService)
        assert isinstance(parsed, ArcGisTileService)
        self.assertEqual(parsed.root_url, basemap.SERVICE_ROOT)
        self.assertEqual(parsed.metadata_url, basemap.METADATA_URL)
        self.assertEqual(parsed.expected_wkid, 4326)
        self.assertEqual(parsed.tile_size, 256)
        self.assertEqual(parsed.image_format, "JPEG")
        self.assertEqual((parsed.origin_x, parsed.origin_y), (-180.0, 90.0))
        self.assertEqual(len(parsed.lod_resolutions), 23)
        self.assertEqual(parsed.lod_resolutions[0], 0.703125)
        self.assertEqual(
            parsed.lod_resolutions[22],
            0.703125 / (2**22),
        )
        self.assertEqual(parsed.copyright_text, _ATTRIBUTION)
        with self.assertRaises(FrozenInstanceError):
            parsed.tile_size = 512  # type: ignore[misc]

        variants: list[tuple[str, object]] = [
            ("capability whitespace/case", " map , TILEMAP , tilesONLY "),
            ("JPEG case", "jPeG"),
            ("JPG lexical variant", "JpG"),
        ]
        for name, value in variants:
            with self.subTest(name=name):
                fixture = _metadata_fixture()
                if name.startswith("capability"):
                    fixture["capabilities"] = value
                else:
                    fixture["tileInfo"]["format"] = value  # type: ignore[index]
                self.assertEqual(parse_service_metadata(fixture), parsed)

        without_export = _metadata_fixture()
        del without_export["exportTilesAllowed"]
        self.assertEqual(parse_service_metadata(without_export), parsed)

        extra_fields = _metadata_fixture()
        extra_fields["unknown"] = {"providerMayAdd": [1, 2, 3]}
        extra_fields["tileInfo"]["unknown"] = "ignored"  # type: ignore[index]
        self.assertEqual(parse_service_metadata(extra_fields), parsed)

        normalized = _metadata_fixture()
        normalized["copyrightText"] = (
            "  Source:\tEsri,\r\nVantor, Earthstar Geographics, "
            "and the GIS User Community  "
        )
        self.assertEqual(parse_service_metadata(normalized), parsed)

    def test_reject_every_unsafe_metadata_mutation(self) -> None:
        error_codes = {
            "invalid_root",
            "invalid_cache",
            "invalid_capabilities",
            "invalid_spatial_reference",
            "invalid_tile_schema",
            "invalid_origin",
            "invalid_lods",
            "invalid_attribution",
            "invalid_export_policy",
        }

        def set_path(
            value: dict[str, object],
            path: tuple[object, ...],
            replacement: object,
        ) -> None:
            target: object = value
            for part in path[:-1]:
                target = target[part]  # type: ignore[index]
            target[path[-1]] = replacement  # type: ignore[index]

        cases: list[tuple[str, object, tuple[object, ...] | None]] = [
            ("nonmapping root", [], None),
            ("missing fused", None, ("singleFusedMapCache",)),
            ("nonboolean fused", 1, ("singleFusedMapCache",)),
            ("false fused", False, ("singleFusedMapCache",)),
            ("missing capabilities", None, ("capabilities",)),
            ("wrong capabilities type", ["TilesOnly"], ("capabilities",)),
            ("empty capabilities", "  ", ("capabilities",)),
            ("nonexact Tiles token", "Map, Tiles", ("capabilities",)),
            (
                "missing service wkid",
                {},
                ("spatialReference",),
            ),
            (
                "wrong service wkid",
                {"wkid": 3857},
                ("spatialReference",),
            ),
            (
                "wrong tile wkid type",
                {"wkid": "4326"},
                ("tileInfo", "spatialReference"),
            ),
            ("wrong rows", 512, ("tileInfo", "rows")),
            ("noninteger columns", 256.0, ("tileInfo", "cols")),
            ("missing format", None, ("tileInfo", "format")),
            ("PNG format", "PNG", ("tileInfo", "format")),
            ("nonnumeric origin", "west", ("tileInfo", "origin", "x")),
            ("nonfinite origin", math.inf, ("tileInfo", "origin", "y")),
            (
                "origin x outside tolerance",
                -180.0 + 1.1e-12,
                ("tileInfo", "origin", "x"),
            ),
            (
                "origin y outside tolerance",
                90.0 - 1.1e-12,
                ("tileInfo", "origin", "y"),
            ),
            ("LOD container wrong type", {}, ("tileInfo", "lods")),
            (
                "LOD item wrong type",
                "level zero",
                ("tileInfo", "lods", 0),
            ),
            (
                "LOD noninteger level",
                0.0,
                ("tileInfo", "lods", 0, "level"),
            ),
            (
                "LOD duplicate level",
                0,
                ("tileInfo", "lods", 1, "level"),
            ),
            (
                "LOD extra level",
                {
                    "level": 23,
                    "resolution": 0.703125 / (2**23),
                },
                ("tileInfo", "lods", 23),
            ),
            (
                "LOD nonnumeric resolution",
                "coarse",
                ("tileInfo", "lods", 0, "resolution"),
            ),
            (
                "LOD nonfinite resolution",
                math.nan,
                ("tileInfo", "lods", 0, "resolution"),
            ),
            (
                "LOD nonpositive resolution",
                0.0,
                ("tileInfo", "lods", 0, "resolution"),
            ),
            (
                "LOD nonmonotonic resolution",
                0.703125,
                ("tileInfo", "lods", 1, "resolution"),
            ),
            (
                "LOD level zero outside tolerance",
                0.703125 * (1.0 + 1.1e-12),
                ("tileInfo", "lods", 0, "resolution"),
            ),
            (
                "LOD level 22 outside tolerance",
                0.703125 / (2**22) + 1.1e-18,
                ("tileInfo", "lods", 22, "resolution"),
            ),
            ("attribution wrong type", 1, ("copyrightText",)),
            ("attribution empty", " \t\r\n ", ("copyrightText",)),
            ("attribution too long", "x" * 501, ("copyrightText",)),
            ("attribution forbidden Cc", "Esri\x00data", ("copyrightText",)),
            ("attribution forbidden Cf", "Esri\u200bdata", ("copyrightText",)),
            ("attribution surrogate", "Esri\ud800data", ("copyrightText",)),
            ("export true", True, ("exportTilesAllowed",)),
            ("export wrong type", 0, ("exportTilesAllowed",)),
        ]

        for name, replacement, path in cases:
            with self.subTest(name=name):
                if path is None:
                    candidate = replacement
                else:
                    candidate = _metadata_fixture()
                    if replacement is None:
                        target: object = candidate
                        for part in path[:-1]:
                            target = target[part]  # type: ignore[index]
                        del target[path[-1]]  # type: ignore[index]
                    elif path == ("tileInfo", "lods", 23):
                        candidate["tileInfo"]["lods"].append(replacement)  # type: ignore[index,union-attr]
                    else:
                        set_path(candidate, path, replacement)
                result = parse_service_metadata(candidate)
                self.assertIsInstance(result, ServiceMetadataError)
                assert isinstance(result, ServiceMetadataError)
                self.assertIn(result.code, error_codes)
                self.assertLessEqual(len(result.message), 80)
                self.assertNotIn("provider-controlled-secret", result.message)
                self.assertEqual(
                    set(result.__dataclass_fields__),
                    {"code", "message"},
                )

        accepted_boundaries = [
            (("tileInfo", "origin", "x"), -180.0 + 0.9e-12),
            (("tileInfo", "origin", "y"), 90.0 - 0.9e-12),
            (
                ("tileInfo", "lods", 0, "resolution"),
                0.703125 * (1.0 + 0.9e-12),
            ),
            (
                ("tileInfo", "lods", 22, "resolution"),
                0.703125 / (2**22) + 0.9e-18,
            ),
        ]
        for path, replacement in accepted_boundaries:
            with self.subTest(accepted_boundary=path):
                candidate = _metadata_fixture()
                set_path(candidate, path, replacement)
                self.assertIsInstance(
                    parse_service_metadata(candidate),
                    ArcGisTileService,
                )

        allowed_controls = _metadata_fixture()
        allowed_controls["copyrightText"] = "Esri\tdata\r\nproviders"
        allowed_result = parse_service_metadata(allowed_controls)
        self.assertIsInstance(allowed_result, ArcGisTileService)
        assert isinstance(allowed_result, ArcGisTileService)
        self.assertEqual(allowed_result.copyright_text, "Esri data providers")

        first = _metadata_fixture()
        first["marker"] = "provider-controlled-secret"
        first["singleFusedMapCache"] = False
        second = _metadata_fixture()
        second["singleFusedMapCache"] = False
        self.assertEqual(parse_service_metadata(first), parse_service_metadata(second))


class TileMatrixTests(TestCase):
    def test_known_matrix_extents_and_route_order(self) -> None:
        for level in (0, 1, 10, 15, 22):
            with self.subTest(level=level):
                self.assertEqual(
                    tile_matrix_shape(level),
                    (2**level, 2 ** (level + 1)),
                )
                self.assertEqual(tile_span(level), 180.0 / (2**level))
                self.assertEqual(
                    tile_resolution(level),
                    0.703125 / (2**level),
                )

        self.assertEqual(tile_matrix_shape(0), (1, 2))
        west = select_tile_addresses((-180.0, -90.0, 0.0, 90.0), 0)
        east = select_tile_addresses((0.0, -90.0, 180.0, 90.0), 0)
        self.assertEqual(west, (TileAddress(0, 0, 0, 0),))
        self.assertEqual(east, (TileAddress(0, 0, 1, 1),))
        address = TileAddress(15, 8283, 16493, 16493)
        self.assertEqual(
            f"{basemap.SERVICE_ROOT}/tile/{address.level}/{address.row}/"
            f"{address.request_column}",
            f"{basemap.SERVICE_ROOT}/tile/15/8283/16493",
        )

    def test_half_open_edges_clamp_without_extra_tiles(self) -> None:
        self.assertEqual(
            select_tile_addresses((-180.0, -90.0, 0.0, 90.0), 0),
            (TileAddress(0, 0, 0, 0),),
        )
        self.assertEqual(
            select_tile_addresses((0.0, -90.0, 180.0, 90.0), 0),
            (TileAddress(0, 0, 1, 1),),
        )
        addresses = select_tile_addresses((-180.0, 0.0, 0.0, 90.0), 1)
        self.assertEqual(
            addresses,
            (
                TileAddress(1, 0, 0, 0),
                TileAddress(1, 0, 1, 1),
            ),
        )
        clipped = select_tile_addresses((-200.0, -100.0, -179.0, 100.0), 1)
        self.assertTrue(clipped)
        self.assertTrue(all(0 <= item.row < 2 for item in clipped))
        self.assertTrue(all(0 <= item.request_column < 4 for item in clipped))

    def test_antimeridian_columns_wrap_in_display_order(self) -> None:
        addresses = select_tile_addresses((170.0, -10.0, -170.0, 10.0), 1)

        self.assertEqual(
            [item.display_column for item in addresses],
            [3, 4, 3, 4],
        )
        self.assertEqual(
            [item.request_column for item in addresses],
            [3, 0, 3, 0],
        )
        self.assertEqual([item.row for item in addresses], [0, 0, 1, 1])
        self.assertEqual(len({(item.row, item.display_column) for item in addresses}), 4)

    def test_adaptive_projected_extent_meets_source_pixel_bound(self) -> None:
        class CurvedTransformer:
            @staticmethod
            def transform(x_value: object, y_value: object) -> tuple[object, object]:
                x = np.asarray(x_value)
                y = np.asarray(y_value)
                return x, y + 10.0 * x * x

        source_resolution = 0.01
        result = sample_projected_perimeter(
            _view(xlim=(-1.0, 1.0), ylim=(-1.0, 1.0)),
            source_resolution=source_resolution,
            transformer=CurvedTransformer(),  # type: ignore[arg-type]
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertLessEqual(
            result.maximum_midpoint_deviation,
            0.25 * source_resolution + 1e-15,
        )
        self.assertLess(result.west, result.east)
        self.assertLess(result.south, result.north)
        self.assertIsNone(
            sample_projected_perimeter(
                _view(xlim=(-1.0, 1.0), ylim=(-1.0, 1.0)),
                source_resolution=source_resolution,
                transformer=CurvedTransformer(),  # type: ignore[arg-type]
                max_depth=0,
            )
        )

    def test_ground_resolution_lod_at_equator_and_high_latitude(self) -> None:
        service = _service()
        geod = Geod(ellps="WGS84")
        for latitude in (0.0, 60.0):
            with self.subTest(latitude=latitude):
                view = _view(
                    xlim=(-0.05, 0.05),
                    ylim=(latitude - 0.05, latitude + 0.05),
                    pixel_width=1000,
                    pixel_height=1000,
                )
                chosen = select_lod(service, view)
                requested_x = abs(
                    geod.inv(0.0, latitude, 0.0001, latitude)[2]
                )
                requested_y = abs(
                    geod.inv(0.0, latitude, 0.0, latitude + 0.0001)[2]
                )
                expected = 22
                for level, resolution in enumerate(service.lod_resolutions):
                    service_x = abs(
                        geod.inv(
                            0.0,
                            latitude,
                            resolution,
                            latitude,
                        )[2]
                    )
                    service_y = abs(
                        geod.inv(
                            0.0,
                            latitude,
                            0.0,
                            latitude + resolution,
                        )[2]
                    )
                    if (
                        service_x <= 1.25 * requested_x
                        and service_y <= 1.25 * requested_y
                    ):
                        expected = level
                        break
                self.assertEqual(chosen, expected)

    def test_invalid_extent_and_resource_caps_fail_safe(self) -> None:
        invalid_limits = [
            ((math.nan, 1.0), (-1.0, 1.0)),
            ((-1.0, math.inf), (-1.0, 1.0)),
            ((1.0, 1.0), (-1.0, 1.0)),
            ((-1.0, 1.0), (2.0, 2.0)),
        ]
        for xlim, ylim in invalid_limits:
            with self.subTest(xlim=xlim, ylim=ylim):
                view = _view(xlim=xlim, ylim=ylim)
                self.assertIsNone(sample_projected_perimeter(view))
                self.assertIsNone(select_lod(_service(), view))

        self.assertEqual(select_tile_addresses((0, 0, 0, 1), 10), ())
        self.assertEqual(select_tile_addresses((0, 0, math.inf, 1), 10), ())
        self.assertEqual(select_tile_addresses((-180, -90, 181, 90), 0), ())

        dimensions = basemap._bounded_output_dimensions(
            _view(pixel_width=100_000, pixel_height=80_000)
        )
        self.assertIsNotNone(dimensions)
        assert dimensions is not None
        self.assertLessEqual(max(dimensions), basemap.MAX_OUTPUT_DIMENSION)
        self.assertLessEqual(
            dimensions[0] * dimensions[1],
            basemap.MAX_OUTPUT_PIXELS,
        )

        bounded_request = basemap._prepare_view_request(
            _service(),
            _view(
                xlim=(-179.0, 179.0),
                ylim=(-89.0, 89.0),
                pixel_width=10_000,
                pixel_height=8_000,
            ),
        )
        self.assertIsNotNone(bounded_request)
        assert bounded_request is not None
        self.assertIn(bounded_request.level, range(23))
        selected_resolution = _service().lod_resolutions[
            bounded_request.level
        ]
        self.assertLessEqual(
            bounded_request.padded_extent[0],
            bounded_request.extent.west - selected_resolution,
        )
        self.assertGreaterEqual(
            bounded_request.padded_extent[2],
            bounded_request.extent.east + selected_resolution,
        )
        self.assertLessEqual(
            len(bounded_request.addresses),
            basemap.MAX_TILES_PER_VIEW,
        )
        self.assertLessEqual(
            max(bounded_request.output_dimensions),
            basemap.MAX_OUTPUT_DIMENSION,
        )
        self.assertLessEqual(
            math.prod(bounded_request.output_dimensions),
            basemap.MAX_OUTPUT_PIXELS,
        )


class TileCacheTests(TestCase):
    def test_lru_count_byte_immutability_and_clear(self) -> None:
        first = np.full((2, 2, 3), 1, dtype=np.uint8)
        second = np.full((2, 2, 3), 2, dtype=np.uint8)
        third = np.full((2, 2, 3), 3, dtype=np.uint8)
        cache = MemoryTileCache(max_items=2, max_bytes=24)

        self.assertTrue(cache.put("first", first))
        self.assertTrue(cache.put("second", second))
        hit = cache.get("first")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertFalse(hit.flags.writeable)
        self.assertEqual(cache.keys, ("second", "first"))
        first[:] = 99
        self.assertTrue(np.all(cache.get("first") == 1))

        self.assertTrue(cache.put("third", third))
        self.assertEqual(cache.keys, ("first", "third"))
        self.assertIsNone(cache.get("second"))
        self.assertEqual(cache.item_count, 2)
        self.assertEqual(cache.decoded_bytes, 24)

        oversized = np.zeros((3, 3, 3), dtype=np.uint8)
        old_keys = cache.keys
        old_bytes = cache.decoded_bytes
        self.assertFalse(cache.put("first", oversized))
        self.assertEqual(cache.keys, old_keys)
        self.assertEqual(cache.decoded_bytes, old_bytes)
        self.assertTrue(np.all(cache.get("first") == 1))

        replacement = np.full((1, 2, 3), 7, dtype=np.uint8)
        self.assertTrue(cache.put("first", replacement))
        self.assertEqual(cache.item_count, 2)
        self.assertEqual(cache.decoded_bytes, 18)
        self.assertEqual(cache.keys[-1], "first")
        self.assertTrue(np.all(cache.get("first") == 7))

        byte_cache = MemoryTileCache(max_items=10, max_bytes=20)
        self.assertTrue(byte_cache.put("a", first))
        self.assertTrue(byte_cache.put("b", second))
        self.assertEqual(byte_cache.keys, ("b",))
        self.assertLessEqual(byte_cache.decoded_bytes, 20)

        class RecordingLock:
            def __init__(self) -> None:
                self._lock = threading.RLock()
                self.acquisitions: list[str] = []

            def __enter__(self) -> "RecordingLock":
                self._lock.acquire()
                self.acquisitions.append(threading.current_thread().name)
                return self

            def __exit__(self, *_args: object) -> None:
                self._lock.release()

        recording_lock = RecordingLock()
        race_cache = MemoryTileCache(
            max_items=2,
            max_bytes=100,
            lock=recording_lock,  # type: ignore[arg-type]
        )
        barrier = threading.Barrier(3)
        writer_values = {"writer-11": 11, "writer-22": 22}

        def writer(value: int) -> None:
            candidate = np.full((2, 2, 3), value, dtype=np.uint8)
            barrier.wait()
            self.assertTrue(race_cache.put("shared", candidate))

        threads = [
            threading.Thread(target=writer, args=(11,), name="writer-11"),
            threading.Thread(target=writer, args=(22,), name="writer-22"),
        ]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(2.0)
            self.assertFalse(thread.is_alive())
        writer_acquisitions = [
            name
            for name in recording_lock.acquisitions
            if name in writer_values
        ]
        self.assertEqual(len(writer_acquisitions), 2)
        expected_final = writer_values[writer_acquisitions[-1]]
        self.assertEqual(race_cache.item_count, 1)
        self.assertEqual(race_cache.decoded_bytes, 12)
        self.assertTrue(np.all(race_cache.get("shared") == expected_final))

        cache.clear()
        self.assertEqual(cache.item_count, 0)
        self.assertEqual(cache.decoded_bytes, 0)
        self.assertEqual(cache.keys, ())

    def test_cache_never_uses_filesystem(self) -> None:
        cache = MemoryTileCache(max_items=1, max_bytes=16)
        tile = np.ones((2, 2, 3), dtype=np.uint8)

        with (
            patch.object(builtins, "open") as open_mock,
            patch("tempfile.mkstemp") as mkstemp,
            patch("tempfile.NamedTemporaryFile") as named_temp,
            patch.object(Path, "write_bytes") as write_bytes,
            patch.object(Path, "write_text") as write_text,
        ):
            self.assertTrue(cache.put("a", tile))
            self.assertIsNotNone(cache.get("a"))
            self.assertTrue(cache.put("b", tile))
            cache.clear()

        open_mock.assert_not_called()
        mkstemp.assert_not_called()
        named_temp.assert_not_called()
        write_bytes.assert_not_called()
        write_text.assert_not_called()


class RasterWarpTests(TestCase):
    def test_identity_wgs84_orientation_and_signed_extents(self) -> None:
        address = TileAddress(0, 0, 0, 0)
        mosaic = assemble_tile_mosaic((address,), {address: _gradient_tile()}, 0)
        self.assertIsNotNone(mosaic)
        assert mosaic is not None

        for invert_x in (False, True):
            for invert_y in (False, True):
                with self.subTest(invert_x=invert_x, invert_y=invert_y):
                    xlim = (-170.0, -10.0)
                    ylim = (-80.0, 80.0)
                    if invert_x:
                        xlim = xlim[::-1]
                    if invert_y:
                        ylim = ylim[::-1]
                    warped = warp_mosaic_to_projected_view(
                        mosaic,
                        _view(
                            xlim=xlim,
                            ylim=ylim,
                            pixel_width=64,
                            pixel_height=64,
                        ),
                    )
                    self.assertIsNotNone(warped)
                    assert warped is not None
                    self.assertEqual(
                        warped.extent,
                        (xlim[0], xlim[1], ylim[0], ylim[1]),
                    )
                    rgba = warped.rgba
                    self.assertTrue(np.all(rgba[:, :, 3] >= 254))
                    left_red = float(np.mean(rgba[:, 0, 0]))
                    right_red = float(np.mean(rgba[:, -1, 0]))
                    top_green = float(np.mean(rgba[0, :, 1]))
                    bottom_green = float(np.mean(rgba[-1, :, 1]))
                    self.assertEqual(left_red > right_red, invert_x)
                    self.assertEqual(top_green > bottom_green, invert_y)

    def test_projected_utm_control_point_accuracy(self) -> None:
        fixtures = [
            (32615, -93.0, 45.04),
            (32755, 147.0, -34.96),
        ]
        for epsg, seed_longitude, seed_latitude in fixtures:
            with self.subTest(epsg=epsg):
                level = 10
                seed_address = select_tile_addresses(
                    (
                        seed_longitude - 1e-6,
                        seed_latitude - 1e-6,
                        seed_longitude + 1e-6,
                        seed_latitude + 1e-6,
                    ),
                    level,
                )[0]
                longitude = (
                    -180.0
                    + (seed_address.display_column + 0.5) * tile_span(level)
                )
                latitude = (
                    90.0 - (seed_address.row + 0.5) * tile_span(level)
                )
                address = select_tile_addresses(
                    (
                        longitude - 1e-6,
                        latitude - 1e-6,
                        longitude + 1e-6,
                        latitude + 1e-6,
                    ),
                    level,
                )[0]
                mosaic = assemble_tile_mosaic(
                    (address,),
                    {address: _gradient_tile()},
                    level,
                    unwrap_reference=longitude,
                )
                self.assertIsNotNone(mosaic)
                assert mosaic is not None
                forward = Transformer.from_crs(
                    4326,
                    epsg,
                    always_xy=True,
                )
                inverse = Transformer.from_crs(
                    epsg,
                    4326,
                    always_xy=True,
                )
                center_x, center_y = forward.transform(longitude, latitude)
                view = _view(
                    epsg=epsg,
                    xlim=(center_x - 3_000.0, center_x + 3_000.0),
                    ylim=(center_y - 3_000.0, center_y + 3_000.0),
                    pixel_width=101,
                    pixel_height=101,
                )
                warped = warp_mosaic_to_projected_view(mosaic, view)
                self.assertIsNotNone(warped)
                assert warped is not None
                self.assertEqual(
                    warped.extent,
                    (
                        view.xlim[0],
                        view.xlim[1],
                        view.ylim[0],
                        view.ylim[1],
                    ),
                )
                rgba = warped.rgba

                errors: list[float] = []
                control_pixels = (5, 20, 35, 50, 65, 80, 95)
                for output_row in control_pixels:
                    for output_column in control_pixels:
                        x_value = view.xlim[0] + (output_column + 0.5) * (
                            (view.xlim[1] - view.xlim[0]) / view.pixel_width
                        )
                        y_value = view.ylim[1] + (output_row + 0.5) * (
                            (view.ylim[0] - view.ylim[1]) / view.pixel_height
                        )
                        test_lon, test_lat = inverse.transform(x_value, y_value)
                        expected_column = (
                            (test_lon - mosaic.west) / mosaic.resolution - 0.5
                        )
                        expected_row = (
                            (mosaic.north - test_lat) / mosaic.resolution - 0.5
                        )
                        error = math.hypot(
                            float(rgba[output_row, output_column, 0])
                            - expected_column,
                            float(rgba[output_row, output_column, 1])
                            - expected_row,
                        )
                        errors.append(error)
                        self.assertGreaterEqual(
                            int(rgba[output_row, output_column, 3]),
                            254,
                        )
                self.assertLessEqual(max(errors), 0.75)
                self.assertLessEqual(
                    math.sqrt(sum(value * value for value in errors) / len(errors)),
                    0.5,
                )

    def test_bilinear_rgb_alpha_and_nonfinite_masks(self) -> None:
        rgb = np.array(
            [
                [[0, 0, 0], [100, 0, 0]],
                [[0, 100, 0], [100, 100, 100]],
            ],
            dtype=np.uint8,
        )
        validity = np.array([[1.0, 1.0], [1.0, 0.0]], dtype=np.float32)
        mosaic = basemap._TileMosaic(
            rgb=rgb,
            validity=validity,
            west=0.0,
            north=2.0,
            resolution=1.0,
            unwrap_reference=1.0,
            addresses=(TileAddress(0, 0, 1, 1),),
            valid_tile_count=1,
            missing_tile_count=0,
        )
        warped = warp_mosaic_to_projected_view(
            mosaic,
            _view(
                xlim=(0.5, 1.5),
                ylim=(0.5, 1.5),
                pixel_width=2,
                pixel_height=2,
            ),
        )
        self.assertIsNotNone(warped)
        assert warped is not None
        self.assertEqual(warped.extent, (0.5, 1.5, 0.5, 1.5))
        rgba = warped.rgba
        np.testing.assert_allclose(
            rgba[:, :, :3],
            np.array(
                [
                    [[25, 25, 6], [75, 25, 19]],
                    [[25, 75, 19], [75, 75, 56]],
                ],
                dtype=np.uint8,
            ),
            atol=1,
        )
        np.testing.assert_allclose(
            rgba[:, :, 3],
            np.array([[239, 207], [207, 112]], dtype=np.uint8),
            atol=1,
        )

        class NonfiniteTransformer:
            @staticmethod
            def transform(x_value: object, y_value: object) -> tuple[np.ndarray, np.ndarray]:
                longitude = np.array(x_value, dtype=float, copy=True)
                latitude = np.array(y_value, dtype=float, copy=True)
                longitude[:, 0] = np.nan
                return longitude, latitude

        masked_warp = warp_mosaic_to_projected_view(
            mosaic,
            _view(
                xlim=(0.5, 1.5),
                ylim=(0.5, 1.5),
                pixel_width=2,
                pixel_height=2,
            ),
            transformer=NonfiniteTransformer(),  # type: ignore[arg-type]
        )
        self.assertIsNotNone(masked_warp)
        assert masked_warp is not None
        masked = masked_warp.rgba
        self.assertTrue(np.all(masked[:, 0, 3] == 0))
        self.assertTrue(np.all(masked[:, 1, 3] > 0))

        outside_warp = warp_mosaic_to_projected_view(
            mosaic,
            _view(
                xlim=(-5.0, -3.0),
                ylim=(0.5, 1.5),
                pixel_width=2,
                pixel_height=2,
            ),
        )
        self.assertIsNotNone(outside_warp)
        assert outside_warp is not None
        outside = outside_warp.rgba
        self.assertTrue(np.all(outside[:, :, 3] == 0))

    def test_antimeridian_mosaic_has_no_flip_gap_or_cap_escape(self) -> None:
        addresses = select_tile_addresses((170.0, 1.0, -170.0, 89.0), 1)
        self.assertEqual(len(addresses), 2)
        tiles = {
            addresses[0]: _solid_tile(40),
            addresses[1]: _solid_tile(220),
        }
        mosaic = assemble_tile_mosaic(
            addresses,
            tiles,
            1,
            unwrap_reference=180.0,
        )
        self.assertIsNotNone(mosaic)
        assert mosaic is not None
        warped = warp_mosaic_to_projected_view(
            mosaic,
            _view(
                xlim=(170.0, 190.0),
                ylim=(10.0, 80.0),
                pixel_width=400,
                pixel_height=200,
            ),
        )
        self.assertIsNotNone(warped)
        assert warped is not None
        self.assertEqual(warped.extent, (170.0, 190.0, 10.0, 80.0))
        rgba = warped.rgba
        self.assertEqual(rgba.shape, (200, 400, 4))
        self.assertTrue(np.all(rgba[:, :, 3] >= 254))
        center_row = rgba.shape[0] // 2
        self.assertLess(int(rgba[center_row, 10, 0]), 100)
        self.assertGreater(int(rgba[center_row, -10, 0]), 150)
        self.assertTrue(np.all(rgba[center_row, 190:210, 3] >= 254))
        self.assertLessEqual(rgba.shape[0] * rgba.shape[1], basemap.MAX_OUTPUT_PIXELS)
        self.assertLessEqual(max(rgba.shape[:2]), basemap.MAX_OUTPUT_DIMENSION)
        self.assertLessEqual(len(addresses), basemap.MAX_TILES_PER_VIEW)


class BasemapHttpTests(TestCase):
    def test_fixed_https_url_user_agent_and_redirect_policy(self) -> None:
        calls: list[tuple[str, str | None, float]] = []

        def opener(request: object, *, timeout: float) -> _Response:
            calls.append(
                (
                    request.full_url,  # type: ignore[attr-defined]
                    request.get_header("User-agent"),  # type: ignore[attr-defined]
                    timeout,
                )
            )
            return _Response(
                b"ok",
                url=request.full_url,  # type: ignore[attr-defined]
                content_type="image/jpeg",
            )

        client, _active_view, context = _registered_client(opener=opener)
        address = TileAddress(15, 8283, 16493, 16493)
        response = client._request_bytes(
            context,
            url=basemap._tile_url(address),
            maximum_bytes=10,
            purpose="tile",
        )
        self.assertIsInstance(response, basemap._HttpBytes)
        self.assertEqual(
            calls,
            [
                (
                    f"{basemap.SERVICE_ROOT}/tile/15/8283/16493",
                    basemap.USER_AGENT,
                    basemap.REQUEST_TIMEOUT_SECONDS,
                )
            ],
        )

        for forbidden in (
            basemap.SERVICE_ROOT.replace("https://", "http://"),
            "https://example.invalid/arcgis/tile/1/2/3",
            "https://user@wi.maptiles.arcgis.com/arcgis",
            "https://wi.maptiles.arcgis.com:444/arcgis",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertFalse(basemap._url_is_allowed(forbidden))
                problem = client._request_bytes(
                    context,
                    url=forbidden,
                    maximum_bytes=10,
                    purpose="tile",
                )
                self.assertIsInstance(problem, basemap._HttpProblem)
        self.assertEqual(len(calls), 1)

        handler = basemap._StrictRedirectHandler()
        for forbidden_redirect in (
            "http://wi.maptiles.arcgis.com/arcgis",
            "https://example.invalid/arcgis",
        ):
            with self.subTest(redirect=forbidden_redirect):
                with self.assertRaises(URLError):
                    handler.redirect_request(
                        basemap.Request(basemap.METADATA_URL),
                        None,
                        302,
                        "Found",
                        {},
                        forbidden_redirect,
                    )

        off_host_opener = lambda _request, timeout: _Response(
                b"ok",
                url="https://example.invalid/tile",
                content_type="image/jpeg",
            )
        final_client, _view_value, final_context = _registered_client(
            opener=off_host_opener
        )
        final_problem = final_client._request_bytes(
            final_context,
            url=basemap._tile_url(address),
            maximum_bytes=10,
            purpose="tile",
        )
        self.assertIsInstance(final_problem, basemap._HttpProblem)
        self.assertEqual(final_problem.kind, "url_policy")
        client.shutdown()
        final_client.shutdown()

    def test_retry_matrix_and_cancel_aware_delay(self) -> None:
        tile_body = _encoded_jpeg()
        address = TileAddress(15, 8283, 16493, 16493)
        retryable: list[tuple[str, object]] = [
            ("timeout", TimeoutError()),
            ("socket timeout", socket.timeout()),
            ("HTTP 408", 408),
            ("HTTP 429", 429),
            ("HTTP 500", 500),
            ("HTTP 503", 503),
            ("HTTP 599", 599),
            ("URL TimeoutError", URLError(TimeoutError())),
            ("URL ConnectionError", URLError(ConnectionError())),
            ("URL socket.timeout", URLError(socket.timeout())),
            ("URL socket.gaierror", URLError(socket.gaierror())),
        ]
        for name, first_outcome in retryable:
            with self.subTest(retryable=name):
                calls = 0
                waits: list[tuple[float, bool]] = []

                def opener(
                    request: object,
                    *,
                    timeout: float,
                    outcome: object = first_outcome,
                ) -> _Response:
                    del timeout
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        if isinstance(outcome, BaseException):
                            raise outcome
                        return _Response(
                            b"",
                            url=request.full_url,  # type: ignore[attr-defined]
                            status=int(outcome),
                            content_type="image/jpeg",
                        )
                    return _Response(
                        tile_body,
                        url=request.full_url,  # type: ignore[attr-defined]
                        content_type="image/jpeg",
                    )

                def retry_wait(
                    seconds: float,
                    predicate: object,
                ) -> bool:
                    waits.append((seconds, bool(predicate())))  # type: ignore[operator]
                    return True

                client, _active_view, context = _registered_client(
                    opener=opener,
                    retry_wait=retry_wait,
                )
                result = client._fetch_tile(context, address)
                self.assertEqual(result.state, "valid")
                self.assertEqual(calls, 2)
                self.assertEqual(
                    waits,
                    [(basemap.RETRY_DELAY_SECONDS, True)],
                )
                client.shutdown()

        nonretryable: list[tuple[str, object, str]] = [
            ("HTTP 400", 400, "failed"),
            ("HTTP 401", 401, "failed"),
            ("HTTP 403", 403, "failed"),
            ("HTTP 404", 404, "missing"),
            ("HTTP 405", 405, "failed"),
            ("HTTP 410", 410, "failed"),
            ("HTTP 300", 300, "failed"),
            ("URL ValueError", URLError(ValueError()), "failed"),
            ("arbitrary transport", RuntimeError(), "failed"),
        ]
        for name, outcome, expected_state in nonretryable:
            with self.subTest(nonretryable=name):
                opener_calls = 0
                wait_calls = 0

                def opener(
                    request: object,
                    *,
                    timeout: float,
                    result: object = outcome,
                ) -> _Response:
                    del timeout
                    nonlocal opener_calls
                    opener_calls += 1
                    if isinstance(result, BaseException):
                        raise result
                    return _Response(
                        b"",
                        url=request.full_url,  # type: ignore[attr-defined]
                        status=int(result),
                        content_type="image/jpeg",
                    )

                def no_retry_wait(
                    _seconds: float,
                    _predicate: object,
                ) -> bool:
                    nonlocal wait_calls
                    wait_calls += 1
                    return True

                client, _active_view, context = _registered_client(
                    opener=opener,
                    retry_wait=no_retry_wait,
                )
                self.assertEqual(
                    client._fetch_tile(context, address).state,
                    expected_state,
                )
                self.assertEqual(opener_calls, 1)
                self.assertEqual(wait_calls, 0)
                client.shutdown()

        for cancellation in ("newer submit", "cancel surface", "shutdown"):
            with self.subTest(cancellation=cancellation):
                calls = 0
                holder: dict[str, object] = {}

                def opener(request: object, *, timeout: float) -> _Response:
                    del timeout
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        raise TimeoutError
                    return _Response(
                        tile_body,
                        url=request.full_url,  # type: ignore[attr-defined]
                        content_type="image/jpeg",
                    )

                def cancel_during_wait(
                    seconds: float,
                    predicate: object,
                ) -> bool:
                    self.assertEqual(seconds, 0.250)
                    client = holder["client"]
                    if cancellation == "newer submit":
                        with client._lock:  # type: ignore[attr-defined]
                            client._latest_generation["main"] = 2  # type: ignore[attr-defined]
                            client._slots["main"].condition.notify_all()  # type: ignore[attr-defined]
                    elif cancellation == "cancel surface":
                        client.cancel_surface("main", 2)  # type: ignore[attr-defined]
                    else:
                        client.shutdown()  # type: ignore[attr-defined]
                    self.assertFalse(predicate())  # type: ignore[operator]
                    return False

                client, _active_view, context = _registered_client(
                    opener=opener,
                    retry_wait=cancel_during_wait,
                )
                holder["client"] = client
                self.assertNotEqual(
                    client._fetch_tile(context, address).state,
                    "valid",
                )
                self.assertEqual(calls, 1)
                client.shutdown()

    def test_metadata_failure_cooldown_and_session_latch(self) -> None:
        clock = [100.0]
        metadata_body = json.dumps(_metadata_fixture()).encode("utf-8")
        calls = 0

        def transient_then_ready(
            request: object,
            *,
            timeout: float,
        ) -> _Response:
            del timeout
            nonlocal calls
            calls += 1
            if calls == 1:
                raise TimeoutError
            return _Response(
                metadata_body,
                url=request.full_url,  # type: ignore[attr-defined]
                content_type="application/json",
            )

        client, active_view, context = _registered_client(
            opener=transient_then_ready,
            monotonic_clock=lambda: clock[0],
        )
        service, failure = client._get_service(active_view, context)
        self.assertIsNone(service)
        self.assertIsInstance(failure, BasemapFailure)
        self.assertEqual(client.metadata_state, "COOLDOWN")
        self.assertEqual(calls, 1)

        clock[0] = 129.999
        service, failure = client._get_service(active_view, context)
        self.assertIsNone(service)
        self.assertIsInstance(failure, BasemapFailure)
        self.assertEqual(calls, 1)

        clock[0] = 130.0
        service, failure = client._get_service(active_view, context)
        self.assertIsInstance(service, ArcGisTileService)
        self.assertIsNone(failure)
        self.assertEqual(calls, 2)
        self.assertEqual(client.metadata_state, "READY")
        client.reset_transient_metadata_failure()
        self.assertEqual(client.metadata_state, "READY")
        client.shutdown()

        transient_statuses = [408, 429, *range(500, 600)]
        for status in transient_statuses:
            with self.subTest(transient_status=status):
                problem = basemap._status_problem(status)
                self.assertTrue(problem.retryable)
                self.assertFalse(problem.permanent)
        for error in (
            TimeoutError(),
            ConnectionError(),
            socket.timeout(),
            URLError(TimeoutError()),
            URLError(ConnectionError()),
            URLError(socket.timeout()),
            URLError(socket.gaierror()),
        ):
            with self.subTest(transient_error=type(error).__name__):
                self.assertTrue(basemap._exception_problem(error).retryable)

        permanent_statuses = [400, 401, 403, 404, 405, 410, 499, 600]
        for status in permanent_statuses:
            with self.subTest(permanent_status=status):
                problem = basemap._status_problem(status)
                self.assertFalse(problem.retryable)
                self.assertTrue(problem.permanent)
        self.assertFalse(
            basemap._exception_problem(URLError(ValueError())).retryable
        )

        metadata_outcomes: list[tuple[str, object, str]] = [
            (
                "malformed JSON",
                _Response(
                    b"{truncated",
                    url=basemap.METADATA_URL,
                    content_type="application/json",
                ),
                "COOLDOWN",
            ),
            (
                "oversized body",
                _Response(
                    b"x" * (basemap.MAX_METADATA_BYTES + 1),
                    url=basemap.METADATA_URL,
                    content_type="application/json",
                ),
                "INCOMPATIBLE",
            ),
            (
                "explicit non-json unparseable",
                _Response(
                    b"not json",
                    url=basemap.METADATA_URL,
                    content_type="text/html",
                ),
                "INCOMPATIBLE",
            ),
            (
                "well-formed incompatible schema",
                _Response(
                    b'{"singleFusedMapCache": false}',
                    url=basemap.METADATA_URL,
                    content_type="application/json",
                ),
                "INCOMPATIBLE",
            ),
        ]
        for name, outcome, expected_state in metadata_outcomes:
            with self.subTest(metadata_outcome=name):
                outcome_calls = 0

                def outcome_opener(
                    _request: object,
                    *,
                    timeout: float,
                    response: object = outcome,
                ) -> object:
                    del timeout
                    nonlocal outcome_calls
                    outcome_calls += 1
                    return response

                tested, tested_view, tested_context = _registered_client(
                    opener=outcome_opener,
                    monotonic_clock=lambda: 0.0,
                )
                tested_service, tested_failure = tested._get_service(
                    tested_view,
                    tested_context,
                )
                self.assertIsNone(tested_service)
                self.assertIsInstance(tested_failure, BasemapFailure)
                self.assertEqual(tested.metadata_state, expected_state)
                before = outcome_calls
                tested._get_service(tested_view, tested_context)
                self.assertEqual(outcome_calls, before)
                tested.reset_transient_metadata_failure()
                self.assertEqual(
                    tested.metadata_state,
                    "EMPTY" if expected_state == "COOLDOWN" else "INCOMPATIBLE",
                )
                self.assertEqual(outcome_calls, before)
                tested.shutdown()

        valid_non_json, valid_view, valid_context = _registered_client(
            opener=lambda request, timeout: _Response(
                metadata_body,
                url=request.full_url,
                content_type="text/plain",
            )
        )
        valid_service, valid_failure = valid_non_json._get_service(
            valid_view,
            valid_context,
        )
        self.assertIsInstance(valid_service, ArcGisTileService)
        self.assertIsNone(valid_failure)
        valid_non_json.shutdown()

        parser_client, parser_view, parser_context = _registered_client(
            metadata_fixture={"singleFusedMapCache": False}
        )
        _service_value, parser_failure = parser_client._get_service(
            parser_view,
            parser_context,
        )
        self.assertEqual(
            (
                parser_failure.surface_id,
                parser_failure.generation,
                parser_failure.result_generation,
            ),
            (
                parser_view.surface_id,
                parser_view.generation,
                parser_view.result_generation,
            ),
        )
        parser_client.shutdown()

        entered = threading.Event()
        release = threading.Event()

        def blocking_metadata(
            request: object,
            *,
            timeout: float,
        ) -> _Response:
            del timeout
            entered.set()
            release.wait(2.0)
            return _Response(
                metadata_body,
                url=request.full_url,  # type: ignore[attr-defined]
                content_type="application/json",
            )

        stale_client, stale_view, stale_context = _registered_client(
            opener=blocking_metadata
        )
        stale_result: list[tuple[object, object]] = []
        thread = threading.Thread(
            target=lambda: stale_result.append(
                stale_client._get_service(stale_view, stale_context)
            )
        )
        thread.start()
        self.assertTrue(entered.wait(1.0))
        stale_client.cancel_surface("main", 2)
        release.set()
        thread.join(2.0)
        self.assertFalse(thread.is_alive())
        self.assertEqual(stale_client.metadata_state, "EMPTY")
        self.assertEqual(stale_result, [(None, None)])
        stale_client.shutdown()

    def test_response_limits_content_and_decoded_shape(self) -> None:
        header = _jpeg_header()
        grayscale = np.arange(256 * 256, dtype=np.uint8).reshape(256, 256)
        one_channel = grayscale[:, :, np.newaxis]
        rgb = np.repeat(one_channel, 3, axis=2)
        rgba = np.concatenate(
            (rgb, np.full((256, 256, 1), 201, dtype=np.uint8)),
            axis=2,
        )
        for name, decoded, expected in (
            ("2-D grayscale", grayscale, rgb),
            ("1-channel grayscale", one_channel, rgb),
            ("RGB", rgb, rgb),
            ("RGBA", rgba, rgb),
        ):
            with self.subTest(normalization=name):
                result = decode_jpeg_tile(
                    header,
                    decoder=lambda *_args, value=decoded, **_kwargs: value,
                )
                self.assertIsNotNone(result)
                assert result is not None
                np.testing.assert_array_equal(result, expected)
                self.assertEqual(result.shape, (256, 256, 3))
                self.assertEqual(result.dtype, np.uint8)
                self.assertTrue(result.flags.c_contiguous)
                self.assertFalse(result.flags.writeable)

        floats = np.zeros((256, 256, 3), dtype=np.float64)
        floats[0, 0] = (-1.0, 0.5, 2.0)
        normalized = decode_jpeg_tile(
            header,
            decoder=lambda *_args, **_kwargs: floats,
        )
        self.assertIsNotNone(normalized)
        assert normalized is not None
        np.testing.assert_array_equal(
            normalized[0, 0],
            np.array([0, 128, 255], dtype=np.uint8),
        )

        invalid_arrays = [
            np.zeros((255, 256, 3), dtype=np.uint8),
            np.zeros((256, 255, 3), dtype=np.uint8),
            np.zeros((256, 256, 2), dtype=np.uint8),
            np.zeros((256, 256, 5), dtype=np.uint8),
            np.zeros((256, 256, 3), dtype=np.int16),
        ]
        nonfinite = np.zeros((256, 256, 3), dtype=float)
        nonfinite[0, 0, 0] = np.nan
        invalid_arrays.append(nonfinite)
        for invalid in invalid_arrays:
            with self.subTest(shape=invalid.shape, dtype=str(invalid.dtype)):
                self.assertIsNone(
                    decode_jpeg_tile(
                        header,
                        decoder=lambda *_args, value=invalid, **_kwargs: value,
                    )
                )

        corrupt_decoder = Mock(return_value=rgb)
        self.assertIsNone(decode_jpeg_tile(b"not-a-jpeg", decoder=corrupt_decoder))
        corrupt_decoder.assert_not_called()

        cache = MemoryTileCache()
        address = TileAddress(15, 8283, 16493, 16493)
        unsafe_responses = [
            _Response(
                _encoded_jpeg(),
                url=basemap._tile_url(address),
                content_type="image/png",
            ),
            _Response(
                b"x" * (basemap.MAX_TILE_BYTES + 1),
                url=basemap._tile_url(address),
                content_type="image/jpeg",
            ),
            _Response(
                b"corrupt",
                url=basemap._tile_url(address),
                content_type="image/jpeg",
            ),
        ]
        for response in unsafe_responses:
            with self.subTest(content_type=response.headers.get_content_type()):
                client, _active_view, context = _registered_client(
                    opener=lambda _request, timeout, value=response: value,
                    cache=cache,
                )
                self.assertEqual(
                    client._fetch_tile(context, address).state,
                    "failed",
                )
                self.assertEqual(cache.item_count, 0)
                client.shutdown()

    def test_jpeg_header_dimension_guard_runs_before_decoder(self) -> None:
        decoded = np.zeros((256, 256, 3), dtype=np.uint8)
        for marker in sorted(basemap._SOF_MARKERS):
            with self.subTest(valid_sof=hex(marker)):
                decoder = Mock(return_value=decoded)
                self.assertIsNotNone(
                    decode_jpeg_tile(
                        _jpeg_header(marker=marker),
                        decoder=decoder,
                    )
                )
                decoder.assert_called_once()

        for prefix in (
            b"",
            b"\xff\x01",
            b"\xff\xd0",
            b"\xff\xd7",
        ):
            with self.subTest(standalone=prefix.hex()):
                decoder = Mock(return_value=decoded)
                data = b"\xff\xd8" + prefix + _jpeg_header()[2:]
                self.assertIsNotNone(decode_jpeg_tile(data, decoder=decoder))
                decoder.assert_called_once()

        app_segment = b"\xff\xe0\x00\x04AB"
        decoder = Mock(return_value=decoded)
        self.assertIsNotNone(
            decode_jpeg_tile(
                b"\xff\xd8" + app_segment + _jpeg_header()[2:],
                decoder=decoder,
            )
        )
        decoder.assert_called_once()

        first_sof = _jpeg_header(tail=b"")[2:]
        contradictory = (
            b"\xff\xd8"
            + first_sof
            + _jpeg_header(width=255)[2:]
        )
        invalid_headers = [
            b"\x00\xd8\xff\xd9",
            b"\xff\xd8\xff\xe0\x00\x01",
            b"\xff\xd8\xff\xe0\xff\xff",
            b"\xff\xd8\xff\xda\x00\x02",
            b"\xff\xd8\xff\xd9",
            b"\xff\xd8\xff\xe0\x00\x04AB\xff\xd9",
            _jpeg_header(width=255),
            _jpeg_header(height=255),
            _jpeg_header(width=65535),
            _jpeg_header(components=0),
            _jpeg_header(components=5),
            _jpeg_header()[:-3],
            contradictory,
        ]
        for index, invalid in enumerate(invalid_headers):
            with self.subTest(invalid_header=index):
                decoder = Mock(return_value=decoded)
                self.assertIsNone(decode_jpeg_tile(invalid, decoder=decoder))
                decoder.assert_not_called()

    def test_missing_tile_and_consecutive_failure_abort(self) -> None:
        addresses = tuple(
            TileAddress(10, 10, column, column)
            for column in range(5)
        )
        request = SimpleNamespace(
            addresses=addresses,
            level=10,
            extent=SimpleNamespace(unwrap_reference=0.0),
        )
        service = _service()
        rgba = np.zeros((16, 16, 4), dtype=np.uint8)
        rgba[:, :, 3] = 0

        sequences = [
            (
                "404 resets failure run",
                ["failed", "missing", "failed", "failed", "valid"],
                BasemapFrame,
            ),
            (
                "isolated failures remain partial",
                ["valid", "failed", "valid", "missing", "valid"],
                BasemapFrame,
            ),
            (
                "three consecutive failures abort",
                ["valid", "failed", "failed", "failed", "valid"],
                BasemapFailure,
            ),
        ]
        for name, states, expected_type in sequences:
            with self.subTest(sequence=name):
                client, active_view, context = _registered_client()
                tile = _solid_tile(10)
                fetches = iter(
                    basemap._TileFetch(
                        state,
                        tile if state == "valid" else None,
                    )
                    for state in states
                )
                publications: list[object] = []
                with (
                    patch.object(
                        client,
                        "_get_service",
                        return_value=(service, None),
                    ),
                    patch.object(
                        client,
                        "_fetch_tile",
                        side_effect=lambda *_args: next(fetches),
                    ),
                    patch.object(
                        basemap,
                        "_prepare_view_request",
                        return_value=request,
                    ),
                    patch.object(
                        basemap,
                        "assemble_tile_mosaic",
                        return_value=SimpleNamespace(),
                    ),
                    patch.object(
                        basemap,
                        "warp_mosaic_to_projected_view",
                        return_value=basemap._WarpedRaster(
                            rgba,
                            (
                                active_view.xlim[0],
                                active_view.xlim[1],
                                active_view.ylim[0],
                                active_view.ylim[1],
                            ),
                        ),
                    ),
                    patch.object(
                        client,
                        "_publish",
                        side_effect=publications.append,
                    ),
                ):
                    client._process_view(active_view, context)

                self.assertEqual(len(publications), 1)
                self.assertIsInstance(publications[0], expected_type)
                if isinstance(publications[0], BasemapFrame):
                    frame = publications[0]
                    self.assertEqual(
                        frame.requested_tile_count,
                        frame.valid_tile_count + frame.missing_tile_count,
                    )
                    self.assertGreater(frame.valid_tile_count, 0)
                    self.assertEqual(
                        frame.is_partial,
                        frame.missing_tile_count > 0,
                    )
                    self.assertTrue(np.all(frame.rgba[:, :, 3] == 0))
                client.shutdown()

        complete_client, complete_view, complete_context = _registered_client()
        complete_request = SimpleNamespace(
            addresses=(addresses[0],),
            level=10,
            extent=SimpleNamespace(unwrap_reference=0.0),
        )
        publications: list[object] = []
        with (
            patch.object(
                complete_client,
                "_get_service",
                return_value=(service, None),
            ),
            patch.object(
                complete_client,
                "_fetch_tile",
                return_value=basemap._TileFetch("valid", _solid_tile(1)),
            ),
            patch.object(
                basemap,
                "_prepare_view_request",
                return_value=complete_request,
            ),
            patch.object(
                basemap,
                "assemble_tile_mosaic",
                return_value=SimpleNamespace(),
            ),
            patch.object(
                basemap,
                "warp_mosaic_to_projected_view",
                return_value=basemap._WarpedRaster(
                    rgba,
                    (
                        complete_view.xlim[0],
                        complete_view.xlim[1],
                        complete_view.ylim[0],
                        complete_view.ylim[1],
                    ),
                ),
            ),
            patch.object(
                complete_client,
                "_publish",
                side_effect=publications.append,
            ),
        ):
            complete_client._process_view(complete_view, complete_context)
        self.assertEqual(len(publications), 1)
        self.assertIsInstance(publications[0], BasemapFrame)
        self.assertFalse(publications[0].is_partial)
        self.assertEqual(publications[0].missing_tile_count, 0)
        complete_client.shutdown()


class BasemapWorkerTests(TestCase):
    def test_latest_request_replaces_same_surface_pending_job(self) -> None:
        class DormantThread:
            def __init__(self, *args: object, **kwargs: object) -> None:
                del args, kwargs
                self.started = False

            def start(self) -> None:
                self.started = True

            def is_alive(self) -> bool:
                return self.started

        if ArcGisBasemapClient is None:
            self.fail("ArcGisBasemapClient is unavailable")
        with patch.object(basemap.threading, "Thread", DormantThread):
            client = ArcGisBasemapClient(metadata_fixture=_metadata_fixture())
            first = _view(generation=1)
            client.submit(first)
            with client._lock:
                slot = client._slots["main"]
                old_context = basemap._JobContext(
                    slot_key="main",
                    surface_id="main",
                    generation=1,
                    registration_epoch=slot.registration_epoch,
                    cache_epoch=client.cache_epoch,
                )
            second = _view(generation=2, result_generation=2)
            client.submit(second)

        with client._lock:
            self.assertEqual(client._slots["main"].pending.view, second)
            self.assertEqual(
                client._slots["main"].pending.cache_epoch,
                client.cache_epoch,
            )
            self.assertEqual(client._latest_generation, {"main": 2})
            self.assertEqual(len(client._surface_slots), 1)
        self.assertFalse(client._is_job_current(old_context))
        self.assertIsNone(
            client._reserve_http_attempt(old_context, "metadata")
        )

        cache_before = client._cache.item_count
        publish = Mock()
        with (
            patch.object(client, "_publish", publish),
            patch.object(
                client,
                "_get_service",
                side_effect=AssertionError("stale job reached metadata"),
            ),
        ):
            client._process_view(first, old_context)
        publish.assert_not_called()
        self.assertEqual(client._cache.item_count, cache_before)
        client.shutdown()

    def test_metadata_single_flight_across_surface_slots(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        fixture_calls = 0
        fixture_lock = threading.Lock()

        def blocking_fixture() -> dict[str, object]:
            nonlocal fixture_calls
            with fixture_lock:
                fixture_calls += 1
            entered.set()
            release.wait(2.0)
            return _metadata_fixture()

        if ArcGisBasemapClient is None:
            self.fail("ArcGisBasemapClient is unavailable")
        client = ArcGisBasemapClient(metadata_fixture=blocking_fixture)
        main_view = _view(surface_id="main")
        inspector_view = _view(surface_id="inspector:1")
        main_context = _register_context(client, main_view)
        inspector_context = _register_context(client, inspector_view)
        results: dict[str, tuple[object, object]] = {}
        main_thread = threading.Thread(
            target=lambda: results.setdefault(
                "main",
                client._get_service(main_view, main_context),
            )
        )
        inspector_thread = threading.Thread(
            target=lambda: results.setdefault(
                "inspector",
                client._get_service(inspector_view, inspector_context),
            )
        )
        main_thread.start()
        self.assertTrue(entered.wait(1.0))
        inspector_thread.start()
        _wait_until(lambda: client.metadata_state == "FETCHING")
        lock_acquired = client._lock.acquire(timeout=0.2)
        self.assertTrue(lock_acquired)
        if lock_acquired:
            client._lock.release()
        release.set()
        main_thread.join(2.0)
        inspector_thread.join(2.0)
        self.assertFalse(main_thread.is_alive())
        self.assertFalse(inspector_thread.is_alive())
        self.assertEqual(fixture_calls, 1)
        self.assertEqual(client.metadata_state, "READY")
        self.assertIs(results["main"][0], results["inspector"][0])
        self.assertIsNone(results["main"][1])
        self.assertIsNone(results["inspector"][1])
        client.shutdown()

        canceled_entered = threading.Event()
        canceled_release = threading.Event()
        canceled_calls = 0

        def second_fixture() -> dict[str, object]:
            nonlocal canceled_calls
            canceled_calls += 1
            canceled_entered.set()
            canceled_release.wait(2.0)
            return _metadata_fixture()

        canceled_client = ArcGisBasemapClient(metadata_fixture=second_fixture)
        owner_view = _view(surface_id="main")
        waiter_view = _view(surface_id="inspector:2")
        owner_context = _register_context(canceled_client, owner_view)
        waiter_context = _register_context(canceled_client, waiter_view)
        canceled_results: dict[str, tuple[object, object]] = {}
        owner_thread = threading.Thread(
            target=lambda: canceled_results.setdefault(
                "owner",
                canceled_client._get_service(owner_view, owner_context),
            )
        )
        waiter_thread = threading.Thread(
            target=lambda: canceled_results.setdefault(
                "waiter",
                canceled_client._get_service(waiter_view, waiter_context),
            )
        )
        owner_thread.start()
        self.assertTrue(canceled_entered.wait(1.0))
        waiter_thread.start()
        canceled_client.cancel_surface("inspector:2", 2)
        waiter_thread.join(1.0)
        self.assertFalse(waiter_thread.is_alive())
        self.assertEqual(canceled_results["waiter"], (None, None))
        canceled_release.set()
        owner_thread.join(2.0)
        self.assertFalse(owner_thread.is_alive())
        self.assertEqual(canceled_calls, 1)
        self.assertEqual(canceled_client.metadata_state, "READY")
        canceled_client.shutdown()

    def test_main_and_inspector_slots_do_not_starve_each_other(self) -> None:
        class DormantThread:
            def __init__(self, *args: object, **kwargs: object) -> None:
                del args, kwargs
                self._alive = False

            def start(self) -> None:
                self._alive = True

            def is_alive(self) -> bool:
                return self._alive

        if ArcGisBasemapClient is None:
            self.fail("ArcGisBasemapClient is unavailable")
        with patch.object(basemap.threading, "Thread", DormantThread):
            client = ArcGisBasemapClient(metadata_fixture=_metadata_fixture())
            main = _view(surface_id="main")
            inspector = _view(surface_id="inspector:1")
            client.submit(main)
            client.submit(inspector)

            with client._lock:
                self.assertEqual(client._slots["main"].pending.view, main)
                self.assertEqual(
                    client._slots["inspector"].pending.view,
                    inspector,
                )
                self.assertEqual(len(client._latest_generation), 2)
                old_epoch = client._slots["inspector"].registration_epoch
            old_context = basemap._JobContext(
                slot_key="inspector",
                surface_id="inspector:1",
                generation=1,
                registration_epoch=old_epoch,
                cache_epoch=client.cache_epoch,
            )

            for generation in range(2, 27):
                surface_id = f"inspector:{generation}"
                next_view = _view(
                    surface_id=surface_id,
                    generation=1,
                    result_generation=generation,
                )
                client.submit(next_view)
                with client._lock:
                    self.assertLessEqual(len(client._latest_generation), 2)
                    self.assertLessEqual(len(client._surface_slots), 2)
                    self.assertNotIn(
                        f"inspector:{generation - 1}",
                        client._latest_generation,
                    )
                    self.assertEqual(
                        client._slots["inspector"].surface_id,
                        surface_id,
                    )
                client.deregister_surface(surface_id)
                with client._lock:
                    self.assertEqual(client._latest_generation, {"main": 1})
                    self.assertEqual(client._surface_slots, {"main": "main"})
                    self.assertIsNone(client._slots["inspector"].surface_id)
                    self.assertIsNone(client._slots["inspector"].pending)
                client.deregister_surface(surface_id)

            client.submit(_view(surface_id="not-a-supported-surface"))

        self.assertFalse(client._is_job_current(old_context))
        self.assertIsNone(client._reserve_http_attempt(old_context, "tile"))
        with client._lock:
            self.assertEqual(set(client._slots), {"main", "inspector"})
            self.assertEqual(len(client._surface_slots), 1)
        client.shutdown()

    def test_stale_cancel_checked_through_fetch_and_warp_chunks(self) -> None:
        address = TileAddress(0, 0, 0, 0)
        mosaic = assemble_tile_mosaic(
            (address,),
            {address: _gradient_tile()},
            0,
        )
        self.assertIsNotNone(mosaic)
        assert mosaic is not None
        cancellation_checks = 0
        coordinate_calls = 0
        original_map_coordinates = basemap.map_coordinates

        def cancel_between_rgb_and_alpha() -> bool:
            nonlocal cancellation_checks
            cancellation_checks += 1
            return cancellation_checks >= 2

        def counted_coordinates(*args: object, **kwargs: object) -> np.ndarray:
            nonlocal coordinate_calls
            coordinate_calls += 1
            return original_map_coordinates(*args, **kwargs)

        with patch.object(
            basemap,
            "map_coordinates",
            side_effect=counted_coordinates,
        ):
            canceled = warp_mosaic_to_projected_view(
                mosaic,
                _view(
                    xlim=(-170.0, -10.0),
                    ylim=(-80.0, 80.0),
                    pixel_width=64,
                    pixel_height=300,
                ),
                is_cancelled=cancel_between_rgb_and_alpha,
            )
        self.assertIsNone(canceled)
        self.assertEqual(cancellation_checks, 2)
        self.assertEqual(coordinate_calls, 3)

        opener_entered = threading.Barrier(3)
        release_openers = threading.Event()
        opener_calls: list[str] = []
        opener_lock = threading.Lock()

        def blocked_opener(
            request: object,
            *,
            timeout: float,
        ) -> _Response:
            del timeout
            with opener_lock:
                opener_calls.append(request.full_url)  # type: ignore[attr-defined]
            opener_entered.wait()
            release_openers.wait(2.0)
            return _Response(
                b"bounded",
                url=request.full_url,  # type: ignore[attr-defined]
                content_type="image/jpeg",
            )

        if ArcGisBasemapClient is None:
            self.fail("ArcGisBasemapClient is unavailable")
        client = ArcGisBasemapClient(opener=blocked_opener)
        main_view = _view(surface_id="main")
        inspector_view = _view(surface_id="inspector:77")
        main_context = _register_context(client, main_view)
        inspector_context = _register_context(client, inspector_view)
        results: list[object] = []

        def request(context: object, suffix: str) -> None:
            results.append(
                client._request_bytes(
                    context,
                    url=f"{basemap.SERVICE_ROOT}/tile/1/0/{suffix}",
                    maximum_bytes=32,
                    purpose="tile",
                )
            )

        threads = [
            threading.Thread(target=request, args=(main_context, "0")),
            threading.Thread(target=request, args=(inspector_context, "1")),
        ]
        for thread in threads:
            thread.start()
        opener_entered.wait()
        self.assertEqual(len(client.active_reservations), 2)
        self.assertEqual(
            {item.slot_key for item in client.active_reservations},
            {"main", "inspector"},
        )

        client.cancel_surface("main", 2)
        client.cancel_surface("inspector:77", 2)
        old_epoch = client.cache_epoch
        client.clear_cache()
        self.assertEqual(client.cache_epoch, old_epoch + 1)
        self.assertIsNone(
            client._reserve_http_attempt(main_context, "tile")
        )
        self.assertIsNone(
            client._reserve_http_attempt(inspector_context, "tile")
        )
        release_openers.set()
        for thread in threads:
            thread.join(2.0)
            self.assertFalse(thread.is_alive())
        self.assertLessEqual(len(opener_calls), 2)
        self.assertEqual(len(opener_calls), 2)
        self.assertTrue(all(item is basemap._CANCELLED for item in results))
        self.assertEqual(client.active_reservations, ())
        self.assertIsNone(client.poll())
        self.assertEqual(client._cache.item_count, 0)
        client.shutdown()

    def test_bounded_response_queue_fifo_overflow_and_prompt_shutdown(self) -> None:
        def failure(index: int) -> BasemapFailure:
            return BasemapFailure(
                surface_id="main",
                generation=index,
                result_generation=index,
                category=f"failure_{index}",
                user_message="Imagery unavailable.",
                retryable=True,
            )

        if ArcGisBasemapClient is None:
            self.fail("ArcGisBasemapClient is unavailable")
        client = ArcGisBasemapClient(metadata_fixture=_metadata_fixture())
        for index in range(5):
            client._publish(failure(index))
        retained: list[BasemapFailure] = []
        while True:
            item = client.poll()
            if item is None:
                break
            retained.append(item)
        self.assertEqual([item.generation for item in retained], [1, 2, 3, 4])
        client.shutdown()

        class RecordingQueue(queue.Queue):
            def __init__(self) -> None:
                super().__init__(maxsize=basemap.MAX_RESPONSE_ITEMS)
                self.publications: list[object] = []

            def put_nowait(self, item: object) -> None:
                self.publications.append(item)
                return super().put_nowait(item)

        response_queue = RecordingQueue()
        concurrent = ArcGisBasemapClient(
            metadata_fixture=_metadata_fixture(),
            response_queue=response_queue,
        )
        prefill = [failure(index) for index in range(10, 14)]
        for item in prefill:
            concurrent._publish(item)
        response_queue.publications.clear()
        barrier = threading.Barrier(3)
        producer_items = [failure(20), failure(21)]

        def producer(item: BasemapFailure) -> None:
            barrier.wait()
            concurrent._publish(item)

        producers = [
            threading.Thread(target=producer, args=(item,))
            for item in producer_items
        ]
        for thread in producers:
            thread.start()
        barrier.wait()
        for thread in producers:
            thread.join(2.0)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(response_queue.publications), 2)
        linearized = response_queue.publications.copy()
        remaining: list[object] = []
        while True:
            item = concurrent.poll()
            if item is None:
                break
            remaining.append(item)
        self.assertEqual(remaining, prefill[2:] + linearized)
        self.assertEqual(set(linearized), set(producer_items))
        concurrent.shutdown()

        entered = threading.Event()
        release = threading.Event()

        def blocking_opener(
            request: object,
            *,
            timeout: float,
        ) -> _Response:
            del timeout
            entered.set()
            release.wait(2.0)
            return _Response(
                _encoded_jpeg(),
                url=request.full_url,  # type: ignore[attr-defined]
                content_type="image/jpeg",
            )

        blocked = ArcGisBasemapClient(
            opener=blocking_opener,
            metadata_fixture=_metadata_fixture(),
        )
        one_address = TileAddress(10, 10, 10, 10)
        request = SimpleNamespace(
            addresses=(one_address,),
            level=10,
            extent=SimpleNamespace(unwrap_reference=0.0),
        )
        patcher = patch.object(
            basemap,
            "_prepare_view_request",
            return_value=request,
        )
        patcher.start()
        try:
            blocked.submit(_view())
            self.assertTrue(entered.wait(1.0))
            started = time.perf_counter()
            blocked.shutdown()
            elapsed = time.perf_counter() - started
            self.assertLess(elapsed, 0.1)
            self.assertIsNone(blocked.poll())
        finally:
            release.set()
            patcher.stop()

    def test_cancelled_fetch_cannot_repopulate_cleared_tile_cache(self) -> None:
        address = TileAddress(15, 8283, 16493, 16493)
        body = _encoded_jpeg()
        for invalidation in ("disable", "input change", "shutdown"):
            with self.subTest(invalidation=invalidation):
                entered = threading.Event()
                release = threading.Event()
                cache = MemoryTileCache()

                def blocking_opener(
                    request: object,
                    *,
                    timeout: float,
                ) -> _Response:
                    del timeout
                    entered.set()
                    release.wait(2.0)
                    return _Response(
                        body,
                        url=request.full_url,  # type: ignore[attr-defined]
                        content_type="image/jpeg",
                    )

                client, _active_view, context = _registered_client(
                    opener=blocking_opener,
                    cache=cache,
                )
                result: list[object] = []
                worker = threading.Thread(
                    target=lambda: result.append(
                        client._fetch_tile(context, address)
                    )
                )
                worker.start()
                self.assertTrue(entered.wait(1.0))
                old_epoch = client.cache_epoch
                if invalidation == "disable":
                    client.cancel_surface("main", 2)
                    client.clear_cache()
                elif invalidation == "input change":
                    client.cancel_surface("main", 2)
                    client.clear_cache()
                else:
                    client.shutdown()
                self.assertEqual(client.cache_epoch, old_epoch + 1)
                release.set()
                worker.join(2.0)
                self.assertFalse(worker.is_alive())
                self.assertEqual(cache.item_count, 0)
                self.assertEqual(result[0].state, "cancelled")
                client.shutdown()

        class DormantThread:
            def __init__(self, *args: object, **kwargs: object) -> None:
                del args, kwargs

            def start(self) -> None:
                return None

            def is_alive(self) -> bool:
                return True

        retained_cache = MemoryTileCache()
        retained_cache.put("sentinel", _solid_tile(1))
        if ArcGisBasemapClient is None:
            self.fail("ArcGisBasemapClient is unavailable")
        same_input = ArcGisBasemapClient(
            metadata_fixture=_metadata_fixture(),
            cache=retained_cache,
        )
        original_epoch = same_input.cache_epoch
        with patch.object(basemap.threading, "Thread", DormantThread):
            same_input.submit(_view(generation=1))
            same_input.submit(_view(generation=2))
        self.assertEqual(same_input.cache_epoch, original_epoch)
        self.assertIsNotNone(retained_cache.get("sentinel"))
        same_input.shutdown()

    def test_default_suite_cannot_open_network_socket(self) -> None:
        if ArcGisBasemapClient is None:
            self.fail("ArcGisBasemapClient is unavailable")
        connect = Mock(side_effect=AssertionError("network socket opened"))
        create_connection = Mock(
            side_effect=AssertionError("network connection opened")
        )
        with (
            patch.object(socket.socket, "connect", connect),
            patch.object(socket, "create_connection", create_connection),
        ):
            parse_service_metadata(_metadata_fixture())
            tile_resolution(10)
            select_tile_addresses((-1.0, -1.0, 1.0, 1.0), 10)
            client = ArcGisBasemapClient(metadata_fixture=_metadata_fixture())
            client.submit(
                _view(
                    xlim=(1.0, 1.0),
                    ylim=(-1.0, 1.0),
                )
            )
            _wait_until(lambda: client.poll() is not None)
            client.shutdown()
        connect.assert_not_called()
        create_connection.assert_not_called()
        if os.environ.get("JPG_BOUNDARY_LIVE_ESRI_TEST") != "1":
            self.assertTrue(
                getattr(LiveEsriSmokeTests, "__unittest_skip__", False)
            )


@skipUnless(
    os.environ.get("JPG_BOUNDARY_LIVE_ESRI_TEST") == "1",
    "set JPG_BOUNDARY_LIVE_ESRI_TEST=1 to enable the bounded live Esri smoke",
)
class LiveEsriSmokeTests(TestCase):
    def test_live_metadata_and_sample_tile(self) -> None:
        service, tile = basemap._live_service_smoke()

        self.assertIsInstance(service, ArcGisTileService)
        self.assertEqual(service.root_url, basemap.SERVICE_ROOT)
        self.assertEqual(service.expected_wkid, 4326)
        self.assertEqual(tile.shape, (256, 256, 3))
        self.assertEqual(tile.dtype, np.uint8)
        self.assertFalse(tile.flags.writeable)
