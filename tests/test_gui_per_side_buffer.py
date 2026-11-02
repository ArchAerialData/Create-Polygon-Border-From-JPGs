from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from tests.test_gui_input import _app
from tests.test_polyline_compatibility import write_kmz, LINE
import jpg_boundary_kmz_gui as gui
from buffer_settings import BufferSettings
from polyline_compatibility import PolylineCompatibility


def import_input(app, path):
    with patch.object(gui.threading, "Thread") as thread:
        app._set_input_path(path)
        call = thread.call_args.kwargs
        call["target"](*call["args"])
    with patch.object(gui.messagebox, "showerror") as error:
        app._drain_queue()
        error.assert_not_called()
    app.root.update_idletasks()


class GuiPerSideBufferTests(TestCase):
    def test_toggle_defaults_restore_and_sync_both_editors(self):
        with TemporaryDirectory() as tmp, _app() as app:
            import_input(app, write_kmz(tmp))
            self.assertTrue(app._compatibility.eligible)
            for location, unified, expected in (
                ("drawer", "350", "350"), ("footer", "0", "200"),
                ("drawer", "0.005", "0.005"), ("footer", "461", "461"),
            ):
                with self.subTest(location=location, unified=unified):
                    app.buffer_var.set(unified)
                    check = app.per_side_checkbutton if location == "drawer" else app.quick_per_side_checkbutton
                    check.invoke()
                    app.root.update_idletasks()
                    self.assertEqual(app.left_buffer_var.get(), expected)
                    self.assertEqual(app.right_buffer_var.get(), expected)
                    self.assertFalse(app._drawer_unified_group.grid_info())
                    self.assertFalse(app._quick_unified_group.grid_info())
                    self.assertTrue(all(group.grid_info() for group, _ in app._quick_side_groups))
                    app.left_buffer_var.set("25")
                    self.assertEqual(app.left_buffer_entry.get(), "25")
                    self.assertEqual(app.quick_left_buffer_entry.get(), "25")
                    self.assertIn("L 25 / R", app._input_settings_summary.cget("text"))
                    check.invoke()
                    app.root.update_idletasks()
                    self.assertEqual(app.buffer_var.get(), unified)
                    self.assertTrue(app._quick_unified_group.grid_info())
                    self.assertFalse(any(group.grid_info() for group, _ in app._quick_side_groups))

    def test_ineligible_import_hides_controls_and_resets_mode(self):
        with TemporaryDirectory() as tmp, _app() as app:
            import_input(app, write_kmz(tmp))
            app.quick_per_side_checkbutton.invoke()
            import_input(app, write_kmz(tmp, LINE + "<Point><coordinates>-80,35</coordinates></Point>", "mixed.kmz"))
            self.assertFalse(app._compatibility.eligible)
            self.assertFalse(app.per_side_var.get())
            self.assertFalse(app.per_side_checkbutton.grid_info())
            self.assertFalse(app._quick_mode_group.grid_info())
            self.assertEqual(app.left_buffer_var.get(), "")

    def test_async_eligibility_survives_geometry_failure(self):
        with TemporaryDirectory() as tmp, _app() as app:
            path = write_kmz(tmp)
            with patch.object(gui.threading, "Thread") as thread:
                app._set_input_path(path)
                self.assertIsNone(app._compatibility)
                call = thread.call_args.kwargs
                with patch.object(gui, "generate_boundary_from_vector_geometry", side_effect=RuntimeError("split failed")):
                    call["target"](*call["args"])
            with patch.object(gui.messagebox, "showerror"):
                app._drain_queue()
            self.assertTrue(app._compatibility.eligible)
            self.assertFalse(app._busy)
            self.assertNotIn("disabled", app.per_side_checkbutton.state())

    def test_stale_a_b_a_and_changed_file_results_are_rejected(self):
        with TemporaryDirectory() as tmp, _app() as app:
            path = write_kmz(tmp)
            app.parent_var.set(str(path))
            old = app._new_geometry_request(path, 100)
            app.parent_var.set(str(Path(tmp) / "B.kmz"))
            app.parent_var.set(str(path))
            app._queue.put(("compatibility", gui._WorkerMessage(old, PolylineCompatibility(True,"eligible","ok",1))))
            app._drain_queue()
            self.assertIsNone(app._compatibility)
            current = app._new_geometry_request(path, 100)
            write_kmz(tmp, LINE + "<Point/>")
            app._queue.put(("compatibility", gui._WorkerMessage(current, PolylineCompatibility(True,"eligible","ok",1))))
            app._drain_queue()
            self.assertIsNone(app._compatibility)

    def test_invalid_unified_busy_and_inactive_values(self):
        with TemporaryDirectory() as tmp, _app() as app:
            import_input(app, write_kmz(tmp))
            app.buffer_var.set("invalid")
            with patch.object(gui.messagebox,"showerror") as error:
                app.per_side_checkbutton.invoke()
            self.assertFalse(app.per_side_var.get())
            error.assert_called_once()
            app.buffer_var.set("350")
            app.per_side_checkbutton.invoke()
            signature = app._preview_control_signature()
            app.buffer_var.set("999")
            self.assertEqual(app._preview_control_signature(),signature)
            app._set_busy(True,"Working")
            for widget in (app.per_side_checkbutton,app.quick_per_side_checkbutton,app.left_buffer_entry,app.quick_right_buffer_entry):
                self.assertIn("disabled",widget.state())
            app._set_busy(False,"Ready")
            self.assertFalse(app._drawer_unified_group.grid_info())

    def test_side_request_results_preserve_values_and_arrows_in_both_views(self):
        with TemporaryDirectory() as tmp, _app() as app:
            path=write_kmz(tmp)
            import_input(app,path)
            app.buffer_var.set("350")
            app.per_side_checkbutton.invoke()
            app.right_buffer_var.set("150")
            with patch.object(gui.threading,"Thread") as thread:
                app._scan_clicked()
                call=thread.call_args.kwargs
                self.assertEqual(call["args"][-1].buffer,BufferSettings.per_side(350,150))
                call["target"](*call["args"])
            with patch.object(gui.messagebox,"showerror") as error:
                app._drain_queue()
                error.assert_not_called()
            self.assertEqual(app.buffer_var.get(),"350")
            self.assertEqual(app.right_buffer_var.get(),"150")
            self.assertEqual(app._last_displayed_result.metadata.buffer_mode,"per_side")
            self.assertEqual(app.preview_state_var.get(),"Preview current")
            app._open_fullscreen_preview()
            for axes in (app.axes,app._fullscreen_axes):
                self.assertTrue(any(artist.get_gid()=="source-direction-arrow" for artist in axes.texts))

    def test_export_and_inspector_apply_use_active_sides_and_revalidate_changed_source(self):
        with TemporaryDirectory() as tmp, _app() as app:
            path = write_kmz(tmp)
            import_input(app, path)
            app.buffer_var.set("350")
            app.quick_per_side_checkbutton.invoke()
            app.right_buffer_var.set("150")
            app._open_fullscreen_preview()
            with patch.object(app, "_start_preview_generation") as start:
                app._apply_fullscreen_preview()
            self.assertEqual(start.call_args.args[1], BufferSettings.per_side(350, 150))
            app._set_output_path(Path(tmp) / "first-export.kmz")
            with patch.object(gui.threading, "Thread") as thread:
                app._export_clicked()
                call = thread.call_args.kwargs
                with patch.object(gui, "load_vector_input", wraps=gui.load_vector_input) as load:
                    call["target"](*call["args"])
                    load.assert_called_once_with(path)
            with patch.object(gui.messagebox, "showerror") as error:
                app._drain_queue()
                error.assert_not_called()
            self.assertTrue((Path(tmp) / "first-export.kmz").is_file())
            self.assertEqual(app._cached_result.metadata.left_buffer_ft, 350)
            self.assertEqual(app._cached_result.metadata.right_buffer_ft, 150)
            self.assertIsNotNone(app._cached_result)
            # Same settings/path but different contents must never reuse a cached export.
            write_kmz(tmp, LINE + "<Point/>")
            app._set_output_path(Path(tmp) / "second-export.kmz")
            with patch.object(gui.threading, "Thread") as thread:
                app._export_clicked()
                call = thread.call_args.kwargs
                self.assertIsNone(call["args"][-2])
                call["target"](*call["args"])
            with patch.object(gui.messagebox, "showerror") as error:
                app._drain_queue()
                error.assert_called_once()
            self.assertFalse((Path(tmp) / "second-export.kmz").exists())
            self.assertFalse(app.per_side_var.get())
            self.assertFalse(app._compatibility.eligible)

    def test_active_fields_fit_small_layout_and_large_text(self):
        for width,height,scale in ((720,500,1.333),(960,600,1.333),(1100,760,2.0),(1500,820,1.667)):
            with self.subTest(width=width,scale=scale), _app() as app:
                app.root.tk.call("tk","scaling",scale)
                # Native hit-testing needs an on-screen, unobscured window;
                # Windows' automatic cascade placement can put the footer off-screen.
                app.root.geometry(f"{width}x{height}+20+20")
                app.root.attributes("-topmost", True)
                app.root.deiconify()
                app.root.update()
                app.root.lift()
                app.root.update()
                app._compatibility=PolylineCompatibility(True,"eligible","ok",1)
                app._refresh_buffer_controls()
                for _ in range(4):
                    app.quick_per_side_checkbutton.invoke()
                    # Process native Configure/Map events as well as idle geometry.
                    app.root.update()
                    for group in app._active_quick_buffer_groups():
                        self.assertTrue(group.winfo_ismapped())
                        self.assertGreaterEqual(group.winfo_rootx(),app.root.winfo_rootx())
                        self.assertLessEqual(group.winfo_rootx()+group.winfo_width(),app.root.winfo_rootx()+app.root.winfo_width())
                        for control in group.winfo_children():
                            hit = app.root.winfo_containing(
                                control.winfo_rootx() + control.winfo_width() // 2,
                                control.winfo_rooty() + control.winfo_height() // 2)
                            self.assertEqual(hit, control, "An active footer control is covered by another widget")
                    self.assertGreater(app.canvas.get_tk_widget().winfo_height(),100)
