from __future__ import annotations

import math
import sys
from collections import deque
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from zipfile import ZipFile

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
from jpg_boundary_gui_basemap import (  # noqa: E402
    BasemapFailure,
    BasemapFrame,
    ProjectedView,
    VIEW_DEBOUNCE_MS,
)
from jpg_boundary_kmz_gui import (  # noqa: E402
    ACTION_BAR_MIN_BREAKPOINT,
    BoundaryKmzApp,
    PREVIEW_MAX_PLOT_POINTS,
    _create_root,
)
from jpg_boundary_gui_theme import PALETTE, style_tk_label  # noqa: E402
from jpg_boundary_gui_window import OuterWindowBounds, WorkArea  # noqa: E402


class GuiInputTests(TestCase):
    def test_loading_folder_starts_zero_buffer_auto_preview(self) -> None:
        with TemporaryDirectory() as tmp, _app() as app, patch.object(app, "_start_preview_generation") as start:
            app.buffer_var.set("75")
            app.outline_mode_var.set("Concave hull")
            with patch.object(gui_module.filedialog, "askdirectory", return_value=tmp):
                app._browse_parent()
            self.assertEqual(start.call_count, 1)
            self.assertEqual(start.call_args.args[0:2], (Path(tmp), 0.0))
            self.assertEqual(app.outline_mode_var.get(), "Auto")
            app.buffer_var.set("12")
            app._commit_input_entry()
            self.assertEqual(start.call_count, 1)
            self.assertEqual(app.buffer_var.get(), "12")

    def test_committed_and_dropped_inputs_start_preview_once(self) -> None:
        with TemporaryDirectory() as tmp, _app() as app, patch.object(app, "_start_preview_generation") as start:
            app.parent_var.set(tmp)
            start.assert_not_called()
            app._commit_input_entry()
            app._commit_input_entry()
            self.assertEqual(start.call_count, 1)
            app._handle_folder_drop(SimpleNamespace(widget=app.drop_label, data=app.root.tk.call("list", tmp)))
            self.assertEqual(start.call_count, 2)
            self.assertEqual(start.call_args.args[1], 0.0)

    def test_loaded_vectors_render_at_zero_or_auto_minimum(self) -> None:
        geometries = {
            "polygon": "<Polygon><outerBoundaryIs><LinearRing><coordinates>-97,32 -96.999,32 -96.999,32.001 -97,32.001 -97,32</coordinates></LinearRing></outerBoundaryIs></Polygon>",
            "line": "<LineString><coordinates>-97,32 -96.999,32</coordinates></LineString>",
        }
        for kind, geometry in geometries.items():
            with self.subTest(kind=kind), TemporaryDirectory() as tmp, _app() as app:
                source = Path(tmp) / "input.kml"
                source.write_text(f'<kml xmlns="http://www.opengis.net/kml/2.2"><Placemark>{geometry}</Placemark></kml>')
                with patch.object(gui_module.threading, "Thread") as worker, patch.object(
                    gui_module.filedialog, "askopenfilename", return_value=str(source)
                ):
                    app._browse_kmz()
                    self.assertTrue(app._busy)
                    self.assertEqual(worker.call_args.kwargs["args"][1], 0.0)
                    worker.return_value.start.assert_called_once()
                    # Run the captured worker deterministically, then use the real
                    # result queue and preview drawing path, without a modal dialog.
                    worker.call_args.kwargs["target"](*worker.call_args.kwargs["args"])
                with patch.object(gui_module.messagebox, "showerror") as error:
                    app._drain_queue()
                    error.assert_not_called()
                self.assertFalse(app._busy)
                self.assertEqual(app.preview_state_var.get(), "Preview current")
                result = app._last_displayed_result
                self.assertIsNotNone(result)
                if kind == "polygon":
                    self.assertEqual(result.metadata.buffer_ft, 0)
                    self.assertEqual(app.buffer_var.get(), "0")
                else:
                    self.assertGreater(result.metadata.buffer_ft, 0)
                    self.assertEqual(result.metadata.polyline_selected_buffer_ft,
                                     result.metadata.polyline_minimum_connected_buffer_ft)
                    self.assertAlmostEqual(float(app.buffer_var.get()), result.metadata.buffer_ft, places=2)

    def test_field_headers_remain_white_when_controls_are_disabled(self) -> None:
        with _app() as app:
            for label in (app.overlap_label, app.shape_label_label, app.split_direction_label,
                          app.outline_mode_label, app.quick_overlap_label):
                self.assertEqual(label.cget("style"), "Field.TLabel")
            for state in ((), ("disabled",)):
                self.assertEqual(app._theme_style.lookup("Field.TLabel", "foreground", state), PALETTE.TEXT)
                self.assertEqual(app._theme_style.lookup("Field.TLabel", "background", state), PALETTE.SURFACE)

    def test_settings_pages_and_custom_angle_follow_selection(self) -> None:
        with _app() as app:
            app._toggle_settings_panel("sections")
            self.assertEqual(app.settings_title.cget("text"), "Section settings")
            self.assertEqual([key for key, frame in app._settings_group_frames.items() if frame.grid_info()],
                             ["sections"])
            self.assertFalse(app.split_direction_custom_entry.grid_info())
            app.section_count_var.set("3")
            app.split_direction_var.set("Custom")
            self.assertTrue(app.split_direction_custom_entry.grid_info())
            app.split_direction_degrees_var.set("42")
            app._set_busy(True, "Building preview...")
            self.assertTrue(app.split_direction_custom_entry.grid_info())
            self.assertTrue(app.split_direction_custom_entry.instate(["disabled"]))
            app._set_busy(False, "Ready")
            self.assertEqual(app.split_direction_custom_entry.get(), "42")
            app._toggle_settings_panel("output")
            self.assertEqual(app.settings_title.cget("text"), "Export settings")
            self.assertEqual([key for key, frame in app._settings_group_frames.items() if frame.grid_info()],
                             ["output"])

    def test_rounded_native_fields_keep_editing_and_arrow_hit_targets(self) -> None:
        with _app() as app:
            app._toggle_settings_panel("sections")
            app.root.update_idletasks()
            spin = app.section_count_spinbox
            for suffix, delta in (("uparrow", 1), ("downarrow", -1)):
                target = next((x, y) for x in range(spin.winfo_width()) for y in range(spin.winfo_height())
                              if spin.identify(x, y).endswith(suffix))
                before = int(spin.get())
                spin.event_generate("<ButtonPress-1>", x=target[0], y=target[1])
                spin.event_generate("<ButtonRelease-1>", x=target[0], y=target[1])
                self.assertEqual(int(spin.get()), before + delta)
            app._toggle_settings_panel("input")
            entry = app.buffer_entry
            entry.delete(0, "end")
            entry.insert(0, "25")
            self.assertEqual(app.buffer_var.get(), "25")
            entry.state(["disabled"])
            entry.insert("end", "9")
            self.assertEqual(entry.get(), "25")
            app.root.update_idletasks()
            combo = app.outline_mode_combo
            self.assertTrue(combo.instate(["readonly"]))
            self.assertTrue(any(combo.identify(x, combo.winfo_height() // 2).endswith("downarrow")
                                for x in range(combo.winfo_width())))

    def test_welcome_card_does_not_extend_under_settings(self) -> None:
        for geometry, visible in (("1440x900+0+0", True), ("720x500+0+0", False)):
            with self.subTest(geometry=geometry):
                root = _create_root()
                root.withdraw()
                root.geometry(geometry)
                try:
                    app = BoundaryKmzApp(root)
                    app._toggle_settings_panel("input")
                    root.update_idletasks()
                    self.assertEqual(bool(app.empty_input_overlay.place_info()), visible)
                    if visible:
                        self.assertLessEqual(app.empty_input_overlay.winfo_x() + app.empty_input_overlay.winfo_width(),
                                             app.settings_drawer.winfo_x())
                    app._close_settings_drawer()
                    self.assertTrue(app.empty_input_overlay.place_info())
                finally:
                    _destroy_test_root(root)

    def test_named_settings_menus_preserve_preview_and_show_selected_group(self) -> None:
        with _app() as app:
            result = _sample_boundary_result()
            app._cached_result = result
            for group, button in (("input", app.settings_button), ("sections", app.sections_settings_button),
                                  ("output", app.output_settings_button)):
                app._toggle_view_menu()
                button.invoke()
                self.assertFalse(app._view_menu_open)
                self.assertTrue(app._settings_drawer_open)
                self.assertEqual(app._active_settings_group, group)
                self.assertEqual(button.cget("style"), "Primary.TButton")
                self.assertIs(app._cached_result, result)
                button.invoke()
                self.assertFalse(app._settings_drawer_open)
                self.assertEqual(button.cget("style"), "Ghost.TButton")

    def test_view_menu_escape_closes_only_the_menu(self) -> None:
        with _app() as app:
            app._toggle_view_menu()
            self.assertTrue(app.view_menu.place_info())
            app._shortcut_escape()
            self.assertFalse(app._view_menu_open)
            self.assertFalse(app.view_menu.place_info())
            self.assertTrue(app.root.winfo_exists())

    def test_busy_feedback_is_inline_and_blocks_duplicate_work(self) -> None:
        with _app() as app, patch.object(app, "_read_inputs") as read_inputs:
            app._set_busy(True, "Exporting KMZ...")
            self.assertTrue(app.activity_overlay.place_info())
            self.assertIsNotNone(app._busy_after_id)
            self.assertIn("background", app.activity_detail.cget("text"))
            self.assertEqual(app.export_button.cget("text"), "Exporting…")
            app._scan_clicked()
            app._export_clicked()
            read_inputs.assert_not_called()
            app._set_busy(False, "KMZ exported.")
            self.assertIsNone(app._busy_after_id)
            self.assertFalse(app.activity_overlay.place_info())
            self.assertEqual(app.export_button.cget("text"), "Export KMZ")

    def test_export_completion_does_not_open_modal_and_links_saved_folder(self) -> None:
        with _app() as app, TemporaryDirectory() as tmp:
            saved = Path(tmp) / "boundary.kmz"
            with patch.object(gui_module.tk, "Toplevel") as dialog:
                app._show_export_success(saved)
                dialog.assert_not_called()
            self.assertTrue(app.open_export_button.grid_info())
            self.assertIn(saved.name, app.status_var.get())
            app.output_var.set(str(Path(tmp) / "elsewhere" / "next.kmz"))
            with patch.object(app, "_open_output_folder") as open_folder:
                app.open_export_button.invoke()
                open_folder.assert_called_once_with(saved.parent)

    def test_responsive_controls_fit_at_normal_and_large_text_scaling(self) -> None:
        for width, height, scaling in ((720, 500, 1.333), (960, 600, 1.333), (1100, 760, 2.0)):
            with self.subTest(width=width, height=height, scaling=scaling):
                root = _create_root()
                root.withdraw()
                previous_scaling = root.tk.call("tk", "scaling")
                root.tk.call("tk", "scaling", scaling)
                root.geometry(f"{width}x{height}+0+0")
                try:
                    app = BoundaryKmzApp(root)
                    root.update_idletasks()
                    app._refresh_workspace_layout()
                    root.update_idletasks()
                    for widget in (app.change_input_button, app.settings_button, app.sections_settings_button,
                                   app.output_settings_button, app.view_button, app.scan_button, app.export_button):
                        right = widget.winfo_rootx() - root.winfo_rootx() + widget.winfo_width()
                        bottom = widget.winfo_rooty() - root.winfo_rooty() + widget.winfo_height()
                        self.assertLessEqual(right, width)
                        self.assertLessEqual(bottom, height)
                    self.assertLessEqual(app.empty_input_overlay.winfo_reqheight(), app.preview_stack.winfo_height())
                    app._toggle_settings_panel("sections")
                    root.update_idletasks()
                    self.assertLessEqual(app.settings_drawer.winfo_width(), app.preview_stack.winfo_width())
                finally:
                    root.tk.call("tk", "scaling", previous_scaling)
                    _destroy_test_root(root)

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
            _destroy_test_root(root)

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
            _destroy_test_root(root)

    def test_preview_workspace_meets_planned_size_targets(self) -> None:
        for geometry, minimum in (
            ("1440x741+0+0", (1360, 400)),
            ("1440x612+0+0", (1360, 300)),
            ("960x600+0+0", (900, 280)),
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
                    _destroy_test_root(root)

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
                PALETTE.BACKGROUND,
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
            ("1440x900+0+0", False),
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
                    _destroy_test_root(root)

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
                        style.lookup(style_name, "background", ("disabled",)),
                        PALETTE.SURFACE,
                    )
            self.assertEqual(app.settings_canvas.cget("background"), PALETTE.SURFACE)
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

    def test_preview_result_draws_vectors_and_scale_without_waiting_for_imagery(
        self,
    ) -> None:
        with _app() as app, _AfterRecorder(app.root) as scheduled:
            result = _sample_boundary_result()

            app._draw_preview(result)
            app.canvas.draw()

            surface = app._main_map_surface
            assert surface is not None
            self.assertGreater(len(_vector_artists(surface.axes)), 0)
            self.assertEqual(len(_scale_artists(surface.axes)), 4)
            self.assertEqual(app._test_basemap_factory.call_count, 0)
            self.assertIsNotNone(surface.debounce_after_id)

            scheduled.fire_surface(surface)

            client = app._test_basemap_factory.client
            self.assertEqual(app._test_basemap_factory.call_count, 1)
            self.assertEqual(len(client.submissions), 1)
            self.assertGreater(len(_vector_artists(surface.axes)), 0)
            self.assertEqual(len(_scale_artists(surface.axes)), 4)

    def test_valid_basemap_frame_applies_below_vectors_without_mutating_view(
        self,
    ) -> None:
        with _app() as app:
            result = _sample_boundary_result()
            app._draw_preview(result)
            app.canvas.draw()
            surface = app._main_map_surface
            assert surface is not None
            view = app._current_projected_view(surface)
            assert view is not None
            before_view = _view_snapshot(surface.axes)
            before_vectors = _vector_snapshot(surface.axes)

            app._apply_basemap_frame(_frame_for(view))

            self.assertEqual(surface.status_var.get(), "")
            self.assertEqual(len(surface.axes.images), 1)
            image = surface.axes.images[0]
            self.assertEqual(image.get_zorder(), -100)
            self.assertEqual(list(image.sticky_edges.x), [])
            self.assertEqual(list(image.sticky_edges.y), [])
            self.assertEqual(_view_snapshot(surface.axes), before_view)
            self.assertEqual(_vector_snapshot(surface.axes), before_vectors)

            app._apply_basemap_frame(_frame_for(view, partial=True))

            self.assertEqual(surface.status_var.get(), "Imagery partial")
            self.assertEqual(len(surface.axes.images), 1)
            self.assertEqual(_view_snapshot(surface.axes), before_view)
            self.assertEqual(_vector_snapshot(surface.axes), before_vectors)

            surface.axes.autoscale_view()
            image_home = (
                surface.axes.get_xlim(),
                surface.axes.get_ylim(),
            )
            app._draw_preview(result)
            surface.axes.autoscale_view()
            vector_home = (
                surface.axes.get_xlim(),
                surface.axes.get_ylim(),
            )
            self.assertEqual(image_home, vector_home)

    def test_imagery_toggle_restores_original_background_and_retains_scale(
        self,
    ) -> None:
        with _app() as empty_app, _AfterRecorder(empty_app.root):
            empty_app.world_imagery_var.set(False)
            empty_app.world_imagery_var.set(True)
            self.assertEqual(empty_app._test_basemap_factory.call_count, 0)
            self.assertEqual(
                empty_app._test_basemap_factory.client.reset_calls,
                0,
            )

        with _app() as lazy_app, _AfterRecorder(lazy_app.root) as lazy_scheduled:
            lazy_app._draw_preview(_sample_boundary_result())
            lazy_surface = lazy_app._main_map_surface
            assert lazy_surface is not None
            self.assertEqual(lazy_app._test_basemap_factory.call_count, 0)

            lazy_app.world_imagery_var.set(False)
            lazy_app.world_imagery_var.set(True)

            self.assertEqual(lazy_app._test_basemap_factory.call_count, 0)
            self.assertEqual(
                lazy_app._test_basemap_factory.client.reset_calls,
                0,
            )
            self.assertEqual(
                lazy_surface.status_var.get(),
                "Imagery loading...",
            )
            lazy_scheduled.fire_surface(lazy_surface)
            self.assertEqual(lazy_app._test_basemap_factory.call_count, 1)
            self.assertEqual(
                len(lazy_app._test_basemap_factory.client.submissions),
                1,
            )

        with _app() as app, _AfterRecorder(app.root) as scheduled:
            result = _sample_boundary_result()
            app._cached_result = result
            app._cached_settings = ("sentinel",)  # type: ignore[assignment]
            app._draw_preview(result)
            app._open_fullscreen_preview()
            main = app._main_map_surface
            inspector = app._fullscreen_map_surface
            assert main is not None
            assert inspector is not None
            client = app._get_basemap_client()
            for surface in (main, inspector):
                view = app._current_projected_view(surface)
                assert view is not None
                app._apply_basemap_frame(_frame_for(view))
            main_scale = main.scale_controller
            inspector_scale = inspector.scale_controller
            main_debounce = main.debounce_after_id
            inspector_debounce = inspector.debounce_after_id
            self.assertIsNotNone(main_debounce)
            self.assertIsNotNone(inspector_debounce)

            before = {
                "queue": app._queue.qsize(),
                "busy": app._busy,
                "cache": app._cached_result,
                "settings": app._cached_settings,
                "accepted": app._accepted_result_generation,
                "active": app._active_result_generation,
                "output_name": app.output_name_var.get(),
                "output": app.output_var.get(),
                "main_vectors": _vector_snapshot(main.axes),
                "inspector_vectors": _vector_snapshot(inspector.axes),
                "main_limits": (main.axes.get_xlim(), main.axes.get_ylim()),
                "inspector_limits": (
                    inspector.axes.get_xlim(),
                    inspector.axes.get_ylim(),
                ),
            }
            generations = {
                main.surface_id: main.surface_generation,
                inspector.surface_id: inspector.surface_generation,
            }

            app.world_imagery_var.set(False)

            self.assertIn(main_debounce, scheduled.cancel_calls)
            self.assertIn(inspector_debounce, scheduled.cancel_calls)
            self.assertEqual(
                (main.axes.get_xlim(), main.axes.get_ylim()),
                before["main_limits"],
            )
            self.assertEqual(
                (inspector.axes.get_xlim(), inspector.axes.get_ylim()),
                before["inspector_limits"],
            )
            for surface, controller in (
                (main, main_scale),
                (inspector, inspector_scale),
            ):
                self.assertIsNone(surface.debounce_after_id)
                self.assertEqual(surface.status_var.get(), "Imagery off")
                self.assertIs(surface.scale_controller, controller)
                self.assertEqual(len(_scale_artists(surface.axes)), 4)
                self.assertEqual(len(surface.axes.images), 0)
                self.assertIsNone(surface.attribution_artist)
                self.assertIsNone(surface.last_submitted_signature)
                self.assertIsNone(surface.last_applied_signature)
                self.assertEqual(
                    surface.figure.get_facecolor(),
                    to_rgba(PALETTE.BACKGROUND_DEEP),
                )
                self.assertEqual(
                    surface.axes.get_facecolor(),
                    to_rgba(PALETTE.BACKGROUND_DEEP),
                )
            self.assertEqual(client.clear_cache_calls, 1)

            submissions = len(client.submissions)
            disabled_surface_state = {
                surface.surface_id: (
                    surface.surface_generation,
                    surface.last_submitted_signature,
                    surface.last_applied_signature,
                    surface.status_var.get(),
                )
                for surface in (main, inspector)
            }
            factory_calls = app._test_basemap_factory.call_count
            for after_id in (main_debounce, inspector_debounce):
                assert after_id is not None
                scheduled.fire_canceled(after_id)
            self.assertEqual(len(client.submissions), submissions)
            self.assertEqual(
                app._test_basemap_factory.call_count,
                factory_calls,
            )
            self.assertEqual(
                disabled_surface_state,
                {
                    surface.surface_id: (
                        surface.surface_generation,
                        surface.last_submitted_signature,
                        surface.last_applied_signature,
                        surface.status_var.get(),
                    )
                    for surface in (main, inspector)
                },
            )
            self.assertEqual(
                main.surface_generation,
                generations[main.surface_id] + 1,
            )
            self.assertEqual(
                inspector.surface_generation,
                generations[inspector.surface_id] + 1,
            )

            with patch.object(
                main.scale_controller,
                "refresh",
                wraps=main.scale_controller.refresh,
            ) as refresh_scale:
                for index, operation in enumerate(
                    (
                        "wheel",
                        "direct pan",
                        "Home",
                        "Back",
                        "Forward",
                        "toolbar Pan",
                        "rectangle Zoom",
                        "Focus resize",
                    ),
                    start=1,
                ):
                    with self.subTest(operation=operation):
                        main.axes.set_xlim(-4.0 - index, 104.0 + index)
                        app._on_preview_map_surface_event(main)
                self.assertGreaterEqual(refresh_scale.call_count, 8)
            inspector.axes.set_xlim(-8.0, 108.0)
            app._on_preview_map_surface_event(inspector)
            self.assertEqual(len(client.submissions), submissions)
            self.assertEqual(len(_scale_artists(main.axes)), 4)
            self.assertEqual(len(_scale_artists(inspector.axes)), 4)

            self.assertEqual(app._queue.qsize(), before["queue"])
            self.assertEqual(app._busy, before["busy"])
            self.assertIs(app._cached_result, before["cache"])
            self.assertEqual(app._cached_settings, before["settings"])
            self.assertEqual(app._accepted_result_generation, before["accepted"])
            self.assertEqual(app._active_result_generation, before["active"])
            self.assertEqual(app.output_name_var.get(), before["output_name"])
            self.assertEqual(app.output_var.get(), before["output"])
            self.assertEqual(_vector_snapshot(main.axes), before["main_vectors"])
            self.assertEqual(
                _vector_snapshot(inspector.axes),
                before["inspector_vectors"],
            )

            app.world_imagery_var.set(True)

            self.assertEqual(client.reset_calls, 1)
            self.assertEqual(main.status_var.get(), "Imagery loading...")
            self.assertEqual(inspector.status_var.get(), "Imagery loading...")
            for surface in (main, inspector):
                self.assertIsNotNone(surface.debounce_after_id)
                scheduled.fire_surface(surface)
            self.assertEqual(len(client.submissions), submissions + 2)
            self.assertEqual(
                main.surface_generation,
                generations[main.surface_id] + 2,
            )
            self.assertEqual(
                inspector.surface_generation,
                generations[inspector.surface_id] + 2,
            )

    def test_all_navigation_paths_refresh_scale_and_schedule_one_debounced_view(
        self,
    ) -> None:
        with _app() as app, _AfterRecorder(app.root) as scheduled:
            app._draw_preview(_sample_boundary_result())
            surface = app._main_map_surface
            assert surface is not None
            initial_generation = surface.surface_generation
            initial_debounce = surface.debounce_after_id
            assert initial_debounce is not None
            scheduled.fire_surface(surface)
            client = app._test_basemap_factory.client
            self.assertEqual(len(client.submissions), 1)

            with patch.object(
                surface.scale_controller,
                "refresh",
                wraps=surface.scale_controller.refresh,
            ) as refresh_scale:
                xlim = surface.axes.get_xlim()
                ylim = surface.axes.get_ylim()
                center_x = sum(xlim) * 0.5
                center_y = sum(ylim) * 0.5
                app._on_preview_scroll(
                    SimpleNamespace(
                        inaxes=surface.axes,
                        xdata=center_x,
                        ydata=center_y,
                        step=1,
                        button="up",
                    )
                )
                surface.canvas.draw()

                app._on_preview_button_press(
                    SimpleNamespace(
                        inaxes=surface.axes,
                        xdata=center_x,
                        ydata=center_y,
                        x=100.0,
                        y=100.0,
                        button=1,
                    )
                )
                app._on_preview_mouse_move(
                    SimpleNamespace(
                        inaxes=surface.axes,
                        xdata=center_x,
                        ydata=center_y,
                        x=125.0,
                        y=118.0,
                    )
                )
                app._on_preview_button_release(SimpleNamespace())
                surface.canvas.draw()

                for index, operation in enumerate(
                    ("Home", "Back", "Forward", "Pan", "rectangle Zoom"),
                    start=1,
                ):
                    with self.subTest(operation=operation):
                        surface.axes.set_xlim(-float(index), 100.0 + index)
                        surface.axes.set_ylim(-float(index), 100.0 + index)
                        surface.canvas.draw()

                surface.canvas.resize(
                    SimpleNamespace(width=790, height=490)
                )
                surface.axes.set_xlim(-9.0, 109.0)
                surface.canvas.draw()
                self.assertGreaterEqual(refresh_scale.call_count, 9)

            pending = scheduled.pending_ids(VIEW_DEBOUNCE_MS)
            self.assertEqual(len(pending), 1)
            generation_before_fire = surface.surface_generation
            scheduled.fire_surface(surface)
            self.assertEqual(surface.surface_generation, generation_before_fire + 1)
            self.assertEqual(len(client.submissions), 2)
            self.assertEqual(
                client.submissions[-1].xlim,
                tuple(surface.axes.get_xlim()),
            )

            surface.canvas.draw()
            self.assertIsNone(surface.debounce_after_id)
            self.assertEqual(len(client.submissions), 2)
            self.assertEqual(initial_generation + 2, surface.surface_generation)

    def test_scale_changed_state_allows_only_one_guarded_followup_draw(self) -> None:
        with _app() as app, _AfterRecorder(app.root):
            app._draw_preview(_sample_boundary_result())
            surface = app._main_map_surface
            assert surface is not None
            with patch.object(surface.canvas, "draw_idle") as draw_idle, patch.object(
                surface.scale_controller,
                "refresh",
                side_effect=(True, False, True, False),
            ):
                app._on_preview_map_surface_event(surface)
                app._on_preview_map_surface_event(surface)
                app._on_preview_map_surface_event(surface)
                app._on_preview_map_surface_event(surface)

            self.assertEqual(draw_idle.call_count, 2)
            self.assertNotIn(surface.surface_id, app._surface_draw_guards)

    def test_focus_preview_reuses_main_map_surface(self) -> None:
        with _app() as app:
            result = _sample_boundary_result()
            app._draw_preview(result)
            surface = app._main_map_surface
            assert surface is not None
            view = app._current_projected_view(surface)
            assert view is not None
            app._apply_basemap_frame(_frame_for(view))
            controller = surface.scale_controller
            observer_ids = tuple(surface.observer_event_cids)
            direct_ids = tuple(app._preview_event_cids)
            image = surface.basemap_image
            scale_ids = tuple(id(artist) for artist in _scale_artists(surface.axes))
            generation = surface.surface_generation

            for _index in range(3):
                app._toggle_focus_mode()
                app._toggle_focus_mode()

            self.assertIs(app._main_map_surface, surface)
            self.assertIs(surface.scale_controller, controller)
            self.assertEqual(tuple(surface.observer_event_cids), observer_ids)
            self.assertEqual(tuple(app._preview_event_cids), direct_ids)
            self.assertIs(surface.basemap_image, image)
            self.assertEqual(
                tuple(id(artist) for artist in _scale_artists(surface.axes)),
                scale_ids,
            )
            self.assertEqual(surface.surface_generation, generation)

    def test_inspector_has_independent_view_with_shared_client_cache_and_preference(
        self,
    ) -> None:
        with _app() as app, _AfterRecorder(app.root) as scheduled:
            result = _sample_boundary_result()
            app._cached_result = result
            app._draw_preview(result)
            app._open_fullscreen_preview()
            main = app._main_map_surface
            inspector = app._fullscreen_map_surface
            assert main is not None
            assert inspector is not None
            main_limits = (main.axes.get_xlim(), main.axes.get_ylim())
            inspector.axes.set_xlim(120.0, -20.0)
            inspector.axes.set_ylim(70.0, -20.0)

            self.assertIsNot(main, inspector)
            self.assertNotEqual(main.surface_id, inspector.surface_id)
            self.assertIsNot(main.scale_controller, inspector.scale_controller)
            self.assertNotEqual(tuple(main.axes.get_xlim()), tuple(inspector.axes.get_xlim()))
            self.assertEqual((main.axes.get_xlim(), main.axes.get_ylim()), main_limits)
            self.assertEqual(len(main.observer_event_cids), 2)
            self.assertEqual(len(inspector.observer_event_cids), 2)
            self.assertEqual(len(app._preview_event_cids), 4)
            self.assertEqual(len(app._fullscreen_event_cids), 4)
            self.assertEqual(
                str(app.world_imagery_checkbutton.cget("variable")),
                str(app.world_imagery_var),
            )
            assert app._fullscreen_imagery_checkbutton is not None
            self.assertEqual(
                str(app._fullscreen_imagery_checkbutton.cget("variable")),
                str(app.world_imagery_var),
            )

            for surface in (main, inspector):
                app._on_preview_map_surface_event(surface)
                scheduled.fire_surface(surface)

            self.assertEqual(app._test_basemap_factory.call_count, 1)
            self.assertIs(app._basemap_client, app._test_basemap_factory.client)
            self.assertEqual(
                {view.surface_id for view in app._basemap_client.submissions},
                {main.surface_id, inspector.surface_id},
            )
            self.assertIs(
                app._test_basemap_factory.client.cache_token,
                app._test_basemap_factory.client.cache_token,
            )
            self.assertEqual(
                app._test_basemap_factory.client.submission_cache_tokens,
                [
                    app._test_basemap_factory.client.cache_token,
                    app._test_basemap_factory.client.cache_token,
                ],
            )

            inspector_generation = inspector.surface_generation
            inspector_limits = (
                inspector.axes.get_xlim(),
                inspector.axes.get_ylim(),
            )
            main.axes.set_xlim(-30.0, 130.0)
            app._on_preview_map_surface_event(main)
            scheduled.fire_surface(main)

            self.assertGreater(main.surface_generation, inspector_generation)
            self.assertEqual(
                inspector.surface_generation,
                inspector_generation,
            )
            self.assertEqual(
                (inspector.axes.get_xlim(), inspector.axes.get_ylim()),
                inspector_limits,
            )
            for surface in (main, inspector):
                current = app._current_projected_view(surface)
                assert current is not None
                app._apply_basemap_frame(_frame_for(current))
            self.assertIsNot(main.basemap_image, inspector.basemap_image)
            self.assertIsNot(
                main.attribution_artist,
                inspector.attribution_artist,
            )

    def test_inspector_close_reopen_rejects_stale_responses_and_leaks_nothing(
        self,
    ) -> None:
        with _app() as app, _AfterRecorder(app.root) as scheduled:
            result = _sample_boundary_result()
            app._cached_result = result
            app._draw_preview(result)
            main = app._main_map_surface
            assert main is not None
            main_observers = tuple(main.observer_event_cids)
            client = app._get_basemap_client()
            old_frames: list[BasemapFrame] = []
            closed_ids: list[str] = []

            for _cycle in range(3):
                app._open_fullscreen_preview()
                inspector = app._fullscreen_map_surface
                assert inspector is not None
                self.assertEqual(len(inspector.observer_event_cids), 2)
                app._on_preview_map_surface_event(inspector)
                scheduled.fire_surface(inspector)
                old_view = client.submissions[-1]
                old_frames.append(_frame_for(old_view))
                old_id = inspector.surface_id
                closed_ids.append(old_id)
                app._apply_basemap_frame(old_frames[-1])
                self.assertEqual(len(inspector.axes.images), 1)
                old_canvas = inspector.canvas
                old_callback_ids = (
                    *inspector.observer_event_cids,
                    *app._fullscreen_event_cids,
                )
                inspector.axes.set_xlim(
                    inspector.axes.get_xlim()[0] - 1.0,
                    inspector.axes.get_xlim()[1] + 1.0,
                )
                app._on_preview_map_surface_event(inspector)
                pending_after_id = inspector.debounce_after_id
                assert pending_after_id is not None

                app._close_fullscreen_preview()

                self.assertIn(old_id, client.deregister_calls)
                self.assertIn(pending_after_id, scheduled.cancel_calls)
                self.assertNotIn(old_id, client.latest)
                self.assertIsNone(app._fullscreen_map_surface)
                self.assertEqual(tuple(main.observer_event_cids), main_observers)
                self.assertLessEqual(len(client.latest), 1)
                registered_callback_ids = {
                    callback_id
                    for callbacks in old_canvas.callbacks.callbacks.values()
                    for callback_id in callbacks
                }
                self.assertTrue(
                    set(old_callback_ids).isdisjoint(registered_callback_ids)
                )
                self.assertEqual(len(inspector.axes.images), 0)
                self.assertEqual(len(_scale_artists(inspector.axes)), 0)
                self.assertIsNone(inspector.attribution_artist)
                before_images = len(main.axes.images)
                app._apply_basemap_frame(old_frames[-1])
                self.assertEqual(len(main.axes.images), before_images)

            self.assertEqual(len(set(closed_ids)), 3)
            self.assertEqual(len(client.deregister_calls), 3)
            self.assertEqual(set(client.latest), {main.surface_id} & set(client.latest))

    def test_input_change_clears_optional_map_state_and_rejects_old_generation(
        self,
    ) -> None:
        with _app() as app:
            result = _sample_boundary_result()
            app._cached_result = result
            app._draw_preview(result)
            app._open_fullscreen_preview()
            main = app._main_map_surface
            inspector = app._fullscreen_map_surface
            assert main is not None
            assert inspector is not None
            client = app._get_basemap_client()
            old_frames: list[BasemapFrame] = []
            old_generations: dict[str, int] = {}
            for surface in (main, inspector):
                view = app._current_projected_view(surface)
                assert view is not None
                frame = _frame_for(view)
                app._apply_basemap_frame(frame)
                old_frames.append(frame)
                old_generations[surface.surface_id] = surface.surface_generation
                self.assertEqual(len(_scale_artists(surface.axes)), 4)
                self.assertEqual(len(surface.axes.images), 1)
            accepted_generation = app._accepted_result_generation

            app.parent_var.set("C:/different/input.kmz")

            for surface in (main, inspector):
                self.assertGreater(
                    surface.surface_generation,
                    old_generations[surface.surface_id],
                )
                self.assertIsNone(surface.result_generation)
                self.assertIsNone(surface.epsg)
                self.assertEqual(len(surface.axes.images), 0)
                self.assertEqual(len(_scale_artists(surface.axes)), 0)
                self.assertIsNone(surface.attribution_artist)
                self.assertEqual(surface.status_var.get(), "")
            self.assertEqual(client.clear_cache_calls, 1)
            self.assertEqual(app._accepted_result_generation, accepted_generation)
            self.assertIsNone(app._active_result_generation)

            for frame in old_frames:
                app._apply_basemap_frame(frame)
            self.assertEqual(len(main.axes.images), 0)
            self.assertEqual(len(inspector.axes.images), 0)

    def test_same_limits_new_result_generation_rejects_old_frame(self) -> None:
        with _app() as app:
            first = _sample_boundary_result()
            second = _sample_boundary_result()
            app._draw_preview(first)
            surface = app._main_map_surface
            assert surface is not None
            old_view = app._current_projected_view(surface)
            assert old_view is not None
            old_frame = _frame_for(old_view)
            old_result_generation = surface.result_generation
            limits = (surface.axes.get_xlim(), surface.axes.get_ylim())

            app._draw_preview(second)

            self.assertEqual(
                (surface.axes.get_xlim(), surface.axes.get_ylim()),
                limits,
            )
            self.assertNotEqual(surface.result_generation, old_result_generation)
            current_status = surface.status_var.get()
            app._apply_basemap_frame(old_frame)
            self.assertEqual(len(surface.axes.images), 0)
            self.assertEqual(surface.status_var.get(), current_status)
            self.assertIsNone(surface.last_applied_signature)

    def test_basemap_failure_is_nonmodal_and_isolated_from_processing_export(
        self,
    ) -> None:
        with _app() as app, patch.object(
            gui_module.messagebox,
            "showerror",
        ) as showerror:
            result = _sample_boundary_result()
            app._cached_result = result
            app._cached_settings = ("settings",)  # type: ignore[assignment]
            app._draw_preview(result)
            surface = app._main_map_surface
            assert surface is not None
            view = app._current_projected_view(surface)
            assert view is not None
            before = {
                "queue": app._queue.qsize(),
                "busy": app._busy,
                "cache": app._cached_result,
                "settings": app._cached_settings,
                "output_name": app.output_name_var.get(),
                "output": app.output_var.get(),
                "vectors": _vector_snapshot(surface.axes),
                "scale": tuple(id(item) for item in _scale_artists(surface.axes)),
            }

            for category in ("timeout", "http", "schema", "decode", "projection"):
                with self.subTest(category=category):
                    app._apply_basemap_frame(_frame_for(view))
                    failure = _failure_for(
                        view,
                        category=category * 80,
                        message="Provider diagnostic " * 40,
                    )
                    app._apply_basemap_failure(failure)
                    self.assertEqual(surface.status_var.get(), "Imagery unavailable")
                    self.assertEqual(len(surface.axes.images), 0)
                    diagnostic = app._basemap_diagnostics[surface.surface_id]
                    self.assertLessEqual(len(diagnostic[0]), 160)
                    self.assertLessEqual(len(diagnostic[1]), 160)
                    self.assertEqual(_vector_snapshot(surface.axes), before["vectors"])
                    self.assertEqual(
                        tuple(id(item) for item in _scale_artists(surface.axes)),
                        before["scale"],
                    )

            hostile_category = "provider-secret-category::DO-NOT-DISPLAY"
            provider_message_sentinel = "PROVIDER_MESSAGE_SENTINEL"
            provider_url_sentinel = "https://provider.invalid/private/error?id=8675309"
            app._apply_basemap_failure(
                _failure_for(
                    view,
                    category=hostile_category,
                    message=(
                        f"{provider_message_sentinel} "
                        f"{provider_url_sentinel}"
                    ),
                )
            )
            diagnostic = app._basemap_diagnostics[surface.surface_id]
            self.assertEqual(
                diagnostic,
                (
                    "imagery_error",
                    "Imagery is unavailable for this view.",
                ),
            )
            diagnostic_text = " ".join(diagnostic)
            for sentinel in (
                hostile_category,
                provider_message_sentinel,
                provider_url_sentinel,
                "provider.invalid",
                "8675309",
            ):
                with self.subTest(sentinel=sentinel):
                    self.assertNotIn(sentinel, diagnostic_text)

            current_status = surface.status_var.get()
            stale = replace(
                _failure_for(view),
                generation=view.generation - 1,
            )
            app._apply_basemap_failure(stale)
            self.assertEqual(surface.status_var.get(), current_status)
            self.assertEqual(app._queue.qsize(), before["queue"])
            self.assertEqual(app._busy, before["busy"])
            self.assertIs(app._cached_result, before["cache"])
            self.assertEqual(app._cached_settings, before["settings"])
            self.assertEqual(app.output_name_var.get(), before["output_name"])
            self.assertEqual(app.output_var.get(), before["output"])
            self.assertEqual(str(app.scan_button.cget("state")), "normal")
            self.assertEqual(str(app.export_button.cget("state")), "normal")
            showerror.assert_not_called()

    def test_repeated_draws_keep_exact_callback_and_artist_counts(self) -> None:
        with _app() as app:
            result = _sample_boundary_result()
            app._cached_result = result
            app._draw_preview(result)
            app._open_fullscreen_preview()
            main = app._main_map_surface
            inspector = app._fullscreen_map_surface
            assert main is not None
            assert inspector is not None
            direct_ids = tuple(app._preview_event_cids)
            inspector_direct_ids = tuple(app._fullscreen_event_cids)
            main_observers = tuple(main.observer_event_cids)
            inspector_observers = tuple(inspector.observer_event_cids)

            for _index in range(4):
                app._draw_preview(result)
                for surface in (main, inspector):
                    view = app._current_projected_view(surface)
                    assert view is not None
                    app._apply_basemap_frame(_frame_for(view))
                    self.assertEqual(len(surface.axes.images), 1)
                    self.assertEqual(len(_scale_artists(surface.axes)), 4)
                    self.assertEqual(len(_attribution_artists(surface.axes)), 1)

            self.assertEqual(len(app._preview_event_cids), 4)
            self.assertEqual(len(app._fullscreen_event_cids), 4)
            self.assertEqual(tuple(app._preview_event_cids), direct_ids)
            self.assertEqual(tuple(app._fullscreen_event_cids), inspector_direct_ids)
            self.assertEqual(tuple(main.observer_event_cids), main_observers)
            self.assertEqual(
                tuple(inspector.observer_event_cids),
                inspector_observers,
            )

    def test_attribution_remains_unobstructed_with_overlays_at_minimum_layout(
        self,
    ) -> None:
        with _app() as app:
            result = _sample_boundary_result()
            app._cached_result = result
            app.root.geometry("960x600+0+0")
            app.root.update()
            app._draw_preview(result)
            app._open_fullscreen_preview()
            assert app._fullscreen_window is not None
            app._fullscreen_window.geometry("640x420+20+20")
            app._fullscreen_window.event_generate(
                "<Configure>",
                width=640,
                height=420,
            )
            app._fullscreen_window.update()
            main = app._main_map_surface
            inspector = app._fullscreen_map_surface
            assert main is not None
            assert inspector is not None
            live_credit = (
                "Source: Esri, Vantor, Earthstar Geographics, "
                "and the GIS User Community"
            )
            credits = (
                live_credit,
                _exact_length_credit(500, multiword=True),
                "W" * 500,
            )

            def assert_credit_layout(
                surface,
                *,
                overlay_name: str,
                overlay: object | None = None,
            ) -> None:
                canvas_widget = surface.canvas.get_tk_widget()
                surface.canvas.resize(
                    SimpleNamespace(
                        width=max(1, canvas_widget.winfo_width()),
                        height=max(1, canvas_widget.winfo_height()),
                    )
                )
                for credit in credits:
                    with self.subTest(
                        surface=surface.surface_id,
                        overlay=overlay_name,
                        length=len(credit),
                    ):
                        view = app._current_projected_view(surface)
                        assert view is not None
                        app._apply_basemap_frame(_frame_for(view, credit=credit))
                        surface.canvas.draw()
                        artist = surface.attribution_artist
                        assert artist is not None
                        normalized = f"Powered by Esri | {credit}"
                        self.assertEqual(
                            "".join(artist.get_text().split()),
                            "".join(normalized.split()),
                        )
                        self.assertGreaterEqual(artist.get_fontsize(), 9.0)
                        renderer = surface.figure.canvas.get_renderer()
                        bbox = artist.get_window_extent(renderer=renderer)
                        figure_bbox = surface.figure.bbox
                        self.assertGreaterEqual(bbox.x0, figure_bbox.x0 - 1.0)
                        self.assertLessEqual(bbox.x1, figure_bbox.x1 + 1.0)
                        self.assertGreaterEqual(bbox.y0, figure_bbox.y0 - 1.0)
                        self.assertLessEqual(bbox.y1, figure_bbox.y1 + 1.0)
                        scale_bbox = _scale_artist_bbox(surface, renderer)
                        self.assertFalse(_bboxes_intersect(bbox, scale_bbox))
                        self.assertEqual(len(surface.axes.images), 1)
                        if overlay is not None:
                            self.assertLessEqual(
                                bbox.x1,
                                overlay.winfo_x() - 1.0,
                            )

            app._toggle_settings_drawer()
            app.root.update()
            self.assertTrue(app._settings_drawer_open)
            assert_credit_layout(
                main,
                overlay_name="Settings",
                overlay=app.settings_drawer,
            )
            app._toggle_settings_drawer()
            app._toggle_preview_key()
            app.root.update()
            self.assertTrue(app._legend_open)
            assert_credit_layout(
                main,
                overlay_name="Key",
                overlay=app.preview_key_overlay,
            )
            assert_credit_layout(
                inspector,
                overlay_name="Inspector Key",
            )

            inspector_controls = app._fullscreen_window.grid_slaves(
                row=0,
                column=0,
            )[0]
            for child in inspector_controls.winfo_children():
                with self.subTest(control=str(child)):
                    self.assertGreaterEqual(child.winfo_x(), 0)
                    self.assertLessEqual(
                        child.winfo_x() + child.winfo_width(),
                        inspector_controls.winfo_width() + 1,
                    )
            assert app._fullscreen_imagery_checkbutton is not None
            inspector_view_controls = app._fullscreen_imagery_checkbutton.master
            for child in inspector_view_controls.winfo_children():
                with self.subTest(toolbar_control=str(child)):
                    self.assertGreaterEqual(child.winfo_x(), 0)
                    self.assertLessEqual(
                        child.winfo_x() + child.winfo_width(),
                        inspector_view_controls.winfo_width() + 1,
                    )
            main_view_controls = app.world_imagery_checkbutton.master
            for child in main_view_controls.winfo_children():
                with self.subTest(main_toolbar_control=str(child)):
                    self.assertGreaterEqual(child.winfo_x(), 0)
                    self.assertLessEqual(
                        child.winfo_x() + child.winfo_width(),
                        main_view_controls.winfo_width() + 1,
                    )
            app._close_fullscreen_preview()

    def test_toolbar_save_contains_imagery_scale_and_attribution_artists(
        self,
    ) -> None:
        with _app() as app:
            result = _sample_boundary_result()
            app._draw_preview(result)
            surface = app._main_map_surface
            assert surface is not None
            view = app._current_projected_view(surface)
            assert view is not None
            app._apply_basemap_frame(_frame_for(view))
            image = surface.basemap_image
            attribution = surface.attribution_artist
            assert image is not None
            assert attribution is not None
            scale = _scale_artists(surface.axes)
            self.assertEqual(len(scale), 4)

            with (
                patch.object(gui_module, "save_kmz") as save_kmz,
                patch.object(image, "draw", wraps=image.draw) as image_draw,
                patch.object(
                    attribution,
                    "draw",
                    wraps=attribution.draw,
                ) as attribution_draw,
                patch.object(
                    scale[1],
                    "draw",
                    wraps=scale[1].draw,
                ) as scale_draw,
            ):
                output = BytesIO()
                app.preview_toolbar.canvas.figure.savefig(
                    output,
                    format="png",
                )
                save_kmz.assert_not_called()

            self.assertGreater(len(output.getvalue()), 100)
            image_draw.assert_called()
            attribution_draw.assert_called()
            scale_draw.assert_called()

            with TemporaryDirectory() as tmp:
                output_kmz = Path(tmp) / "vector-only.kmz"
                export_result = replace(
                    result,
                    metadata=replace(
                        result.metadata,
                        generation_profile=GENERATION_PROFILE_EXPORT,
                    ),
                )
                saved_kmz = gui_module.save_kmz(
                    export_result,
                    output_kmz,
                )
                with ZipFile(saved_kmz) as archive:
                    names = [name.lower() for name in archive.namelist()]
                self.assertTrue(any(name.endswith(".kml") for name in names))
                self.assertFalse(
                    any(
                        name.endswith(
                            (
                                ".png",
                                ".jpg",
                                ".jpeg",
                                ".gif",
                                ".tif",
                                ".tiff",
                                ".webp",
                            )
                        )
                        for name in names
                    )
                )


class _RecordingBasemapClient:
    def __init__(self) -> None:
        self.submissions: list[ProjectedView] = []
        self.submission_cache_tokens: list[object] = []
        self.responses: deque[BasemapFrame | BasemapFailure] = deque()
        self.cancel_calls: list[tuple[str, int]] = []
        self.deregister_calls: list[str] = []
        self.clear_cache_calls = 0
        self.reset_calls = 0
        self.shutdown_calls = 0
        self.latest: dict[str, ProjectedView] = {}
        self.cache_token = object()

    def submit(self, view: ProjectedView) -> None:
        self.submissions.append(view)
        self.submission_cache_tokens.append(self.cache_token)
        self.latest[view.surface_id] = view

    def cancel_surface(self, surface_id: str, minimum_generation: int) -> None:
        self.cancel_calls.append((surface_id, minimum_generation))
        current = self.latest.get(surface_id)
        if current is not None and current.generation < minimum_generation:
            self.latest.pop(surface_id, None)

    def deregister_surface(self, surface_id: str) -> None:
        self.deregister_calls.append(surface_id)
        self.latest.pop(surface_id, None)

    def poll(self) -> BasemapFrame | BasemapFailure | None:
        if not self.responses:
            return None
        return self.responses.popleft()

    def clear_cache(self) -> None:
        self.clear_cache_calls += 1

    def reset_transient_metadata_failure(self) -> None:
        self.reset_calls += 1

    def shutdown(self) -> None:
        self.shutdown_calls += 1


class _RecordingBasemapFactory:
    def __init__(self, client: _RecordingBasemapClient | None = None) -> None:
        self.client = client or _RecordingBasemapClient()
        self.call_count = 0

    def __call__(self) -> _RecordingBasemapClient:
        self.call_count += 1
        return self.client


def _destroy_test_root(root) -> None:
    try:
        pending = root.tk.splitlist(root.tk.call("after", "info"))
        for after_id in pending:
            root.after_cancel(after_id)
    except gui_module.tk.TclError:
        pass
    try:
        root.destroy()
    except gui_module.tk.TclError:
        pass


class _AfterRecorder:
    def __init__(self, root) -> None:
        self.root = root
        self.callbacks: dict[str, tuple[int, object, tuple[object, ...]]] = {}
        self.canceled: dict[str, tuple[int, object, tuple[object, ...]]] = {}
        self.cancel_calls: list[str] = []
        self._serial = 0
        self._after_patch = None
        self._cancel_patch = None

    def __enter__(self) -> "_AfterRecorder":
        self._after_patch = patch.object(
            self.root,
            "after",
            side_effect=self.after,
        )
        self._cancel_patch = patch.object(
            self.root,
            "after_cancel",
            side_effect=self.after_cancel,
        )
        self._after_patch.start()
        self._cancel_patch.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        assert self._cancel_patch is not None
        assert self._after_patch is not None
        self._cancel_patch.stop()
        self._after_patch.stop()

    def after(self, delay: int, callback=None, *args: object) -> str:
        self._serial += 1
        after_id = f"recorded-after-{self._serial}"
        if callback is not None:
            self.callbacks[after_id] = (int(delay), callback, args)
        return after_id

    def after_cancel(self, after_id: str) -> None:
        self.cancel_calls.append(after_id)
        callback = self.callbacks.pop(after_id, None)
        if callback is not None:
            self.canceled[after_id] = callback

    def pending_ids(self, delay: int | None = None) -> list[str]:
        return [
            after_id
            for after_id, (recorded_delay, _callback, _args) in self.callbacks.items()
            if delay is None or recorded_delay == delay
        ]

    def fire(self, after_id: str) -> None:
        _delay, callback, args = self.callbacks.pop(after_id)
        callback(*args)

    def fire_surface(self, surface) -> None:
        after_id = surface.debounce_after_id
        if after_id is None:
            raise AssertionError("Surface has no pending debounce callback.")
        self.fire(after_id)

    def fire_canceled(self, after_id: str) -> None:
        _delay, callback, args = self.canceled[after_id]
        callback(*args)


class _app:
    def __init__(
        self,
        basemap_factory: _RecordingBasemapFactory | None = None,
    ) -> None:
        self.factory = basemap_factory or _RecordingBasemapFactory()

    def __enter__(self) -> BoundaryKmzApp:
        self._inspector_display_patches = [
            patch.object(
                BoundaryKmzApp,
                "_maximize_fullscreen_window",
                autospec=True,
                return_value=None,
            ),
            patch.object(
                gui_module.tk.Toplevel,
                "deiconify",
                autospec=True,
                side_effect=lambda window: window.withdraw(),
            ),
            patch.object(
                gui_module.tk.Toplevel,
                "focus_set",
                autospec=True,
                return_value=None,
            ),
            patch.object(
                gui_module.tk.Toplevel,
                "focus_force",
                autospec=True,
                return_value=None,
            ),
            patch.object(
                gui_module.tk.Toplevel,
                "lift",
                autospec=True,
                return_value=None,
            ),
        ]
        for display_patch in self._inspector_display_patches:
            display_patch.start()
        try:
            self.root = _create_root()
            self.root.withdraw()
            self.app = BoundaryKmzApp(
                self.root,
                basemap_client_factory=self.factory,
            )
        except Exception:
            for display_patch in reversed(self._inspector_display_patches):
                display_patch.stop()
            raise
        for after_id in self.root.tk.splitlist(
            self.root.tk.call("after", "info")
        ):
            try:
                script, _kind = self.root.tk.call(
                    "after",
                    "info",
                    after_id,
                )
            except gui_module.tk.TclError:
                continue
            if "_drain_queue" in str(script):
                self.root.after_cancel(after_id)
        real_after = self.root.after

        def test_after(delay: int, callback=None, *args: object):
            if (
                getattr(callback, "__self__", None) is self.app
                and getattr(callback, "__name__", "") == "_drain_queue"
            ):
                return "test-drain-queue-disabled"
            return real_after(delay, callback, *args)

        self._drain_after_patch = patch.object(
            self.root,
            "after",
            side_effect=test_after,
        )
        self._drain_after_patch.start()
        self.app._test_basemap_factory = self.factory
        return self.app

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self.app.canvas.draw()
            if self.app._fullscreen_canvas is not None:
                self.app._fullscreen_canvas.draw()
            self.root.update_idletasks()
        except Exception:
            pass
        try:
            pending = self.root.tk.splitlist(
                self.root.tk.call("after", "info")
            )
            for after_id in pending:
                self.root.after_cancel(after_id)
        except Exception:
            pass
        self.app._shutdown_basemap()
        self.app._shutdown_basemap()
        self._drain_after_patch.stop()
        for display_patch in reversed(self._inspector_display_patches):
            display_patch.stop()


def _frame_for(
    view: ProjectedView,
    *,
    partial: bool = False,
    credit: str = "Esri, Maxar, Earthstar Geographics",
) -> BasemapFrame:
    rgba = np.zeros((2, 2, 4), dtype=np.uint8)
    rgba[..., 0] = 40
    rgba[..., 1] = 90
    rgba[..., 2] = 130
    rgba[..., 3] = 255
    rgba.flags.writeable = False
    return BasemapFrame(
        surface_id=view.surface_id,
        generation=view.generation,
        result_generation=view.result_generation,
        epsg=view.epsg,
        xlim=view.xlim,
        ylim=view.ylim,
        pixel_width=view.pixel_width,
        pixel_height=view.pixel_height,
        rgba=rgba,
        copyright_text=credit,
        requested_tile_count=2 if partial else 1,
        valid_tile_count=1,
        missing_tile_count=1 if partial else 0,
        is_partial=partial,
    )


def _failure_for(
    view: ProjectedView,
    *,
    category: str = "timeout",
    message: str = "Imagery is temporarily unavailable.",
) -> BasemapFailure:
    return BasemapFailure(
        surface_id=view.surface_id,
        generation=view.generation,
        result_generation=view.result_generation,
        category=category,
        user_message=message,
        retryable=False,
    )


def _scale_artists(axes) -> list[object]:
    artists = [*axes.patches, *axes.lines, *axes.texts]
    return [
        artist
        for artist in artists
        if str(artist.get_gid() or "").startswith("jpg-boundary-scale-")
    ]


def _attribution_artists(axes) -> list[object]:
    return [
        artist
        for artist in axes.texts
        if artist.get_gid() == "jpg-boundary-basemap-attribution"
    ]


def _vector_artists(axes) -> list[object]:
    artists: list[object] = []
    artists.extend(
        line
        for line in axes.lines
        if not str(line.get_gid() or "").startswith("jpg-boundary-scale-")
    )
    artists.extend(axes.collections)
    return artists


def _vector_snapshot(axes) -> tuple[object, ...]:
    line_state = tuple(
        (
            id(line),
            tuple(float(value) for value in line.get_xdata()),
            tuple(float(value) for value in line.get_ydata()),
            float(line.get_zorder()),
        )
        for line in axes.lines
        if not str(line.get_gid() or "").startswith("jpg-boundary-scale-")
    )
    collection_state = tuple(
        (id(collection), float(collection.get_zorder()))
        for collection in axes.collections
    )
    return line_state, collection_state


def _view_snapshot(axes) -> dict[str, object]:
    return {
        "xlim": tuple(axes.get_xlim()),
        "ylim": tuple(axes.get_ylim()),
        "data_lim": tuple(axes.dataLim.bounds),
        "autoscale_x": bool(axes.get_autoscalex_on()),
        "autoscale_y": bool(axes.get_autoscaley_on()),
        "use_sticky_edges": bool(axes.use_sticky_edges),
        "aspect": axes.get_aspect(),
        "adjustable": axes.get_adjustable(),
        "anchor": axes.get_anchor(),
    }


def _exact_length_credit(length: int, *, multiword: bool) -> str:
    if not multiword:
        return "X" * length
    repeated, remainder = divmod(length, len("credit "))
    value = ("credit " * repeated) + ("X" * remainder)
    if value.endswith(" "):
        value = f"{value[:-1]}X"
    return value[:length]


def _scale_artist_bbox(surface, renderer):
    bboxes = [
        artist.get_window_extent(renderer=renderer)
        for artist in _scale_artists(surface.axes)
    ]
    x0 = min(box.x0 for box in bboxes)
    y0 = min(box.y0 for box in bboxes)
    x1 = max(box.x1 for box in bboxes)
    y1 = max(box.y1 for box in bboxes)
    return SimpleNamespace(x0=x0, y0=y0, x1=x1, y1=y1)


def _bboxes_intersect(first, second) -> bool:
    return (
        first.x0 < second.x1
        and first.x1 > second.x0
        and first.y0 < second.y1
        and first.y1 > second.y0
    )


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
