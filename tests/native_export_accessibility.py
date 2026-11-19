"""Native Tk integration: python -B -m unittest tests.native_export_accessibility -v.

Disabled by default. Requires an explicit user request for a foreground session
and BOUNDARY_ALLOW_FOREGROUND_GUI_TESTS=1 in a fresh process.
Keep these window tests serial: native keyboard input requires foreground ownership
and hit-testing requires an unobscured app. A long CPU-only phase before creating
windows does not reliably preserve Windows foreground focus on this host.
The basemap client is an offline recorder and all windows are closed afterwards.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest import TestCase
from unittest.mock import patch

from tests.gui_test_support import foreground_gui_test, require_foreground_gui

from tests.test_gui_input import _RecordingBasemapFactory, _destroy_test_root
from tests.test_polyline_compatibility import write_kmz
import jpg_boundary_kmz_gui as gui


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


def _within(widget, ancestor):
    while widget is not None:
        if widget is ancestor:
            return True
        widget = getattr(widget, "master", None)
    return False


def _bound_widget(parent, variable):
    return next(widget for widget in _descendants(parent)
                if "textvariable" in widget.keys()
                and str(widget.cget("textvariable")) == str(variable))


def _pump_until(root, predicate, *, timeout=1.5):
    """Allow native activation/focus messages to arrive without forcing a result."""
    deadline = time.monotonic() + timeout
    while True:
        root.update()
        if predicate():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)


@contextmanager
def _visible_app(width=720, height=500, scaling=1.333):
    require_foreground_gui()
    root = gui._create_root()
    root.withdraw()
    previous_scaling = root.tk.call("tk", "scaling")
    root.tk.call("tk", "scaling", scaling)
    root.geometry(f"{width}x{height}+20+20")
    callback_errors = []
    root.report_callback_exception = lambda *error: callback_errors.append(error)
    app = None
    try:
        app = gui.BoundaryKmzApp(root, basemap_client_factory=_RecordingBasemapFactory())
        root.attributes("-topmost", True)
        root.deiconify()
        root.update()
        root.lift()
        root.focus_force()
        if not _pump_until(root, lambda: root.focus_get() is not None):
            raise AssertionError("Native test window did not acquire keyboard focus")
        yield app, callback_errors
    finally:
        try:
            root.tk.call("tk", "scaling", previous_scaling)
            if app is not None:
                app._shutdown_basemap()
        finally:
            _destroy_test_root(root)


@foreground_gui_test
class ExportAccessibilityTests(TestCase):
    def assert_hit(self, app, widget):
        self.assertTrue(widget.winfo_ismapped(), str(widget))
        hit = app.root.winfo_containing(
            widget.winfo_rootx() + widget.winfo_width() // 2,
            widget.winfo_rooty() + widget.winfo_height() // 2,
        )
        self.assertTrue(_within(hit, widget), f"{widget} is covered by {hit}")

    def assert_in_viewport(self, app, widget):
        canvas = app.settings_canvas
        self.assertGreaterEqual(widget.winfo_rootx(), canvas.winfo_rootx())
        self.assertGreaterEqual(widget.winfo_rooty(), canvas.winfo_rooty())
        self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                             canvas.winfo_rootx() + canvas.winfo_width())
        self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                             canvas.winfo_rooty() + canvas.winfo_height())
        self.assert_hit(app, widget)

    def key(self, app, sequence):
        focused = app.root.focus_get()
        self.assertIsNotNone(focused)
        focused.event_generate(sequence)
        self.assertTrue(_pump_until(app.root, lambda: app.root.focus_get() is not None),
                        f"Keyboard focus was lost after {sequence}")
        return app.root.focus_get()

    def open_export(self, app):
        # Creating/closing several native roots can queue activation messages.
        # Establish the visible opener first; after Ctrl+E, only observe the
        # resulting focus transition, never focus the expected filename here.
        app.root.lift()
        app.root.focus_force()
        app.export_button.focus_set()
        self.assertTrue(_pump_until(app.root, lambda: app.root.focus_get() is app.export_button),
                        "Export opener did not acquire keyboard focus")
        self.key(app, "<Control-e>")
        self.assertTrue(_pump_until(app.root, lambda: app.root.focus_get() is app.output_name_entry),
                        "Ctrl+E did not move focus from Export to the filename")
        self.assertEqual(app.root.focus_get(), app.output_name_entry)
        self.assert_in_viewport(app, app.output_name_entry)

    def test_tab_and_reverse_tab_reveal_each_export_field(self):
        with _visible_app() as (app, errors):
            app.section_count_var.set("2")
            app.export_palette_var.set(False)
            self.open_export(app)
            expected = {
                app.output_name_entry, app.output_path_entry,
                app.save_as_button, app.view_output_button,
                app.output_shape_label_entry, app.export_palette_checkbutton,
                *(_bound_widget(app.settings_content, variable) for variable in (
                    app.export_line_color_var, app.export_fill_color_var,
                    app.export_line_width_var, app.export_line_opacity_var,
                    app.export_fill_opacity_var,
                )),
            }
            for sequence, stop in (("<Tab>", app.confirm_export_button),
                                   ("<Shift-Tab>", app.output_name_entry)):
                seen = {app.root.focus_get()}
                for _ in range(80):
                    focused = self.key(app, sequence)
                    seen.add(focused)
                    if _within(focused, app.settings_content):
                        self.assert_in_viewport(app, focused)
                    if focused is stop:
                        break
                else:
                    self.fail(f"Keyboard traversal did not reach {stop}")
                self.assertTrue(expected <= seen, f"Missed export controls: {expected - seen}")
            self.assertFalse(errors)

    def test_repeated_export_shortcut_reveals_filename_and_escape_restores_opener(self):
        with _visible_app() as (app, errors):
            self.open_export(app)
            app.settings_canvas.yview_moveto(1)
            app.root.update()
            self.assertGreater(app.settings_canvas.yview()[0], 0)
            self.key(app, "<Control-e>")
            self.assertEqual(app.root.focus_get(), app.output_name_entry)
            self.assert_in_viewport(app, app.output_name_entry)
            self.key(app, "<Escape>")
            self.assertFalse(app.settings_drawer.winfo_ismapped())
            self.assertEqual(app.root.focus_get(), app.export_button)
            self.assert_hit(app, app.export_button)
            self.assertFalse(errors)

    def test_escape_uses_visible_export_when_original_opener_is_hidden(self):
        with _visible_app() as (app, errors):
            app.workspace_controls_button.invoke()
            app.root.update()
            app.output_settings_button.focus_set()
            app.output_settings_button.invoke()
            app.root.update()
            app.output_name_entry.focus_set()
            app.output_settings_button.grid_remove()
            app.root.update()
            self.key(app, "<Escape>")
            self.assertFalse(app.settings_drawer.winfo_ismapped())
            self.assertEqual(app.root.focus_get(), app.export_button)
            self.assert_hit(app, app.export_button)
            self.assertFalse(errors)

    def test_hidden_split_fields_are_not_keyboard_stops(self):
        with _visible_app() as (app, errors):
            app.section_count_var.set("2")
            app.shape_label_var.set("Retained split label")
            app.overlap_var.set("75")
            app.section_count_var.set("1")
            self.open_export(app)
            hidden = {app.output_shape_label_entry, app.quick_shape_label_entry,
                      app.quick_overlap_entry}
            self.assertTrue(all(not widget.winfo_ismapped() for widget in hidden))
            seen = set()
            for _ in range(100):
                focused = self.key(app, "<Tab>")
                seen.add(focused)
                if focused is app.output_name_entry:
                    break
            else:
                self.fail("Tab order did not return to the filename")
            self.assertFalse(hidden & seen)
            app.section_count_var.set("2")
            app.root.update()
            self.assertEqual(app.output_shape_label_entry.get(), "Retained split label")
            self.assertEqual(app.quick_overlap_entry.get(), "75")
            self.assertTrue(all(widget.winfo_ismapped() for widget in hidden))
            self.assertFalse(errors)

    def test_export_panel_fits_startup_scaling_and_keeps_final_action_reachable(self):
        for width, height, scaling in (
            (720, 500, 1.333), (720, 500, 2.0), (960, 600, 1.667),
            (960, 600, 2.0), (1100, 760, 2.667),
        ):
            with self.subTest(width=width, height=height, scaling=scaling), \
                    _visible_app(width, height, scaling) as (app, errors):
                app.section_count_var.set("2")
                app.export_palette_var.set(False)
                self.open_export(app)
                self.assertLessEqual(app.app_title_label.winfo_reqwidth(), app.app_title_label.winfo_width())
                drawer = app.settings_drawer
                self.assertGreaterEqual(drawer.winfo_rootx(), app.root.winfo_rootx())
                self.assertGreaterEqual(drawer.winfo_rooty(), app.root.winfo_rooty())
                self.assertLessEqual(drawer.winfo_rootx() + drawer.winfo_width(),
                                     app.root.winfo_rootx() + app.root.winfo_width())
                self.assertLessEqual(drawer.winfo_rooty() + drawer.winfo_height(),
                                     app.root.winfo_rooty() + app.root.winfo_height())
                self.assert_hit(app, app.confirm_export_button)
                for variable in (app.export_line_color_var, app.export_fill_color_var,
                                 app.export_line_width_var, app.export_line_opacity_var,
                                 app.export_fill_opacity_var):
                    field = _bound_widget(app.settings_content, variable)
                    field.focus_set()
                    app.root.update()
                    self.assert_in_viewport(app, field)
                    self.assert_hit(app, app.confirm_export_button)
                self.assertFalse(errors)

    def test_long_validation_message_wraps_within_the_export_panel(self):
        with _visible_app(720, 500, 2.0) as (app, errors):
            self.open_export(app)
            app.export_style_error_var.set(
                "Invalid export appearance: Outline color must be a six-digit hex color, "
                "such as #336699. Choose a valid outline color, then retry the export. "
                "Your file has not been written.")
            app.root.update()
            label = _bound_widget(app.settings_content, app.export_style_error_var)
            self.assertGreater(label.winfo_height(), 1)
            self.assertLessEqual(int(float(label.cget("wraplength"))), label.winfo_width())
            self.assertLessEqual(label.winfo_reqwidth(), label.winfo_width() + 2)
            self.assertGreaterEqual(label.winfo_rootx(), app.settings_canvas.winfo_rootx())
            self.assertLessEqual(label.winfo_rootx() + label.winfo_width(),
                                 app.settings_canvas.winfo_rootx() + app.settings_canvas.winfo_width())
            self.assert_hit(app, app.confirm_export_button)
            self.assertFalse(errors)

    def test_invalid_appearance_focuses_and_reveals_the_named_field(self):
        with TemporaryDirectory() as tmp, _visible_app() as (app, errors):
            with patch.object(app, "_scan_clicked"):
                app._set_input_path(write_kmz(tmp))
            app._set_output_path(Path(tmp) / "Delivery.kmz")
            app.export_fill_opacity_var.set("")
            self.open_export(app)
            with patch.object(gui.messagebox, "showerror") as error, \
                    patch.object(gui.threading, "Thread") as worker:
                app.confirm_export_button.invoke()
                app.root.update()
            worker.assert_not_called()
            self.assertIn("Fill opacity", error.call_args.args[1])
            field = _bound_widget(app.settings_content, app.export_fill_opacity_var)
            self.assertEqual(app.root.focus_get(), field)
            self.assert_in_viewport(app, field)
            self.assertFalse(errors)
