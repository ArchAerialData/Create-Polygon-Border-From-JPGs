from __future__ import annotations

import math
from pathlib import Path
import sys
from unittest import TestCase
from unittest.mock import patch

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from pyproj import CRS, Transformer

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import jpg_boundary_gui_scale_bar as scale_module  # noqa: E402
from jpg_boundary_gui_scale_bar import (  # noqa: E402
    METRES_PER_STATUTE_MILE,
    SCALE_BISECTION_MAX_ITERATIONS,
    SCALE_MAX_WIDTH_FRACTION,
    SCALE_MIN_MILES,
    SCALE_RELATIVE_ERROR_TOLERANCE,
    SCALE_START_X_FRACTION,
    SCALE_Y_FRACTION,
    ScaleBarController,
    calculate_scale_bar,
    format_miles,
    select_nice_miles,
)


class ScaleFormattingTests(TestCase):
    def test_nice_mileage_values_and_two_decimal_labels(self) -> None:
        expected_labels = {
            10.0: "10 mi",
            2.5: "2.5 mi",
            0.25: "0.25 mi",
            0.05: "0.05 mi",
            0.01: "0.01 mi",
        }
        for miles, expected in expected_labels.items():
            with self.subTest(miles=miles):
                label = format_miles(miles)
                self.assertEqual(label, expected)
                number = label.removesuffix(" mi")
                decimals = number.partition(".")[2]
                self.assertLessEqual(len(decimals), 2)
                self.assertNotIn("e", number.lower())

        selection_cases = (
            (11.0, 10.0),
            (10.0, 10.0),
            (4.99, 2.0),
            (2.0, 2.0),
            (0.999, 0.5),
            (0.499, 0.2),
            (0.059, 0.05),
            (0.019, 0.01),
        )
        for available, expected in selection_cases:
            with self.subTest(available=available):
                selected = select_nice_miles(available)
                self.assertEqual(selected, expected)
                self.assertLessEqual(selected, available)

        self.assertIsNone(select_nice_miles(0.00999))
        self.assertIsNone(select_nice_miles(math.nan))
        self.assertIsNone(select_nice_miles(math.inf))
        for invalid in (0.0, -1.0, 0.009, math.nan, math.inf):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    format_miles(invalid)


