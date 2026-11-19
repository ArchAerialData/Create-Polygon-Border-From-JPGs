"""Regression checks for the user's background-only GUI test policy."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from unittest import TestCase, TestResult, defaultTestLoader, skipIf
from unittest.mock import patch

from tests.gui_test_support import FOREGROUND_GUI_ALLOWED


@skipIf(FOREGROUND_GUI_ALLOWED, "background policy checks need the default guarded process")
class BackgroundGuiTests(TestCase):
    def root(self, **kwargs):
        # Match application startup before the first native handle is created.
        # Otherwise Windows can lock this process into DPI-unaware behavior and
        # contaminate subsequent layout tests, even though these roots are hidden.
        from tests.test_gui_input import gui_module

        gui_module.enable_windows_dpi_awareness()
        root = tk.Tk(**kwargs)
        self.addCleanup(root.destroy)
        return root

    def assert_hidden(self, window):
        # Verify the policy before pumping events, so a failure cannot itself
        # display a test window while checking the guard.
        self.assertEqual(window.state(), "withdrawn")
        window.update_idletasks()
        self.assertFalse(window.winfo_ismapped())
        self.assertFalse(window.winfo_viewable())

    def test_root_stays_hidden_through_every_visibility_alias(self):
        root = self.root()
        self.assert_hidden(root)
        for operation in (
            root.deiconify, root.wm_deiconify, root.iconify,
            lambda: root.state("normal"), lambda: root.wm_state("zoomed"),
            lambda: root.attributes("-topmost", True),
            lambda: root.attributes("-fullscreen", True),
            lambda: root.tk.call("wm", "deic", "."),
            lambda: root.tk.call("wm", "state", ".", "normal"),
        ):
            with self.subTest(operation=operation):
                operation()
                self.assert_hidden(root)
        self.assertFalse(root.attributes("-topmost"))
        self.assertFalse(root.attributes("-fullscreen"))

    def test_child_and_direct_tcl_toplevels_stay_hidden(self):
        root = self.root()
        child = tk.Toplevel(root)
        self.assert_hidden(child)
        child.tk.call("wm", "deiconify", str(child))
        child.state("normal")
        self.assert_hidden(child)
        root.tk.call("toplevel", ".raw_child")
        root.tk.call("wm", "deiconify", ".raw_child")
        self.assertEqual(root.tk.call("wm", "state", ".raw_child"), "withdrawn")
        self.assert_hidden(root)
        self.assertFalse(root.tk.getboolean(root.tk.call("winfo", "ismapped", ".raw_child")))

    def test_lazy_tk_loading_is_guarded(self):
        root = self.root(useTk=False)
        root.loadtk()
        root.deiconify()
        self.assert_hidden(root)

    def test_focus_and_raise_do_not_activate_roots_or_children(self):
        root = self.root()
        child = tk.Toplevel(root)
        for window in (root, child):
            window.focus_force()
            window.focus_set()
            window.lift()
            window.tk.call("focus", "-force", str(window))
            self.assert_hidden(window)
            self.assertIsNone(window.focus_get())
        # Raising ordinary frames remains available for overlay rendering.
        first, second = tk.Frame(root), tk.Frame(root)
        first.place(x=0, y=0)
        second.place(x=0, y=0)
        first.lift(second)
        self.assert_hidden(root)

    def test_unmocked_dialogs_and_menus_fail_before_display(self):
        root = self.root()
        menu = tk.Menu(root, tearoff=False)
        for operation in (
            lambda: messagebox.showinfo("Test", "Must stay hidden", parent=root),
            lambda: menu.post(0, 0), lambda: menu.tk_popup(0, 0),
            root.wait_visibility,
        ):
            with self.subTest(operation=operation), self.assertRaisesRegex(RuntimeError, "Background GUI"):
                operation()
        self.assert_hidden(root)

    def test_direct_tcl_dialogs_and_menu_posting_cannot_bypass_guard(self):
        root = self.root()
        menu = tk.Menu(root, tearoff=False)
        calls = [
            (command,) for command in (
                "tk_messageBox", "tk_getOpenFile", "tk_getSaveFile",
                "tk_chooseDirectory", "tk_chooseColor", "tk_popup",
            )
        ]
        calls.extend(((str(menu), "post", 0, 0),
                      (str(menu), "postcascade", 0),
                      ("wm", "manage", str(tk.Frame(root)))))
        for call in calls:
            with self.subTest(call=call), self.assertRaisesRegex(tk.TclError, "Background GUI"):
                root.tk.call(*call)
        self.assert_hidden(root)

    def test_focus_preview_and_inspector_cannot_remap_app(self):
        from tests.test_gui_input import _app, _sample_boundary_result

        with _app() as app:
            app._enter_focus_mode()
            self.assert_hidden(app.root)
            app._exit_focus_mode()
            self.assert_hidden(app.root)
            app._draw_preview(_sample_boundary_result())
            app._open_fullscreen_preview()
            self.assert_hidden(app._fullscreen_window)
            self.assert_hidden(app.root)

    def test_native_suite_is_skipped_even_when_invoked_directly(self):
        from tests.native_export_accessibility import ExportAccessibilityTests

        result = TestResult()
        suite = defaultTestLoader.loadTestsFromTestCase(ExportAccessibilityTests)
        suite.run(result)
        self.assertGreater(result.testsRun, 0)
        self.assertEqual(len(result.skipped), result.testsRun)
        self.assertFalse(result.errors or result.failures)

    def test_manual_preview_is_blocked_before_root_creation(self):
        from tests import preview_gui

        with patch("sys.argv", ["preview_gui"]), patch.object(preview_gui, "_create_root") as create:
            with self.assertRaisesRegex(RuntimeError, "Foreground GUI review is disabled"):
                preview_gui.main()
        create.assert_not_called()
