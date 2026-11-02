from dataclasses import replace
from pathlib import Path
import random
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from shapely.geometry import LineString
from pyproj import Transformer

from tests.test_gui_input import _app, _sample_boundary_result, _frame_for, _scale_artist_bbox, _bboxes_intersect
from tests.test_gui_per_side_buffer import import_input
from tests.test_polyline_compatibility import write_kmz
import jpg_boundary_kmz_gui as gui
import jpg_boundary_kmz_core as core
from buffer_settings import BufferSettings
from polyline_boundary import build_per_side_polyline_boundary, _project_linework


class PerSideAuditTests(TestCase):
    def test_controls_bind_to_app_window_when_another_tk_root_exists(self):
        host = gui.tk.Tk()
        host.withdraw()
        try:
            with TemporaryDirectory() as tmp, _app() as app:
                import_input(app, write_kmz(tmp))
                app.buffer_var.set("350")
                app.quick_per_side_checkbutton.invoke()
                self.assertTrue(app.per_side_var.get())
                self.assertEqual(app.left_buffer_entry.get(), "350")
                self.assertEqual(app.quick_right_buffer_entry.get(), "350")
                app.quick_right_buffer_entry.delete(0, "end")
                app.quick_right_buffer_entry.insert(0, "150")
                self.assertEqual(app.right_buffer_var.get(), "150")
                self.assertEqual(app.right_buffer_entry.get(), "150")
                app.per_side_checkbutton.invoke()
                self.assertFalse(app.per_side_var.get())
                self.assertEqual(app.quick_buffer_entry.get(), "350")
        finally:
            host.destroy()

    def test_visible_dpi_layout_keeps_long_credits_above_panels_and_scale(self):
        with _app() as app:
            app.root.geometry("960x600+80+80")
            app.root.deiconify()
            app.root.update()
            result = _sample_boundary_result()
            app._cached_result = result
            app._last_displayed_result = result
            app._draw_preview(result)
            app.empty_input_overlay.place_forget()
            app._toggle_settings_drawer()
            app._open_fullscreen_preview()
            inspector = app._fullscreen_window
            inspector.tk.call("wm", "deiconify", str(inspector))
            inspector.tk.call("wm", "geometry", str(inspector), "640x420+100+100")
            app.root.update()
            for surface, panel in ((app._main_map_surface, app.settings_drawer),
                                   (app._fullscreen_map_surface, app._fullscreen_key_frame)):
                with self.subTest(surface=surface.surface_id):
                    widget = surface.canvas.get_tk_widget()
                    surface.canvas.resize(SimpleNamespace(width=widget.winfo_width(), height=widget.winfo_height()))
                    app._apply_basemap_frame(_frame_for(app._current_projected_view(surface), credit="W" * 500))
                    for _ in range(3):
                        app.root.update()
                        surface.canvas.draw()
                    artist = surface.attribution_artist
                    renderer = surface.figure.canvas.get_renderer()
                    bbox = artist.get_bbox_patch().get_window_extent(renderer)
                    self.assertGreaterEqual(artist.get_fontsize(), 9)
                    self.assertEqual("".join(artist.get_text().split()), "PoweredbyEsri|" + "W" * 500)
                    self.assertGreaterEqual(bbox.y0, 0)
                    self.assertLessEqual(bbox.x1, surface.figure.bbox.x1)
                    self.assertFalse(_bboxes_intersect(bbox, _scale_artist_bbox(surface, renderer)))
                    if app._attribution_bands.get(surface.surface_id):
                        self.assertGreaterEqual(bbox.y0, surface.axes.bbox.y1 - panel.winfo_y())
                    else:
                        self.assertLessEqual(bbox.x1, panel.winfo_x())
                    # Returning to an ordinary credit restores the full panel height.
                    app._apply_basemap_frame(_frame_for(app._current_projected_view(surface), credit="Esri"))
                    app.root.update()
                    self.assertEqual(app._attribution_bands.get(surface.surface_id, 0), 0)

    def test_attribution_reflows_when_panels_change_without_another_imagery_response(self):
        with _app() as app:
            result = _sample_boundary_result()
            app._cached_result = result
            app.root.geometry("960x600")
            app.root.update()
            app._draw_preview(result)
            surface = app._main_map_surface
            widget = surface.canvas.get_tk_widget()
            surface.canvas.resize(SimpleNamespace(width=widget.winfo_width(), height=widget.winfo_height()))
            app._apply_basemap_frame(_frame_for(app._current_projected_view(surface), credit="W" * 500))
            surface.canvas.draw()
            full_width_lines = len(surface.attribution_artist.get_text().splitlines())
            for action, overlay in ((app._toggle_settings_drawer, app.settings_drawer),
                                    (app._toggle_preview_key, app.preview_key_overlay),
                                    (app._close_preview_key, None)):
                action()
                app.root.update()
                surface.canvas.draw()
                artist = surface.attribution_artist
                renderer = surface.figure.canvas.get_renderer()
                bbox = artist.get_bbox_patch().get_window_extent(renderer)
                self.assertFalse(_bboxes_intersect(bbox, _scale_artist_bbox(surface, renderer)))
                if overlay:
                    self.assertLessEqual(bbox.x1, overlay.winfo_x() - 1)
                else:
                    self.assertEqual(len(artist.get_text().splitlines()), full_width_lines)

    def test_shutdown_stops_progressbar_and_owned_layout_callbacks(self):
        with _app() as app:
            app._set_busy(True, "Working")
            app._queue_attribution_layout()
            app._shutdown_basemap()
            scripts = [str(app.root.tk.call("after", "info", after_id))
                       for after_id in app.root.tk.splitlist(app.root.tk.call("after", "info"))]
            for script in scripts:
                self.assertNotIn("Autoincrement", script)
                self.assertNotIn("_finish_buffer_layout", script)
                self.assertNotIn("_refresh_main_attribution_layout", script)

    def test_seeded_bends_preserve_connectivity_coverage_and_reversal(self):
        rng = random.Random(92026)
        transform = Transformer.from_crs(32617, 4326, always_xy=True)
        for case in range(40):
            points = [(400000 + i * 70, 3800000 + rng.uniform(-150, 150)) for i in range(10)]
            line = LineString([transform.transform(*point) for point in points])
            source = _project_linework([line]).projected_linework
            for left, right in ((0, 100), (100, 0), (0.005, 0.01), (350, 150), (1, 2000)):
                with self.subTest(case=case, left=left, right=right):
                    shape = build_per_side_polyline_boundary([line], left, right).final_polygon_projected
                    reverse = build_per_side_polyline_boundary(
                        [LineString(list(line.coords)[::-1])], right, left).final_polygon_projected
                    self.assertTrue(shape.is_valid and shape.geom_type == "Polygon" and shape.area > 0)
                    self.assertTrue(shape.buffer(2e-6).covers(source))
                    self.assertLess(shape.symmetric_difference(reverse).area / shape.area, 1e-5)

    def test_backend_rejects_invalid_section_numbers_and_distances(self):
        with TemporaryDirectory() as tmp:
            path = write_kmz(tmp)
            for settings in ({"section_count": 1.5}, {"section_count": float("nan")},
                             {"section_count": True}, {"overlap_ft": float("inf")},
                             {"overlap_ft": float("nan")}, {"split_direction_deg": float("inf")}):
                with self.subTest(settings=settings), self.assertRaises(core.BoundaryError):
                    core.generate_boundary_from_input(path, 0, buffer_settings=BufferSettings.per_side(100, 50), **settings)

    def test_folder_with_vector_suffix_still_uses_jpg_import(self):
        with TemporaryDirectory(suffix=".kmz") as tmp, _app() as app:
            request = app._new_geometry_request(Path(tmp), 0)
            with patch.object(gui, "generate_boundary_from_input", return_value=_sample_boundary_result()) as generate:
                app._generate_for_request(request)
            generate.assert_called_once()

    def test_parse_failure_clears_previous_compatibility(self):
        with TemporaryDirectory() as tmp, _app() as app:
            path = write_kmz(tmp)
            import_input(app, path)
            app.quick_per_side_checkbutton.invoke()
            path.write_bytes(b"corrupt KMZ")
            with patch.object(gui.threading, "Thread") as thread:
                app._scan_clicked()
                call = thread.call_args.kwargs
                call["target"](*call["args"])
            with patch.object(gui.messagebox, "showerror") as error:
                app._drain_queue()
                error.assert_called_once()
            self.assertFalse(app._compatibility.eligible)
            self.assertFalse(app.per_side_var.get())
            self.assertFalse(app._quick_mode_group.grid_info())

    def test_pending_result_cannot_mark_changed_side_values_current(self):
        with TemporaryDirectory() as tmp, _app() as app:
            import_input(app, write_kmz(tmp))
            app.buffer_var.set("350")
            app.quick_per_side_checkbutton.invoke()
            app.right_buffer_var.set("150")
            with patch.object(gui.threading, "Thread") as thread:
                app._scan_clicked()
                call = thread.call_args.kwargs
                app.right_buffer_var.set("225")
                call["target"](*call["args"])
            app._drain_queue()
            self.assertEqual(app.right_buffer_var.get(), "225")
            self.assertEqual(app._last_displayed_result.metadata.right_buffer_ft, 150)
            self.assertEqual(app.preview_state_var.get(), "Preview out of date")

    def test_invalid_overlap_rejected_before_worker_submission(self):
        with TemporaryDirectory() as tmp, _app() as app:
            import_input(app, write_kmz(tmp))
            app.quick_per_side_checkbutton.invoke()
            app.section_count_var.set("4")
            for value in ("nan", "inf", "-inf"):
                with self.subTest(value=value):
                    app.overlap_var.set(value)
                    with self.assertRaises(core.BoundaryError):
                        app._read_inputs(require_output=False)

    def test_export_failure_preserves_existing_file_and_cleans_partial_output(self):
        with TemporaryDirectory() as tmp:
            source = write_kmz(tmp)
            result = core.generate_boundary_from_input(source, 0, buffer_settings=BufferSettings.per_side(100, 50))
            output = Path(tmp) / "existing.kmz"
            output.write_bytes(b"previous export")

            def fail_after_write(path):
                Path(path).write_bytes(b"partial export")
                raise OSError("disk write failed")

            with patch.object(core.simplekml.Kml, "savekmz", side_effect=fail_after_write):
                with self.assertRaises(OSError):
                    core.save_kmz(result, output)
            self.assertEqual(output.read_bytes(), b"previous export")
            self.assertEqual({p.name for p in Path(tmp).iterdir()}, {source.name, output.name})
            # A locked destination must also retain its existing contents.
            with patch.object(core.os, "replace", side_effect=PermissionError("destination locked")):
                with self.assertRaises(PermissionError):
                    core.save_kmz(result, output)
            self.assertEqual(output.read_bytes(), b"previous export")
            self.assertEqual({p.name for p in Path(tmp).iterdir()}, {source.name, output.name})

    def test_direction_arrows_stay_on_original_segments_at_bends(self):
        with _app() as app:
            result = _sample_boundary_result()
            result.metadata = replace(result.metadata, input_type="KMZ polyline", buffer_mode="per_side")
            # A quarter of this route falls exactly on a right-angle turn.
            line = LineString([(0, 0), (100, 0), (100, 300)])
            result.source_lines_projected = (line,)
            app._draw_preview(result)
            arrows = [a for a in app.axes.texts if a.get_gid() == "source-direction-arrow"]
            self.assertTrue(arrows)
            for arrow in arrows:
                shaft = LineString([arrow.xy, arrow.get_position()])
                self.assertTrue(line.buffer(1e-8).covers(shaft))
