"""Offline visual review harness: python -B -m tests.preview_gui --state sections.

Uses synthetic boundary data and disables imagery before rendering a result.
No source imagery or user outputs are read, written, or exported.
"""

from __future__ import annotations

import argparse

from tests.test_gui_input import _sample_boundary_result
from jpg_boundary_kmz_gui import BoundaryKmzApp, _create_root
from jpg_boundary_gui_theme import apply_native_chrome


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", choices=("empty", "preview", "sections", "boundary", "output", "view", "busy"), default="empty")
    parser.add_argument("--geometry", default="1280x800+40+40")
    parser.add_argument("--scale", type=float)
    args = parser.parse_args()
    root = _create_root()
    root.withdraw()
    if args.scale is not None:
        root.tk.call("tk", "scaling", args.scale)
    root.geometry(args.geometry)
    app = BoundaryKmzApp(root)
    app.world_imagery_var.set(False)
    root.title("Boundary workspace — UI review")
    if args.state != "empty":
        result = _sample_boundary_result()
        app.parent_var.set("C:/Survey/Elkin Estes/Drone photos")
        app.output_name_var.set("Elkin_Estes_boundary")
        app._cached_result = result
        app._last_displayed_result = result
        app._draw_preview(result)
        app._mark_preview_current()
        app.status_var.set("Review your boundary, then export the KMZ.")
    if args.state in {"sections", "boundary", "output"}:
        app._toggle_settings_panel("input" if args.state == "boundary" else args.state)
    elif args.state == "view":
        app._toggle_view_menu()
    elif args.state == "busy":
        app._set_busy(True, "Reading input and building preview...")
    apply_native_chrome(root)
    root.deiconify()
    root.lift()
    root.mainloop()


if __name__ == "__main__":
    main()
