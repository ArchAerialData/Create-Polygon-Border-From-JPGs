"""Central visual styling for the JPG Boundary to KMZ GUI.

The helpers in this module deliberately operate on GUI surfaces only.  They do
not own application state, processing behavior, or Matplotlib geometry.
"""

from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from ctypes import wintypes
from dataclasses import dataclass
from tkinter import font as tkfont
from tkinter import ttk
from typing import Any, Iterable

try:
    from jpg_boundary_gui_window import get_toplevel_hwnd
except ImportError:  # pragma: no cover - package-style import fallback
    try:
        from .jpg_boundary_gui_window import get_toplevel_hwnd
    except ImportError:  # pragma: no cover - window module may be unavailable in isolation
        get_toplevel_hwnd = None  # type: ignore[assignment]


@dataclass(frozen=True)
class GuiPalette:
    """Application color tokens shared by Tk, ttk, and Matplotlib."""

    BACKGROUND: str = "#1a1a1a"
    BRAND: str = "#012458"
    BRAND_LIGHT: str = "#a9c9f4"
    BACKGROUND_DEEP: str = "#0f0f0f"
    SURFACE: str = "#242629"
    SURFACE_RAISED: str = "#303338"
    BORDER: str = "#42464d"
    PRIMARY: str = "#314dec"
    FOCUS_INFO: str = "#60a5fa"
    TEXT: str = "#ffffff"
    TEXT_SECONDARY: str = "#b3b3b3"
    TEXT_MUTED: str = "#969ca6"
    SUCCESS: str = "#10b981"
    WARNING: str = "#f59e0b"
    ERROR: str = "#ef4444"
    ERROR_TEXT: str = "#f87171"


PALETTE = GuiPalette()

_BUTTON_STYLE_COLORS = {
    "Secondary.TButton": {
        "normal": PALETTE.SURFACE_RAISED,
        "active": "#3a3a3a",
        "pressed": "#242424",
        "disabled": "#252525",
    },
    "Primary.TButton": {
        "normal": PALETTE.PRIMARY,
        "active": "#405bf0",
        "pressed": "#263bc2",
        "disabled": "#34395a",
    },
    "Success.TButton": {
        "normal": PALETTE.SUCCESS,
        "active": "#18c990",
        "pressed": "#0d9367",
        "disabled": "#24483d",
        "foreground": PALETTE.BACKGROUND_DEEP,
    },
    "Ghost.TButton": {
        "normal": PALETTE.SURFACE,
        "active": PALETTE.SURFACE_RAISED,
        "pressed": PALETTE.SURFACE,
        "disabled": PALETTE.SURFACE,
    },
}
_BUTTON_ELEMENT_NAMES = {
    style_name: f"App.{style_name.removesuffix('.TButton')}.RoundedButton"
    for style_name in _BUTTON_STYLE_COLORS
}
_DWM_ATTRIBUTE_ORDER = (35, 36, 20)
_DWMWA_CAPTION_COLOR = 35
_DWMWA_TEXT_COLOR = 36
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20


def apply_gui_theme(root: tk.Misc) -> ttk.Style:
    """Apply the complete app theme and return its ``ttk.Style`` instance.

    ``clam`` is preferred because it honors the broadest set of portable ttk
    color options.  Every operation that is known to vary by Tk build has a
    deterministic flat fallback.
    """

    style = ttk.Style(root)
    try:
        if "clam" in style.theme_names() and style.theme_use() != "clam":
            style.theme_use("clam")
    except tk.TclError:
        pass

    _configure_root_surface(root)
    _configure_named_fonts(root)
    _configure_base_styles(style)
    _configure_frame_styles(style)
    _configure_label_styles(style)
    _configure_input_styles(style)
    _configure_checkbutton_style(style)
    _configure_flat_button_styles(style)
    _configure_scrollbar_and_progress_styles(style)
    install_rounded_button_elements(style, root)
    _install_rounded_field_elements(style, root)
    _install_checkbox_elements(style, root)
    return style


def style_matplotlib_figure(figure: Any, axes: Any = None) -> None:
    """Apply dark visual defaults to a Figure and one or more axes.

    Plot data, limits, aspect, transforms, and line geometry are untouched.
    """

    try:
        figure.set_facecolor(PALETTE.BACKGROUND_DEEP)
    except (AttributeError, TypeError, ValueError):
        pass

    target_axes = _coerce_axes(figure, axes)
    for item in target_axes:
        style_matplotlib_axes(figure, item)


