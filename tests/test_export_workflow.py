from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from tests.test_gui_input import _app, _sample_boundary_result
from tests.test_polyline_compatibility import write_kmz
import jpg_boundary_kmz_gui as gui
from jpg_boundary_kmz_core import BoundaryError
from polyline_compatibility import PolylineCompatibility


class ExportWorkflowTests(TestCase):
    def select_input(self, app, source):
        with patch.object(app, "_scan_clicked"):
            app._set_input_path(source)

    def test_vector_default_names_and_other_workflow_scope(self):
        with TemporaryDirectory() as tmp:
            for extension in ("kml", "kmz"):
                source = write_kmz(tmp, name=f"SURF Park.{extension}")
                for value, text in ((0, "0"), (50, "50"), (125.0, "125"),
                                    (12.5, "12.5"), (0.005, "0.005")):
                    with self.subTest(extension=extension, buffer=value):
                        actual = gui.BoundaryKmzApp._default_output_path(source, buffer_ft=value)
                        self.assertEqual(actual.name, f"SURF Park - ({text} ft Buffer).kmz")
                for options in ({"section_count": 2}, {"per_side": True}, {"source_polygon_count": 2}):
                    self.assertEqual(gui.BoundaryKmzApp._default_output_path(
                        source, buffer_ft=50, **options).name, "SURF Park_boundary.kmz")
            folder = Path(tmp) / "Photo flight"
            folder.mkdir()
            self.assertEqual(gui.BoundaryKmzApp._default_output_path(
                folder, buffer_ft=50).name, "Photo flight_boundary.kmz")

    def test_auto_name_updates_and_invalid_edits_preserve_last_name(self):
        with TemporaryDirectory() as tmp, _app() as app:
            self.select_input(app, write_kmz(tmp, name="Source.kmz"))
            app.buffer_var.set("50")
            self.assertEqual(app.output_name_var.get(), "Source - (50 ft Buffer)")
            before = app.output_var.get()
            for text in ("", "-", "nan", "inf", "invalid"):
                app.buffer_var.set(text)
                self.assertEqual(app.output_var.get(), before)
            app.buffer_var.set("12.5")
            self.assertEqual(app.output_name_var.get(), "Source - (12.5 ft Buffer)")
            app.section_count_var.set("2")
            self.assertEqual(app.output_name_var.get(), "Source_boundary")
            app.section_count_var.set("1")
            self.assertEqual(app.output_name_var.get(), "Source - (12.5 ft Buffer)")

    def test_custom_names_survive_settings_and_new_import_resets_default(self):
        with TemporaryDirectory() as tmp, _app() as app:
            self.select_input(app, write_kmz(tmp, name="Source.kmz"))
            app.output_name_var.set("Client delivery")
            app.shape_label_var.set("Inspection area")
            app.buffer_var.set("75")
            app.section_count_var.set("2")
            app.section_count_var.set("1")
            self.assertEqual(Path(app.output_var.get()).name, "Client delivery.kmz")
            self.assertEqual(app.shape_label_var.get(), "Inspection area")
            self.select_input(app, write_kmz(tmp, name="Next.kmz"))
            app.buffer_var.set("100")
            self.assertEqual(app.output_name_var.get(), "Next - (100 ft Buffer)")

    def test_save_as_folder_preserves_automatic_tracking_but_rename_does_not(self):
        with TemporaryDirectory() as tmp, _app() as app:
            self.select_input(app, write_kmz(tmp, name="Source.kmz"))
            app.buffer_var.set("50")
            destination = Path(tmp) / "Chosen folder"
            destination.mkdir()
            selected = destination / Path(app.output_var.get()).name
            with patch.object(gui.filedialog, "asksaveasfilename", return_value=str(selected)), \
                    patch.object(app, "_remember_browse_directory"):
                app._browse_output()
            app.buffer_var.set("60")
            self.assertEqual(Path(app.output_var.get()), destination / "Source - (60 ft Buffer).kmz")
            with patch.object(gui.filedialog, "asksaveasfilename", return_value=str(destination / "Reviewed.kmz")), \
                    patch.object(app, "_remember_browse_directory"):
                app._browse_output()
            app.buffer_var.set("80")
            self.assertEqual(Path(app.output_var.get()), destination / "Reviewed.kmz")

    def test_per_side_and_collection_defaults(self):
        with TemporaryDirectory() as tmp, _app() as app:
            self.select_input(app, write_kmz(tmp, name="Source.kmz"))
            app.buffer_var.set("50")
            app._compatibility = PolylineCompatibility(True, "eligible", "OK", 1)
            app._refresh_buffer_controls()
            app.per_side_checkbutton.invoke()
            self.assertEqual(app.output_name_var.get(), "Source_boundary")
            app.per_side_checkbutton.invoke()
            self.assertEqual(app.output_name_var.get(), "Source - (50 ft Buffer)")
            app._source_polygon_count = 3
            app._refresh_output_default()
            self.assertEqual(app.output_name_var.get(), "Source_boundary")

    def test_export_menu_and_shortcut_require_final_confirmation(self):
        with TemporaryDirectory() as tmp, _app() as app:
            self.select_input(app, write_kmz(tmp))
            output = Path(tmp) / "Delivery.kmz"
            app._set_output_path(output)
            app.section_count_var.set("2")
            with patch.object(gui.threading, "Thread") as worker, patch.object(gui.messagebox, "showerror") as error:
                self.assertEqual(app.export_button.cget("text"), "Export")
                app.export_button.invoke()
                self.assertTrue(app._settings_drawer_open)
                self.assertEqual(app._active_settings_group, "output")
                worker.assert_not_called()
                app.export_button.invoke()
                self.assertTrue(app._settings_drawer_open)
                app._close_settings_drawer()
                self.assertEqual(app._shortcut_export(), "break")
                self.assertTrue(app._settings_drawer_open)
                worker.assert_not_called()
                app.output_shape_label_entry.delete(0, "end")
                app.output_shape_label_entry.insert(0, "Survey section")
                self.assertEqual(app.quick_shape_label_entry.get(), "Survey section")
                app.confirm_export_button.invoke()
                worker.return_value.start.assert_called_once()
                self.assertEqual(worker.call_args.kwargs["args"][4], "Survey section")
                self.assertEqual(worker.call_args.kwargs["args"][8], output)
                error.assert_not_called()

    def test_output_label_visibility_and_busy_controls(self):
        with _app() as app:
            app._open_export_settings()
            self.assertFalse(app.output_shape_label_entry.grid_info())
            app.section_count_var.set("2")
            self.assertTrue(app.output_shape_label_entry.grid_info())
            self.assertNotIn("disabled", app.output_shape_label_entry.state())
            app._source_polygon_count = 2
            app._update_section_control_state()
            self.assertIn("disabled", app.output_shape_label_entry.state())
            app._source_polygon_count = 0
            app._set_busy(True, "Exporting KMZ...")
            self.assertTrue(app.output_shape_label_entry.grid_info())
            self.assertIn("disabled", app.output_shape_label_entry.state())
            self.assertIn("disabled", app.confirm_export_button.state())
            app._set_busy(False, "Ready")
            self.assertNotIn("disabled", app.confirm_export_button.state())
            app.section_count_var.set("1")
            self.assertFalse(app.output_shape_label_entry.grid_info())

    def test_quick_fields_reserve_space_and_keep_values_while_hidden(self):
        with _app() as app:
            app.root.geometry("1440x900+0+0")
            app.root.update_idletasks()
            fields = (app.quick_overlap_label, app.quick_overlap_entry,
                      app.quick_shape_label_label, app.quick_shape_label_entry)
            groups = (app.quick_overlap_entry.master, app.quick_shape_label_entry.master)
            self.assertTrue(all(not w.grid_info() for w in fields))
            app.section_count_var.set("2")
            app.root.update_idletasks()
            self.assertTrue(all(w.grid_info() for w in fields))
            sizes = [(g.winfo_reqwidth(), g.winfo_reqheight()) for g in groups]
            self.assertTrue(all(w > 1 and h > 1 for w, h in sizes))
            app.overlap_var.set("75")
            app.shape_label_var.set("Section label")
            app._set_busy(True, "Building preview...")
            self.assertTrue(all(w.grid_info() for w in fields))
            self.assertTrue(all("disabled" in w.state()
                                for w in (app.quick_overlap_entry, app.quick_shape_label_entry)))
            app._set_busy(False, "Ready")
            app.section_count_var.set("1")
            app.root.update_idletasks()
            self.assertTrue(all(not w.grid_info() for w in fields))
            self.assertEqual([(g.winfo_reqwidth(), g.winfo_reqheight()) for g in groups], sizes)
            app.section_count_var.set("2")
            self.assertEqual(app.quick_overlap_entry.get(), "75")
            self.assertEqual(app.quick_shape_label_entry.get(), "Section label")

    def set_custom_style(self, app):
        for variable, value in ((app.export_palette_var, False),
                                (app.export_line_color_var, "#123456"),
                                (app.export_fill_color_var, "#abcdef"),
                                (app.export_line_width_var, "3.5"),
                                (app.export_line_opacity_var, "75"),
                                (app.export_fill_opacity_var, "25"),
                                (app.export_mode_var, "both")):
            variable.set(value)

    def test_appearance_preserves_geometry_cache_and_view(self):
        with _app() as app:
            result = _sample_boundary_result()
            app._cached_result = app._last_displayed_result = result
            app._draw_preview(result)
            app._preview_stale = False
            signature = app._preview_control_signature()
            view = (app.axes.get_xlim(), app.axes.get_ylim())
            self.set_custom_style(app)
            self.assertIs(app._cached_result, result)
            self.assertFalse(app._preview_stale)
            self.assertEqual(app._preview_control_signature(), signature)
            self.assertEqual((app.axes.get_xlim(), app.axes.get_ylim()), view)
            line = next(line for line in app.axes.lines if hasattr(line, "_export_color_index"))
            fill = next(p for p in app.axes.patches if hasattr(p, "_export_color_index"))
            self.assertEqual(line.get_color(), "#123456")
            self.assertEqual(line.get_alpha(), .75)
            self.assertEqual(fill.get_alpha(), .25)
            self.assertTrue(fill.get_visible())
            app.export_mode_var.set("fill")
            self.assertFalse(line.get_visible())
            self.assertTrue(fill.get_visible())
            self.assertEqual(app._main_map_surface.key_entries[-1][1:3], ("#abcdef", "fill"))

    def test_style_snapshot_reaches_worker_and_invalid_style_blocks_export(self):
        with TemporaryDirectory() as tmp, _app() as app:
            self.select_input(app, write_kmz(tmp))
            output = Path(tmp) / "Styled.kmz"
            app._set_output_path(output)
            self.set_custom_style(app)
            expected = app._read_export_style()
            with patch.object(gui.threading, "Thread") as worker:
                app._export_clicked()
            call = worker.call_args.kwargs
            frozen = call["kwargs"]["style"]
            self.assertEqual(frozen, expected)
            with self.assertRaises(FrozenInstanceError):
                frozen.line_width = 999
            app.export_line_color_var.set("#ffffff")
            app.export_line_width_var.set("10")
            result = _sample_boundary_result()
            with patch.object(app, "_generate_for_request", return_value=result), \
                    patch.object(gui, "save_kmz", return_value=output) as save:
                call["target"](*call["args"], **call["kwargs"])
            save.assert_called_once_with(result, output, style=expected)
            app._set_busy(False, "Ready")
            for invalid in ("-1", "nan", "101"):
                app.export_line_opacity_var.set(invalid)
                with self.assertRaises(BoundaryError):
                    app._read_export_style()
                with patch.object(gui.threading, "Thread") as worker, patch.object(gui.messagebox, "showerror") as error:
                    app._export_clicked()
                    worker.assert_not_called()
                    error.assert_called_once()

    def test_auto_adjusted_buffer_requires_review_before_writing(self):
        with TemporaryDirectory() as tmp, patch.object(gui, "DEFAULT_OUTPUT_DIR", Path(tmp) / "outputs"), _app() as app:
            source = write_kmz(tmp, name="Line source.kmz")
            self.select_input(app, source)
            self.assertEqual(Path(app.output_var.get()).name, "Line source - (0 ft Buffer).kmz")
            result = _sample_boundary_result()
            result.metadata = replace(result.metadata, source_folder=source, input_type="KMZ polyline",
                                      buffer_ft=1, generation_profile="export", polyline_selected_buffer_ft=1,
                                      polyline_buffer_adjustment_reason="Selected connected buffer")
            with patch.object(gui.threading, "Thread") as worker:
                app._export_clicked()
            call = worker.call_args.kwargs
            self.assertTrue(call["kwargs"]["automatic_name"])
            with patch.object(app, "_generate_for_request", return_value=result), patch.object(gui, "save_kmz") as save:
                call["target"](*call["args"], **call["kwargs"])
                save.assert_not_called()
            with patch.object(gui.messagebox, "showerror") as error:
                app._drain_queue()
                error.assert_not_called()
            self.assertFalse(app._busy)
            self.assertEqual(app.buffer_var.get(), "1")
            self.assertEqual(Path(app.output_var.get()).name, "Line source - (1 ft Buffer).kmz")
            self.assertTrue(app._settings_drawer_open)
            self.assertEqual(app._active_settings_group, "output")
            actual = Path(app.output_var.get())
            actual.parent.mkdir(parents=True, exist_ok=True)
            actual.write_bytes(b"existing delivery")
            with patch.object(gui.messagebox, "askyesno", return_value=False) as ask, patch.object(gui.threading, "Thread") as worker:
                app.confirm_export_button.invoke()
                ask.assert_called_once()
                self.assertIn(str(actual), ask.call_args.args[1])
                worker.assert_not_called()
            self.assertEqual(actual.read_bytes(), b"existing delivery")
