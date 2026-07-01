from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from jpg_boundary_kmz_core import BoundaryError  # noqa: E402
from jpg_boundary_kmz_gui import BoundaryKmzApp, _create_root  # noqa: E402


class GuiInputTests(TestCase):
    def test_read_inputs_accepts_kml_file(self) -> None:
        with TemporaryDirectory() as tmp, _app() as app:
            kml_path = Path(tmp) / "input.kml"
            kml_path.write_text("<kml/>", encoding="utf-8")
            app.parent_var.set(str(kml_path))
            app.buffer_var.set("100")
            app.section_count_var.set("1")

            input_path, _buffer, _count, _overlap, _label, outline_mode, _split, _out = (
                app._read_inputs(require_output=False)
            )

            self.assertEqual(input_path, kml_path)
            self.assertEqual(outline_mode, "source_polygon")

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

    def test_vector_input_disables_outline_mode(self) -> None:
        with TemporaryDirectory() as tmp, _app() as app:
            kml_path = Path(tmp) / "input.kml"
            kml_path.write_text("<kml/>", encoding="utf-8")
            app.parent_var.set(str(kml_path))
            app._update_outline_mode_state()

            self.assertEqual(str(app.outline_mode_combo.cget("state")), "disabled")

    def test_split_direction_controls_only_enable_for_multiple_sections(self) -> None:
        with _app() as app:
            app.section_count_var.set("1")
            app._update_section_control_state()
            self.assertEqual(str(app.split_direction_combo.cget("state")), "disabled")

            app.section_count_var.set("2")
            app._update_section_control_state()
            self.assertEqual(str(app.split_direction_combo.cget("state")), "readonly")


class _app:
    def __enter__(self) -> BoundaryKmzApp:
        self.root = _create_root()
        self.root.withdraw()
        self.app = BoundaryKmzApp(self.root)
        return self.app

    def __exit__(self, exc_type, exc, tb) -> None:
        self.root.destroy()