def style_matplotlib_axes(figure: Any, axes: Any) -> None:
    """Reapply dark axes styling after an ``axes.clear()`` call."""

    try:
        figure.set_facecolor(PALETTE.BACKGROUND_DEEP)
    except (AttributeError, TypeError, ValueError):
        pass
    try:
        axes.set_facecolor(PALETTE.BACKGROUND_DEEP)
    except (AttributeError, TypeError, ValueError):
        pass

    try:
        axes.tick_params(
            axis="both",
            colors=PALETTE.TEXT_SECONDARY,
            labelcolor=PALETTE.TEXT_SECONDARY,
        )
    except (AttributeError, TypeError, ValueError):
        pass

    for spine in getattr(axes, "spines", {}).values():
        try:
            spine.set_color(PALETTE.BORDER)
        except (AttributeError, TypeError, ValueError):
            pass

    for label in (
        getattr(axes, "title", None),
        getattr(getattr(axes, "xaxis", None), "label", None),
        getattr(getattr(axes, "yaxis", None), "label", None),
    ):
        try:
            label.set_color(PALETTE.TEXT)
        except (AttributeError, TypeError, ValueError):
            pass

    for text_item in list(getattr(axes, "texts", ())):
        try:
            text_item.set_color(PALETTE.TEXT_SECONDARY)
        except (AttributeError, TypeError, ValueError):
            pass

    try:
        gridlines = tuple(axes.get_xgridlines()) + tuple(axes.get_ygridlines())
    except (AttributeError, TypeError, ValueError):
        gridlines = ()
    for gridline in gridlines:
        try:
            gridline.set_color(PALETTE.BORDER)
            gridline.set_alpha(0.35)
        except (AttributeError, TypeError, ValueError):
            continue


def style_tk_text(text_widget: tk.Misc) -> None:
    """Style an app-owned raw Tk Text-like widget without changing its state."""

    _safe_configure(
        text_widget,
        background=PALETTE.BACKGROUND_DEEP,
        foreground=PALETTE.TEXT,
        insertbackground=PALETTE.TEXT,
        selectbackground=PALETTE.PRIMARY,
        selectforeground=PALETTE.TEXT,
        highlightbackground=PALETTE.BORDER,
        highlightcolor=PALETTE.FOCUS_INFO,
        highlightthickness=1,
        borderwidth=0,
        relief="flat",
    )


def _resolve_surface_color(surface: str) -> str:
    aliases = {
        "background": PALETTE.BACKGROUND,
        "deep": PALETTE.BACKGROUND_DEEP,
        "background_deep": PALETTE.BACKGROUND_DEEP,
        "surface": PALETTE.SURFACE,
        "raised": PALETTE.SURFACE_RAISED,
        "surface_raised": PALETTE.SURFACE_RAISED,
    }
    return aliases.get(surface.lower(), surface)


def style_tk_canvas(
    canvas: tk.Misc,
    surface: str = PALETTE.SURFACE,
) -> None:
    """Style an app-owned raw Tk Canvas without changing its items or bindings."""

    surface = _resolve_surface_color(surface)
    _safe_configure(
        canvas,
        background=surface,
        highlightbackground=PALETTE.BORDER,
        highlightcolor=PALETTE.FOCUS_INFO,
        highlightthickness=0,
        borderwidth=0,
        relief="flat",
    )


def style_tk_label(
    label: tk.Misc,
    surface: str = PALETTE.SURFACE,
    foreground: str = PALETTE.TEXT,
) -> None:
    """Style an app-owned raw Tk Label, including the compact drop target."""

    surface = _resolve_surface_color(surface)
    _safe_configure(
        label,
        background=surface,
        foreground=foreground,
        activebackground=PALETTE.SURFACE_RAISED,
        activeforeground=PALETTE.TEXT,
        highlightbackground=PALETTE.BORDER,
        highlightcolor=PALETTE.FOCUS_INFO,
    )


def style_navigation_toolbar(toolbar: tk.Misc) -> None:
    """Darken a Matplotlib Tk toolbar while preserving every toolbar command."""

    _style_raw_tk_surface_tree(toolbar, PALETTE.SURFACE)


def style_app_toplevel(window: tk.Misc) -> bool:
    """Style an app-owned root/Toplevel and apply native chrome when supported."""

    _safe_configure(window, background=PALETTE.BACKGROUND)
    return apply_windows_native_chrome(window)