class ScaleCalculationTests(TestCase):
    def test_utm_north_and_south_geodesic_accuracy(self) -> None:
        fixtures = (
            ("EPSG:32615", -89.4, 43.1),
            ("EPSG:32755", 147.0, -35.0),
        )
        for crs_input, longitude, latitude in fixtures:
            with self.subTest(crs=crs_input):
                figure, _canvas, axes, crs = _projected_axes(
                    crs_input,
                    longitude,
                    latitude,
                )
                spec = calculate_scale_bar(axes, crs)
                self.assertIsNotNone(spec)
                assert spec is not None
                _assert_accurate_spec(self, axes, crs, spec)
                figure.clear()

    def test_web_mercator_latitude_and_nonmetre_crs_accuracy(self) -> None:
        fixtures = (
            ("EPSG:3857", 0.0, 0.0),
            ("EPSG:3857", 0.0, 60.0),
            ("EPSG:2263", -73.98, 40.75),
        )
        for crs_input, longitude, latitude in fixtures:
            with self.subTest(crs=crs_input, latitude=latitude):
                figure, _canvas, axes, crs = _projected_axes(
                    crs_input,
                    longitude,
                    latitude,
                )
                center_x = sum(axes.get_xlim()) / 2.0
                center_y = sum(axes.get_ylim()) / 2.0
                center_to_geodetic = Transformer.from_crs(
                    crs,
                    crs.geodetic_crs,
                    always_xy=True,
                )
                _center_lon, center_lat = center_to_geodetic.transform(
                    center_x,
                    center_y,
                )
                self.assertAlmostEqual(center_lat, latitude, places=8)

                spec = calculate_scale_bar(axes, crs)
                self.assertIsNotNone(spec)
                assert spec is not None
                _assert_accurate_spec(self, axes, crs, spec)
                figure.clear()

    def test_inverted_limits_use_signed_axes_endpoints(self) -> None:
        figure, canvas, axes, crs = _projected_axes(
            "EPSG:32615",
            -89.4,
            43.1,
        )
        normal_xlim = axes.get_xlim()
        normal_ylim = axes.get_ylim()
        selected_miles: list[float] = []

        for invert_x, invert_y in (
            (False, False),
            (True, False),
            (False, True),
            (True, True),
        ):
            with self.subTest(invert_x=invert_x, invert_y=invert_y):
                axes.set_xlim(normal_xlim[::-1] if invert_x else normal_xlim)
                axes.set_ylim(normal_ylim[::-1] if invert_y else normal_ylim)
                canvas.draw()
                spec = calculate_scale_bar(axes, crs)
                self.assertIsNotNone(spec)
                assert spec is not None
                measured = _assert_accurate_spec(self, axes, crs, spec)
                self.assertGreater(measured, 0.0)
                selected_miles.append(spec.miles)

                start_data = _axes_fraction_to_data(
                    axes,
                    spec.start_fraction,
                    spec.y_fraction,
                )
                end_data = _axes_fraction_to_data(
                    axes,
                    spec.end_fraction,
                    spec.y_fraction,
                )
                if invert_x:
                    self.assertLess(end_data[0], start_data[0])
                else:
                    self.assertGreater(end_data[0], start_data[0])

        self.assertEqual(len(set(selected_miles)), 1)
        figure.clear()

    def test_threshold_minimum_and_extreme_views(self) -> None:
        threshold_cases = (
            (0.0101, 0.01),
            (0.0201, 0.02),
            (0.0501, 0.05),
            (0.1001, 0.1),
            (2.01, 2.0),
            (5.01, 5.0),
        )
        for available_miles, expected_miles in threshold_cases:
            with self.subTest(available_miles=available_miles):
                spec = _calculate_injected_linear_scale(available_miles)
                self.assertIsNotNone(spec)
                assert spec is not None
                self.assertEqual(spec.miles, expected_miles)
                self.assertLessEqual(
                    spec.relative_error,
                    SCALE_RELATIVE_ERROR_TOLERANCE,
                )
                self.assertGreaterEqual(
                    spec.end_fraction - spec.start_fraction,
                    0.10 - 1.0e-12,
                )
                self.assertLessEqual(
                    spec.end_fraction - spec.start_fraction,
                    SCALE_MAX_WIDTH_FRACTION,
                )

        minimum_spec = _calculate_injected_linear_scale(0.010001)
        self.assertIsNotNone(minimum_spec)
        assert minimum_spec is not None
        self.assertEqual(minimum_spec.miles, SCALE_MIN_MILES)
        self.assertIsNone(_calculate_injected_linear_scale(0.009999))

        calls = {"end": 0}

        def nonconverging_transform(
            x_fraction: float,
            _y_fraction: float,
        ) -> tuple[float, float]:
            if x_fraction == SCALE_START_X_FRACTION:
                return (0.0, 0.0)
            calls["end"] += 1
            if x_fraction >= SCALE_START_X_FRACTION + SCALE_MAX_WIDTH_FRACTION:
                miles = 4.9
            elif x_fraction < 0.15:
                miles = 1.9
            else:
                miles = 2.1
            return (miles * METRES_PER_STATUTE_MILE, 0.0)

        nonconverging = calculate_scale_bar(
            None,
            "EPSG:3857",
            axes_fraction_to_data=nonconverging_transform,
            xlim=(0.0, 1.0),
            ylim=(0.0, 1.0),
            axes_pixel_bounds=(0.0, 0.0, 800.0, 500.0),
        )
        self.assertIsNone(nonconverging)
        self.assertEqual(
            calls["end"],
            8 + SCALE_BISECTION_MAX_ITERATIONS + 1,
        )

        self.assertIsNone(
            calculate_scale_bar(
                None,
                "invalid-crs",
                axes_fraction_to_data=lambda x, y: (x, y),
                xlim=(0.0, 1.0),
                ylim=(0.0, 1.0),
                axes_pixel_bounds=(0.0, 0.0, 800.0, 500.0),
            )
        )
        self.assertIsNone(
            calculate_scale_bar(
                None,
                "EPSG:3857",
                axes_fraction_to_data=lambda x, y: (math.nan, y),
                xlim=(0.0, 1.0),
                ylim=(0.0, 1.0),
                axes_pixel_bounds=(0.0, 0.0, 800.0, 500.0),
            )
        )
        self.assertIsNone(
            calculate_scale_bar(
                None,
                "EPSG:3857",
                axes_fraction_to_data=lambda x, y: (x, y),
                xlim=(1.0, 1.0),
                ylim=(0.0, 1.0),
                axes_pixel_bounds=(0.0, 0.0, 800.0, 500.0),
            )
        )


