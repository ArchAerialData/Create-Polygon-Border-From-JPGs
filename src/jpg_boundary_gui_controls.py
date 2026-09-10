"""Small, native Tk controls shared by the desktop workspace.

Keep behavior here limited to presentation, focus, and keyboard interaction.
Boundary generation and export remain in the existing application controller.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from jpg_boundary_gui_theme import PALETTE


class DropdownButton(ttk.Button):
    """A themed button with a native, keyboard-accessible command menu."""

    def __init__(self, parent, **kwargs) -> None:
        super().__init__(parent, command=self._post_menu, **kwargs)
        self.menu = tk.Menu(
            self, tearoff=False, background=PALETTE.SURFACE_RAISED,
            foreground=PALETTE.TEXT, activebackground=PALETTE.PRIMARY,
            activeforeground=PALETTE.TEXT, relief="flat", borderwidth=1,
            font=("Segoe UI", 10),
        )
        self.bind("<Down>", self._post_menu)
        self.bind("<Return>", self._post_menu)

    def _post_menu(self, _event=None) -> str:
        if not self.instate(["disabled"]):
            try:
                self.menu.tk_popup(self.winfo_rootx(), self.winfo_rooty() + self.winfo_height() + 3)
            finally:
                self.menu.grab_release()
        return "break"


class ToolTip:
    """Show contextual help on hover or keyboard focus without stealing focus."""

    def __init__(self, widget: tk.Widget, text) -> None:
        self.widget = widget
        self.text = text
        self.window: tk.Toplevel | None = None
        self.after_id: str | None = None
        for event in ("<Enter>", "<FocusIn>"):
            widget.bind(event, self._schedule, add="+")
        for event in ("<Leave>", "<FocusOut>", "<ButtonPress>", "<Destroy>"):
            widget.bind(event, self.hide, add="+")

    def _schedule(self, _event=None) -> None:
        self.hide()
        self.after_id = self.widget.after(650, self._show)

    def _show(self) -> None:
        self.after_id = None
        if not self.widget.winfo_viewable():
            return
        text = self.text() if callable(self.text) else self.text
        if not text:
            return
        window = self.window = tk.Toplevel(self.widget)
        window.withdraw()
        window.overrideredirect(True)
        tk.Label(
            window, text=text, justify="left", wraplength=360,
            background=PALETTE.SURFACE_RAISED, foreground=PALETTE.TEXT,
            font=("Segoe UI", 10), padx=12, pady=8,
            highlightthickness=1, highlightbackground=PALETTE.BORDER,
        ).pack()
        window.update_idletasks()
        # Keep help beside its control, including monitors with negative origins.
        from jpg_boundary_gui_window import get_window_work_area
        area = get_window_work_area(self.widget.winfo_toplevel())
        x = min(self.widget.winfo_rootx(), area.right - window.winfo_reqwidth() - 8)
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        if y + window.winfo_reqheight() > area.bottom - 8:
            y = self.widget.winfo_rooty() - window.winfo_reqheight() - 6
        window.geometry(f"+{max(area.left + 8, x)}+{max(area.top + 8, y)}")
        window.deiconify()

    def hide(self, _event=None) -> None:
        if self.after_id is not None:
            self.widget.after_cancel(self.after_id)
            self.after_id = None
        if self.window is not None:
            self.window.destroy()
            self.window = None