def install_rounded_button_elements(style: ttk.Style, root: tk.Misc) -> bool:
    """Install image-backed rounded ttk button elements.

    On unsupported or restricted Tk builds, this returns ``False`` and leaves
    the already-configured flat ``ttk.Button`` styles intact.
    """

    try:
        existing_elements = set(style.element_names())
        if all(name in existing_elements for name in _BUTTON_ELEMENT_NAMES.values()):
            return True

        images: dict[str, tk.PhotoImage] = {}
        element_specs: list[tuple[str, str, dict[str, tk.PhotoImage]]] = []
        for style_name, colors in _BUTTON_STYLE_COLORS.items():
            prefix = style_name.removesuffix(".TButton").lower()
            state_images = {
                "normal": _create_rounded_image(
                    root,
                    colors["normal"],
                    PALETTE.BORDER,
                ),
                "active": _create_rounded_image(
                    root,
                    colors["active"],
                    PALETTE.FOCUS_INFO,
                ),
                "pressed": _create_rounded_image(
                    root,
                    colors["pressed"],
                    PALETTE.FOCUS_INFO,
                ),
                "focus": _create_rounded_image(
                    root,
                    colors["normal"],
                    PALETTE.FOCUS_INFO,
                    border_width=2,
                ),
                "disabled": _create_rounded_image(
                    root,
                    colors["disabled"],
                    PALETTE.BORDER,
                ),
            }
            for state_name, image in state_images.items():
                images[f"{prefix}_{state_name}"] = image
            element_specs.append(
                (_BUTTON_ELEMENT_NAMES[style_name], style_name, state_images)
            )

        for element_name, _style_name, state_images in element_specs:
            style.element_create(
                element_name,
                "image",
                state_images["normal"],
                ("disabled", state_images["disabled"]),
                ("pressed", state_images["pressed"]),
                ("focus", state_images["focus"]),
                ("active", state_images["active"]),
                border=_rounded_corner_size(root),
                padding=2,
                sticky="nsew",
            )

        for element_name, style_name, _state_images in element_specs:
            # Transparent image corners reveal the widget's background. The
            # colored fill belongs to the image, not the rectangular Tk surface.
            style.configure(style_name, background=PALETTE.SURFACE)
            style.map(style_name, background=[("disabled", PALETTE.SURFACE),
                                               ("active", PALETTE.SURFACE)])
            style.layout(
                style_name,
                [
                    (
                        element_name,
                        {
                            "sticky": "nsew",
                            "children": [
                                (
                                    "Button.padding",
                                    {
                                        "sticky": "nsew",
                                        "children": [
                                            ("Button.label", {"sticky": "nsew"})
                                        ],
                                    },
                                )
                            ],
                        },
                    )
                ],
            )

        setattr(root, "_jpg_boundary_gui_theme_images", images)
        return True
    except Exception:
        return False


def _install_checkbox_elements(style: ttk.Style, root: tk.Misc) -> None:
    """Larger, high-contrast indicators while retaining native checkbox semantics."""
    if "App.Check.indicator" in style.element_names():
        return
    try:
        from PIL import Image, ImageDraw, ImageTk
        size = max(16, round(14 * float(root.tk.call("tk", "scaling"))))
        images = {}
        for name, checked, disabled in (("off", False, False), ("on", True, False),
                                         ("disabled_off", False, True), ("disabled_on", True, True)):
            image = Image.new("RGBA", (size * 4, size * 4))
            draw = ImageDraw.Draw(image)
            fill = PALETTE.PRIMARY if checked and not disabled else PALETTE.SURFACE_RAISED
            border = PALETTE.BORDER if disabled else PALETTE.FOCUS_INFO if checked else PALETTE.TEXT_MUTED
            draw.rounded_rectangle((2, 2, size * 4 - 3, size * 4 - 3), radius=12,
                                   fill=fill, outline=border, width=4)
            if checked:
                draw.line([(size * 1.0, size * 2.0), (size * 1.7, size * 2.7),
                           (size * 3.0, size * 1.2)],
                          fill=PALETTE.TEXT_MUTED if disabled else PALETTE.TEXT, width=6)
            padded = Image.new("RGBA", (size + 8, size))
            padded.paste(image.resize((size, size), Image.Resampling.LANCZOS), (0, 0))
            images[name] = ImageTk.PhotoImage(padded, master=root)
        name = "App.Check.indicator"
        style.element_create(name, "image", images["off"],
                             ("disabled", "selected", images["disabled_on"]),
                             ("disabled", images["disabled_off"]), ("selected", images["on"]))
        for style_name in ("App.TCheckbutton", "Surface.TCheckbutton"):
            style.layout(style_name, [("Checkbutton.padding", {"sticky": "nswe", "children": [
                (name, {"side": "left", "sticky": ""}),
                ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [
                    ("Checkbutton.label", {"sticky": "nswe"}),
                ]}),
            ]})])
        setattr(root, "_jpg_boundary_checkbox_images", images)
    except (ImportError, tk.TclError):
        # The native themed checkbox remains fully usable on other Tk builds.
        pass


