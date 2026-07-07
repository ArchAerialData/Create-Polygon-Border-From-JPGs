from __future__ import annotations

import math
import sys
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase

import numpy as np
from shapely.geometry import Polygon

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from jpg_boundary_kmz_core import (  # noqa: E402
    BoundaryError,
    BoundaryMetadata,
    BoundaryResult,
    GENERATION_PROFILE_EXPORT,
    GENERATION_PROFILE_PREVIEW,
)
from jpg_boundary_kmz_gui import (  # noqa: E402
    BoundaryKmzApp,
    PREVIEW_MAX_PLOT_POINTS,
    _create_root,
)


class GuiInputTests(TestCase):
    def test_read_inputs_accepts_kml_file(self) -> None:
        with TemporaryDirectory() as tmp, _app() as app:
            kml_path = Path(tmp) / "input.kml"
            kml_path.write_text("<kml/>", encoding="utf-8")
            app.parent_var.set(str(kml_path))
            app.buffer_var.set("100")
            app.section_count_var.set("1")

            input_path, _buffer, _count, _overlap, _label, outline_mode, _split, _out = (
                app._read_inputs(require_output=False)
            )

            self.assertEqual(input_path, kml_path)
            self.assertEqual(outline_mode, "source_polygon")

    def test_custom_split_direction_is_normalized(self) -> None:
        with TemporaryDirectory() as tmp, _app() as app:
            folder = Path(tmp)
            app.parent_var.set(str(folder))
            app.buffer_var.set("0")
            app.section_count_var.set("2")
            app.split_direction_var.set("Custom")
            app.split_direction_degrees_var.set("270")

            values = app._read_inputs(require_output=False)

            self.assertEqual(values[6], 90.0)

    def test_invalid_custom_split_direction_raises(self) -> None:
        with TemporaryDirectory() as tmp, _app() as app:
            app.parent_var.set(str(Path(tmp)))
            app.buffer_var.set("0")
            app.section_count_var.set("2")
            app.split_direction_var.set("Custom")
            app.split_direction_degrees_var.set("not-a-number")

            with self.assertRaisesRegex(BoundaryError, "must be a number"):
                app._read_inputs(require_output=False)

    def test_settings_key_includes_split_direction(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp)
            auto_key = BoundaryKmzApp._settings_key(path, 0.0, 2, 50.0, "Shape", "Auto", None)
            explicit_key = BoundaryKmzApp._settings_key(path, 0.0, 2, 50.0, "Shape", "Auto", 90.0)

            self.assertNotEqual(auto_key, explicit_key)

    def test_settings_key_normalizes_vector_outline_modes(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.kml"
            path.write_text("<kml/>", encoding="utf-8")

            source_polygon_key = BoundaryKmzApp._settings_key(
                path,
                170.0,
                2,
                50.0,
                "Shape",
                "source_polygon",
                None,
            )
            source_linework_key = BoundaryKmzApp._settings_key(
                path,
                170.0,
                2,
                50.0,
                "Shape",
                "source_linework",
                None,
            )

            self.assertEqual(source_polygon_key, source_linework_key)

    def test_settings_key_includes_generation_profile(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.kmz"
            path.write_text("placeholder", encoding="utf-8")

            preview_key = BoundaryKmzApp._settings_key(
                path,
                0.0,
                2,
                50.0,
                "Shape",
                "source_polygon",
                None,
                GENERATION_PROFILE_PREVIEW,
            )
            export_key = BoundaryKmzApp._settings_key(
                path,
                0.0,
                2,
                50.0,
                "Shape",
                "source_polygon",
                None,
                GENERATION_PROFILE_EXPORT,
            )

            self.assertNotEqual(preview_key, export_key)

    def test_vector_input_disables_outline_mode(self) -> None:
        with TemporaryDirectory() as tmp, _app() as app:
            kml_path = Path(tmp) / "input.kml"
            kml_path.write_text("<kml/>", encoding="utf-8")
            app.parent_var.set(str(kml_path))
            app._update_outline_mode_state()

            self.assertEqual(str(app.outline_mode_combo.cget("state")), "disabled")

    def test_split_direction_controls_only_enable_for_multiple_sections(self) -> None:
        with _app() as app:
            app.section_count_var.set("1")
            app._update_section_control_state()
            self.assertEqual(str(app.split_direction_combo.cget("state")), "disabled")

            app.section_count_var.set("2")
            app._update_section_control_state()
            self.assertEqual(str(app.split_direction_combo.cget("state")), "readonly")

    def test_preview_toolbar_is_initialized(self) -> None:
        with _app() as app:
            self.assertTrue(hasattr(app, "preview_toolbar"))
            self.assertTrue(app.preview_toolbar.winfo_exists())
            self.assertTrue(hasattr(app, "expand_preview_button"))
            self.assertTrue(app.expand_preview_button.winfo_exists())
            self.assertTrue(app.preview_key_frame.winfo_exists())
            self.assertTrue(app.preview_key_canvas.winfo_exists())

    def test_preview_canvas_and_toolbar_are_gridded(self) -> None:
        with _app() as app:
            canvas_grid = app.canvas_widget.grid_info()
            toolbar_grid = app.preview_toolbar.grid_info()
            expand_grid = app.expand_preview_button.grid_info()
            key_grid = app.preview_key_frame.grid_info()

            self.assertEqual(int(canvas_grid["row"]), 0)
            self.assertEqual(int(canvas_grid["column"]), 0)
            self.assertEqual(int(toolbar_grid["row"]), 1)
            self.assertEqual(int(expand_grid["row"]), 1)
            self.assertEqual(int(key_grid["row"]), 0)
            self.assertEqual(int(key_grid["column"]), 1)
            self.assertEqual(app.canvas_widget.master, app.preview_toolbar.master)

    def test_empty_preview_redraw_remains_safe(self) -> None:
        with _app() as app:
            app._draw_empty_preview()
            app.root.update_idletasks()

    def test_preview_polygon_xy_decimates_large_polygon_and_preserves_closure(self) -> None:
        coords = [
            (
                math.cos(2.0 * math.pi * index / 3000),
                math.sin(2.0 * math.pi * index / 3000),
            )
            for index in range(3000)
        ]
        coords.append(coords[0])
        polygon = Polygon(coords)

        x_values, y_values = BoundaryKmzApp._preview_polygon_xy(polygon)

        self.assertLessEqual(len(x_values), PREVIEW_MAX_PLOT_POINTS)
        self.assertEqual(len(x_values), len(y_values))
        self.assertEqual((x_values[0], y_values[0]), (x_values[-1], y_values[-1]))

    def test_preview_interaction_callbacks_are_registered(self) -> None:
        with _app() as app:
            self.assertEqual(len(app._preview_event_cids), 4)
            self.assertTrue(all(isinstance(cid, int) for cid in app._preview_event_cids))

    def test_preview_scroll_inside_axes_changes_limits(self) -> None:
        with _app() as app:
            app.axes.set_xlim(0.0, 100.0)
            app.axes.set_ylim(0.0, 100.0)
            before_xlim = app.axes.get_xlim()
            before_ylim = app.axes.get_ylim()

            app._on_preview_scroll(
                SimpleNamespace(
                    inaxes=app.axes,
                    xdata=50.0,
                    ydata=50.0,
                    step=1,
                    button="up",
                )
            )

            after_xlim = app.axes.get_xlim()
            after_ylim = app.axes.get_ylim()
            self.assertLess(after_xlim[1] - after_xlim[0], before_xlim[1] - before_xlim[0])
            self.assertLess(after_ylim[1] - after_ylim[0], before_ylim[1] - before_ylim[0])

    def test_preview_scroll_outside_axes_is_ignored(self) -> None:
        with _app() as app:
            app.axes.set_xlim(0.0, 100.0)
            app.axes.set_ylim(0.0, 100.0)
            before_xlim = app.axes.get_xlim()
            before_ylim = app.axes.get_ylim()

            app._on_preview_scroll(
                SimpleNamespace(
                    inaxes=None,
                    xdata=None,
                    ydata=None,
                    step=1,
                    button="up",
                )
            )

            self.assertEqual(app.axes.get_xlim(), before_xlim)
            self.assertEqual(app.axes.get_ylim(), before_ylim)

    def test_preview_left_drag_pans_and_release_clears_state(self) -> None:
        with _app() as app:
            app.axes.set_xlim(0.0, 100.0)
            app.axes.set_ylim(0.0, 100.0)
            before_xlim = app.axes.get_xlim()
            before_ylim = app.axes.get_ylim()

            app._on_preview_button_press(
                SimpleNamespace(
                    inaxes=app.axes,
                    xdata=50.0,
                    ydata=50.0,
                    x=100.0,
                    y=100.0,
                    button=1,
                )
            )
            app._on_preview_mouse_move(
                SimpleNamespace(
                    inaxes=app.axes,
                    xdata=60.0,
                    ydata=65.0,
                    x=120.0,
                    y=130.0,
                )
            )
            app._on_preview_button_release(SimpleNamespace())

            self.assertNotEqual(app.axes.get_xlim(), before_xlim)
            self.assertNotEqual(app.axes.get_ylim(), before_ylim)
            self.assertIsNone(app._preview_pan_start)

    def test_preview_left_drag_defers_to_active_toolbar_mode(self) -> None:
        with _app() as app:
            app.preview_toolbar.zoom()
            try:
                app._on_preview_button_press(
                    SimpleNamespace(
                        inaxes=app.axes,
                        xdata=50.0,
                        ydata=50.0,
                        x=100.0,
                        y=100.0,
                        button=1,
                    )
                )
                self.assertIsNone(app._preview_pan_start)
            finally:
                app.preview_toolbar.zoom()

    def test_preview_left_drag_same_pixel_does_not_accumulate_motion(self) -> None:
        with _app() as app:
            app.axes.set_xlim(0.0, 100.0)
            app.axes.set_ylim(0.0, 100.0)
            app.canvas.draw()

            app._on_preview_button_press(
                SimpleNamespace(
                    inaxes=app.axes,
                    xdata=50.0,
                    ydata=50.0,
                    x=100.0,
                    y=100.0,
                    button=1,
                )
            )
            move_event = SimpleNamespace(x=120.0, y=130.0)
            app._on_preview_mouse_move(move_event)
            first_xlim = app.axes.get_xlim()
            first_ylim = app.axes.get_ylim()

            app._on_preview_mouse_move(move_event)

            self.assertEqual(app.axes.get_xlim(), first_xlim)
            self.assertEqual(app.axes.get_ylim(), first_ylim)

    def test_fullscreen_preview_opens_canvas_toolbar_and_controls(self) -> None:
        with _app() as app:
            app.section_count_var.set("2")
            app.overlap_var.set("75")
            app.shape_label_var.set("Test Shape")

            app._open_fullscreen_preview()

            self.assertTrue(app._fullscreen_window_exists())
            self.assertIsNotNone(app._fullscreen_canvas)
            self.assertIsNotNone(app._fullscreen_toolbar)
            self.assertIsNotNone(app._fullscreen_key_frame)
            self.assertIsNotNone(app._fullscreen_key_canvas)
            self.assertIsNotNone(app._fullscreen_key_content)
            self.assertIsNotNone(app._fullscreen_apply_button)
            self.assertEqual(len(app._fullscreen_event_cids), 4)
            self.assertEqual(app._fullscreen_section_count_var.get(), "2")
            self.assertEqual(app._fullscreen_overlap_var.get(), "75")
            self.assertEqual(app._fullscreen_shape_label_var.get(), "Test Shape")

            app._close_fullscreen_preview()
            self.assertFalse(app._fullscreen_window_exists())
            self.assertEqual(app._fullscreen_event_cids, [])

    def test_fullscreen_preview_draws_cached_result(self) -> None:
        with _app() as app:
            result = _sample_boundary_result()
            app._cached_result = result

            app._open_fullscreen_preview()

            self.assertTrue(app._fullscreen_window_exists())
            self.assertGreater(len(app._fullscreen_axes.lines), 0)
            self.assertIsNone(app._fullscreen_axes.get_legend())
            self.assertFalse(app._fullscreen_axes.axison)
            self.assertGreater(len(app._fullscreen_key_content.winfo_children()), 1)
            app._draw_preview(result)
            self.assertGreater(len(app._fullscreen_axes.lines), 0)

    def test_preview_long_corridor_preserves_equal_map_scale(self) -> None:
        with _app() as app:
            result = _long_corridor_boundary_result()

            app._draw_preview(result)
            app.canvas.draw()

            xlim = app.axes.get_xlim()
            ylim = app.axes.get_ylim()
            self.assertEqual(app.axes.get_aspect(), 1.0)
            self.assertEqual(app.axes.get_adjustable(), "box")
            self.assertFalse(app.axes.axison)
            self.assertIsNone(app.axes.get_legend())
            self.assertGreater(len(app.preview_key_content.winfo_children()), 1)
            self.assertLess(xlim[0], 0.0)
            self.assertGreater(xlim[1], 10000.0)
            self.assertLess(ylim[0], 0.0)
            self.assertGreater(ylim[1], 100.0)

    def test_fullscreen_long_corridor_preserves_equal_map_scale(self) -> None:
        with _app() as app:
            result = _long_corridor_boundary_result()
            app._cached_result = result

            app._open_fullscreen_preview()
            app._fullscreen_canvas.draw()

            xlim = app._fullscreen_axes.get_xlim()
            ylim = app._fullscreen_axes.get_ylim()
            self.assertEqual(app._fullscreen_axes.get_aspect(), 1.0)
            self.assertEqual(app._fullscreen_axes.get_adjustable(), "box")
            self.assertFalse(app._fullscreen_axes.axison)
            self.assertIsNone(app._fullscreen_axes.get_legend())
            self.assertGreater(len(app._fullscreen_key_content.winfo_children()), 1)
            self.assertLess(xlim[0], 0.0)
            self.assertGreater(xlim[1], 10000.0)
            self.assertLess(ylim[0], 0.0)
            self.assertGreater(ylim[1], 100.0)

    def test_fullscreen_apply_syncs_controls_and_starts_preview(self) -> None:
        with TemporaryDirectory() as tmp, _app() as app:
            app.parent_var.set(str(Path(tmp)))
            app.buffer_var.set("0")
            app._open_fullscreen_preview()
            app._fullscreen_section_count_var.set("3")
            app._fullscreen_overlap_var.set("25")
            app._fullscreen_shape_label_var.set("Fullscreen Shape")
            app._fullscreen_split_direction_var.set("90 deg / North-South")

            captured = {}

            def fake_start_preview(
                input_path,
                buffer_ft,
                section_count,
                overlap_ft,
                shape_label,
                outline_mode,
                split_direction_deg,
            ) -> None:
                captured.update(
                    input_path=input_path,
                    buffer_ft=buffer_ft,
                    section_count=section_count,
                    overlap_ft=overlap_ft,
                    shape_label=shape_label,
                    outline_mode=outline_mode,
                    split_direction_deg=split_direction_deg,
                )

            app._start_preview_generation = fake_start_preview

            app._apply_fullscreen_preview()

            self.assertEqual(app.section_count_var.get(), "3")
            self.assertEqual(app.overlap_var.get(), "25")
            self.assertEqual(app.shape_label_var.get(), "Fullscreen Shape")
            self.assertEqual(app.split_direction_var.get(), "90 deg / North-South")
            self.assertEqual(captured["section_count"], 3)
            self.assertEqual(captured["overlap_ft"], 25.0)
            self.assertEqual(captured["shape_label"], "Fullscreen Shape")
            self.assertEqual(captured["split_direction_deg"], 90.0)

    def test_fullscreen_direct_pan_uses_independent_canvas(self) -> None:
        with _app() as app:
            app._open_fullscreen_preview()
            axes = app._fullscreen_axes
            canvas = app._fullscreen_canvas
            toolbar = app._fullscreen_toolbar
            axes.set_xlim(0.0, 100.0)
            axes.set_ylim(0.0, 100.0)
            canvas.draw()
            before_xlim = axes.get_xlim()
            before_ylim = axes.get_ylim()

            app._handle_preview_button_press(
                SimpleNamespace(
                    inaxes=axes,
                    xdata=50.0,
                    ydata=50.0,
                    x=100.0,
                    y=100.0,
                    button=1,
                ),
                axes,
                canvas,
                toolbar,
            )
            app._handle_preview_mouse_move(
                SimpleNamespace(x=130.0, y=110.0),
                axes,
                canvas,
                toolbar,
            )
            app._on_preview_button_release(SimpleNamespace())

            self.assertNotEqual(axes.get_xlim(), before_xlim)
            self.assertNotEqual(axes.get_ylim(), before_ylim)

    def test_scan_done_auto_selected_polyline_buffer_updates_buffer_field(self) -> None:
        with _app() as app:
            result = _sample_boundary_result()
            result.metadata = replace(
                result.metadata,
                input_type="KML polyline",
                buffer_ft=114.0,
                source_line_count=2,
                source_point_count=20,
                polyline_requested_buffer_ft=0.0,
                polyline_minimum_connected_buffer_ft=81.0,
                polyline_selected_buffer_ft=114.0,
                polyline_buffer_regularity_ratio=1.54,
                polyline_buffer_regularity_target=1.55,
                polyline_buffer_candidate_count=30,
                polyline_buffer_adjustment_reason=(
                    "Requested buffer was zero; auto-selected a connected regular buffer."
                ),
            )
            app.buffer_var.set("0")
            app._queue.put(("scan_done", result))

            app._drain_queue()

            self.assertEqual(app.buffer_var.get(), "114")
            self.assertIn("Selected polyline buffer: 114.0 ft", app._details_text)


class _app:
    def __enter__(self) -> BoundaryKmzApp:
        self.root = _create_root()
        self.root.withdraw()
        self.app = BoundaryKmzApp(self.root)
        return self.app

    def __exit__(self, exc_type, exc, tb) -> None:
        self.root.destroy()


def _sample_boundary_result() -> BoundaryResult:
    polygon = Polygon(
        [
            (0.0, 0.0),
            (100.0, 0.0),
            (100.0, 50.0),
            (0.0, 50.0),
            (0.0, 0.0),
        ]
    )
    metadata = BoundaryMetadata(
        source_folder=Path.cwd(),
        input_type="KML polygon",
        jpg_count=0,
        gps_count=0,
        skipped_count=0,
        epsg=32615,
        crs_name="WGS 84 / UTM zone 15N",
        buffer_ft=0.0,
        median_spacing_ft=0.0,
        smoothing_ft=0.0,
        containment_padding_ft=0.0,
        concave_ratio=0.0,
        vertex_count=5,
        section_count=1,
        overlap_ft=0.0,
        shape_label="",
        split_strategy="",
        section_area_min_acres=0.0,
        section_area_max_acres=0.0,
        sections_connected=True,
        generation_profile=GENERATION_PROFILE_PREVIEW,
    )
    return BoundaryResult(
        metadata=metadata,
        gps_points=[],
        projected_points=np.empty((0, 2)),
        base_polygon_projected=polygon,
        final_polygon_projected=polygon,
        final_polygon_wgs84=polygon,
        sections=[],
    )


def _long_corridor_boundary_result() -> BoundaryResult:
    polygon = Polygon(
        [
            (0.0, 0.0),
            (10000.0, 0.0),
            (10000.0, 100.0),
            (0.0, 100.0),
            (0.0, 0.0),
        ]
    )
    result = _sample_boundary_result()
    result.metadata = replace(
        result.metadata,
        vertex_count=5,
        section_count=1,
    )
    result.base_polygon_projected = polygon
    result.final_polygon_projected = polygon
    result.final_polygon_wgs84 = polygon
    return result