class ScaleArtistTests(TestCase):
    def test_bind_refresh_axes_clear_rebind_is_idempotent_and_passive(self) -> None:
        figure, canvas, axes, crs = _projected_axes(
            "EPSG:32615",
            -89.4,
            43.1,
        )
        original_xlim = axes.get_xlim()
        original_ylim = axes.get_ylim()
        callback_counts = _callback_counts(canvas)
        controller = ScaleBarController(axes, canvas)

        self.assertTrue(controller.bind_result(crs, 1))
        self.assertTrue(controller.refresh())
        self.assertEqual(len(_scale_artists(axes)), 4)
        artist_ids = {id(artist) for artist in _scale_artists(axes)}
        self.assertFalse(controller.refresh())
        self.assertEqual(
            {id(artist) for artist in _scale_artists(axes)},
            artist_ids,
        )

        axes.clear()
        axes.set_xlim(original_xlim)
        axes.set_ylim(original_ylim)
        canvas.draw()
        self.assertEqual(_scale_artists(axes), [])
        self.assertTrue(controller.refresh())
        self.assertEqual(len(_scale_artists(axes)), 4)
        self.assertFalse(controller.refresh())

        self.assertTrue(controller.clear())
        self.assertEqual(_scale_artists(axes), [])
        self.assertFalse(controller.clear())

        self.assertTrue(controller.bind_result(crs, 2))
        self.assertTrue(controller.refresh())
        self.assertEqual(len(_scale_artists(axes)), 4)
        self.assertEqual(_callback_counts(canvas), callback_counts)
        figure.clear()

    def test_resize_and_view_signature_recalculate_only_when_changed(self) -> None:
        figure, canvas, axes, crs = _projected_axes(
            "EPSG:32615",
            -89.4,
            43.1,
        )
        controller = ScaleBarController(axes, canvas)
        controller.bind_result(crs, 10)

        with patch.object(
            scale_module,
            "calculate_scale_bar",
            wraps=scale_module.calculate_scale_bar,
        ) as calculate:
            self.assertTrue(controller.refresh())
            self.assertEqual(calculate.call_count, 1)
            self.assertFalse(controller.refresh())
            self.assertEqual(calculate.call_count, 1)

            left, right = axes.get_xlim()
            axes.set_xlim(left + 1000.0, right + 1000.0)
            canvas.draw()
            self.assertTrue(controller.refresh())
            self.assertEqual(calculate.call_count, 2)
            self.assertFalse(controller.refresh())
            self.assertEqual(calculate.call_count, 2)

            figure.set_size_inches(9.0, 5.0)
            canvas.draw()
            self.assertTrue(controller.refresh())
            self.assertEqual(calculate.call_count, 3)

            figure.set_dpi(120.0)
            canvas.draw()
            self.assertTrue(controller.refresh())
            self.assertEqual(calculate.call_count, 4)

            self.assertTrue(controller.bind_result("EPSG:26915", 10))
            self.assertTrue(controller.refresh())
            self.assertEqual(calculate.call_count, 5)

            self.assertTrue(controller.bind_result("EPSG:26915", 11))
            self.assertTrue(controller.refresh())
            self.assertEqual(calculate.call_count, 6)
            self.assertFalse(controller.refresh())
            self.assertEqual(calculate.call_count, 6)

        self.assertEqual(len(_scale_artists(axes)), 4)
        figure.clear()

    def test_invalid_crs_transform_and_degenerate_axes_hide_without_raise(self) -> None:
        figure, canvas, axes, crs = _projected_axes(
            "EPSG:32615",
            -89.4,
            43.1,
        )
        controller = ScaleBarController(axes, canvas)
        controller.bind_result(crs, 1)
        self.assertTrue(controller.refresh())
        self.assertEqual(len(_scale_artists(axes)), 4)

        controller.bind_result("not-a-valid-crs", 2)
        controller.refresh()
        self.assertEqual(_scale_artists(axes), [])

        controller.bind_result(crs, 3)
        self.assertTrue(controller.refresh())
        self.assertEqual(len(_scale_artists(axes)), 4)
        axes.set_position((0.1, 0.1, 0.0, 0.0))
        canvas.draw()
        controller.refresh()
        self.assertEqual(_scale_artists(axes), [])

        axes.set_position((0.125, 0.11, 0.775, 0.77))
        canvas.draw()
        controller.bind_result(crs, 4)
        self.assertTrue(controller.refresh())
        self.assertEqual(len(_scale_artists(axes)), 4)
        with patch.object(
            scale_module,
            "calculate_scale_bar",
            side_effect=RuntimeError("transform failed"),
        ):
            controller.bind_result(crs, 5)
            controller.refresh()
        self.assertEqual(_scale_artists(axes), [])

        def raising_transform(
            _x_fraction: float,
            _y_fraction: float,
        ) -> tuple[float, float]:
            raise RuntimeError("injected transform failure")

        invalid_calculations = (
            calculate_scale_bar(
                None,
                "EPSG:3857",
                axes_fraction_to_data=raising_transform,
                xlim=(0.0, 1.0),
                ylim=(0.0, 1.0),
                axes_pixel_bounds=(0.0, 0.0, 800.0, 500.0),
            ),
            calculate_scale_bar(
                None,
                "EPSG:3857",
                axes_fraction_to_data=lambda x, y: (x, y),
                xlim=(0.0, math.inf),
                ylim=(0.0, 1.0),
                axes_pixel_bounds=(0.0, 0.0, 800.0, 500.0),
            ),
            calculate_scale_bar(
                None,
                "EPSG:3857",
                axes_fraction_to_data=lambda x, y: (x, y),
                xlim=(0.0, 1.0),
                ylim=(0.0, 1.0),
                axes_pixel_bounds=(0.0, 0.0, 0.0, 500.0),
            ),
        )
        self.assertEqual(invalid_calculations, (None, None, None))
        figure.clear()


