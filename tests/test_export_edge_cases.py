"""Regressions from the follow-up export workflow audit."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch

from matplotlib.figure import Figure
from shapely.geometry import Polygon

from tests.test_gui_input import _app, _sample_boundary_result
from tests.test_polyline_compatibility import write_kmz
from export_style import ExportStyle
import jpg_boundary_kmz_gui as gui


class ExportEdgeCaseTests(TestCase):
    def test_filename_suggestion_does_not_require_writable_default_directory(self):
        with TemporaryDirectory() as tmp:
            source = write_kmz(tmp, name="Source.kmz")
            with patch.object(Path, "mkdir", side_effect=PermissionError("read-only application folder")):
                suggested = gui.BoundaryKmzApp._default_output_path(source, 50)
            self.assertEqual(suggested.name, "Source - (50 ft Buffer).kmz")

    def test_save_as_can_select_writable_destination_when_default_is_read_only(self):
        with TemporaryDirectory() as tmp, _app() as app:
            destination = Path(tmp) / "Delivery.kmz"
            with patch.object(Path, "mkdir", side_effect=PermissionError("read-only application folder")), \
                    patch.object(app, "_browse_initial_directory", return_value=tmp), \
                    patch.object(app, "_remember_browse_directory"), \
                    patch.object(gui.filedialog, "asksaveasfilename", return_value=str(destination)) as choose:
                app._browse_output()
            choose.assert_called_once()
            self.assertEqual(Path(app.output_var.get()), destination)
            self.assertFalse(destination.exists(), "Choosing a destination must not export yet")

    def test_single_shape_rename_and_destination_change_preserve_geometry_cache(self):
        with TemporaryDirectory() as tmp, _app() as app:
            first = Path(tmp) / "First.kmz"
            app._set_output_path(first)
            result = _sample_boundary_result()
            settings, identity = object(), object()
            app._cached_result = result
            app._cached_settings = settings
            app._cached_source_identity = identity
            app._set_output_path(Path(tmp) / "Other folder" / "Renamed.kmz")
            self.assertIs(app._cached_result, result)
            self.assertIs(app._cached_settings, settings)
            self.assertIs(app._cached_source_identity, identity)
            # Direct editing of the full path must follow the same cache rule.
            app.output_var.set(str(Path(tmp) / "Edited path.kmz"))
            self.assertIs(app._cached_result, result)
            app.output_name_var.set("Edited name")
            self.assertIs(app._cached_result, result)

    def test_custom_split_label_preserves_cache_but_automatic_label_change_invalidates(self):
        with TemporaryDirectory() as tmp, _app() as app:
            app.section_count_var.set("2")
            app._set_output_path(Path(tmp) / "Original.kmz")
            app.shape_label_var.set("Survey section")
            result = _sample_boundary_result()
            app._cached_result = result
            app._set_output_path(Path(tmp) / "Chosen folder" / "Delivery.kmz")
            self.assertIs(app._cached_result, result)
            self.assertEqual(app.shape_label_var.get(), "Survey section")

            app._refresh_shape_label_default(force=True)
            self.assertEqual(app.shape_label_var.get(), "Delivery")
            app._cached_result = result
            app._set_output_path(Path(tmp) / "Revised delivery.kmz")
            self.assertEqual(app.shape_label_var.get(), "Revised delivery")
            self.assertIsNone(app._cached_result)

    def test_existing_directory_in_save_location_preserves_filename(self):
        with TemporaryDirectory() as tmp, _app() as app:
            source = write_kmz(tmp, name="Source.kmz")
            destination = Path(tmp) / "Chosen folder"
            destination.mkdir()
            with patch.object(app, "_scan_clicked"):
                app._set_input_path(source)
            app.output_name_var.set("Client delivery")
            app.output_var.set(str(destination))
            self.assertEqual(app.output_name_var.get(), "Client delivery")

            output = app._read_inputs(require_output=True)[-1]

            self.assertEqual(output, destination / "Client delivery.kmz")
            self.assertEqual(Path(app.output_var.get()), output)
            self.assertFalse(output.exists())

    @skipUnless(sys.platform == "win32", "Windows filename restrictions")
    def test_invalid_custom_filename_is_rejected_before_starting_worker(self):
        with TemporaryDirectory() as tmp, _app() as app:
            with patch.object(app, "_scan_clicked"):
                app._set_input_path(write_kmz(tmp, name="Source.kmz"))
            for name in ("", ".kmz", "CON", "nul.txt", "COM1", "bad\x01name", "Client:review", "Delivery."):
                with self.subTest(name=name):
                    app.output_name_var.set(name)
                    with patch.object(gui.threading, "Thread") as worker, \
                            patch.object(gui.messagebox, "showerror") as error:
                        app._export_clicked()
                    worker.assert_not_called()
                    error.assert_called_once()
                    self.assertRegex(error.call_args.args[1], r"(?i)file.?name|reserved|invalid")

    def test_facility_named_like_source_legend_does_not_restyle_reference_key(self):
        # The input parser permits a facility literally named "Source polygons".
        # Its output key must be distinguished from the preview's reference key.
        app = gui.BoundaryKmzApp.__new__(gui.BoundaryKmzApp)
        figure = Figure()
        axes = figure.add_subplot()
        app._preview_export_style = ExportStyle()
        source_key = ("Source polygons", "#1f77b4", ":", 1.4)
        output_key = app._plot_export_polygon(
            axes, Polygon([(0, 0), (1, 0), (1, 1), (0, 0)]),
            "Source polygons", 0, gid="boundary-polygon-1-0")
        surface = SimpleNamespace(axes=axes, canvas=Mock(), key_entries=(source_key, output_key))
        app._main_map_surface = surface
        app.preview_key_content = object()
        app._update_export_style_controls = Mock()
        app._read_export_style = Mock(return_value=ExportStyle(mode="fill"))
        app.export_style_error_var = Mock()
        app._active_map_surfaces = Mock(return_value=[surface])
        app._update_preview_key = Mock()

        app._on_export_style_changed()

        self.assertEqual(surface.key_entries[0], source_key)
        self.assertEqual(surface.key_entries[1], ("Source polygons", "#d62728", "fill", 5.0))
        app._update_preview_key.assert_called_once_with(app.preview_key_content, list(surface.key_entries))
