from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import jpg_boundary_kmz_gui as gui


class BrowseHistoryTests(TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.preferences = self.directory / "preferences" / "last-directory.txt"
        patcher = patch.object(gui.BoundaryKmzApp, "_browse_directory_file", return_value=self.preferences)
        patcher.start()
        self.addCleanup(patcher.stop)

    def app(self):
        app = gui.BoundaryKmzApp.__new__(gui.BoundaryKmzApp)
        app._last_browse_directory = app._load_browse_directory()
        app._busy = False
        app.root = Mock()
        app.output_var = Mock()
        app.output_var.get.return_value = ""
        app._set_input_path = Mock()
        app._set_output_path = Mock()
        return app

    def test_dialogs_share_history_and_restore_it_in_a_new_instance(self):
        app = self.app()
        folder = self.directory / "photos"
        folder.mkdir()
        with patch.object(gui.filedialog, "askdirectory", return_value=str(folder)):
            app._browse_parent()
        vector = self.directory / "boundary.kml"
        with patch.object(gui.filedialog, "askopenfilename", return_value=str(vector)) as dialog:
            app._browse_kmz()
            self.assertEqual(Path(dialog.call_args.kwargs["initialdir"]), folder)
        with patch.object(gui.filedialog, "asksaveasfilename", return_value=str(folder / "output.kmz")) as dialog:
            app._browse_output()
            self.assertEqual(Path(dialog.call_args.kwargs["initialdir"]), self.directory)
        self.assertEqual(Path(self.app()._browse_initial_directory()), folder)

    def test_cancel_preserves_saved_history_for_every_dialog(self):
        app = self.app()
        app._remember_browse_directory(self.directory)
        before = self.preferences.read_bytes()
        for dialog, browse in (("askdirectory", app._browse_parent),
                               ("askopenfilename", app._browse_kmz),
                               ("asksaveasfilename", app._browse_output)):
            with patch.object(gui.filedialog, dialog, return_value=""):
                browse()
            self.assertEqual(self.preferences.read_bytes(), before)
            self.assertEqual(Path(app._browse_initial_directory()), self.directory)

    def test_missing_or_corrupt_preferences_and_deleted_folder_fall_back(self):
        self.assertEqual(self.app()._last_browse_directory, "")
        self.preferences.parent.mkdir()
        self.preferences.write_bytes(b"\xff")
        self.assertEqual(self.app()._last_browse_directory, "")
        self.preferences.write_text(str(self.directory / "deleted"), encoding="utf-8")
        with patch.object(gui.sys, "platform", "linux"):
            self.assertEqual(self.app()._browse_initial_directory(), str(Path.home()))

    def test_unwritable_preferences_still_remember_directory_in_session(self):
        app = self.app()
        with patch.object(gui.tempfile, "NamedTemporaryFile", side_effect=PermissionError):
            app._remember_browse_directory(self.directory)
        self.assertEqual(Path(app._browse_initial_directory()), self.directory)
