from __future__ import annotations

import math
import sys
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import numpy as np
from matplotlib.colors import to_rgba
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
import jpg_boundary_kmz_gui as gui_module  # noqa: E402
import jpg_boundary_gui_theme as theme_module  # noqa: E402
from jpg_boundary_kmz_gui import (  # noqa: E402
    ACTION_BAR_MIN_BREAKPOINT,
    BoundaryKmzApp,
    PREVIEW_MAX_PLOT_POINTS,
    _create_root,
)
from jpg_boundary_gui_theme import PALETTE, style_tk_label  # noqa: E402
from jpg_boundary_gui_window import OuterWindowBounds, WorkArea  # noqa: E402


class GuiInputTests(TestCase):
    def test_read_inputs_accepts_kml_file(self) -> None:
        with TemporaryDirectory() as tmp, _app() as app:
            kml_path = Path(tmp) / "input.kml"
            kml_path.write_text("<kml/>", encoding="utf-8")
            app.parent_var.set(str(kml_path))
            app.buffer_var.set("100")
            app.section_count_var.set("1")

            (
                input_path,
                _buffer,
                _count,
                _overlap,
                _label,
                outline_mode,
                _split,
                simplify_vector_output,
                _out,
            ) = app._read_inputs(require_output=False)

            self.assertEqual(input_path, kml_path)
            self.assertEqual(outline_mode, "source_polygon")
            self.assertFalse(simplify_vector_output)

            app.simplify_vector_var.set(True)

            self.assertTrue(app._read_inputs(require_output=False)[7])

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

    def test_settings_key_includes_vector_simplification_toggle(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.kmz"
            path.write_text("placeholder", encoding="utf-8")

            preserve_key = BoundaryKmzApp._settings_key(
                path,
                0.0,
                1,
                0.0,
                "",
                "source_polygon",
                None,
                GENERATION_PROFILE_EXPORT,
                simplify_vector_output=False,
            )
            simplify_key = BoundaryKmzApp._settings_key(
                path,
                0.0,
                1,
                0.0,
                "",
                "source_polygon",
                None,
                GENERATION_PROFILE_EXPORT,
                simplify_vector_output=True,
            )

            self.assertNotEqual(preserve_key, simplify_key)

    def test_vector_input_disables_outline_mode(self) -> None:
        with TemporaryDirectory() as tmp, _app() as app:
            kml_path = Path(tmp) / "input.kml"
            kml_path.write_text("<kml/>", encoding="utf-8")
            app.parent_var.set(str(kml_path))
            app._update_outline_mode_state()

            self.assertEqual(str(app.outline_mode_combo.cget("state")), "disabled")
            self.assertEqual(
                str(app.simplify_vector_checkbutton.cget("state")),
                "normal",
            )

    def test_folder_input_disables_vector_simplification_toggle(self) -> None:
        with TemporaryDirectory() as tmp, _app() as app:
            app.parent_var.set(str(Path(tmp)))
            app._update_outline_mode_state()

            self.assertEqual(
                str(app.simplify_vector_checkbutton.cget("state")),
                "disabled",
            )

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

    def test_preview_canvas_toolbar_and_permanent_actions_are_mapped(self) -> None:
        with _app() as app:
            canvas_grid = app.canvas_widget.grid_info()
            toolbar_grid = app.preview_toolbar.grid_info()
            update_grid = app.scan_button.grid_info()
            export_grid = app.export_button.grid_info()

            self.assertEqual(int(canvas_grid["row"]), 0)
            self.assertEqual(int(canvas_grid["column"]), 0)
            self.assertEqual(int(toolbar_grid["row"]), 0)
            self.assertTrue(update_grid)
            self.assertTrue(export_grid)
            self.assertEqual(app.root_frame.grid_rowconfigure(1)["weight"], 1)
            self.assertFalse(app._legend_open)
            self.assertFalse(app._settings_drawer_open)

    def test_app_initialization_preserves_caller_withdrawn_root(self) -> None:
        root = _create_root()
        root.withdraw()
        try:
            BoundaryKmzApp(root)
            self.assertEqual(root.state(), "withdrawn")
        finally:
            root.destroy()

    def test_main_applies_geometry_before_deiconify_and_surfaces_warning(self) -> None:
        events: list[str] = []

        class FakeRoot:
            def withdraw(self) -> None:
                events.append("withdraw")

            def update_idletasks(self) -> None:
                events.append("idle")

            def deiconify(self) -> None:
                events.append("deiconify")

            def mainloop(self) -> None:
                events.append("mainloop")

        class FakeApp:
            def _set_window_fit_warning(self, received_fit: object) -> None:
                self.received_fit = received_fit
                events.append("warning")

        root = FakeRoot()
        app = FakeApp()
        work_area = object()
        fit = SimpleNamespace(
            contained=False,
            used_reserve_fallback=True,
            warning="Conservative window fit used.",
        )

        with (
            patch.object(gui_module, "_create_root", return_value=root),
            patch.object(
                gui_module,
                "get_launch_work_area",
                side_effect=lambda _root: (events.append("work_area"), work_area)[1],
            ),
            patch.object(
                gui_module,
                "BoundaryKmzApp",
                side_effect=lambda _root: (events.append("build"), app)[1],
            ),
            patch.object(
                gui_module,
                "apply_initial_geometry",
                side_effect=lambda _root, _area: (events.append("geometry"), fit)[1],
            ),
            patch.object(
                gui_module,
                "apply_native_chrome",
                side_effect=lambda _root: events.append("chrome"),
            ),
        ):
            gui_module.main()

        self.assertEqual(
            events,
            [
                "withdraw",
                "work_area",
                "build",
                "idle",
                "geometry",
                "warning",
                "chrome",
                "deiconify",
                "mainloop",
            ],
        )
        self.assertIs(app.received_fit, fit)

    def test_shell_uses_preview_as_only_expanding_content(self) -> None:
        with _app() as app:
            self.assertEqual(app.root_frame.grid_rowconfigure(0)["weight"], 0)
            self.assertEqual(app.root_frame.grid_rowconfigure(1)["weight"], 1)
            self.assertEqual(app.root_frame.grid_rowconfigure(2)["weight"], 0)
            self.assertTrue(app.scan_button.grid_info())
            self.assertTrue(app.export_button.grid_info())

    def test_header_keeps_all_controls_inside_adaptive_small_width(self) -> None:
        root = _create_root()
        root.withdraw()
        root.geometry("720x500+0+0")
        try:
            app = BoundaryKmzApp(root)
            root.update_idletasks()

            self.assertTrue(app._header_compact)
            for widget in (
                app.compact_input_target,
                app.change_input_button,
                app.key_button,
                app.settings_button,
                app.focus_button,
                app.expand_preview_button,
            ):
                with self.subTest(widget=str(widget)):
                    self.assertTrue(widget.grid_info())
                    self.assertLessEqual(
                        widget.winfo_x() + widget.winfo_width(),
                        root.winfo_width(),
                    )
            self.assertTrue(app.scan_button.grid_info())
            self.assertTrue(app.export_button.grid_info())
            for widget in (app.scan_button, app.export_button):
                with self.subTest(action=str(widget)):
                    right_edge = (
                        widget.winfo_rootx()
                        - root.winfo_rootx()
                        + widget.winfo_width()
                    )
                    self.assertLessEqual(right_edge, root.winfo_width())
        finally:
            root.destroy()

    def test_preview_workspace_meets_planned_size_targets(self) -> None:
        for geometry, minimum in (
            ("1440x741+0+0", (1360, 520)),
            ("1440x612+0+0", (1360, 390)),
            ("960x600+0+0", (900, 350)),
        ):
            with self.subTest(geometry=geometry):
                root = _create_root()
                root.withdraw()
                root.geometry(geometry)
                try:
                    app = BoundaryKmzApp(root)
                    root.update_idletasks()
                    self.assertGreaterEqual(app.preview_stack.winfo_width(), minimum[0])
                    self.assertGreaterEqual(app.preview_stack.winfo_height(), minimum[1])
                    self.assertTrue(app.scan_button.grid_info())
                    self.assertTrue(app.export_button.grid_info())
                    app.canvas.draw()
                    root.update_idletasks()
                finally:
                    root.destroy()

    def test_empty_input_compacts_after_selection_and_restores_when_cleared(self) -> None:
        with TemporaryDirectory() as tmp, _app() as app:
            self.assertTrue(app.empty_input_overlay.place_info())

            app.parent_var.set(str(Path(tmp)))
            app.root.update_idletasks()

            self.assertFalse(app.empty_input_overlay.place_info())
            self.assertIn(Path(tmp).name, app.input_summary_var.get())

            app.parent_var.set("")
            app.root.update_idletasks()

            self.assertTrue(app.empty_input_overlay.place_info())
            self.assertIn("No input selected", app.input_summary_var.get())

    def test_empty_and_compact_drop_targets_use_event_specific_feedback(self) -> None:
        with _app() as app:
            self.assertEqual(
                app._drop_targets,
                [app.compact_input_target, app.drop_label],
            )
            if gui_module.DND_FILES is not None:
                for target in app._drop_targets:
                    with self.subTest(target=str(target)):
                        self.assertTrue(target.dnd_bind("<<Drop>>"))
                        self.assertTrue(target.dnd_bind("<<DragEnter>>"))
                        self.assertTrue(target.dnd_bind("<<DragLeave>>"))
            empty_background = app.drop_label.cget("background")

            app._handle_drag_enter(SimpleNamespace(widget=app.compact_input_target))

            self.assertEqual(
                app.compact_input_target.cget("background"),
                "#1e3a5f",
            )
            self.assertEqual(app.drop_label.cget("background"), empty_background)

            app._handle_drag_leave(SimpleNamespace(widget=app.compact_input_target))

            self.assertEqual(
                app.compact_input_target.cget("background"),
                "#202838",
            )

    def test_drop_registration_failure_keeps_browse_available(self) -> None:
        with _app() as app:
            with (
                patch.object(gui_module, "DND_FILES", "DND_Files"),
                patch.object(
                    app.drop_label,
                    "drop_target_register",
                    side_effect=gui_module.tk.TclError("DND unavailable"),
                ),
            ):
                app._register_drop_target(
                    app.drop_label,
                    feedback_surface=app.drop_label,
                )

            self.assertIn("failed to initialize", app.drop_label.cget("text"))
            self.assertEqual(
                app.drop_label.cget("highlightbackground"),
                "#f59e0b",
            )
            self.assertEqual(str(app.browse_folder_button.cget("state")), "normal")
            self.assertEqual(str(app.browse_vector_button.cget("state")), "normal")

    def test_drawer_and_action_bar_share_canonical_variables(self) -> None:
        with _app() as app:
            app.quick_buffer_entry.delete(0, "end")
            app.quick_buffer_entry.insert(0, "125")
            self.assertEqual(app.buffer_var.get(), "125")
            self.assertEqual(app.buffer_entry.get(), "125")

            app.section_count_spinbox.delete(0, "end")
            app.section_count_spinbox.insert(0, "3")
            self.assertEqual(app.quick_section_count_spinbox.get(), "3")

    def test_settings_and_key_overlays_are_mutually_exclusive(self) -> None:
        with _app() as app:
            app._toggle_settings_drawer()
            self.assertTrue(app._settings_drawer_open)
            self.assertFalse(app._legend_open)
            self.assertTrue(app.settings_drawer.place_info())

            app._toggle_preview_key()
            self.assertFalse(app._settings_drawer_open)
            self.assertTrue(app._legend_open)
            self.assertFalse(app.settings_drawer.place_info())
            self.assertTrue(app.preview_key_overlay.place_info())

            app._toggle_settings_drawer()
            self.assertTrue(app._settings_drawer_open)
            self.assertFalse(app._legend_open)
            self.assertFalse(app.preview_key_overlay.place_info())

    def test_settings_scrollbar_only_appears_when_content_overflows(self) -> None:
        for geometry, expected_visible in (
            ("1440x741+0+0", False),
            ("960x600+0+0", True),
        ):
            with self.subTest(geometry=geometry):
                root = _create_root()
                root.withdraw()
                root.geometry(geometry)
                try:
                    app = BoundaryKmzApp(root)
                    app._toggle_settings_drawer()
                    root.update_idletasks()
                    app._refresh_settings_scrollbar()
                    self.assertEqual(
                        bool(app.settings_scrollbar.grid_info()),
                        expected_visible,
                    )
                finally:
                    root.destroy()

    def test_key_overlay_remains_scrollable_with_maximum_sections(self) -> None:
        with _app() as app:
            entries = [
                (f"Section {index:03d}", "#60a5fa", "-", 1.8)
                for index in range(1, 101)
            ]
            app._update_preview_key(app.preview_key_content, entries)
            app._toggle_preview_key()
            app.root.update_idletasks()

            key_bounds = app.preview_key_canvas.bbox("all")
            self.assertIsNotNone(key_bounds)
            self.assertEqual(len(app.preview_key_content.winfo_children()), 200)
            self.assertGreater(
                key_bounds[3] - key_bounds[1],
                app.preview_key_canvas.winfo_height(),
            )
            self.assertTrue(app.scan_button.grid_info())
            self.assertTrue(app.export_button.grid_info())

    def test_overlay_toggles_preserve_preview_view_and_callbacks(self) -> None:
        with _app() as app:
            app.axes.set_xlim(10.0, 20.0)
            app.axes.set_ylim(30.0, 40.0)
            before_xlim = app.axes.get_xlim()
            before_ylim = app.axes.get_ylim()

            for _ in range(3):
                app._toggle_settings_drawer()
                app._toggle_settings_drawer()
                app._toggle_preview_key()
                app._toggle_preview_key()

            self.assertEqual(len(app._preview_event_cids), 4)
            self.assertEqual(app.axes.get_xlim(), before_xlim)
            self.assertEqual(app.axes.get_ylim(), before_ylim)

    def test_action_bar_uses_scaling_aware_breakpoint(self) -> None:
        with _app() as app:
            app._refresh_action_bar_layout(ACTION_BAR_MIN_BREAKPOINT - 1)
            self.assertTrue(app._action_bar_compact)
            self.assertEqual(int(app.action_right_group.grid_info()["row"]), 1)

            app._refresh_action_bar_layout(app._action_bar_breakpoint + 1)
            self.assertFalse(app._action_bar_compact)
            self.assertEqual(int(app.action_right_group.grid_info()["row"]), 0)

    def test_quick_overlap_is_hidden_for_one_shape_and_visible_for_multiple(self) -> None:
        with _app() as app:
            app.section_count_var.set("1")
            app.root.update_idletasks()
            self.assertFalse(app.quick_overlap_entry.grid_info())

            app.section_count_var.set("2")
            app.root.update_idletasks()
            self.assertTrue(app.quick_overlap_entry.grid_info())

    def test_buffer_change_invalidates_cache_and_marks_preview_stale(self) -> None:
        with _app() as app:
            result = _sample_boundary_result()
            app._cached_result = result
            app._cached_settings = ("cached",)  # type: ignore[assignment]
            app._last_displayed_result = result
            app._mark_preview_current()

            app.buffer_var.set("25")

            self.assertIsNone(app._cached_result)
            self.assertIsNone(app._cached_settings)
            self.assertTrue(app._preview_stale)
            self.assertEqual(app.preview_state_var.get(), "Preview out of date")

    def test_output_change_with_touched_label_keeps_geometry_current(self) -> None:
        with _app() as app:
            result = _sample_boundary_result()
            app.shape_label_var.set("Custom Label")
            app._shape_label_touched = True
            app._last_displayed_result = result
            app._cached_result = result
            app._mark_preview_current()

            app.output_name_var.set("different_output")

            self.assertEqual(app.shape_label_var.get(), "Custom Label")
            self.assertFalse(app._preview_stale)
            self.assertIsNone(app._cached_result)

    def test_one_shape_output_change_with_default_label_keeps_geometry_current(
        self,
    ) -> None:
        with _app() as app:
            result = _sample_boundary_result()
            app.section_count_var.set("1")
            app._shape_label_touched = False
            app._refresh_shape_label_default(force=True)
            app._last_displayed_result = result
            app._cached_result = result
            app._mark_preview_current()

            app.output_name_var.set("new_default_label")

            self.assertEqual(app.shape_label_var.get(), "new_default_label")
            self.assertFalse(app._preview_stale)
            self.assertIsNone(app._cached_result)

    def test_multiple_shapes_output_change_with_default_label_marks_preview_stale(
        self,
    ) -> None:
        with _app() as app:
            result = _sample_boundary_result()
            app.section_count_var.set("2")
            app._shape_label_touched = False
            app._refresh_shape_label_default(force=True)
            app._last_displayed_result = result
            app._mark_preview_current()

            app.output_name_var.set("new_default_label")

            self.assertEqual(app.shape_label_var.get(), "new_default_label")
            self.assertTrue(app._preview_stale)

    def test_busy_preview_status_uses_unicode_ellipsis(self) -> None:
        with _app() as app:
            app._busy = True

            self.assertEqual(app._preview_status_text(), "Working…")

    def test_input_change_clears_previous_preview(self) -> None:
        with TemporaryDirectory() as tmp, _app() as app:
            result = _sample_boundary_result()
            app._last_displayed_result = result
            app._cached_result = result
            app._mark_preview_current()

            app.parent_var.set(str(Path(tmp)))

            self.assertIsNone(app._last_displayed_result)
            self.assertIsNone(app._cached_result)
            self.assertFalse(app._preview_stale)
            self.assertEqual(app.preview_state_var.get(), "No preview")

    def test_drop_is_ignored_while_busy(self) -> None:
        with TemporaryDirectory() as tmp, _app() as app:
            app.parent_var.set("unchanged")
            app._busy = True

            app._handle_folder_drop(
                SimpleNamespace(widget=app.drop_label, data=str(Path(tmp)))
            )

            self.assertEqual(app.parent_var.get(), "unchanged")
            self.assertIn("Please wait", app.status_var.get())

    def test_busy_state_disables_mutations_and_restores_dependencies(self) -> None:
        with TemporaryDirectory() as tmp, _app() as app:
            app.parent_var.set(str(Path(tmp)))
            app.section_count_var.set("1")
            app._set_busy(True, "Working")

            for widget in app._all_mutation_widgets + app._busy_action_widgets:
                self.assertEqual(str(widget.cget("state")), "disabled")
            self.assertTrue(app.busy_progress.grid_info())

            app._set_busy(False, "Ready")

            self.assertEqual(str(app.scan_button.cget("state")), "normal")
            self.assertEqual(str(app.outline_mode_combo.cget("state")), "readonly")
            self.assertEqual(
                str(app.simplify_vector_checkbutton.cget("state")),
                "disabled",
            )
            self.assertEqual(str(app.overlap_entry.cget("state")), "disabled")
            self.assertFalse(app.busy_progress.grid_info())

    def test_shortcuts_do_not_start_work_while_busy(self) -> None:
        with _app() as app:
            app._scan_clicked = Mock()
            app._export_clicked = Mock()
            app._busy = True

            self.assertEqual(app._shortcut_update_preview(), "break")
            self.assertEqual(app._shortcut_export(), "break")
            app._scan_clicked.assert_not_called()
            app._export_clicked.assert_not_called()

    def test_focus_mode_reuses_canvas_and_restores_withdrawn_state(self) -> None:
        with _app() as app:
            canvas = app.canvas
            callbacks = tuple(app._preview_event_cids)
            original_geometry = app.root.geometry()

            app._enter_focus_mode()
            app._exit_focus_mode()

            self.assertIs(app.canvas, canvas)
            self.assertEqual(tuple(app._preview_event_cids), callbacks)
            self.assertEqual(app.root.state(), "withdrawn")
            self.assertEqual(app.root.geometry(), original_geometry)

    def test_focus_mode_retains_controls_and_escape_closes_overlay_first(self) -> None:
        with _app() as app:
            canvas = app.canvas
            app._enter_focus_mode()
            app._toggle_settings_drawer()

            self.assertTrue(app._focus_mode)
            self.assertTrue(app._settings_drawer_open)
            self.assertTrue(app.settings_button.grid_info())
            self.assertTrue(app.key_button.grid_info())
            self.assertTrue(app.expand_preview_button.grid_info())
            self.assertTrue(app.scan_button.grid_info())
            self.assertTrue(app.export_button.grid_info())

            app._shortcut_escape()

            self.assertFalse(app._settings_drawer_open)
            self.assertTrue(app._focus_mode)
            self.assertIs(app.canvas, canvas)

            app._shortcut_escape()

            self.assertFalse(app._focus_mode)
            self.assertIs(app.canvas, canvas)

    def test_focus_mode_falls_back_when_zoomed_outer_bounds_escape_work_area(
        self,
    ) -> None:
        with _app() as app:
            work_area = WorkArea(0, 0, 1200, 700)
            outside = OuterWindowBounds(-8, -8, 1208, 708)
            with (
                patch.object(
                    gui_module,
                    "get_window_work_area",
                    return_value=work_area,
                ),
                patch.object(
                    gui_module,
                    "get_outer_window_bounds",
                    return_value=outside,
                ),
                patch.object(gui_module, "fit_window_to_work_area") as fit_window,
            ):
                app._enter_focus_mode()

            fit_window.assert_called_once_with(
                app.root,
                work_area,
                max_fraction=0.94,
            )

    def test_scan_validation_dialog_is_parented_to_root(self) -> None:
        with _app() as app, patch.object(
            gui_module.messagebox,
            "showerror",
        ) as showerror:
            app._scan_clicked()

            showerror.assert_called_once()
            self.assertIs(showerror.call_args.kwargs["parent"], app.root)

    def test_browse_cancel_is_parented_and_preserves_input(self) -> None:
        with _app() as app, patch.object(
            gui_module.filedialog,
            "askdirectory",
            return_value="",
        ) as askdirectory:
            before = app.parent_var.get()
            app._browse_parent()

            askdirectory.assert_called_once()
            self.assertIs(askdirectory.call_args.kwargs["parent"], app.root)
            self.assertEqual(app.parent_var.get(), before)

    def test_vector_and_save_browse_cancel_are_parented_and_preserve_values(
        self,
    ) -> None:
        with _app() as app:
            input_before = app.parent_var.get()
            output_before = app.output_var.get()
            with (
                patch.object(
                    gui_module.filedialog,
                    "askopenfilename",
                    return_value="",
                ) as askopenfilename,
                patch.object(
                    gui_module.filedialog,
                    "asksaveasfilename",
                    return_value="",
                ) as asksaveasfilename,
            ):
                app._browse_kmz()
                app._browse_output()

            self.assertIs(
                askopenfilename.call_args.kwargs["parent"],
                app.root,
            )
            self.assertIs(
                asksaveasfilename.call_args.kwargs["parent"],
                app.root,
            )
            self.assertEqual(app.parent_var.get(), input_before)
            self.assertEqual(app.output_var.get(), output_before)

    def test_export_validation_and_overwrite_dialogs_are_parented(self) -> None:
        with _app() as app, patch.object(
            gui_module.messagebox,
            "showerror",
        ) as showerror:
            app._export_clicked()

            showerror.assert_called_once()
            self.assertIs(showerror.call_args.kwargs["parent"], app.root)

        with TemporaryDirectory() as tmp, _app() as app:
            input_folder = Path(tmp) / "input"
            input_folder.mkdir()
            output_path = Path(tmp) / "existing.kmz"
            output_path.write_bytes(b"existing")
            app.parent_var.set(str(input_folder))
            app.output_var.set(str(output_path))

            with patch.object(
                gui_module.messagebox,
                "askyesno",
                return_value=False,
            ) as askyesno:
                app._export_clicked()

            askyesno.assert_called_once()
            self.assertIs(askyesno.call_args.kwargs["parent"], app.root)

    def test_surface_styles_match_card_backgrounds_and_aliases(self) -> None:
        with _app() as app:
            style = app._theme_style
            for style_name in (
                "Title.TLabel",
                "Secondary.TLabel",
                "Muted.TLabel",
                "Surface.TCheckbutton",
            ):
                with self.subTest(style=style_name):
                    self.assertEqual(
                        style.lookup(style_name, "background"),
                        PALETTE.SURFACE,
                    )
            self.assertEqual(
                style.lookup("Muted.TLabel", "foreground"),
                PALETTE.TEXT_SECONDARY,
            )
            self.assertGreaterEqual(
                _contrast_ratio(PALETTE.TEXT_SECONDARY, PALETTE.SURFACE),
                4.5,
            )
            self.assertGreaterEqual(
                _contrast_ratio(PALETTE.ERROR_TEXT, PALETTE.SURFACE),
                4.5,
            )
            self.assertEqual(
                str(app.simplify_vector_checkbutton.cget("style")),
                "Surface.TCheckbutton",
            )

            style_tk_label(app.drop_label, surface="surface")
            self.assertEqual(app.drop_label.cget("background"), PALETTE.SURFACE)

    def test_native_chrome_failure_is_nonfatal(self) -> None:
        with (
            patch.object(theme_module.sys, "platform", "win32"),
            patch.object(
                theme_module,
                "get_toplevel_hwnd",
                side_effect=OSError("unavailable"),
            ),
        ):
            self.assertFalse(theme_module.apply_windows_native_chrome(Mock()))

    def test_dark_theme_survives_empty_and_result_redraw(self) -> None:
        with _app() as app:
            app._draw_preview(_sample_boundary_result())
            app._draw_empty_preview()
            app._draw_preview(_sample_boundary_result())

            self.assertEqual(
                app.figure.get_facecolor(),
                to_rgba(PALETTE.BACKGROUND_DEEP),
            )
            self.assertEqual(
                app.axes.get_facecolor(),
                to_rgba(PALETTE.BACKGROUND_DEEP),
            )

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

    def test_inspector_reopen_lifts_existing_window(self) -> None:
        with _app() as app:
            app._open_fullscreen_preview()
            first_window = app._fullscreen_window
            assert first_window is not None
            first_canvas = app._fullscreen_canvas
            first_window.lift = Mock()
            first_window.focus_force = Mock()
            app._maximize_fullscreen_window = Mock()

            app._open_fullscreen_preview()

            self.assertIs(app._fullscreen_window, first_window)
            self.assertIs(app._fullscreen_canvas, first_canvas)
            app._maximize_fullscreen_window.assert_called_once_with(first_window)
            first_window.lift.assert_called_once()
            first_window.focus_force.assert_called_once()

    def test_inspector_opened_while_busy_disables_mutations_and_apply(self) -> None:
        with _app() as app:
            app._set_busy(True, "Working")
            app._open_fullscreen_preview()

            self.assertEqual(
                str(app._fullscreen_apply_button.cget("state")),
                "disabled",
            )
            for widget in app._fullscreen_mutation_widgets:
                with self.subTest(widget=str(widget)):
                    self.assertEqual(str(widget.cget("state")), "disabled")

    def test_inspector_draws_last_displayed_result_after_cache_invalidation(self) -> None:
        with _app() as app:
            result = _sample_boundary_result()
            app._last_displayed_result = result
            app._cached_result = None
            app._preview_stale = True
            app._stale_reason = "Buffer changed."

            app._open_fullscreen_preview()

            self.assertTrue(app._fullscreen_window_exists())
            self.assertGreater(len(app._fullscreen_axes.lines), 0)
            self.assertIn("Preview out of date", app._fullscreen_status_var.get())

    def test_inspector_key_wheel_targets_its_own_canvas(self) -> None:
        with _app() as app:
            app._open_fullscreen_preview()
            assert app.preview_key_canvas is not None
            assert app._fullscreen_key_canvas is not None
            assert app._fullscreen_key_content is not None
            main_scroll = Mock()
            inspector_scroll = Mock()
            app.preview_key_canvas.yview_scroll = main_scroll
            app._fullscreen_key_canvas.yview_scroll = inspector_scroll

            handler = app._preview_key_scroll_handler(
                app._fullscreen_key_content,
            )
            result = handler(SimpleNamespace(delta=-120))

            self.assertEqual(result, "break")
            inspector_scroll.assert_called_once_with(1, "units")
            main_scroll.assert_not_called()

    def test_preview_long_corridor_uses_full_axes_with_equal_map_scale(self) -> None:
        with _app() as app:
            result = _long_corridor_boundary_result()

            app._draw_preview(result)
            app.canvas.draw()

            xlim = app.axes.get_xlim()
            ylim = app.axes.get_ylim()
            self.assertEqual(app.axes.get_aspect(), 1.0)
            self.assertEqual(app.axes.get_adjustable(), "datalim")
            self.assertFalse(app.axes.axison)
            self.assertIsNone(app.axes.get_legend())
            self.assertGreater(len(app.preview_key_content.winfo_children()), 1)
            self.assertEqual(app.axes.get_position().bounds, (0.0, 0.0, 1.0, 1.0))
            self.assertLess(xlim[0], 0.0)
            self.assertGreater(xlim[1], 10000.0)
            self.assertLess(ylim[0], 0.0)
            self.assertGreater(ylim[1], 100.0)

    def test_fullscreen_long_corridor_uses_full_axes_with_equal_map_scale(self) -> None:
        with _app() as app:
            result = _long_corridor_boundary_result()
            app._cached_result = result

            app._open_fullscreen_preview()
            app._fullscreen_canvas.draw()

            xlim = app._fullscreen_axes.get_xlim()
            ylim = app._fullscreen_axes.get_ylim()
            self.assertEqual(app._fullscreen_axes.get_aspect(), 1.0)
            self.assertEqual(app._fullscreen_axes.get_adjustable(), "datalim")
            self.assertFalse(app._fullscreen_axes.axison)
            self.assertIsNone(app._fullscreen_axes.get_legend())
            self.assertGreater(len(app._fullscreen_key_content.winfo_children()), 1)
            self.assertEqual(
                app._fullscreen_axes.get_position().bounds,
                (0.0, 0.0, 1.0, 1.0),
            )
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
                simplify_vector_output,
            ) -> None:
                captured.update(
                    input_path=input_path,
                    buffer_ft=buffer_ft,
                    section_count=section_count,
                    overlap_ft=overlap_ft,
                    shape_label=shape_label,
                    outline_mode=outline_mode,
                    split_direction_deg=split_direction_deg,
                    simplify_vector_output=simplify_vector_output,
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
            self.assertFalse(captured["simplify_vector_output"])

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

    def test_export_done_marks_preview_current_and_keeps_result_visible(self) -> None:
        with TemporaryDirectory() as tmp, _app() as app:
            result = _sample_boundary_result()
            saved_path = Path(tmp) / "saved.kmz"
            app._last_displayed_result = result
            app._mark_preview_stale("Buffer changed.")
            app._queue.put(("export_done", (result, saved_path)))

            with patch.object(app, "_show_export_success") as show_success:
                app._drain_queue()

            self.assertIs(app._last_displayed_result, result)
            self.assertIs(app._cached_result, result)
            self.assertFalse(app._preview_stale)
            self.assertEqual(app.preview_state_var.get(), "Preview current")
            show_success.assert_called_once_with(saved_path)

    def test_error_keeps_displayed_result_and_shows_explicit_error_state(self) -> None:
        with _app() as app, patch.object(
            gui_module.messagebox,
            "showerror",
        ) as showerror:
            result = _sample_boundary_result()
            app._last_displayed_result = result
            app._mark_preview_current()
            app._set_busy(True, "Working")
            app._queue.put(("error", RuntimeError("synthetic failure")))

            app._drain_queue()

            self.assertFalse(app._busy)
            self.assertIs(app._last_displayed_result, result)
            self.assertEqual(app.preview_state_var.get(), "Preview error")
            self.assertEqual(
                str(app.preview_state_label.cget("style")),
                "Error.Status.TLabel",
            )
            self.assertIn("Error: synthetic failure", app.status_var.get())
            self.assertEqual(str(app.scan_button.cget("state")), "normal")
            self.assertEqual(str(app.export_button.cget("state")), "normal")
            showerror.assert_called_once()


class _app:
    def __enter__(self) -> BoundaryKmzApp:
        self.root = _create_root()
        self.root.withdraw()
        self.app = BoundaryKmzApp(self.root)
        return self.app

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self.app.canvas.draw()
            if self.app._fullscreen_canvas is not None:
                self.app._fullscreen_canvas.draw()
            self.root.update_idletasks()
        except Exception:
            pass
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


def _contrast_ratio(foreground: str, background: str) -> float:
    def relative_luminance(color: str) -> float:
        channels = to_rgba(color)[:3]
        linear = [
            value / 12.92
            if value <= 0.04045
            else ((value + 0.055) / 1.055) ** 2.4
            for value in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    lighter, darker = sorted(
        (
            relative_luminance(foreground),
            relative_luminance(background),
        ),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


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
