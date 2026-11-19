"""Exercise the actual GUI worker, serializer, and external diagnostic log."""
import logging
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from tests.test_gui_input import _app
from tests.test_polyline_compatibility import write_kmz
import generation_log
import jpg_boundary_kmz_gui as gui


class ExportEndToEndTests(TestCase):
    def test_export_menu_to_real_styled_file_and_external_log(self):
        body = ("<Polygon><outerBoundaryIs><LinearRing><coordinates>"
                "-80,35 -79.99,35 -79.99,35.01 -80,35.01 -80,35"
                "</coordinates></LinearRing></outerBoundaryIs></Polygon>")
        logger = logging.Logger("export-audit-integration")
        with TemporaryDirectory() as tmp, _app() as app, \
                patch.object(generation_log, "generation_logger", logger), \
                patch.object(gui, "generation_logger", logger), \
                patch.object(gui.messagebox, "showerror") as error:
            log_path = generation_log.configure_generation_log(Path(tmp) / "logs")
            try:
                source = write_kmz(tmp, body, name="Client source.kmz")
                with patch.object(app, "_scan_clicked"):
                    app._set_input_path(source)
                app.buffer_var.set("50")
                app.export_palette_var.set(False)
                app.export_line_color_var.set("#123456")
                app.export_fill_color_var.set("#abcdef")
                app.export_line_width_var.set("3.5")
                app.export_line_opacity_var.set("75")
                app.export_fill_opacity_var.set("25")
                previous_result = None
                for mode, count in (("outline", 1), ("both", 2), ("fill", 2)):
                    if count != app._current_section_count_for_state():
                        app.section_count_var.set(str(count))
                        app.shape_label_var.set("Survey α")
                    app.export_mode_var.set(mode)
                    destination = Path(tmp) / "Chosen folder" / f"Delivery – {mode}.kmz"
                    app._set_output_path(destination)
                    app.export_button.invoke()
                    self.assertFalse(destination.exists())
                    self.assertTrue(app._settings_drawer_open)
                    app.confirm_export_button.invoke()
                    deadline = time.monotonic() + 30
                    while app._busy and time.monotonic() < deadline:
                        app.root.update()
                        app._drain_queue()
                        time.sleep(0.01)
                    self.assertFalse(app._busy, "Actual export worker did not finish")
                    error.assert_not_called()
                    self.assertEqual(app._last_export_path, destination)
                    self.assertTrue(destination.is_file())
                    with ZipFile(destination) as archive:
                        root = ET.fromstring(archive.read("doc.kml"))
                    self.assertEqual(root.findall(".//{*}description"), [])
                    names = [item.text for item in root.findall(".//{*}Placemark/{*}name")]
                    self.assertEqual(names, [destination.stem] if count == 1 else
                                     ["Survey α (1 of 2)", "Survey α (2 of 2)"])
                    self.assertEqual(len(root.findall(".//{*}Polygon")), count)
                    for style in root.findall(".//{*}Style"):
                        self.assertEqual(style.findtext("{*}LineStyle/{*}color"), "bf563412")
                        self.assertEqual(style.findtext("{*}PolyStyle/{*}color"), "40efcdab")
                        self.assertEqual(float(style.findtext("{*}LineStyle/{*}width")), 3.5)
                        self.assertEqual(style.findtext("{*}PolyStyle/{*}fill"), str(int(mode != "outline")))
                        self.assertEqual(style.findtext("{*}PolyStyle/{*}outline"), str(int(mode != "fill")))
                    if mode == "fill":
                        self.assertIs(app._cached_result, previous_result,
                                      "Appearance and filename edits should reuse export-quality geometry")
                    previous_result = app._cached_result
                    self.assertIn(f"Saved KMZ: {destination}", log_path.read_text(encoding="utf-8"))
                self.assertIn(str(source), log_path.read_text(encoding="utf-8"))
                self.assertIn("Section name: Survey α (2 of 2)", log_path.read_text(encoding="utf-8"))
            finally:
                for handler in logger.handlers:
                    handler.close()