def apply_windows_native_chrome(root: tk.Misc) -> bool:
    """Best-effort dark Windows title-bar styling for an app-owned window."""

    if sys.platform != "win32" or get_toplevel_hwnd is None:
        return False

    try:
        hwnd = get_toplevel_hwnd(root)
        if not hwnd:
            return False

        dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
        setter = dwmapi.DwmSetWindowAttribute
        setter.argtypes = [
            wintypes.HWND,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        setter.restype = ctypes.c_long

        caption_color = wintypes.DWORD(_hex_to_colorref(PALETTE.BACKGROUND))
        text_color = wintypes.DWORD(_hex_to_colorref(PALETTE.TEXT))
        dark_mode = wintypes.BOOL(1)
        values = (
            (_DWMWA_CAPTION_COLOR, caption_color),
            (_DWMWA_TEXT_COLOR, text_color),
            (_DWMWA_USE_IMMERSIVE_DARK_MODE, dark_mode),
        )

        any_succeeded = False
        for attribute, value in values:
            try:
                result = setter(
                    wintypes.HWND(hwnd),
                    wintypes.DWORD(attribute),
                    ctypes.cast(ctypes.byref(value), ctypes.c_void_p),
                    wintypes.DWORD(ctypes.sizeof(value)),
                )
            except (AttributeError, OSError, OverflowError, TypeError, ValueError):
                continue
            result_value = getattr(result, "value", result)
            any_succeeded = int(result_value) == 0 or any_succeeded
        return any_succeeded
    except (
        AttributeError,
        ImportError,
        OSError,
        OverflowError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        return False


def apply_app_theme(root: tk.Misc) -> ttk.Style:
    """Stable integration alias for :func:`apply_gui_theme`."""

    return apply_gui_theme(root)


def style_toolbar(toolbar: tk.Misc) -> None:
    """Stable integration alias for :func:`style_navigation_toolbar`."""

    style_navigation_toolbar(toolbar)


def apply_native_chrome(window: tk.Misc) -> bool:
    """Stable integration alias for :func:`apply_windows_native_chrome`."""

    return apply_windows_native_chrome(window)


def _configure_root_surface(root: tk.Misc) -> None:
    _safe_configure(root, background=PALETTE.BACKGROUND)
    option_colors = {
        "*background": PALETTE.BACKGROUND,
        "*foreground": PALETTE.TEXT,
        "*Background": PALETTE.BACKGROUND,
        "*Foreground": PALETTE.TEXT,
        "*activeBackground": PALETTE.SURFACE_RAISED,
        "*activeForeground": PALETTE.TEXT,
        "*disabledForeground": PALETTE.TEXT_MUTED,
        "*highlightBackground": PALETTE.BORDER,
        "*highlightColor": PALETTE.FOCUS_INFO,
        "*insertBackground": PALETTE.TEXT,
        "*selectBackground": PALETTE.PRIMARY,
        "*selectForeground": PALETTE.TEXT,
        "*TCombobox*Listbox.background": PALETTE.SURFACE_RAISED,
        "*TCombobox*Listbox.foreground": PALETTE.TEXT,
        "*TCombobox*Listbox.selectBackground": PALETTE.PRIMARY,
        "*TCombobox*Listbox.selectForeground": PALETTE.TEXT,
        "*TCombobox*Listbox.highlightBackground": PALETTE.BORDER,
        "*TCombobox*Listbox.highlightColor": PALETTE.FOCUS_INFO,
        "*Canvas.background": PALETTE.BACKGROUND_DEEP,
        "*Listbox.background": PALETTE.SURFACE_RAISED,
        "*Listbox.foreground": PALETTE.TEXT,
        "*Listbox.selectBackground": PALETTE.PRIMARY,
        "*Listbox.selectForeground": PALETTE.TEXT,
        "*Menu.background": PALETTE.SURFACE,
        "*Menu.foreground": PALETTE.TEXT,
        "*Menu.activeBackground": PALETTE.PRIMARY,
        "*Menu.activeForeground": PALETTE.TEXT,
        "*Text.background": PALETTE.BACKGROUND_DEEP,
        "*Text.foreground": PALETTE.TEXT,
    }
    for pattern, value in option_colors.items():
        try:
            root.option_add(pattern, value)
        except (AttributeError, tk.TclError):
            continue


def _configure_named_fonts(root: tk.Misc) -> None:
    try:
        families = {name.casefold(): name for name in tkfont.families(root)}
        preferred_family = families.get("segoe ui")
        if preferred_family is None:
            return
        for font_name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
            tkfont.nametofont(font_name, root=root).configure(family=preferred_family, size=10)
        tkfont.nametofont("TkHeadingFont", root=root).configure(
            family=preferred_family,
            size=12,
            weight="bold",
        )
    except (AttributeError, RuntimeError, tk.TclError):
        pass


def _configure_base_styles(style: ttk.Style) -> None:
    """Define composite surface styles used by the preview-first shell."""
    style.configure(
        "Card.TFrame",
        background=PALETTE.SURFACE,
        bordercolor=PALETTE.BORDER,
        lightcolor=PALETTE.BORDER,
        darkcolor=PALETTE.BORDER,
        borderwidth=1,
        relief="flat",
    )
    style.configure(
        "Overlay.TFrame",
        background=PALETTE.SURFACE,
        bordercolor=PALETTE.FOCUS_INFO,
        lightcolor=PALETTE.BORDER,
        darkcolor=PALETTE.BORDER,
        borderwidth=1,
        relief="flat",
    )
    style.configure(
        "Preview.TFrame",
        background=PALETTE.BACKGROUND_DEEP,
        borderwidth=0,
        relief="flat",
    )


def _configure_frame_styles(style: ttk.Style) -> None:
    style.configure("Brand.TFrame", background=PALETTE.BRAND)
    style.configure("TFrame", background=PALETTE.BACKGROUND)
    style.configure(
        "TLabelframe",
        background=PALETTE.BACKGROUND,
        bordercolor=PALETTE.BORDER,
        lightcolor=PALETTE.BORDER,
        darkcolor=PALETTE.BORDER,
        borderwidth=1,
        relief="flat",
    )
    style.configure(
        "TLabelframe.Label",
        background=PALETTE.BACKGROUND,
        foreground=PALETTE.TEXT_SECONDARY,
        font="TkDefaultFont",
    )
    style.configure("App.TFrame", background=PALETTE.BACKGROUND)
    style.configure("Surface.TFrame", background=PALETTE.SURFACE)
    style.configure("Raised.TFrame", background=PALETTE.SURFACE_RAISED)
    style.configure(
        "ActionBar.TFrame",
        background=PALETTE.SURFACE,
        bordercolor=PALETTE.BORDER,
        borderwidth=1,
        relief="flat",
    )
    style.configure(
        "Drawer.TFrame",
        background=PALETTE.SURFACE,
        bordercolor=PALETTE.BORDER,
        borderwidth=1,
        relief="flat",
    )
    style.configure("Toolbar.TFrame", background=PALETTE.SURFACE)


def _configure_label_styles(style: ttk.Style) -> None:
    style.configure("Brand.TLabel", background=PALETTE.BRAND, foreground=PALETTE.TEXT,
                    font=("Segoe UI", 18, "bold"))
    style.configure("Brand.Caption.TLabel", background=PALETTE.BRAND,
                    foreground=PALETTE.BRAND_LIGHT, font=("Segoe UI", 9, "bold"))
    style.configure("Hero.TLabel", background=PALETTE.SURFACE,
                    foreground=PALETTE.TEXT, font=("Segoe UI", 20, "bold"))
    style.configure("Eyebrow.TLabel", background=PALETTE.SURFACE,
                    foreground=PALETTE.FOCUS_INFO, font=("Segoe UI", 9, "bold"))
    style.configure(
        "TLabel",
        background=PALETTE.BACKGROUND,
        foreground=PALETTE.TEXT,
        font="TkDefaultFont",
    )
    style.configure(
        "App.TLabel",
        background=PALETTE.BACKGROUND,
        foreground=PALETTE.TEXT,
        font="TkDefaultFont",
    )
    style.configure(
        "Secondary.TLabel",
        background=PALETTE.SURFACE,
        foreground=PALETTE.TEXT_SECONDARY,
        font="TkDefaultFont",
    )
    style.configure(
        "Surface.TLabel",
        background=PALETTE.SURFACE,
        foreground=PALETTE.TEXT,
        font="TkDefaultFont",
    )
    style.configure(
        "Surface.Secondary.TLabel",
        background=PALETTE.SURFACE,
        foreground=PALETTE.TEXT_SECONDARY,
        font="TkDefaultFont",
    )
    style.configure(
        "Raised.TLabel",
        background=PALETTE.SURFACE_RAISED,
        foreground=PALETTE.TEXT,
        font="TkDefaultFont",
    )
    style.configure(
        "Muted.TLabel",
        background=PALETTE.SURFACE,
        foreground=PALETTE.TEXT_SECONDARY,
        font="TkDefaultFont",
    )
    style.configure(
        "Title.TLabel",
        background=PALETTE.SURFACE,
        foreground=PALETTE.TEXT,
        font="TkHeadingFont",
    )
    style.configure(
        "Status.TLabel",
        background=PALETTE.SURFACE,
        foreground=PALETTE.TEXT_SECONDARY,
        font="TkDefaultFont",
    )
    style.configure(
        "Stale.Status.TLabel",
        background=PALETTE.SURFACE,
        foreground=PALETTE.WARNING,
        font="TkDefaultFont",
    )
    style.configure(
        "Success.Status.TLabel",
        background=PALETTE.SURFACE,
        foreground=PALETTE.SUCCESS,
        font="TkDefaultFont",
    )
    style.configure(
        "Error.Status.TLabel",
        background=PALETTE.SURFACE,
        foreground=PALETTE.ERROR_TEXT,
        font="TkDefaultFont",
    )
    for style_name in (
        "TLabel",
        "Brand.TLabel",
        "Brand.Caption.TLabel",
        "Hero.TLabel",
        "Eyebrow.TLabel",
        "App.TLabel",
        "Secondary.TLabel",
        "Surface.TLabel",
        "Surface.Secondary.TLabel",
        "Raised.TLabel",
        "Muted.TLabel",
        "Title.TLabel",
        "Status.TLabel",
        "Stale.Status.TLabel",
        "Success.Status.TLabel",
        "Error.Status.TLabel",
    ):
        style.map(
            style_name,
            background=[("disabled", style.configure(style_name, "background"))],
            foreground=[
                ("disabled", PALETTE.TEXT_MUTED),
            ],
        )


    # Field headings remain legible when the associated editor is unavailable.
    style.configure("Field.TLabel", background=PALETTE.SURFACE, foreground=PALETTE.TEXT)
    style.map("Field.TLabel", background=[("disabled", PALETTE.SURFACE)],
              foreground=[("disabled", PALETTE.TEXT)])


def _configure_input_styles(style: ttk.Style) -> None:
    common = {
        "background": PALETTE.SURFACE_RAISED,
        "fieldbackground": PALETTE.SURFACE_RAISED,
        "foreground": PALETTE.TEXT,
        "insertcolor": PALETTE.TEXT,
        "bordercolor": PALETTE.BORDER,
        "lightcolor": PALETTE.BORDER,
        "darkcolor": PALETTE.BORDER,
        "selectbackground": PALETTE.PRIMARY,
        "selectforeground": PALETTE.TEXT,
        "padding": (8, 6),
    }
    for style_name in ("TEntry", "App.TEntry"):
        style.configure(style_name, **common)
    for style_name in ("TCombobox", "App.TCombobox"):
        style.configure(
            style_name,
            **common,
            arrowcolor=PALETTE.TEXT_SECONDARY,
        )
    for style_name in ("TSpinbox", "App.TSpinbox"):
        style.configure(
            style_name,
            **common,
            arrowcolor=PALETTE.TEXT_SECONDARY,
        )

    for style_name in (
        "TEntry",
        "App.TEntry",
        "TCombobox",
        "App.TCombobox",
        "TSpinbox",
        "App.TSpinbox",
    ):
        style.map(
            style_name,
            foreground=[
                ("disabled", PALETTE.TEXT_MUTED),
                ("readonly", PALETTE.TEXT),
            ],
            fieldbackground=[
                ("disabled", PALETTE.SURFACE),
                ("readonly", PALETTE.SURFACE_RAISED),
            ],
            bordercolor=[
                ("invalid", PALETTE.ERROR),
                ("focus", PALETTE.FOCUS_INFO),
                ("disabled", PALETTE.BORDER),
                ("readonly", PALETTE.BORDER),
            ],
            lightcolor=[
                ("focus", PALETTE.FOCUS_INFO),
            ],
            darkcolor=[
                ("focus", PALETTE.FOCUS_INFO),
            ],
        )
    for style_name in ("TCombobox", "App.TCombobox"):
        style.map(
            style_name,
            arrowcolor=[
                ("disabled", PALETTE.TEXT_MUTED),
                ("pressed", PALETTE.TEXT),
                ("active", PALETTE.FOCUS_INFO),
                ("readonly", PALETTE.TEXT_SECONDARY),
            ],
            selectbackground=[
                ("readonly", PALETTE.SURFACE_RAISED),
            ],
            selectforeground=[
                ("readonly", PALETTE.TEXT),
            ],
        )
    for style_name in ("TSpinbox", "App.TSpinbox"):
        style.map(
            style_name,
            arrowcolor=[
                ("disabled", PALETTE.TEXT_MUTED),
                ("pressed", PALETTE.TEXT),
                ("active", PALETTE.FOCUS_INFO),
            ],
        )


def _configure_checkbutton_style(style: ttk.Style) -> None:
    for style_name, background in (
        ("TCheckbutton", PALETTE.BACKGROUND),
        ("App.TCheckbutton", PALETTE.BACKGROUND),
        ("Surface.TCheckbutton", PALETTE.SURFACE),
    ):
        style.configure(
            style_name,
            background=background,
            foreground=PALETTE.TEXT,
            indicatorcolor=PALETTE.SURFACE_RAISED,
            indicatormargin=4,
            focuscolor=PALETTE.FOCUS_INFO,
            padding=(2, 4),
        )
        style.map(
            style_name,
            background=[
                ("active", background),
                ("disabled", background),
            ],
            foreground=[
                ("disabled", PALETTE.TEXT_MUTED),
                ("active", PALETTE.TEXT),
            ],
            indicatorcolor=[
                ("disabled", PALETTE.SURFACE),
                ("selected", PALETTE.PRIMARY),
                ("pressed", PALETTE.FOCUS_INFO),
                ("active", PALETTE.SURFACE_RAISED),
            ],
        )


def _configure_flat_button_styles(style: ttk.Style) -> None:
    style_colors = {
        "TButton": _BUTTON_STYLE_COLORS["Secondary.TButton"],
        **_BUTTON_STYLE_COLORS,
    }
    for style_name, colors in style_colors.items():
        button_foreground = colors.get("foreground", PALETTE.TEXT)
        style.configure(
            style_name,
            background=colors["normal"],
            foreground=button_foreground,
            bordercolor=PALETTE.BORDER,
            lightcolor=colors["normal"],
            darkcolor=colors["normal"],
            focuscolor=PALETTE.FOCUS_INFO,
            focusthickness=2,
            borderwidth=1,
            relief="flat",
            padding=(12, 5),
            font=("Segoe UI", 10),
            anchor="center",
        )
        style.map(
            style_name,
            background=[
                ("disabled", colors["disabled"]),
                ("pressed", colors["pressed"]),
                ("active", colors["active"]),
            ],
            foreground=[
                ("disabled", PALETTE.TEXT_SECONDARY),
                ("pressed", button_foreground),
                ("active", button_foreground),
                ("focus", button_foreground),
            ],
            bordercolor=[
                ("disabled", PALETTE.BORDER),
                ("focus", PALETTE.FOCUS_INFO),
                ("pressed", PALETTE.FOCUS_INFO),
                ("active", PALETTE.FOCUS_INFO),
            ],
            lightcolor=[
                ("focus", PALETTE.FOCUS_INFO),
            ],
            darkcolor=[
                ("focus", PALETTE.FOCUS_INFO),
            ],
        )


def _configure_scrollbar_and_progress_styles(style: ttk.Style) -> None:
    for style_name in ("Vertical.TScrollbar", "App.Vertical.TScrollbar"):
        style.configure(
            style_name,
            background=PALETTE.SURFACE_RAISED,
            troughcolor=PALETTE.BACKGROUND_DEEP,
            bordercolor=PALETTE.BACKGROUND_DEEP,
            arrowcolor=PALETTE.TEXT_SECONDARY,
            lightcolor=PALETTE.SURFACE_RAISED,
            darkcolor=PALETTE.SURFACE_RAISED,
            gripcount=0,
        )
        style.map(
            style_name,
            background=[
                ("disabled", PALETTE.SURFACE),
                ("pressed", PALETTE.PRIMARY),
                ("active", PALETTE.FOCUS_INFO),
            ],
            arrowcolor=[
                ("disabled", PALETTE.TEXT_MUTED),
                ("active", PALETTE.TEXT),
            ],
        )
    for style_name in ("Horizontal.TProgressbar", "Busy.Horizontal.TProgressbar"):
        style.configure(
            style_name,
            background=PALETTE.PRIMARY,
            troughcolor=PALETTE.BACKGROUND_DEEP,
            bordercolor=PALETTE.BORDER,
            lightcolor=PALETTE.PRIMARY,
            darkcolor=PALETTE.PRIMARY,
            thickness=6,
        )


def _rounded_corner_size(root: tk.Misc) -> int:
    return max(8, round(8 * float(root.tk.call("tk", "scaling")) / (96 / 72)))


def _install_rounded_field_elements(style: ttk.Style, root: tk.Misc) -> None:
    """Skin native editors without replacing their editing or keyboard bindings."""
    element = "App.RoundedField"
    if element in style.element_names():
        return
    images = {
        "normal": _create_rounded_image(root, PALETTE.SURFACE_RAISED, PALETTE.BORDER),
        "focus": _create_rounded_image(root, PALETTE.SURFACE_RAISED, PALETTE.FOCUS_INFO, border_width=2),
        "invalid": _create_rounded_image(root, PALETTE.SURFACE_RAISED, PALETTE.ERROR, border_width=2),
        "disabled": _create_rounded_image(root, PALETTE.SURFACE, PALETTE.BORDER),
    }
    style.element_create(element, "image", images["normal"],
                         ("disabled", images["disabled"]), ("invalid", images["invalid"]),
                         ("focus", images["focus"]), border=_rounded_corner_size(root), padding=3,
                         sticky="nsew")
    # Image arrows avoid the square, separately painted clam arrow buttons.
    # The uparrow/downarrow suffixes retain ttk's native hit targets and bindings.
    arrow_size = max(16, round(16 * float(root.tk.call("tk", "scaling")) / (96 / 72)))
    for direction in ("up", "down"):
        for state, color in (("normal", PALETTE.TEXT_SECONDARY), ("disabled", PALETTE.TEXT_MUTED)):
            arrow = tk.PhotoImage(master=root, width=arrow_size, height=arrow_size // 2 + 3)
            triangle_height = max(4, round(arrow_size / 4))
            for row in range(triangle_height):
                half_width = row if direction == "up" else triangle_height - 1 - row
                x = arrow_size // 2
                y = 3 + row
                arrow.put(color, to=(x - half_width, y, x + half_width + 1, y + 1))
            images[f"{direction}_{state}"] = arrow
        style.element_create(f"App.Field.{direction}arrow", "image", images[f"{direction}_normal"],
                             ("disabled", images[f"{direction}_disabled"]))
    for kind in ("Entry", "Combobox", "Spinbox"):
        children = []
        if kind == "Combobox":
            children.append(("App.Field.downarrow", {"side": "right", "sticky": ""}))
        elif kind == "Spinbox":
            children.append(("null", {"side": "right", "children": [
                ("App.Field.uparrow", {"side": "top", "sticky": "e"}),
                ("App.Field.downarrow", {"side": "bottom", "sticky": "e"}),
            ]}))
        children.append((f"{kind}.padding", {"sticky": "nsew", "children": [
            (f"{kind}.textarea", {"sticky": "nsew"}),
        ]}))
        name = f"App.T{kind}"
        style.layout(name, [(element, {"sticky": "nsew", "children": children})])
        style.configure(name, background=PALETTE.SURFACE)
        style.map(name, background=[("disabled", PALETTE.SURFACE), ("readonly", PALETTE.SURFACE),
                                    ("active", PALETTE.SURFACE)])
    root._jpg_boundary_field_images = images


def _create_rounded_image(
    root: tk.Misc,
    fill: str,
    outline: str,
    *,
    border_width: int = 1,
) -> tk.PhotoImage:
    # Supersampling removes jagged corners while preserving the native ttk
    # focus, pressed, disabled and keyboard states. Pillow ships with Matplotlib.
    try:
        from PIL import Image, ImageDraw, ImageTk
        scale = 4
        corner = _rounded_corner_size(root)
        size = corner * 2 + 4
        image = Image.new("RGBA", (size * scale, size * scale))
        drawing = ImageDraw.Draw(image)
        drawing.rounded_rectangle(
            (1, 1, size * scale - 2, size * scale - 2), radius=corner * scale,
            fill=fill, outline=outline, width=border_width * scale,
        )
        return ImageTk.PhotoImage(image.resize((size, size), Image.Resampling.LANCZOS), master=root)
    except ImportError:
        pass
    width = 20
    height = 20
    image = tk.PhotoImage(master=root, width=width, height=height)
    outer_insets = (6, 4, 3, 2, 1, 1, 0, 0, 0, 0)
    for y in range(height):
        mirrored_y = min(y, height - 1 - y)
        inset = outer_insets[min(mirrored_y, len(outer_insets) - 1)]
        image.put(outline, to=(inset, y, width - inset, y + 1))

    effective_border = max(1, min(int(border_width), 3))
    for y in range(effective_border, height - effective_border):
        mirrored_y = min(y, height - 1 - y)
        inset = outer_insets[min(mirrored_y, len(outer_insets) - 1)]
        inner_inset = max(inset + effective_border, effective_border)
        if inner_inset < width - inner_inset:
            image.put(fill, to=(inner_inset, y, width - inner_inset, y + 1))
    return image


def _coerce_axes(figure: Any, axes: Any) -> Iterable[Any]:
    if axes is None:
        return tuple(getattr(figure, "axes", ()))
    if isinstance(axes, (list, tuple, set)):
        return tuple(axes)
    return (axes,)


def _style_raw_tk_surface_tree(widget: tk.Misc, surface: str) -> None:
    if isinstance(widget, tk.Canvas):
        style_tk_canvas(widget, surface)
    elif isinstance(widget, tk.Text):
        style_tk_text(widget)
    elif isinstance(widget, (tk.Button, tk.Checkbutton, tk.Radiobutton)):
        _safe_configure(
            widget,
            background=surface,
            foreground=PALETTE.TEXT,
            activebackground=PALETTE.SURFACE_RAISED,
            activeforeground=PALETTE.TEXT,
            disabledforeground=PALETTE.TEXT_MUTED,
            selectcolor=PALETTE.PRIMARY,
            highlightbackground=surface,
            highlightcolor=PALETTE.FOCUS_INFO,
            borderwidth=0,
            relief="flat",
        )
    elif isinstance(widget, (tk.Label, tk.Message)):
        style_tk_label(widget, surface)
    else:
        _safe_configure(widget, background=surface)

    try:
        children = widget.winfo_children()
    except (AttributeError, tk.TclError):
        children = ()
    for child in children:
        _style_raw_tk_surface_tree(child, surface)


def _safe_configure(widget: tk.Misc, **options: object) -> None:
    try:
        widget.configure(**options)
    except (AttributeError, TypeError, tk.TclError):
        for name, value in options.items():
            try:
                widget.configure(**{name: value})
            except (AttributeError, TypeError, tk.TclError):
                continue


def _hex_to_colorref(color: str) -> int:
    normalized = color.lstrip("#")
    if len(normalized) != 6:
        raise ValueError(f"Expected #RRGGBB color, got {color!r}")
    red = int(normalized[0:2], 16)
    green = int(normalized[2:4], 16)
    blue = int(normalized[4:6], 16)
    return red | (green << 8) | (blue << 16)


__all__ = [
    "GuiPalette",
    "PALETTE",
    "apply_app_theme",
    "apply_gui_theme",
    "apply_native_chrome",
    "apply_windows_native_chrome",
    "install_rounded_button_elements",
    "style_app_toplevel",
    "style_matplotlib_axes",
    "style_matplotlib_figure",
    "style_navigation_toolbar",
    "style_toolbar",
    "style_tk_canvas",
    "style_tk_label",
    "style_tk_text",
]
