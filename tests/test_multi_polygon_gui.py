from __future__ import annotations

import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import numpy as np

from tests.test_gui_input import _app
from tests.test_multi_polygon import FIXTURE, NS
import jpg_boundary_kmz_gui as gui_module
from jpg_boundary_kmz_core import BOUNDARY_COLORS, BoundaryCollectionResult


class MultiPolygonGuiTests(TestCase):
    def run_worker(self, app, action):
        with patch.object(gui_module.threading, "Thread") as worker:
            action()
            worker.return_value.start.assert_called_once()
            worker.call_args.kwargs["target"](*worker.call_args.kwargs["args"])
        with patch.object(gui_module.messagebox, "showerror") as error:
            app._drain_queue()
            error.assert_not_called()
        return worker.call_args.kwargs["args"]

    def test_fixture_preview_export_controls_and_cache(self):
        with TemporaryDirectory() as tmp, _app() as app:
            source = Path(tmp) / "source.kmz"
            shutil.copyfile(FIXTURE, source)
            app.parent_var.set(str(source))
            app._set_output_path(Path(tmp) / "facilities.kmz")
            app.buffer_var.set("100")
            app.section_count_var.set("2")
            self.run_worker(app, app._scan_clicked)
            result = app._last_displayed_result
            self.assertIsInstance(result, BoundaryCollectionResult)
            self.assertEqual(result.metadata.output_polygon_count, 74)
            self.assertEqual(app.preview_state_var.get(), "Preview current")
            self.assertEqual(app.section_count_label.cget("text"), "Sections per polygon")
            self.assertEqual(app.quick_section_count_label.cget("text"), "Sections per polygon")
            self.assertIn("disabled", app.shape_label_entry.state())
            self.assertIn("disabled", app.quick_shape_label_entry.state())
            self.assertIn("74 outputs", app.status_var.get())
            app._open_fullscreen_preview()
            self.assertEqual(app._fullscreen_section_count_label.cget("text"), "Sections per polygon")
            self.assertTrue(all("disabled" in w.state() for w in app._fullscreen_shape_label_widgets))

            expected_polygons = [s.polygon_projected for d in result.display_results for s in d.sections]
            for surface in app._active_map_surfaces():
                boundaries = [line for line in surface.axes.lines if (line.get_gid() or "").startswith("boundary-")]
                sources = [line for line in surface.axes.lines if (line.get_gid() or "").startswith("source-polygon-")]
                self.assertEqual(len(boundaries), 74)
                self.assertEqual(len(sources), 37)
                for index, (line, expected) in enumerate(zip(boundaries, expected_polygons)):
                    actual = np.column_stack((line.get_xdata(), line.get_ydata()))
                    self.assertTrue(np.allclose(actual, np.asarray(expected.exterior.coords), atol=1e-6))
                    self.assertEqual(line.get_color(), BOUNDARY_COLORS[index % len(BOUNDARY_COLORS)])
                    x0, x1 = surface.axes.get_xlim()
                    y0, y1 = surface.axes.get_ylim()
                    left, bottom, right, top = expected.bounds
                    self.assertLessEqual(x0, left)
                    self.assertGreaterEqual(x1, right)
                    self.assertLessEqual(y0, bottom)
                    self.assertGreaterEqual(y1, top)
                view = app._current_projected_view(surface)
                self.assertEqual(view.epsg, result.metadata.epsg)

            with patch.object(app, "_show_export_success"):
                self.run_worker(app, app._export_clicked)
            exported = app._cached_result
            self.assertEqual(exported.metadata.generation_profile, "export")
            self.assertLess(exported.metadata.vertex_count, result.metadata.vertex_count)
            with ZipFile(Path(tmp) / "facilities.kmz") as archive:
                root = ET.fromstring(archive.read("doc.kml"))
            self.assertEqual(len(root.findall("k:Document/k:Folder", NS)), 37)
            self.assertEqual(len(root.findall(".//k:Polygon", NS)), 74)

            # An unchanged export reuses the complete export-quality collection.
            with patch.object(gui_module.messagebox, "askyesno", return_value=True), \
                    patch.object(app, "_show_export_success"), \
                    patch.object(app, "_generate_for_request", side_effect=AssertionError("cache was not reused")):
                args = self.run_worker(app, app._export_clicked)
                self.assertIs(args[-2], exported)

            # Same-path source changes cannot reuse the cached collection.
            stat = source.stat()
            os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
            with patch.object(gui_module.messagebox, "askyesno", return_value=True), patch.object(app, "_show_export_success"):
                args = self.run_worker(app, app._export_clicked)
                self.assertIsNone(args[-2])

            for variable, value in ((app.buffer_var, "25"), (app.section_count_var, "1"),
                                    (app.simplify_vector_var, False)):
                app._cached_result = exported
                variable.set(value)
                self.assertIsNone(app._cached_result)
                self.assertTrue(app._preview_stale)

            app.parent_var.set(str(Path(tmp)))
            self.assertEqual(app._source_polygon_count, 0)
            app.section_count_var.set("2")
            app._update_fullscreen_control_state()
            self.assertEqual(app.section_count_label.cget("text"), "Number of shapes")
            self.assertNotIn("disabled", app.shape_label_entry.state())
            self.assertTrue(all("disabled" not in w.state() for w in app._fullscreen_shape_label_widgets))
