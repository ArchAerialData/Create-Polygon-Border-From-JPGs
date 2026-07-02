from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from jpg_boundary_kmz_core import (  # noqa: E402
    BoundaryError,
    GENERATION_PROFILE_EXPORT,
    GENERATION_PROFILE_PREVIEW,
)
from jpg_boundary_kmz_gui import BoundaryKmzApp, _create_root  # noqa: E402


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

    def test_preview_canvas_and_toolbar_are_gridded(self) -> None:
        with _app() as app:
            canvas_grid = app.canvas_widget.grid_info()
            toolbar_grid = app.preview_toolbar.grid_info()

            self.assertEqual(int(canvas_grid["row"]), 0)
            self.assertEqual(int(toolbar_grid["row"]), 1)
            self.assertEqual(app.canvas_widget.master, app.preview_toolbar.master)

    def test_empty_preview_redraw_remains_safe(self) -> None:
        with _app() as app:
            app._draw_empty_preview()
            app.root.update_idletasks()

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
                    button=1,
                )
            )
            app._on_preview_mouse_move(
                SimpleNamespace(
                    inaxes=app.axes,
                    xdata=60.0,
                    ydata=65.0,
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
                        button=1,
                    )
                )
                self.assertIsNone(app._preview_pan_start)
            finally:
                app.preview_toolbar.zoom()


class _app:
    def __enter__(self) -> BoundaryKmzApp:
        self.root = _create_root()
        self.root.withdraw()
        self.app = BoundaryKmzApp(self.root)
        return self.app

    def __exit__(self, exc_type, exc, tb) -> None:
        self.root.destroy()