def _projected_axes(
    crs_input: str,
    longitude: float,
    latitude: float,
) -> tuple[Figure, FigureCanvasAgg, object, CRS]:
    crs = CRS.from_user_input(crs_input)
    to_display = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    center_x, center_y = to_display.transform(longitude, latitude)
    unit_to_metres = crs.axis_info[0].unit_conversion_factor
    view_width = 200_000.0 / unit_to_metres
    view_height = 120_000.0 / unit_to_metres

    figure = Figure(figsize=(8.0, 5.0), dpi=100.0)
    canvas = FigureCanvasAgg(figure)
    axes = figure.add_subplot(111)
    axes.set_xlim(center_x - view_width / 2.0, center_x + view_width / 2.0)
    axes.set_ylim(center_y - view_height / 2.0, center_y + view_height / 2.0)
    canvas.draw()
    return figure, canvas, axes, crs


def _axes_fraction_to_data(
    axes: object,
    x_fraction: float,
    y_fraction: float,
) -> tuple[float, float]:
    display_point = axes.transAxes.transform((x_fraction, y_fraction))
    data_point = axes.transData.inverted().transform(display_point)
    return (float(data_point[0]), float(data_point[1]))


def _measured_geodesic_miles(
    axes: object,
    display_crs: CRS,
    start_fraction: float,
    end_fraction: float,
    y_fraction: float,
) -> float:
    start_data = _axes_fraction_to_data(axes, start_fraction, y_fraction)
    end_data = _axes_fraction_to_data(axes, end_fraction, y_fraction)
    to_geodetic = Transformer.from_crs(
        display_crs,
        display_crs.geodetic_crs,
        always_xy=True,
    )
    start_lon, start_lat = to_geodetic.transform(*start_data)
    end_lon, end_lat = to_geodetic.transform(*end_data)
    _azimuth, _reverse_azimuth, distance_metres = display_crs.get_geod().inv(
        start_lon,
        start_lat,
        end_lon,
        end_lat,
    )
    return abs(distance_metres) / METRES_PER_STATUTE_MILE


