from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from tests.test_gui_input import _app, _sample_boundary_result
from tests.test_polyline_compatibility import write_kmz
import jpg_boundary_kmz_gui as gui


class WorkspaceFollowupTests(TestCase):
    def test_failed_import_restores_browse_controls_and_new_input_clears_error(self):
        polygon = '<Polygon><outerBoundaryIs><LinearRing><coordinates>-80,35 -79.99,35 -79.99,35.01 -80,35</coordinates></LinearRing></outerBoundaryIs></Polygon>'
        with TemporaryDirectory() as tmp, _app() as app:
            path = write_kmz(tmp, f'<MultiGeometry>{polygon}{polygon}</MultiGeometry>')
            with patch.object(gui.threading, "Thread") as thread:
                app._set_input_path(path)
                call = thread.call_args.kwargs
                call['target'](*call['args'])
            with patch.object(gui.messagebox, 'showerror') as error:
                app._drain_queue()
                error.assert_called_once()
            app.root.update_idletasks()
            self.assertTrue(app.empty_input_overlay.place_info())
            self.assertIsNone(app._last_displayed_result)
            self.assertNotIn('disabled', app.browse_vector_button.state())
            self.assertIn('found 2', app.status_var.get())
            app.new_input_button.invoke()
            self.assertEqual(app.parent_var.get(), '')
            self.assertEqual(app._preview_error, '')
            self.assertEqual(app.preview_state_var.get(), 'No preview')
            self.assertIsNone(app._active_request)
            self.assertTrue(app.empty_input_overlay.place_info())

    def test_new_input_clears_successful_preview_cache_and_saved_link(self):
        with _app() as app:
            app.parent_var.set('previous.kmz')
            result = _sample_boundary_result()
            app._cached_result = app._last_displayed_result = result
            app._draw_preview(result)
            app._show_export_success(Path('previous-boundary.kmz'))
            generation = app._input_generation
            app.new_input_button.invoke()
            self.assertGreater(app._input_generation, generation)
            self.assertIsNone(app._cached_result)
            self.assertIsNone(app._last_displayed_result)
            self.assertIsNone(app._last_export_path)
            self.assertFalse(app.open_export_button.grid_info())
            self.assertTrue(app.empty_input_overlay.place_info())
            self.assertEqual(len(app.axes.lines), 0)

    def test_busy_import_hides_welcome_and_disables_reset_until_done(self):
        with _app() as app:
            app.parent_var.set('pending.kmz')
            app._preview_error = 'previous error'
            app._refresh_input_shell_state()
            self.assertTrue(app.empty_input_overlay.place_info())
            app._set_busy(True, 'Building preview')
            self.assertFalse(app.empty_input_overlay.place_info())
            app.new_input_button.invoke()
            self.assertEqual(app.parent_var.get(), 'pending.kmz')
            self.assertIn('disabled', app.new_input_button.state())
            app._set_busy(False, 'Finished')

    def test_wide_footer_is_one_row_and_small_layout_wraps_without_overlap(self):
        with _app() as app:
            app.root.attributes('-alpha', 0)
            app.root.deiconify()
            app.root.geometry('2500x1000+0+0')
            app.root.update()
            app._show_export_success(Path('saved.kmz'))
            app.root.update_idletasks()
            app._refresh_workspace_layout()
            app.root.update_idletasks()
            self.assertTrue(app._action_bar_inline)
            self.assertEqual(app.quick_controls.grid_info()['row'], 0)
            self.assertEqual(app.open_export_button.grid_info()['row'], 0)
            self.assertLess(app.brand_frame.winfo_height(), 70)
            self.assertLess(app.action_bar.winfo_height(), 75)
            self.assertLessEqual(app.quick_controls.winfo_rootx() + app.quick_controls.winfo_width(),
                                 app.action_right_group.winfo_rootx())
            for width, height in ((1280, 720), (800, 600), (720, 500)):
                with self.subTest(width=width, height=height):
                    app.root.geometry(f'{width}x{height}+0+0')
                    app.root.update()
                    app._refresh_workspace_layout()
                    app.root.update_idletasks()
                    widgets = (app.new_input_button, app.scan_button, app.export_button,
                               app.open_export_button, app.quick_buffer_entry,
                               app.quick_overlap_entry, app.quick_shape_label_entry)
                    for widget in widgets:
                        right = widget.winfo_rootx() - app.root.winfo_rootx() + widget.winfo_width()
                        bottom = widget.winfo_rooty() - app.root.winfo_rooty() + widget.winfo_height()
                        self.assertLessEqual(right, width, str(widget))
                        self.assertLessEqual(bottom, height, str(widget))
                    self.assertFalse(app._action_bar_inline)
                    self.assertLessEqual(app.empty_input_overlay.winfo_reqheight(), app.preview_stack.winfo_height())
                    for widget in (app.drop_label, app.browse_folder_button, app.browse_vector_button):
                        top = widget.winfo_rooty() - app.preview_stack.winfo_rooty()
                        self.assertGreaterEqual(top, 0)
                        self.assertLessEqual(top + widget.winfo_height(), app.preview_stack.winfo_height())
