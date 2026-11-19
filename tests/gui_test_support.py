"""Background-only Tk policy for test processes, including direct Tcl calls.

This guards visibility, not native desktop behavior: hidden tests can check
widgets, callbacks, rendering and requested layout, but cannot certify native
focus or hit-testing. Those checks require explicit, per-run user authorization
and BOUNDARY_ALLOW_FOREGROUND_GUI_TESTS=1 in a fresh process.
"""
from __future__ import annotations

from functools import wraps
import os
import tkinter as tk
from tkinter import commondialog
from unittest import skipUnless


FOREGROUND_GUI_ALLOWED = os.environ.get("BOUNDARY_ALLOW_FOREGROUND_GUI_TESTS") == "1"
foreground_gui_test = skipUnless(
    FOREGROUND_GUI_ALLOWED,
    "foreground GUI check requires explicit user authorization and opt-in",
)

# Intercept below the Python wm_* aliases: some tests/application paths call
# Tcl directly. Keeping every toplevel withdrawn also prevents focus_set from
# activating a window. Child-widget raise must still work for overlay layout.
_BACKGROUND_TCL = r"""
namespace eval ::background_gui_tests {}
rename ::wm ::background_gui_tests::wm
proc ::wm {operation window args} {
    if {[string match ${operation}* manage]} {
        error "Background GUI tests cannot promote widgets to visible windows."
    }
    if {[string match ${operation}* deiconify] ||
        [string match ${operation}* iconify]} {
        return [::background_gui_tests::wm withdraw $window]
    }
    if {[string match ${operation}* state] && [llength $args] > 0} {
        return [::background_gui_tests::wm withdraw $window]
    }
    if {[string match ${operation}* attributes] && [llength $args] > 1} {
        foreach {option value} $args {
            if {$option in {-topmost -fullscreen -zoomed} && $value} {
                return ""
            }
        }
    }
    tailcall ::background_gui_tests::wm $operation $window {*}$args
}
rename ::toplevel ::background_gui_tests::toplevel
proc ::toplevel {window args} {
    set result [::background_gui_tests::toplevel $window {*}$args]
    ::background_gui_tests::wm withdraw $window
    return $result
}
rename ::focus ::background_gui_tests::focus
proc ::focus {args} {
    if {[llength $args] > 0 && [lindex $args 0] ni {-displayof -lastfor}} {
        return ""
    }
    tailcall ::background_gui_tests::focus {*}$args
}
rename ::raise ::background_gui_tests::raise
proc ::raise {window args} {
    if {[winfo toplevel $window] eq $window} { return "" }
    tailcall ::background_gui_tests::raise $window {*}$args
}
# Native dialogs can also be requested directly from Tcl, bypassing the
# Python commondialog hook. Define blockers before any lazy Tk autoload.
foreach command {tk_messageBox tk_getOpenFile tk_getSaveFile tk_chooseDirectory tk_chooseColor tk_popup} {
    proc ::$command {args} {
        error "Background GUI tests must mock dialogs and popup menus."
    }
}
rename ::menu ::background_gui_tests::menu
proc ::background_gui_tests::check_menu_post {command operation} {
    set subcommand [lindex $command 1]
    if {$subcommand ne "" &&
        ([string match ${subcommand}* post] || [string match ${subcommand}* postcascade])} {
        error "Background GUI tests must mock dialogs and popup menus."
    }
}
proc ::menu {window args} {
    set result [::background_gui_tests::menu $window {*}$args]
    trace add execution $window enter ::background_gui_tests::check_menu_post
    return $result
}
wm withdraw .
"""


def require_foreground_gui() -> None:
    """Fail before creating windows when a visible harness is run by accident."""
    if not FOREGROUND_GUI_ALLOWED:
        raise RuntimeError(
            "Foreground GUI review is disabled. Only after an explicit user "
            "request, set BOUNDARY_ALLOW_FOREGROUND_GUI_TESTS=1 for that run."
        )


def _blocked_dialog(*args, **kwargs):
    raise RuntimeError("Background GUI tests must mock dialogs and popup menus.")


def install_background_gui_guard() -> None:
    """Install once before any Tk root is created; production imports are untouched."""
    if FOREGROUND_GUI_ALLOWED or getattr(tk.Tk, "_background_test_guard", False):
        return
    original_loadtk = tk.Tk._loadtk

    @wraps(original_loadtk)
    def hidden_loadtk(self):
        original_loadtk(self)
        if not self.tk.call("info", "commands", "::background_gui_tests::wm"):
            self.tk.eval(_BACKGROUND_TCL)

    # _loadtk also covers Tk(useTk=False).loadtk(), and runs before Tk's
    # optional profile scripts or a subclass can process its first idle event.
    tk.Tk._loadtk = hidden_loadtk
    tk.Tk._background_test_guard = True
    # Unmocked dialogs should fail immediately instead of blocking the test run
    # or stealing focus. Normal tests already mock their expected responses.
    commondialog.Dialog.show = _blocked_dialog
    tk.Menu.post = _blocked_dialog
    tk.Menu.tk_popup = _blocked_dialog
    tk.Misc.wait_visibility = _blocked_dialog