def _assert_accurate_spec(
    test: TestCase,
    axes: object,
    crs: CRS,
    spec: object,
) -> float:
    test.assertEqual(spec.start_fraction, SCALE_START_X_FRACTION)
    test.assertEqual(spec.y_fraction, SCALE_Y_FRACTION)
    test.assertLessEqual(
        spec.end_fraction,
        SCALE_START_X_FRACTION + SCALE_MAX_WIDTH_FRACTION,
    )
    visual_width = spec.end_fraction - spec.start_fraction
    test.assertGreaterEqual(visual_width, 0.10 - 1.0e-12)
    test.assertLessEqual(visual_width, SCALE_MAX_WIDTH_FRACTION + 1.0e-12)
    measured = _measured_geodesic_miles(
        axes,
        crs,
        spec.start_fraction,
        spec.end_fraction,
        spec.y_fraction,
    )
    relative_error = abs(measured - spec.miles) / spec.miles
    test.assertLessEqual(relative_error, SCALE_RELATIVE_ERROR_TOLERANCE)
    test.assertAlmostEqual(relative_error, spec.relative_error, places=12)
    test.assertEqual(spec.label, format_miles(spec.miles))
    test.assertLessEqual(len(spec.label.removesuffix(" mi").partition(".")[2]), 2)
    return measured


def _calculate_injected_linear_scale(available_miles: float) -> object:
    def mapper(
        x_fraction: float,
        _y_fraction: float,
    ) -> tuple[float, float]:
        width_ratio = (
            x_fraction - SCALE_START_X_FRACTION
        ) / SCALE_MAX_WIDTH_FRACTION
        return (
            width_ratio * available_miles * METRES_PER_STATUTE_MILE,
            0.0,
        )

    return calculate_scale_bar(
        None,
        "EPSG:3857",
        axes_fraction_to_data=mapper,
        xlim=(0.0, 1.0),
        ylim=(0.0, 1.0),
        axes_pixel_bounds=(0.0, 0.0, 800.0, 500.0),
    )


def _scale_artists(axes: object) -> list[object]:
    return [
        artist
        for artist in axes.get_children()
        if isinstance(artist.get_gid(), str)
        and artist.get_gid().startswith("jpg-boundary-scale-")
    ]


def _callback_counts(canvas: FigureCanvasAgg) -> dict[str, int]:
    return {
        event_name: len(callbacks)
        for event_name, callbacks in canvas.callbacks.callbacks.items()
    }
