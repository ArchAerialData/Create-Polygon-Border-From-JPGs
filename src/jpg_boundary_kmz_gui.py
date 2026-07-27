from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import math
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.parse import unquote, urlparse

from matplotlib import patheffects
from matplotlib.backend_bases import MouseButton
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from jpg_boundary_gui_basemap import (
    MAX_OUTPUT_DIMENSION,
    MAX_OUTPUT_PIXELS,
    VIEW_DEBOUNCE_MS,
    ArcGisBasemapClient,
    BasemapFailure,
    BasemapFrame,
    ProjectedView,
)
from jpg_boundary_gui_scale_bar import ScaleBarController
from jpg_boundary_gui_theme import (
    PALETTE,
    apply_gui_theme,
    apply_native_chrome,
    style_app_toplevel,
    style_matplotlib_axes,
    style_navigation_toolbar,
    style_tk_canvas,
    style_tk_label,
    style_tk_text,
)
from jpg_boundary_gui_window import (
    WindowFitResult,
    apply_initial_geometry,
    clamp_child_geometry,
    fit_window_to_work_area,
    get_launch_work_area,
    get_outer_window_bounds,
    get_window_work_area,
)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:
    DND_FILES = None
    TkinterDnD = None

from jpg_boundary_kmz_core import (
    BoundaryError,
    BoundaryResult,
    GENERATION_PROFILE_EXPORT,
    GENERATION_PROFILE_PREVIEW,
    MAX_SECTION_COUNT,
    format_summary,
    generate_boundary_from_input,
    save_kmz,
)
from outline_strategies import (
    OUTLINE_MODE_AUTO,
    OUTLINE_MODE_CONCAVE,
    OUTLINE_MODE_LAWNMOWER,
    OUTLINE_MODE_ROUTE_AWARE,
)


SRC_DIR = Path(__file__).resolve().parent
APP_ROOT = SRC_DIR.parent
DEFAULT_OUTPUT_DIR = APP_ROOT / "outputs"
OUTLINE_MODE_LABELS = {
    "Auto": OUTLINE_MODE_AUTO,
    "Concave hull": OUTLINE_MODE_CONCAVE,
    "Route-aware": OUTLINE_MODE_ROUTE_AWARE,
    "Lawnmower outer envelope": OUTLINE_MODE_LAWNMOWER,
}
OUTLINE_MODE_SOURCE_POLYGON = "source_polygon"
PREVIEW_SCROLL_ZOOM_FACTOR = 1.2
PREVIEW_MAX_PLOT_POINTS = 2500
PREVIEW_LIMIT_PADDING_RATIO = 0.04
PREVIEW_KEY_PANEL_WIDTH = 340
PREVIEW_KEY_WRAP_LENGTH = 270
ACTION_BAR_MIN_BREAKPOINT = 1120
HEADER_MIN_BREAKPOINT = 760
SETTINGS_DRAWER_WIDTH = 430
SPLIT_DIRECTION_OPTIONS = (
    "Auto",
    "0 deg / East-West",
    "90 deg / North-South",
    "Custom",
)
BASEMAP_FAILURE_DIAGNOSTICS = {
    "imagery_error": "Imagery is unavailable for this view.",
    "metadata_unavailable": "Imagery service is temporarily unavailable.",
    "metadata_incompatible": "Imagery service metadata is incompatible.",
    "invalid_view": "Imagery is unavailable for this view.",
    "tile_failures": "Imagery is unavailable for this view.",
    "no_imagery": "No imagery is available for this view.",
    "raster_error": "Imagery is unavailable for this view.",
}


@dataclass
class _PreviewMapSurface:
    surface_id: str
    axes: object
    figure: Figure
    canvas: FigureCanvasTkAgg
    status_var: tk.StringVar
    surface_generation: int
    result_generation: int | None
    epsg: int | None
    basemap_image: object | None
    attribution_artist: object | None
    scale_controller: ScaleBarController
    observer_event_cids: list[int]
    debounce_after_id: str | None
    last_submitted_signature: tuple[object, ...] | None
    last_applied_signature: tuple[object, ...] | None


class BoundaryKmzApp:
    def __init__(
        self,
        root: tk.Tk,
        *,
        basemap_client_factory=None,
        basemap_client: ArcGisBasemapClient | None = None,
    ) -> None:
        self.root = root
        self.root.title("JPG Boundary to KMZ")
        self._theme_style = apply_gui_theme(self.root)

        default_output_path = self._default_output_path()
        self.parent_var = tk.StringVar()
        self.buffer_var = tk.StringVar(value="0")
        self.output_name_var = tk.StringVar(value=default_output_path.stem)
        self.output_var = tk.StringVar(value=str(default_output_path))
        self.outline_mode_var = tk.StringVar(value="Auto")
        self.section_count_var = tk.StringVar(value="1")
        self.overlap_var = tk.StringVar(value="50")
        self.shape_label_var = tk.StringVar(value=self._default_shape_label())
        self.split_direction_var = tk.StringVar(value="Auto")
        self.split_direction_degrees_var = tk.StringVar(value="")
        self.simplify_vector_var = tk.BooleanVar(value=False)
        self.world_imagery_var = tk.BooleanVar(value=True)
        self.imagery_status_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Choose a JPG folder, KML, or KMZ file to begin.")
        self.preview_state_var = tk.StringVar(value="No preview")
        self.input_summary_var = tk.StringVar(value="No input selected")
        self._updating_output_fields = False
        self._updating_shape_label = False
        self._shape_label_touched = False
        self._details_text = ""

        self._queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._cached_result: BoundaryResult | None = None
        self._cached_settings: (
            tuple[str, float, int, float, str, str, str, str, str] | None
        ) = None
        self._last_displayed_result: BoundaryResult | None = None
        self._last_displayed_signature: tuple[str, ...] | None = None
        self._preview_stale = False
        self._stale_reason = ""
        self._preview_error = ""
        self._last_input_text = ""
        self._busy = False
        self._settings_drawer_open = False
        self._legend_open = False
        self._focus_mode = False
        self._has_selected_input = False
        self._active_settings_group: str | None = "input"
        self._settings_group_frames: dict[str, ttk.Frame] = {}
        self._settings_group_buttons: dict[str, ttk.Button] = {}
        self._drop_targets: list[tk.Widget] = []
        self._drop_feedback_surfaces: dict[str, tk.Widget] = {}
        self._all_mutation_widgets: list[tk.Widget] = []
        self._section_multiple_widgets: list[tk.Widget] = []
        self._custom_direction_widgets: list[tk.Widget] = []
        self._vector_only_widgets: list[tk.Widget] = []
        self._folder_only_widgets: list[tk.Widget] = []
        self._busy_action_widgets: list[tk.Widget] = []
        self._fullscreen_mutation_widgets: list[tk.Widget] = []
        self._action_bar_breakpoint = ACTION_BAR_MIN_BREAKPOINT
        self._action_bar_compact: bool | None = None
        self._header_breakpoint = HEADER_MIN_BREAKPOINT
        self._header_compact: bool | None = None
        self._focus_saved_state: str | None = None
        self._focus_saved_geometry: str | None = None
        self._focus_title_was_mapped = True
        self._preview_pan_start: tuple[
            object,
            object,
            float,
            float,
            tuple[float, float],
            tuple[float, float],
            float,
            float,
        ] | None = None
        self._preview_event_cids: list[int] = []
        self._main_map_surface: _PreviewMapSurface | None = None
        self._fullscreen_map_surface: _PreviewMapSurface | None = None
        self._basemap_client_factory = (
            basemap_client_factory
            if basemap_client_factory is not None
            else ArcGisBasemapClient
        )
        self._basemap_client = basemap_client
        self._basemap_poll_after_id: str | None = None
        self._closing = False
        self._accepted_result_generation = 0
        self._active_result_generation: int | None = None
        self._map_result_reference: BoundaryResult | None = None
        self._fullscreen_surface_serial = 0
        self._surface_draw_guards: set[str] = set()
        self._surface_copyright_text: dict[str, str] = {}
        self._surface_applied_status: dict[str, str] = {}
        self._basemap_diagnostics: dict[str, tuple[str, str]] = {}
        self._fullscreen_window: tk.Toplevel | None = None
        self._fullscreen_event_cids: list[int] = []
        self._fullscreen_figure: Figure | None = None
        self._fullscreen_axes: object | None = None
        self._fullscreen_canvas: FigureCanvasTkAgg | None = None
        self._fullscreen_toolbar: NavigationToolbar2Tk | None = None
        self._fullscreen_imagery_checkbutton: ttk.Checkbutton | None = None
        self._fullscreen_imagery_status_label: ttk.Label | None = None
        self._fullscreen_key_frame: ttk.LabelFrame | None = None
        self._fullscreen_key_canvas: tk.Canvas | None = None
        self._fullscreen_key_content: ttk.Frame | None = None
        self._fullscreen_status_var: tk.StringVar | None = None
        self._fullscreen_imagery_status_var: tk.StringVar | None = None
        self._fullscreen_section_count_var: tk.StringVar | None = None
        self._fullscreen_overlap_var: tk.StringVar | None = None
        self._fullscreen_shape_label_var: tk.StringVar | None = None
        self._fullscreen_split_direction_var: tk.StringVar | None = None
        self._fullscreen_split_direction_degrees_var: tk.StringVar | None = None
        self._fullscreen_apply_button: ttk.Button | None = None
        self._fullscreen_section_widgets: list[tk.Widget] = []
        self._fullscreen_split_direction_combo: ttk.Combobox | None = None
        self._fullscreen_split_direction_custom_label: ttk.Label | None = None
        self._fullscreen_split_direction_custom_entry: ttk.Entry | None = None
        self.preview_key_frame: ttk.LabelFrame | None = None
        self.preview_key_canvas: tk.Canvas | None = None
        self.preview_key_content: ttk.Frame | None = None

        self._build_ui()
        self.output_name_var.trace_add("write", self._on_output_name_changed)
        self.output_var.trace_add("write", self._on_output_changed)
        self.parent_var.trace_add("write", self._on_input_changed)
        self.outline_mode_var.trace_add("write", self._on_outline_mode_changed)
        self.section_count_var.trace_add("write", self._on_section_options_changed)
        self.overlap_var.trace_add("write", self._on_section_options_changed)
        self.shape_label_var.trace_add("write", self._on_shape_label_changed)
        self.split_direction_var.trace_add("write", self._on_split_direction_changed)
        self.split_direction_degrees_var.trace_add("write", self._on_split_direction_changed)
        self.simplify_vector_var.trace_add("write", self._on_vector_simplification_changed)
        self.buffer_var.trace_add("write", self._on_buffer_changed)
        self.world_imagery_var.trace_add("write", self._on_world_imagery_toggled)
        self._update_outline_mode_state()
        self._update_section_control_state()
        self._refresh_input_shell_state()
        self._refresh_preview_state_badge()
        self._register_keyboard_shortcuts()
        self.root.bind("<Configure>", self._on_root_configure, add="+")
        self.root.protocol("WM_DELETE_WINDOW", self._shutdown_basemap)
        self.root.after(100, self._drain_queue)

    def _build_ui(self) -> None:
        self.root_frame = ttk.Frame(self.root, style="App.TFrame", padding=12)
        self.root_frame.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.root_frame.columnconfigure(0, weight=1)
        self.root_frame.rowconfigure(1, weight=1)

        self._build_top_input_strip(self.root_frame)
        self._build_preview_workspace(self.root_frame)
        self._build_action_bar(self.root_frame)
        self._refresh_header_layout()

    def _build_top_input_strip(self, parent: ttk.Frame) -> None:
        self.header_frame = ttk.Frame(
            parent,
            style="Card.TFrame",
            padding=(12, 8),
        )
        self.header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.header_frame.columnconfigure(1, weight=1)

        self.app_title_label = ttk.Label(
            self.header_frame,
            text="JPG Boundary to KMZ",
            style="Title.TLabel",
        )
        self.app_title_label.grid(row=0, column=0, sticky="w", padx=(0, 14))

        self.compact_input_target = tk.Label(
            self.header_frame,
            textvariable=self.input_summary_var,
            anchor="w",
            padx=10,
            pady=6,
            cursor="hand2",
            background="#202838",
            foreground="#d8e7ff",
            highlightthickness=1,
            highlightbackground="#3b4a63",
        )
        self.compact_input_target.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        style_tk_label(
            self.compact_input_target,
            surface="#202838",
            foreground="#d8e7ff",
        )
        self.compact_input_target.bind(
            "<Button-1>",
            lambda _event: self._open_input_settings(),
        )

        self.change_input_button = ttk.Button(
            self.header_frame,
            text="Change Input",
            style="Ghost.TButton",
            command=self._open_input_settings,
        )
        self.change_input_button.grid(row=0, column=2, padx=(0, 6))
        self.key_button = ttk.Button(
            self.header_frame,
            text="Key",
            style="Ghost.TButton",
            command=self._toggle_preview_key,
        )
        self.key_button.grid(row=0, column=3, padx=(0, 6))
        self.settings_button = ttk.Button(
            self.header_frame,
            text="Settings",
            style="Secondary.TButton",
            command=self._toggle_settings_drawer,
        )
        self.settings_button.grid(row=0, column=4, padx=(0, 6))
        self.focus_button = ttk.Button(
            self.header_frame,
            text="Focus Preview",
            style="Ghost.TButton",
            command=self._toggle_focus_mode,
        )
        self.focus_button.grid(row=0, column=5, padx=(0, 6))
        self.expand_preview_button = ttk.Button(
            self.header_frame,
            text="Open Inspector",
            style="Ghost.TButton",
            command=self._open_fullscreen_preview,
        )
        self.expand_preview_button.grid(row=0, column=6)
        self._register_drop_target(
            self.compact_input_target,
            feedback_surface=self.compact_input_target,
        )

    def _build_preview_workspace(self, parent: ttk.Frame) -> None:
        self.preview_frame = ttk.Frame(parent, style="Preview.TFrame")
        self.preview_frame.grid(row=1, column=0, sticky="nsew")
        self.preview_frame.columnconfigure(0, weight=1)
        self.preview_frame.rowconfigure(1, weight=1)

        self.preview_toolbar_frame = ttk.Frame(
            self.preview_frame,
            style="Toolbar.TFrame",
        )
        self.preview_toolbar_frame.grid(row=0, column=0, sticky="ew")
        self.preview_toolbar_frame.columnconfigure(0, weight=1)

        self.preview_stack = ttk.Frame(self.preview_frame, style="Preview.TFrame")
        self.preview_stack.grid(row=1, column=0, sticky="nsew")
        self.preview_stack.columnconfigure(0, weight=1)
        self.preview_stack.rowconfigure(0, weight=1)

        self.figure = Figure(figsize=(8, 5), dpi=100)
        self.axes = self.figure.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.figure, master=self.preview_stack)
        self.canvas_widget = self.canvas.get_tk_widget()
        style_tk_canvas(self.canvas_widget, PALETTE.BACKGROUND_DEEP)
        self.canvas_widget.grid(row=0, column=0, sticky="nsew")

        self.preview_toolbar = NavigationToolbar2Tk(
            self.canvas,
            self.preview_toolbar_frame,
            pack_toolbar=False,
        )
        self.preview_toolbar.update()
        self._disable_toolbar_coordinate_message(self.preview_toolbar)
        style_navigation_toolbar(self.preview_toolbar)
        self.preview_toolbar.grid(row=0, column=0, sticky="ew")

        self.preview_view_controls = ttk.Frame(
            self.preview_toolbar_frame,
            style="Toolbar.TFrame",
        )
        self.preview_view_controls.grid(row=0, column=1, sticky="e", padx=(8, 6))
        self.world_imagery_checkbutton = ttk.Checkbutton(
            self.preview_view_controls,
            text="World Imagery",
            variable=self.world_imagery_var,
            style="Surface.TCheckbutton",
        )
        self.world_imagery_checkbutton.grid(row=0, column=0, sticky="e")
        self.imagery_status_label = ttk.Label(
            self.preview_view_controls,
            textvariable=self.imagery_status_var,
            style="Surface.Secondary.TLabel",
            anchor="e",
            width=20,
        )
        self.imagery_status_label.grid(row=0, column=1, sticky="e", padx=(8, 0))

        self._main_map_surface = self._create_preview_map_surface(
            "main",
            self.axes,
            self.figure,
            self.canvas,
            self.imagery_status_var,
        )
        self._draw_empty_preview()
        self._build_empty_input_overlay(self.preview_stack)
        self._build_settings_drawer(self.preview_stack)
        self._build_preview_key_overlay(self.preview_stack)
        self._register_preview_interactions()

    def _create_preview_map_surface(
        self,
        surface_id: str,
        axes: object,
        figure: Figure,
        canvas: FigureCanvasTkAgg,
        status_var: tk.StringVar,
    ) -> _PreviewMapSurface:
        surface = _PreviewMapSurface(
            surface_id=surface_id,
            axes=axes,
            figure=figure,
            canvas=canvas,
            status_var=status_var,
            surface_generation=0,
            result_generation=None,
            epsg=None,
            basemap_image=None,
            attribution_artist=None,
            scale_controller=ScaleBarController(axes, canvas),
            observer_event_cids=[],
            debounce_after_id=None,
            last_submitted_signature=None,
            last_applied_signature=None,
        )
        surface.observer_event_cids = [
            canvas.mpl_connect(
                "draw_event",
                lambda event, bound=surface: self._on_preview_map_surface_event(
                    bound,
                    event,
                ),
            ),
            canvas.mpl_connect(
                "resize_event",
                lambda event, bound=surface: self._on_preview_map_surface_event(
                    bound,
                    event,
                ),
            ),
        ]
        return surface

    def _active_map_surfaces(self) -> list[_PreviewMapSurface]:
        surfaces: list[_PreviewMapSurface] = []
        if self._main_map_surface is not None:
            surfaces.append(self._main_map_surface)
        if self._fullscreen_map_surface is not None:
            surfaces.append(self._fullscreen_map_surface)
        return surfaces

    def _surface_is_active(self, surface: _PreviewMapSurface) -> bool:
        if surface is self._main_map_surface:
            return True
        return (
            surface is self._fullscreen_map_surface
            and self._fullscreen_window_exists()
        )

    def _surface_for_id(self, surface_id: str) -> _PreviewMapSurface | None:
        for surface in self._active_map_surfaces():
            if surface.surface_id == surface_id:
                return surface
        return None

    def _bind_preview_map_surface(
        self,
        surface: _PreviewMapSurface,
        result_generation: int | None,
        epsg: int | None,
    ) -> None:
        surface.result_generation = result_generation
        surface.epsg = epsg
        if result_generation is None or epsg is None:
            surface.scale_controller.clear()
            surface.status_var.set("")
            return
        surface.scale_controller.bind_result(epsg, result_generation)
        surface.scale_controller.refresh()
        surface.status_var.set(
            "Imagery loading..." if self.world_imagery_var.get() else "Imagery off"
        )

    def _cancel_surface_debounce(self, surface: _PreviewMapSurface) -> None:
        after_id = surface.debounce_after_id
        surface.debounce_after_id = None
        if after_id is None:
            return
        try:
            self.root.after_cancel(after_id)
        except tk.TclError:
            pass

    def _reset_preview_map_surface(
        self,
        surface: _PreviewMapSurface,
        *,
        deregister: bool = False,
    ) -> None:
        self._cancel_surface_debounce(surface)
        surface.surface_generation += 1
        if self._basemap_client is not None:
            if deregister:
                self._basemap_client.deregister_surface(surface.surface_id)
            else:
                self._basemap_client.cancel_surface(
                    surface.surface_id,
                    surface.surface_generation,
                )
        self._remove_basemap_artist(surface)
        surface.scale_controller.clear()
        surface.result_generation = None
        surface.epsg = None
        surface.last_submitted_signature = None
        surface.last_applied_signature = None
        surface.status_var.set("")
        self._surface_draw_guards.discard(surface.surface_id)
        self._surface_copyright_text.pop(surface.surface_id, None)
        self._surface_applied_status.pop(surface.surface_id, None)
        self._basemap_diagnostics.pop(surface.surface_id, None)

    def _on_preview_map_surface_event(
        self,
        surface: _PreviewMapSurface,
        _event: object | None = None,
    ) -> None:
        if self._closing or not self._surface_is_active(surface):
            return
        changed = surface.scale_controller.refresh()
        changed = self._refresh_attribution_artist(surface) or changed
        if changed and surface.surface_id not in self._surface_draw_guards:
            self._surface_draw_guards.add(surface.surface_id)
            surface.canvas.draw_idle()
        elif not changed:
            self._surface_draw_guards.discard(surface.surface_id)
        self._schedule_basemap_refresh(surface)

    def _on_world_imagery_toggled(self, *_args: object) -> None:
        if self._closing:
            return
        enabled = bool(self.world_imagery_var.get())
        surfaces = self._active_map_surfaces()
        if not enabled:
            for surface in surfaces:
                self._cancel_surface_debounce(surface)
                surface.surface_generation += 1
                if self._basemap_client is not None:
                    self._basemap_client.cancel_surface(
                        surface.surface_id,
                        surface.surface_generation,
                    )
                surface.last_submitted_signature = None
                surface.last_applied_signature = None
            if self._basemap_client is not None:
                self._basemap_client.clear_cache()
            for surface in surfaces:
                self._remove_basemap_artist(surface)
                style_matplotlib_axes(surface.figure, surface.axes)
                surface.scale_controller.refresh()
                surface.status_var.set(
                    "Imagery off"
                    if surface.result_generation is not None
                    else ""
                )
                surface.canvas.draw_idle()
            return

        if self._basemap_client is not None:
            self._basemap_client.reset_transient_metadata_failure()
        for surface in surfaces:
            if surface.result_generation is None or surface.epsg is None:
                surface.status_var.set("")
                continue
            surface.status_var.set("Imagery loading...")
            self._schedule_basemap_refresh(surface)

    def _schedule_basemap_refresh(self, surface: _PreviewMapSurface) -> None:
        if (
            self._closing
            or not self._surface_is_active(surface)
            or surface.result_generation is None
            or surface.epsg is None
        ):
            self._cancel_surface_debounce(surface)
            surface.status_var.set("")
            return
        if not self.world_imagery_var.get():
            self._cancel_surface_debounce(surface)
            surface.status_var.set("Imagery off")
            return

        candidate = self._current_projected_view(surface)
        if candidate is None:
            self._cancel_surface_debounce(surface)
            surface.status_var.set("Imagery unavailable")
            return
        signature = self._projected_view_signature(candidate)
        applied_signature = (
            surface.last_applied_signature[1:]
            if surface.last_applied_signature is not None
            else None
        )
        image_attached = (
            surface.basemap_image is not None
            and any(
                image is surface.basemap_image
                for image in getattr(surface.axes, "images", ())
            )
        )
        if signature == applied_signature and image_attached:
            self._cancel_surface_debounce(surface)
            if surface.last_submitted_signature != signature:
                surface.surface_generation += 1
                if self._basemap_client is not None:
                    self._basemap_client.cancel_surface(
                        surface.surface_id,
                        surface.surface_generation,
                    )
            surface.last_submitted_signature = signature
            surface.status_var.set(
                self._surface_applied_status.get(surface.surface_id, "")
            )
            return
        if signature == surface.last_submitted_signature:
            return

        self._cancel_surface_debounce(surface)
        surface.status_var.set("Imagery loading...")

        def submit_latest() -> None:
            surface.debounce_after_id = None
            if (
                self._closing
                or not self.world_imagery_var.get()
                or not self._surface_is_active(surface)
                or surface.result_generation is None
                or surface.epsg is None
            ):
                return
            current = self._current_projected_view(surface)
            if current is None:
                surface.status_var.set("Imagery unavailable")
                return
            current_signature = self._projected_view_signature(current)
            if current_signature == surface.last_submitted_signature:
                return
            surface.surface_generation += 1
            view = ProjectedView(
                surface_id=surface.surface_id,
                generation=surface.surface_generation,
                result_generation=current.result_generation,
                epsg=current.epsg,
                xlim=current.xlim,
                ylim=current.ylim,
                pixel_width=current.pixel_width,
                pixel_height=current.pixel_height,
            )
            surface.last_submitted_signature = current_signature
            try:
                client = self._get_basemap_client()
                client.submit(view)
                self._ensure_basemap_poller()
            except Exception:
                surface.status_var.set("Imagery unavailable")
                self._basemap_diagnostics[surface.surface_id] = (
                    "client",
                    "Imagery support could not be started.",
                )

        try:
            surface.debounce_after_id = self.root.after(
                VIEW_DEBOUNCE_MS,
                submit_latest,
            )
        except tk.TclError:
            surface.debounce_after_id = None

    def _current_projected_view(
        self,
        surface: _PreviewMapSurface,
    ) -> ProjectedView | None:
        if surface.result_generation is None or surface.epsg is None:
            return None
        try:
            xlim = tuple(float(value) for value in surface.axes.get_xlim())
            ylim = tuple(float(value) for value in surface.axes.get_ylim())
            bounds = surface.axes.get_window_extent().bounds
            width = max(1, int(round(float(bounds[2]))))
            height = max(1, int(round(float(bounds[3]))))
        except (AttributeError, TypeError, ValueError, OverflowError):
            return None
        if (
            len(xlim) != 2
            or len(ylim) != 2
            or not all(math.isfinite(value) for value in (*xlim, *ylim))
            or xlim[0] == xlim[1]
            or ylim[0] == ylim[1]
        ):
            return None
        scale = min(
            1.0,
            MAX_OUTPUT_DIMENSION / width,
            MAX_OUTPUT_DIMENSION / height,
            math.sqrt(MAX_OUTPUT_PIXELS / (width * height)),
        )
        pixel_width = max(1, int(math.floor(width * scale)))
        pixel_height = max(1, int(math.floor(height * scale)))
        return ProjectedView(
            surface_id=surface.surface_id,
            generation=surface.surface_generation,
            result_generation=surface.result_generation,
            epsg=surface.epsg,
            xlim=(xlim[0], xlim[1]),
            ylim=(ylim[0], ylim[1]),
            pixel_width=pixel_width,
            pixel_height=pixel_height,
        )

    @staticmethod
    def _projected_view_signature(view: ProjectedView) -> tuple[object, ...]:
        return (
            view.surface_id,
            view.result_generation,
            view.epsg,
            view.xlim,
            view.ylim,
            view.pixel_width,
            view.pixel_height,
        )

    def _get_basemap_client(self):
        if self._basemap_client is None:
            self._basemap_client = self._basemap_client_factory()
        return self._basemap_client

    def _ensure_basemap_poller(self) -> None:
        if self._closing or self._basemap_poll_after_id is not None:
            return
        try:
            self._basemap_poll_after_id = self.root.after(
                50,
                self._run_basemap_poller,
            )
        except tk.TclError:
            self._basemap_poll_after_id = None

    def _run_basemap_poller(self) -> None:
        self._basemap_poll_after_id = None
        self._drain_basemap_queue()

    def _drain_basemap_queue(self) -> None:
        if self._closing:
            return
        client = self._basemap_client
        if client is not None:
            for _index in range(4):
                response = client.poll()
                if response is None:
                    break
                if isinstance(response, BasemapFrame):
                    self._apply_basemap_frame(response)
                elif isinstance(response, BasemapFailure):
                    self._apply_basemap_failure(response)
            self._ensure_basemap_poller()

    def _apply_basemap_frame(self, frame: BasemapFrame) -> None:
        surface = self._surface_for_id(frame.surface_id)
        if (
            surface is None
            or not self.world_imagery_var.get()
            or frame.generation != surface.surface_generation
            or frame.result_generation != surface.result_generation
            or frame.epsg != surface.epsg
        ):
            return
        current = self._current_projected_view(surface)
        if (
            current is None
            or frame.xlim != current.xlim
            or frame.ylim != current.ylim
            or frame.pixel_width != current.pixel_width
            or frame.pixel_height != current.pixel_height
        ):
            return

        axes = surface.axes
        xlim = tuple(axes.get_xlim())
        ylim = tuple(axes.get_ylim())
        data_lim = axes.dataLim.frozen()
        autoscale_x = bool(axes.get_autoscalex_on())
        autoscale_y = bool(axes.get_autoscaley_on())
        use_sticky_edges = bool(axes.use_sticky_edges)
        aspect = axes.get_aspect()
        adjustable = axes.get_adjustable()
        anchor = axes.get_anchor()
        try:
            image_attached = (
                surface.basemap_image is not None
                and any(
                    image is surface.basemap_image
                    for image in axes.images
                )
            )
            if image_attached:
                surface.basemap_image.set_data(frame.rgba)
                surface.basemap_image.set_extent(
                    (frame.xlim[0], frame.xlim[1], frame.ylim[0], frame.ylim[1])
                )
                surface.basemap_image.set_zorder(-100)
            else:
                surface.basemap_image = axes.imshow(
                    frame.rgba,
                    extent=(
                        frame.xlim[0],
                        frame.xlim[1],
                        frame.ylim[0],
                        frame.ylim[1],
                    ),
                    origin="upper",
                    interpolation="bilinear",
                    zorder=-100,
                )
            surface.basemap_image.sticky_edges.x[:] = []
            surface.basemap_image.sticky_edges.y[:] = []
        finally:
            axes.dataLim.set(data_lim)
            axes.use_sticky_edges = use_sticky_edges
            axes.set_aspect(aspect, adjustable=adjustable, anchor=anchor)
            axes.set_xlim(xlim, auto=autoscale_x)
            axes.set_ylim(ylim, auto=autoscale_y)
            axes.set_autoscalex_on(autoscale_x)
            axes.set_autoscaley_on(autoscale_y)
            axes.dataLim.set(data_lim)

        self._surface_copyright_text[surface.surface_id] = frame.copyright_text
        self._refresh_attribution_artist(surface, frame.copyright_text)
        surface.last_applied_signature = (
            frame.generation,
            *self._projected_view_signature(current),
        )
        applied_status = "Imagery partial" if frame.is_partial else ""
        self._surface_applied_status[surface.surface_id] = applied_status
        surface.status_var.set(applied_status)
        self._basemap_diagnostics.pop(surface.surface_id, None)
        surface.canvas.draw_idle()

    def _apply_basemap_failure(self, failure: BasemapFailure) -> None:
        surface = self._surface_for_id(failure.surface_id)
        if (
            surface is None
            or not self.world_imagery_var.get()
            or failure.generation != surface.surface_generation
            or failure.result_generation != surface.result_generation
        ):
            return
        self._remove_basemap_artist(surface)
        style_matplotlib_axes(surface.figure, surface.axes)
        surface.scale_controller.refresh()
        surface.last_applied_signature = None
        surface.status_var.set("Imagery unavailable")
        category = (
            failure.category
            if failure.category in BASEMAP_FAILURE_DIAGNOSTICS
            else "imagery_error"
        )
        self._basemap_diagnostics[surface.surface_id] = (
            category,
            BASEMAP_FAILURE_DIAGNOSTICS[category],
        )
        surface.canvas.draw_idle()

    def _remove_basemap_artist(self, surface: _PreviewMapSurface) -> None:
        for image in list(getattr(surface.axes, "images", ())):
            try:
                image.remove()
            except (AttributeError, ValueError):
                pass
        surface.basemap_image = None
        if surface.attribution_artist is not None:
            try:
                surface.attribution_artist.remove()
            except (AttributeError, ValueError):
                pass
        surface.attribution_artist = None
        self._surface_copyright_text.pop(surface.surface_id, None)
        self._surface_applied_status.pop(surface.surface_id, None)

    def _refresh_attribution_artist(
        self,
        surface: _PreviewMapSurface,
        copyright_text: str | None = None,
    ) -> bool:
        if copyright_text is not None:
            self._surface_copyright_text[surface.surface_id] = copyright_text
        provider_text = self._surface_copyright_text.get(surface.surface_id)
        image_attached = (
            surface.basemap_image is not None
            and any(
                image is surface.basemap_image
                for image in getattr(surface.axes, "images", ())
            )
        )
        if not provider_text or not image_attached:
            if surface.attribution_artist is None:
                return False
            try:
                surface.attribution_artist.remove()
            except (AttributeError, ValueError):
                pass
            surface.attribution_artist = None
            return True

        created = False
        if (
            surface.attribution_artist is None
            or not any(
                artist is surface.attribution_artist
                for artist in getattr(surface.axes, "texts", ())
            )
        ):
            surface.attribution_artist = surface.axes.text(
                0.03,
                0.97,
                "",
                transform=surface.axes.transAxes,
                ha="left",
                va="top",
                fontsize=9,
                linespacing=0.9,
                color="#F8FAFC",
                clip_on=False,
                zorder=1010,
                parse_math=False,
                bbox={
                    "boxstyle": "round,pad=0.35",
                    "facecolor": "#0B1220",
                    "edgecolor": "#CBD5E1",
                    "linewidth": 0.7,
                    "alpha": 0.84,
                },
            )
            surface.attribution_artist.set_gid(
                "jpg-boundary-basemap-attribution"
            )
            created = True

        full_text = f"Powered by Esri | {provider_text}"
        previous_text = surface.attribution_artist.get_text()
        wrapped = self._wrap_attribution_text(
            surface,
            surface.attribution_artist,
            full_text,
        )
        surface.attribution_artist.set_text(previous_text)
        changed = previous_text != wrapped
        if changed:
            surface.attribution_artist.set_text(wrapped)
        return created or changed

    def _wrap_attribution_text(
        self,
        surface: _PreviewMapSurface,
        artist: object,
        text: str,
    ) -> str:
        try:
            axes_width = float(surface.axes.get_window_extent().width)
        except (AttributeError, TypeError, ValueError):
            axes_width = 640.0
        reserved_width = (
            0
            if surface.surface_id.startswith("inspector:")
            else max(PREVIEW_KEY_PANEL_WIDTH, SETTINGS_DRAWER_WIDTH) + 24
        )
        max_width = max(
            90.0,
            axes_width - reserved_width - (axes_width * 0.03) - 18.0,
        )
        try:
            renderer = surface.figure.canvas.get_renderer()
        except (AttributeError, RuntimeError):
            renderer = None

        def fits(candidate: str) -> bool:
            if renderer is None:
                return len(candidate) <= max(8, int(max_width / 5.5))
            try:
                artist.set_text(candidate)
                return artist.get_window_extent(renderer=renderer).width <= max_width
            except (AttributeError, RuntimeError, TypeError, ValueError):
                return len(candidate) <= max(8, int(max_width / 5.5))

        lines: list[str] = []
        current = ""
        for token in text.split(" "):
            candidate = token if not current else f"{current} {token}"
            if fits(candidate):
                current = candidate
                continue
            if current:
                lines.append(current)
                current = ""
            remaining = token
            while remaining:
                if fits(remaining):
                    current = remaining
                    remaining = ""
                    break
                low = 1
                high = len(remaining)
                best = 1
                while low <= high:
                    middle = (low + high) // 2
                    if fits(remaining[:middle]):
                        best = middle
                        low = middle + 1
                    else:
                        high = middle - 1
                lines.append(remaining[:best])
                remaining = remaining[best:]
        if current:
            lines.append(current)
        return "\n".join(lines)

    def _shutdown_basemap(self) -> None:
        if self._closing:
            return
        self._closing = True
        if self._main_map_surface is not None:
            self._reset_preview_map_surface(self._main_map_surface)
        if self._fullscreen_window_exists():
            self._close_fullscreen_preview()
        poll_after_id = self._basemap_poll_after_id
        self._basemap_poll_after_id = None
        if poll_after_id is not None:
            try:
                self.root.after_cancel(poll_after_id)
            except tk.TclError:
                pass
        if self._basemap_client is not None:
            self._basemap_client.shutdown()
            self._basemap_client.clear_cache()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _build_empty_input_overlay(self, parent: ttk.Frame) -> None:
        self.empty_input_overlay = ttk.Frame(
            parent,
            style="Overlay.TFrame",
            padding=(22, 18),
        )
        ttk.Label(
            self.empty_input_overlay,
            text="Choose an input to build a boundary",
            style="Title.TLabel",
        ).grid(row=0, column=0, columnspan=2, pady=(0, 5))
        ttk.Label(
            self.empty_input_overlay,
            text="Drop a JPG folder, KML, or KMZ file below",
            style="Secondary.TLabel",
        ).grid(row=1, column=0, columnspan=2, pady=(0, 12))

        drop_text = (
            "Drop folder, KML, or KMZ here"
            if DND_FILES is not None
            else "Drag-and-drop unavailable — browse below"
        )
        self.drop_label = tk.Label(
            self.empty_input_overlay,
            text=drop_text,
            anchor="center",
            padx=36,
            pady=24,
            cursor="hand2",
            background="#202838",
            foreground="#d8e7ff",
            highlightthickness=2,
            highlightbackground="#3b82f6",
        )
        self.drop_label.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        style_tk_label(
            self.drop_label,
            surface="#202838",
            foreground="#d8e7ff",
        )
        self.browse_folder_button = ttk.Button(
            self.empty_input_overlay,
            text="Browse Folder…",
            style="Secondary.TButton",
            command=self._browse_parent,
        )
        self.browse_folder_button.grid(row=3, column=0, sticky="ew", padx=(0, 5))
        self.browse_vector_button = ttk.Button(
            self.empty_input_overlay,
            text="Browse KML/KMZ…",
            style="Secondary.TButton",
            command=self._browse_kmz,
        )
        self.browse_vector_button.grid(row=3, column=1, sticky="ew", padx=(5, 0))
        self.empty_input_overlay.place(relx=0.5, rely=0.5, anchor="center")
        self._register_drop_target(self.drop_label, feedback_surface=self.drop_label)

    def _build_settings_drawer(self, parent: ttk.Frame) -> None:
        self.settings_drawer = ttk.Frame(
            parent,
            style="Overlay.TFrame",
            padding=(12, 10),
        )
        self.settings_drawer.columnconfigure(0, weight=1)
        self.settings_drawer.rowconfigure(1, weight=1)

        drawer_header = ttk.Frame(self.settings_drawer, style="Overlay.TFrame")
        drawer_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        drawer_header.columnconfigure(0, weight=1)
        ttk.Label(
            drawer_header,
            text="Settings",
            style="Title.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(
            drawer_header,
            text="Close",
            style="Ghost.TButton",
            command=self._close_settings_drawer,
        ).grid(row=0, column=1, sticky="e")

        self.settings_canvas = tk.Canvas(
            self.settings_drawer,
            background="#252b38",
            highlightthickness=0,
            borderwidth=0,
        )
        self.settings_scrollbar = ttk.Scrollbar(
            self.settings_drawer,
            orient="vertical",
            command=self.settings_canvas.yview,
            style="App.Vertical.TScrollbar",
        )
        self.settings_content = ttk.Frame(
            self.settings_canvas,
            style="Overlay.TFrame",
        )
        self._settings_canvas_window = self.settings_canvas.create_window(
            (0, 0),
            window=self.settings_content,
            anchor="nw",
        )
        self.settings_canvas.configure(yscrollcommand=self.settings_scrollbar.set)
        self.settings_canvas.grid(row=1, column=0, sticky="nsew")
        self.settings_scrollbar.grid(row=1, column=1, sticky="ns", padx=(6, 0))
        self.settings_scrollbar.grid_remove()
        self.settings_content.columnconfigure(0, weight=1)
        self.settings_content.bind("<Configure>", self._update_settings_scrollregion)
        self.settings_canvas.bind("<Configure>", self._update_settings_canvas_width)
        self.settings_canvas.bind("<MouseWheel>", self._scroll_settings_drawer)
        self.settings_content.bind("<MouseWheel>", self._scroll_settings_drawer)

        self._create_settings_group(
            self.settings_content,
            "input",
            "Input & Geometry",
            self._build_geometry_settings,
        )
        self._create_settings_group(
            self.settings_content,
            "sections",
            "Sections",
            self._build_section_settings,
        )
        self._create_settings_group(
            self.settings_content,
            "output",
            "Output",
            self._build_output_settings,
        )
        self._bind_local_mousewheel_tree(
            self.settings_drawer,
            self._scroll_settings_drawer,
        )
        self.settings_drawer.place_forget()

    def _create_settings_group(
        self,
        parent: ttk.Frame,
        key: str,
        title: str,
        builder,
    ) -> None:
        row = len(self._settings_group_frames) * 2
        header = ttk.Frame(parent, style="Card.TFrame", padding=(5, 4))
        header.grid(row=row, column=0, sticky="ew", pady=(0, 4))
        header.columnconfigure(1, weight=1)
        button = ttk.Button(
            header,
            text=("▾ " if key == self._active_settings_group else "▸ ") + title,
            style="Ghost.TButton",
            command=lambda group=key: self._toggle_settings_group(group),
        )
        button.grid(row=0, column=0, sticky="w")
        summary = ttk.Label(header, style="Muted.TLabel")
        summary.grid(row=0, column=1, sticky="e", padx=(8, 4))

        content = ttk.Frame(parent, style="Card.TFrame", padding=(10, 8))
        content.grid(row=row + 1, column=0, sticky="ew", pady=(0, 8))
        content.columnconfigure(1, weight=1)
        builder(content)
        if key != self._active_settings_group:
            content.grid_remove()
        self._settings_group_frames[key] = content
        self._settings_group_buttons[key] = button
        setattr(self, f"_{key}_settings_summary", summary)

    def _build_geometry_settings(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Input path", style="Secondary.TLabel").grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 8),
            pady=4,
        )
        self.input_path_entry = ttk.Entry(
            parent,
            textvariable=self.parent_var,
            style="App.TEntry",
        )
        self.input_path_entry.grid(row=0, column=1, sticky="ew", pady=4)
        input_buttons = ttk.Frame(parent, style="Card.TFrame")
        input_buttons.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 8))
        input_buttons.columnconfigure((0, 1), weight=1)
        self.drawer_browse_folder_button = ttk.Button(
            input_buttons,
            text="Browse Folder…",
            style="Secondary.TButton",
            command=self._browse_parent,
        )
        self.drawer_browse_folder_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.drawer_browse_vector_button = ttk.Button(
            input_buttons,
            text="Browse KML/KMZ…",
            style="Secondary.TButton",
            command=self._browse_kmz,
        )
        self.drawer_browse_vector_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        ttk.Label(parent, text="Buffer (feet)", style="Secondary.TLabel").grid(
            row=2,
            column=0,
            sticky="w",
            padx=(0, 8),
            pady=4,
        )
        self.buffer_entry = ttk.Entry(
            parent,
            textvariable=self.buffer_var,
            width=16,
            style="App.TEntry",
        )
        self.buffer_entry.grid(row=2, column=1, sticky="ew", pady=4)

        self.outline_mode_label = ttk.Label(
            parent,
            text="Outline mode",
            style="Secondary.TLabel",
        )
        self.outline_mode_label.grid(row=3, column=0, sticky="w", padx=(0, 8), pady=4)
        self.outline_mode_combo = ttk.Combobox(
            parent,
            textvariable=self.outline_mode_var,
            values=list(OUTLINE_MODE_LABELS.keys()),
            state="readonly",
            style="App.TCombobox",
        )
        self.outline_mode_combo.grid(row=3, column=1, sticky="ew", pady=4)

        self.simplify_vector_label = ttk.Label(
            parent,
            text="Vector output",
            style="Secondary.TLabel",
        )
        self.simplify_vector_label.grid(row=4, column=0, sticky="w", padx=(0, 8), pady=4)
        self.simplify_vector_checkbutton = ttk.Checkbutton(
            parent,
            text="Simplify KML/KMZ output vertices",
            variable=self.simplify_vector_var,
            style="Surface.TCheckbutton",
        )
        self.simplify_vector_checkbutton.grid(row=4, column=1, sticky="w", pady=4)

    def _build_section_settings(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="# of Shapes", style="Secondary.TLabel").grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 8),
            pady=4,
        )
        self.section_count_spinbox = ttk.Spinbox(
            parent,
            from_=1,
            to=MAX_SECTION_COUNT,
            textvariable=self.section_count_var,
            width=8,
            style="App.TSpinbox",
        )
        self.section_count_spinbox.grid(row=0, column=1, sticky="ew", pady=4)

        self.overlap_label = ttk.Label(
            parent,
            text="Overlap (feet)",
            style="Secondary.TLabel",
        )
        self.overlap_label.grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        self.overlap_entry = ttk.Entry(
            parent,
            textvariable=self.overlap_var,
            style="App.TEntry",
        )
        self.overlap_entry.grid(row=1, column=1, sticky="ew", pady=4)

        self.shape_label_label = ttk.Label(
            parent,
            text="Shape Label",
            style="Secondary.TLabel",
        )
        self.shape_label_label.grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        self.shape_label_entry = ttk.Entry(
            parent,
            textvariable=self.shape_label_var,
            style="App.TEntry",
        )
        self.shape_label_entry.grid(row=2, column=1, sticky="ew", pady=4)

        self.split_direction_label = ttk.Label(
            parent,
            text="Split direction",
            style="Secondary.TLabel",
        )
        self.split_direction_label.grid(row=3, column=0, sticky="w", padx=(0, 8), pady=4)
        self.split_direction_combo = ttk.Combobox(
            parent,
            textvariable=self.split_direction_var,
            values=SPLIT_DIRECTION_OPTIONS,
            state="readonly",
            style="App.TCombobox",
        )
        self.split_direction_combo.grid(row=3, column=1, sticky="ew", pady=4)

        self.split_direction_custom_label = ttk.Label(
            parent,
            text="Custom degrees",
            style="Secondary.TLabel",
        )
        self.split_direction_custom_label.grid(
            row=4,
            column=0,
            sticky="w",
            padx=(0, 8),
            pady=4,
        )
        self.split_direction_custom_entry = ttk.Entry(
            parent,
            textvariable=self.split_direction_degrees_var,
            style="App.TEntry",
        )
        self.split_direction_custom_entry.grid(row=4, column=1, sticky="ew", pady=4)

    def _build_output_settings(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Output file name", style="Secondary.TLabel").grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 8),
            pady=4,
        )
        output_name_frame = ttk.Frame(parent, style="Card.TFrame")
        output_name_frame.grid(row=0, column=1, sticky="ew", pady=4)
        output_name_frame.columnconfigure(0, weight=1)
        self.output_name_entry = ttk.Entry(
            output_name_frame,
            textvariable=self.output_name_var,
            style="App.TEntry",
        )
        self.output_name_entry.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            output_name_frame,
            text=".kmz",
            style="Secondary.TLabel",
        ).grid(row=0, column=1, padx=(5, 0))

        ttk.Label(parent, text="Output KMZ", style="Secondary.TLabel").grid(
            row=1,
            column=0,
            sticky="w",
            padx=(0, 8),
            pady=4,
        )
        self.output_path_entry = ttk.Entry(
            parent,
            textvariable=self.output_var,
            style="App.TEntry",
        )
        self.output_path_entry.grid(row=1, column=1, sticky="ew", pady=4)

        output_buttons = ttk.Frame(parent, style="Card.TFrame")
        output_buttons.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        output_buttons.columnconfigure((0, 1), weight=1)
        self.save_as_button = ttk.Button(
            output_buttons,
            text="Save As…",
            style="Secondary.TButton",
            command=self._browse_output,
        )
        self.save_as_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.view_output_button = ttk.Button(
            output_buttons,
            text="View Output Folder",
            style="Ghost.TButton",
            command=self._view_output_folder,
        )
        self.view_output_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))

    def _build_preview_key_overlay(self, parent: ttk.Frame) -> None:
        self.preview_key_overlay = ttk.Frame(
            parent,
            style="Overlay.TFrame",
            padding=(10, 8),
        )
        self.preview_key_overlay.columnconfigure(0, weight=1)
        self.preview_key_overlay.rowconfigure(1, weight=1)
        header = ttk.Frame(self.preview_key_overlay, style="Overlay.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Preview Key", style="Title.TLabel").grid(
            row=0,
            column=0,
            sticky="w",
        )
        ttk.Button(
            header,
            text="Close",
            style="Ghost.TButton",
            command=self._close_preview_key,
        ).grid(row=0, column=1, sticky="e")
        (
            self.preview_key_frame,
            self.preview_key_canvas,
            self.preview_key_content,
        ) = self._create_preview_key_panel(self.preview_key_overlay)
        self.preview_key_frame.grid(row=1, column=0, sticky="nsew")
        if self.preview_key_canvas is not None:
            self.preview_key_canvas.bind("<MouseWheel>", self._scroll_preview_key)
        if self.preview_key_content is not None:
            self.preview_key_content.bind("<MouseWheel>", self._scroll_preview_key)
        self.preview_key_overlay.place_forget()

    def _build_action_bar(self, parent: ttk.Frame) -> None:
        self.action_bar = ttk.Frame(
            parent,
            style="ActionBar.TFrame",
            padding=(10, 8),
        )
        self.action_bar.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.action_bar.columnconfigure(0, weight=1)

        self.action_left_group = ttk.Frame(self.action_bar, style="ActionBar.TFrame")
        self.action_right_group = ttk.Frame(self.action_bar, style="ActionBar.TFrame")

        self.preview_state_label = ttk.Label(
            self.action_left_group,
            textvariable=self.preview_state_var,
            style="Status.TLabel",
        )
        self.preview_state_label.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.status_label = ttk.Label(
            self.action_left_group,
            textvariable=self.status_var,
            style="Muted.TLabel",
            width=28,
        )
        self.status_label.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        self.action_left_group.columnconfigure(1, weight=1)

        ttk.Label(
            self.action_left_group,
            text="Buffer",
            style="Secondary.TLabel",
        ).grid(row=0, column=2, padx=(0, 4))
        self.quick_buffer_entry = ttk.Entry(
            self.action_left_group,
            textvariable=self.buffer_var,
            width=8,
            style="App.TEntry",
        )
        self.quick_buffer_entry.grid(row=0, column=3, padx=(0, 8))
        ttk.Label(
            self.action_left_group,
            text="Shapes",
            style="Secondary.TLabel",
        ).grid(row=0, column=4, padx=(0, 4))
        self.quick_section_count_spinbox = ttk.Spinbox(
            self.action_left_group,
            from_=1,
            to=MAX_SECTION_COUNT,
            textvariable=self.section_count_var,
            width=5,
            style="App.TSpinbox",
        )
        self.quick_section_count_spinbox.grid(row=0, column=5, padx=(0, 8))
        self.quick_overlap_label = ttk.Label(
            self.action_left_group,
            text="Overlap",
            style="Secondary.TLabel",
        )
        self.quick_overlap_label.grid(row=0, column=6, padx=(0, 4))
        self.quick_overlap_entry = ttk.Entry(
            self.action_left_group,
            textvariable=self.overlap_var,
            width=7,
            style="App.TEntry",
        )
        self.quick_overlap_entry.grid(row=0, column=7)

        self.busy_progress = ttk.Progressbar(
            self.action_right_group,
            mode="indeterminate",
            length=70,
            style="Busy.Horizontal.TProgressbar",
        )
        self.busy_progress.grid(row=0, column=0, padx=(0, 8))
        self.busy_progress.grid_remove()
        self.details_button = ttk.Button(
            self.action_right_group,
            text="Details",
            style="Ghost.TButton",
            command=self._show_details,
            state="disabled",
        )
        self.details_button.grid(row=0, column=1, padx=(0, 8))
        self.scan_button = ttk.Button(
            self.action_right_group,
            text="Update Preview",
            style="Primary.TButton",
            command=self._scan_clicked,
        )
        self.scan_button.grid(row=0, column=2, padx=(0, 8))
        self.export_button = ttk.Button(
            self.action_right_group,
            text="Export KMZ",
            style="Success.TButton",
            command=self._export_clicked,
        )
        self.export_button.grid(row=0, column=3)

        self._populate_widget_state_registries()
        self.root.update_idletasks()
        self._refresh_action_bar_layout()

    def _populate_widget_state_registries(self) -> None:
        self._all_mutation_widgets = [
            self.input_path_entry,
            self.buffer_entry,
            self.outline_mode_combo,
            self.simplify_vector_checkbutton,
            self.section_count_spinbox,
            self.overlap_entry,
            self.shape_label_entry,
            self.split_direction_combo,
            self.split_direction_custom_entry,
            self.output_name_entry,
            self.output_path_entry,
            self.quick_buffer_entry,
            self.quick_section_count_spinbox,
            self.quick_overlap_entry,
        ]
        self._busy_action_widgets = [
            self.change_input_button,
            self.browse_folder_button,
            self.browse_vector_button,
            self.drawer_browse_folder_button,
            self.drawer_browse_vector_button,
            self.save_as_button,
            self.view_output_button,
            self.scan_button,
            self.export_button,
        ]
        self._section_multiple_widgets = [
            self.overlap_label,
            self.overlap_entry,
            self.quick_overlap_label,
            self.quick_overlap_entry,
            self.shape_label_label,
            self.shape_label_entry,
            self.split_direction_label,
            self.split_direction_combo,
        ]
        self._custom_direction_widgets = [
            self.split_direction_custom_label,
            self.split_direction_custom_entry,
        ]
        self._folder_only_widgets = [
            self.outline_mode_label,
            self.outline_mode_combo,
        ]
        self._vector_only_widgets = [
            self.simplify_vector_label,
            self.simplify_vector_checkbutton,
        ]

    def _toggle_settings_group(self, group: str) -> None:
        if group not in self._settings_group_frames:
            return
        self._active_settings_group = (
            None if self._active_settings_group == group else group
        )
        for key, frame in self._settings_group_frames.items():
            title = {
                "input": "Input & Geometry",
                "sections": "Sections",
                "output": "Output",
            }[key]
            expanded = key == self._active_settings_group
            self._settings_group_buttons[key].configure(
                text=("▾ " if expanded else "▸ ") + title
            )
            if expanded:
                frame.grid()
            else:
                frame.grid_remove()
        self.settings_canvas.after_idle(
            lambda: self.settings_canvas.configure(
                scrollregion=self.settings_canvas.bbox("all")
            )
        )

    def _toggle_settings_drawer(self) -> None:
        if self._settings_drawer_open:
            self._close_settings_drawer()
            return
        self._close_preview_key()
        self._settings_drawer_open = True
        self._place_settings_drawer()
        self.settings_drawer.lift()

    def _close_settings_drawer(self) -> None:
        self._settings_drawer_open = False
        if hasattr(self, "settings_drawer"):
            self.settings_drawer.place_forget()

    def _open_input_settings(self) -> None:
        self._close_preview_key()
        self._settings_drawer_open = True
        if self._active_settings_group != "input":
            self._toggle_settings_group("input")
        self._place_settings_drawer()
        self.settings_drawer.lift()
        self.input_path_entry.focus_set()
        self.input_path_entry.icursor("end")

    def _place_settings_drawer(self) -> None:
        self.preview_stack.update_idletasks()
        available = max(self.preview_stack.winfo_width() - 24, 300)
        width = min(SETTINGS_DRAWER_WIDTH, available)
        self.settings_drawer.place(
            relx=1.0,
            rely=0.0,
            relheight=1.0,
            width=width,
            anchor="ne",
        )
        self.settings_drawer.after_idle(self._refresh_settings_scrollbar)

    def _toggle_preview_key(self) -> None:
        if self._legend_open:
            self._close_preview_key()
            return
        self._close_settings_drawer()
        self._legend_open = True
        self._place_preview_key()
        self.preview_key_overlay.lift()

    def _close_preview_key(self) -> None:
        self._legend_open = False
        if hasattr(self, "preview_key_overlay"):
            self.preview_key_overlay.place_forget()

    def _place_preview_key(self) -> None:
        self.preview_stack.update_idletasks()
        available = max(self.preview_stack.winfo_width() - 24, 280)
        width = min(PREVIEW_KEY_PANEL_WIDTH + 28, available)
        self.preview_key_overlay.place(
            relx=1.0,
            rely=0.0,
            relheight=1.0,
            width=width,
            anchor="ne",
        )

    def _close_topmost_overlay(self) -> bool:
        if self._settings_drawer_open:
            self._close_settings_drawer()
            return True
        if self._legend_open:
            self._close_preview_key()
            return True
        return False

    def _update_settings_scrollregion(self, _event: object) -> None:
        self.settings_canvas.configure(scrollregion=self.settings_canvas.bbox("all"))
        self._refresh_settings_scrollbar()

    def _update_settings_canvas_width(self, event: object) -> None:
        width = max(int(getattr(event, "width", SETTINGS_DRAWER_WIDTH)), 1)
        self.settings_canvas.itemconfigure(self._settings_canvas_window, width=width)
        self._refresh_settings_scrollbar()

    def _refresh_settings_scrollbar(self) -> None:
        try:
            bounds = self.settings_canvas.bbox("all")
            canvas_height = max(1, self.settings_canvas.winfo_height())
            content_height = 0 if bounds is None else bounds[3] - bounds[1]
            if content_height > canvas_height:
                self.settings_scrollbar.grid()
            else:
                self.settings_scrollbar.grid_remove()
        except tk.TclError:
            return

    def _scroll_settings_drawer(self, event: object) -> str:
        delta = int(getattr(event, "delta", 0))
        if delta:
            self.settings_canvas.yview_scroll(-1 if delta > 0 else 1, "units")
        return "break"

    def _scroll_preview_key(self, event: object) -> str:
        self._scroll_key_canvas(self.preview_key_canvas, event)
        return "break"

    def _scroll_fullscreen_preview_key(self, event: object) -> str:
        self._scroll_key_canvas(self._fullscreen_key_canvas, event)
        return "break"

    @staticmethod
    def _scroll_key_canvas(canvas: tk.Canvas | None, event: object) -> None:
        if canvas is None:
            return
        delta = int(getattr(event, "delta", 0))
        if delta:
            canvas.yview_scroll(-1 if delta > 0 else 1, "units")

    def _preview_key_scroll_handler(self, key_content: ttk.Frame):
        if key_content is self._fullscreen_key_content:
            return self._scroll_fullscreen_preview_key
        return self._scroll_preview_key

    def _bind_local_mousewheel_tree(self, widget: tk.Widget, handler) -> None:
        """Bind wheel scrolling only inside one overlay widget tree."""
        try:
            widget.bind("<MouseWheel>", handler, add="+")
            for child in widget.winfo_children():
                self._bind_local_mousewheel_tree(child, handler)
        except tk.TclError:
            return

    def _refresh_drawer_summaries(self) -> None:
        summaries = {
            "input": (
                f"Buffer {self.buffer_var.get().strip() or '—'} · "
                f"{self.outline_mode_var.get().strip() or 'Auto'}"
            ),
            "sections": (
                f"{self.section_count_var.get().strip() or '—'} shape(s)"
            ),
            "output": self.output_name_var.get().strip() or "Unnamed",
        }
        for key, text in summaries.items():
            label = getattr(self, f"_{key}_settings_summary", None)
            if label is not None:
                label.configure(text=text[:34])

    def _on_root_configure(self, event: object) -> None:
        if getattr(event, "widget", None) is not self.root:
            return
        if self._settings_drawer_open:
            self._place_settings_drawer()
        elif self._legend_open:
            self._place_preview_key()
        width = int(getattr(event, "width", 0)) or None
        self._refresh_header_layout(width)
        self._refresh_action_bar_layout(width)

    def _refresh_header_layout(self, width: int | None = None) -> None:
        if not hasattr(self, "header_frame"):
            return
        self.root.update_idletasks()
        fixed_width = (
            self.app_title_label.winfo_reqwidth()
            + self.change_input_button.winfo_reqwidth()
            + self.key_button.winfo_reqwidth()
            + self.settings_button.winfo_reqwidth()
            + self.focus_button.winfo_reqwidth()
            + self.expand_preview_button.winfo_reqwidth()
            + 130
        )
        self._header_breakpoint = max(HEADER_MIN_BREAKPOINT, fixed_width)
        current_width = width or self.root.winfo_width()
        compact = current_width < self._header_breakpoint
        if compact == self._header_compact:
            return

        self._header_compact = compact
        for widget in (
            self.app_title_label,
            self.compact_input_target,
            self.change_input_button,
            self.key_button,
            self.settings_button,
            self.focus_button,
            self.expand_preview_button,
        ):
            widget.grid_forget()

        show_title = not self._focus_mode and self._focus_title_was_mapped
        if compact:
            if show_title:
                self.app_title_label.grid(
                    row=0,
                    column=0,
                    sticky="w",
                    padx=(0, 10),
                )
            self.compact_input_target.grid(
                row=0,
                column=1,
                columnspan=6,
                sticky="ew",
            )
            self.change_input_button.grid(row=1, column=0, pady=(6, 0))
            self.key_button.grid(row=1, column=1, padx=(6, 0), pady=(6, 0))
            self.settings_button.grid(row=1, column=2, padx=(6, 0), pady=(6, 0))
            self.focus_button.grid(row=1, column=3, padx=(6, 0), pady=(6, 0))
            self.expand_preview_button.grid(
                row=1,
                column=4,
                padx=(6, 0),
                pady=(6, 0),
            )
        else:
            if show_title:
                self.app_title_label.grid(
                    row=0,
                    column=0,
                    sticky="w",
                    padx=(0, 14),
                )
            self.compact_input_target.grid(
                row=0,
                column=1,
                sticky="ew",
                padx=(0, 8),
            )
            self.change_input_button.grid(row=0, column=2, padx=(0, 6))
            self.key_button.grid(row=0, column=3, padx=(0, 6))
            self.settings_button.grid(row=0, column=4, padx=(0, 6))
            self.focus_button.grid(row=0, column=5, padx=(0, 6))
            self.expand_preview_button.grid(row=0, column=6)

    def _refresh_action_bar_layout(self, width: int | None = None) -> None:
        if not hasattr(self, "action_left_group"):
            return
        self.root.update_idletasks()
        self._action_bar_breakpoint = max(
            ACTION_BAR_MIN_BREAKPOINT,
            self.action_left_group.winfo_reqwidth()
            + self.action_right_group.winfo_reqwidth()
            + 32,
        )
        current_width = width or self.root.winfo_width()
        compact = current_width < self._action_bar_breakpoint
        if compact == self._action_bar_compact:
            return
        self._action_bar_compact = compact
        self.action_left_group.grid_forget()
        self.action_right_group.grid_forget()
        if compact:
            self.action_left_group.grid(row=0, column=0, sticky="ew")
            self.action_right_group.grid(row=1, column=0, sticky="e", pady=(8, 0))
        else:
            self.action_left_group.grid(row=0, column=0, sticky="ew")
            self.action_right_group.grid(row=0, column=1, sticky="e", padx=(12, 0))

    def _refresh_input_shell_state(self) -> None:
        text = self.parent_var.get().strip()
        self._has_selected_input = bool(text)
        if text:
            path = self._path_from_text(text)
            display = str(path)
            if len(display) > 78:
                display = f"…{display[-77:]}"
            self.input_summary_var.set(f"Input: {display}")
            if hasattr(self, "empty_input_overlay"):
                self.empty_input_overlay.place_forget()
        else:
            self.input_summary_var.set("No input selected — drop or browse to begin")
            if hasattr(self, "empty_input_overlay"):
                self.empty_input_overlay.place(
                    relx=0.5,
                    rely=0.5,
                    anchor="center",
                )
                self.empty_input_overlay.lift()

    def _register_keyboard_shortcuts(self) -> None:
        self.root.bind("<F5>", self._shortcut_update_preview, add="+")
        self.root.bind("<Control-Return>", self._shortcut_update_preview, add="+")
        self.root.bind("<Control-e>", self._shortcut_export, add="+")
        self.root.bind("<Control-E>", self._shortcut_export, add="+")
        self.root.bind("<Control-comma>", self._shortcut_toggle_settings, add="+")
        self.root.bind("<Control-l>", self._shortcut_focus_input, add="+")
        self.root.bind("<Control-L>", self._shortcut_focus_input, add="+")
        self.root.bind("<Escape>", self._shortcut_escape, add="+")

    def _shortcut_update_preview(self, _event: object = None) -> str:
        if not self._busy:
            self._scan_clicked()
        return "break"

    def _shortcut_export(self, _event: object = None) -> str:
        if not self._busy:
            self._export_clicked()
        return "break"

    def _shortcut_toggle_settings(self, _event: object = None) -> str:
        self._toggle_settings_drawer()
        return "break"

    def _shortcut_focus_input(self, _event: object = None) -> str:
        if not self._busy:
            self._open_input_settings()
        return "break"

    def _shortcut_escape(self, _event: object = None) -> str:
        if self._close_topmost_overlay():
            return "break"
        if self._focus_mode:
            self._exit_focus_mode()
            return "break"
        return "break"

    def _toggle_focus_mode(self) -> None:
        if self._focus_mode:
            self._exit_focus_mode()
        else:
            self._enter_focus_mode()

    def _enter_focus_mode(self) -> None:
        if self._focus_mode:
            return
        self._focus_mode = True
        self._focus_saved_state = str(self.root.state())
        self._focus_saved_geometry = self.root.geometry()
        self._focus_title_was_mapped = bool(self.app_title_label.winfo_manager())
        try:
            self.app_title_label.grid_remove()
        except tk.TclError:
            pass
        self.focus_button.configure(text="Exit Focus")

        work_area = get_window_work_area(self.root)
        zoom_contained = False
        try:
            if self._focus_saved_state != "zoomed":
                self.root.state("zoomed")
            self.root.update_idletasks()
            outer_bounds = get_outer_window_bounds(self.root)
            zoom_contained = (
                outer_bounds is not None
                and outer_bounds.is_within(work_area)
            )
        except tk.TclError:
            zoom_contained = False

        if zoom_contained:
            return

        try:
            self.root.state("normal")
            self.root.update_idletasks()
        except tk.TclError:
            pass
        fit_window_to_work_area(
            self.root,
            work_area,
            max_fraction=0.94,
        )

    def _exit_focus_mode(self) -> None:
        if not self._focus_mode:
            return
        saved_state = self._focus_saved_state
        saved_geometry = self._focus_saved_geometry
        self._focus_mode = False
        try:
            if self._focus_title_was_mapped:
                self.app_title_label.grid()
            else:
                self.app_title_label.grid_remove()
        except tk.TclError:
            pass
        self.focus_button.configure(text="Focus Preview")
        self._header_compact = None
        self._refresh_header_layout()
        try:
            if saved_state == "zoomed":
                self.root.state("zoomed")
            elif saved_state == "withdrawn":
                self.root.state("normal")
                self.root.update_idletasks()
                if saved_geometry:
                    self.root.geometry(saved_geometry)
                    self.root.update_idletasks()
                self.root.withdraw()
            else:
                self.root.state("normal")
                self.root.update_idletasks()
                if saved_geometry:
                    self.root.geometry(saved_geometry)
                    self.root.update_idletasks()
        except tk.TclError:
            pass

    def _preview_control_signature(self) -> tuple[str, ...]:
        effective_shape_label = (
            self.shape_label_var.get().strip()
            if self._current_section_count_for_state() > 1
            else ""
        )
        return (
            self.parent_var.get().strip(),
            self.buffer_var.get().strip(),
            self.outline_mode_var.get().strip(),
            self.section_count_var.get().strip(),
            self.overlap_var.get().strip(),
            effective_shape_label,
            self.split_direction_var.get().strip(),
            self.split_direction_degrees_var.get().strip(),
            "1" if self.simplify_vector_var.get() else "0",
        )

    def _mark_preview_stale(self, reason: str = "") -> None:
        self._preview_error = ""
        if self._last_displayed_result is None:
            self._preview_stale = False
            self._stale_reason = ""
        else:
            self._preview_stale = True
            self._stale_reason = reason
        self._refresh_preview_state_badge()

    def _mark_preview_current(self) -> None:
        self._preview_stale = False
        self._stale_reason = ""
        self._preview_error = ""
        self._last_displayed_signature = self._preview_control_signature()
        self._refresh_preview_state_badge()

    def _refresh_preview_state_badge(self) -> None:
        if not hasattr(self, "preview_state_label"):
            return
        if self._busy:
            self.preview_state_var.set("Working…")
            self.preview_state_label.configure(style="Status.TLabel")
        elif self._preview_error:
            self.preview_state_var.set("Preview error")
            self.preview_state_label.configure(style="Error.Status.TLabel")
        elif self._preview_stale:
            self.preview_state_var.set("Preview out of date")
            self.preview_state_label.configure(style="Stale.Status.TLabel")
        elif self._last_displayed_result is not None:
            self.preview_state_var.set("Preview current")
            self.preview_state_label.configure(style="Success.Status.TLabel")
        else:
            self.preview_state_var.set("No preview")
            self.preview_state_label.configure(style="Status.TLabel")
        if self._fullscreen_window_exists():
            self._set_fullscreen_status(self._preview_status_text())

    def _preview_status_text(self) -> str:
        if self._busy:
            return "Working…"
        if self._preview_error:
            return f"Error: {self._preview_error}"
        if self._preview_stale:
            if self._stale_reason:
                return f"Preview out of date: {self._stale_reason}"
            return "Preview out of date"
        if self._last_displayed_result is not None:
            return "Preview current"
        return "No preview"

    def _clear_preview_for_input_change(self) -> None:
        self._last_displayed_result = None
        self._last_displayed_signature = None
        self._preview_stale = False
        self._stale_reason = ""
        self._preview_error = ""
        if hasattr(self, "axes"):
            self._draw_empty_preview()
        if self._basemap_client is not None:
            self._basemap_client.clear_cache()
        self._refresh_preview_state_badge()

    def _refresh_stale_from_signature(self, reason: str) -> None:
        if (
            self._last_displayed_signature is not None
            and self._preview_control_signature() != self._last_displayed_signature
        ):
            self._mark_preview_stale(reason)
        elif self._last_displayed_result is not None:
            self._preview_stale = False
            self._stale_reason = ""
            self._preview_error = ""
            self._refresh_preview_state_badge()

    def _set_window_fit_warning(self, fit: WindowFitResult) -> None:
        if fit.warning:
            self.status_var.set(fit.warning)

    def _create_preview_key_panel(
        self,
        parent: tk.Widget,
    ) -> tuple[ttk.LabelFrame, tk.Canvas, ttk.Frame]:
        key_frame = ttk.LabelFrame(parent, text="Key")
        key_frame.columnconfigure(0, weight=1)
        key_frame.rowconfigure(0, weight=1)
        key_frame.configure(width=PREVIEW_KEY_PANEL_WIDTH)

        key_canvas = tk.Canvas(
            key_frame,
            width=PREVIEW_KEY_PANEL_WIDTH,
            highlightthickness=0,
            borderwidth=0,
        )
        style_tk_canvas(key_canvas, surface="surface")
        scrollbar = ttk.Scrollbar(
            key_frame,
            orient="vertical",
            command=key_canvas.yview,
        )
        key_content = ttk.Frame(key_canvas)
        key_window = key_canvas.create_window(
            (0, 0),
            window=key_content,
            anchor="nw",
        )
        key_canvas.configure(yscrollcommand=scrollbar.set)
        key_canvas.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(4, 6), pady=6)

        def update_scrollregion(_event: object) -> None:
            key_canvas.configure(scrollregion=key_canvas.bbox("all"))

        def update_content_width(event: object) -> None:
            width = max(int(getattr(event, "width", PREVIEW_KEY_PANEL_WIDTH)), 1)
            key_canvas.itemconfigure(key_window, width=width)

        key_content.bind("<Configure>", update_scrollregion)
        key_canvas.bind("<Configure>", update_content_width)
        self._update_preview_key(key_content, [])
        return key_frame, key_canvas, key_content

    @staticmethod
    def _disable_toolbar_coordinate_message(toolbar: NavigationToolbar2Tk) -> None:
        toolbar.set_message("")
        toolbar.set_message = lambda _message: None

    def _register_preview_interactions(self) -> None:
        self._preview_event_cids = self._register_preview_canvas_interactions(
            self.canvas,
            self.axes,
            self.preview_toolbar,
        )

    def _register_preview_canvas_interactions(
        self,
        canvas: FigureCanvasTkAgg,
        axes: object,
        toolbar: NavigationToolbar2Tk,
    ) -> list[int]:
        return [
            canvas.mpl_connect(
                "scroll_event",
                lambda event: self._handle_preview_scroll(event, axes, canvas),
            ),
            canvas.mpl_connect(
                "button_press_event",
                lambda event: self._handle_preview_button_press(
                    event,
                    axes,
                    canvas,
                    toolbar,
                ),
            ),
            canvas.mpl_connect(
                "motion_notify_event",
                lambda event: self._handle_preview_mouse_move(
                    event,
                    axes,
                    canvas,
                    toolbar,
                ),
            ),
            canvas.mpl_connect(
                "button_release_event",
                self._on_preview_button_release,
            ),
        ]

    def _on_preview_scroll(self, event: object) -> None:
        self._handle_preview_scroll(event, self.axes, self.canvas)

    def _handle_preview_scroll(
        self,
        event: object,
        axes: object,
        canvas: FigureCanvasTkAgg,
    ) -> None:
        if not self._is_preview_axes_event(event, axes):
            return

        direction = self._scroll_direction(event)
        if direction == 0:
            return

        xdata = float(getattr(event, "xdata"))
        ydata = float(getattr(event, "ydata"))
        x_min, x_max = axes.get_xlim()
        y_min, y_max = axes.get_ylim()
        scale = (
            1.0 / PREVIEW_SCROLL_ZOOM_FACTOR
            if direction > 0
            else PREVIEW_SCROLL_ZOOM_FACTOR
        )
        new_width = (x_max - x_min) * scale
        new_height = (y_max - y_min) * scale
        x_fraction = (xdata - x_min) / (x_max - x_min) if x_max != x_min else 0.5
        y_fraction = (ydata - y_min) / (y_max - y_min) if y_max != y_min else 0.5

        axes.set_xlim(
            xdata - new_width * x_fraction,
            xdata + new_width * (1.0 - x_fraction),
            auto=True,
        )
        axes.set_ylim(
            ydata - new_height * y_fraction,
            ydata + new_height * (1.0 - y_fraction),
            auto=True,
        )
        canvas.draw_idle()

    def _on_preview_button_press(self, event: object) -> None:
        self._handle_preview_button_press(
            event,
            self.axes,
            self.canvas,
            self.preview_toolbar,
        )

    def _handle_preview_button_press(
        self,
        event: object,
        axes: object,
        canvas: FigureCanvasTkAgg,
        toolbar: NavigationToolbar2Tk,
    ) -> None:
        if self._preview_toolbar_has_active_mode(toolbar):
            self._preview_pan_start = None
            return
        if not self._is_preview_axes_event(event, axes):
            self._preview_pan_start = None
            return
        if not self._is_left_mouse_event(event):
            return

        event_pixels = self._event_pixels(event, axes)
        if event_pixels is None:
            self._preview_pan_start = None
            return

        axes_bbox = axes.bbox
        axes_width = max(float(axes_bbox.width), 1.0)
        axes_height = max(float(axes_bbox.height), 1.0)
        self._preview_pan_start = (
            axes,
            canvas,
            event_pixels[0],
            event_pixels[1],
            tuple(float(value) for value in axes.get_xlim()),
            tuple(float(value) for value in axes.get_ylim()),
            axes_width,
            axes_height,
        )

    def _on_preview_mouse_move(self, event: object) -> None:
        self._handle_preview_mouse_move(
            event,
            self.axes,
            self.canvas,
            self.preview_toolbar,
        )

    def _handle_preview_mouse_move(
        self,
        event: object,
        axes: object,
        canvas: FigureCanvasTkAgg,
        toolbar: NavigationToolbar2Tk,
    ) -> None:
        if self._preview_pan_start is None:
            return
        if self._preview_toolbar_has_active_mode(toolbar):
            self._preview_pan_start = None
            return

        (
            start_axes,
            start_canvas,
            start_x,
            start_y,
            start_xlim,
            start_ylim,
            axes_width,
            axes_height,
        ) = self._preview_pan_start
        if start_axes is not axes or start_canvas is not canvas:
            return

        event_pixels = self._event_pixels(event, axes)
        if event_pixels is None:
            return

        x_range = start_xlim[1] - start_xlim[0]
        y_range = start_ylim[1] - start_ylim[0]
        dx = (start_x - event_pixels[0]) * x_range / axes_width
        dy = (start_y - event_pixels[1]) * y_range / axes_height
        axes.set_xlim(start_xlim[0] + dx, start_xlim[1] + dx, auto=True)
        axes.set_ylim(start_ylim[0] + dy, start_ylim[1] + dy, auto=True)
        canvas.draw_idle()

    def _on_preview_button_release(self, _event: object) -> None:
        self._preview_pan_start = None

    def _is_preview_axes_event(self, event: object, axes: object | None = None) -> bool:
        target_axes = self.axes if axes is None else axes
        return (
            getattr(event, "inaxes", None) is target_axes
            and getattr(event, "xdata", None) is not None
            and getattr(event, "ydata", None) is not None
        )

    def _preview_toolbar_has_active_mode(
        self,
        toolbar: NavigationToolbar2Tk | None = None,
    ) -> bool:
        return bool(getattr(toolbar or self.preview_toolbar, "mode", None))

    @staticmethod
    def _event_pixels(event: object, axes: object) -> tuple[float, float] | None:
        x = getattr(event, "x", None)
        y = getattr(event, "y", None)
        if x is not None and y is not None:
            return float(x), float(y)

        xdata = getattr(event, "xdata", None)
        ydata = getattr(event, "ydata", None)
        if xdata is None or ydata is None:
            return None
        pixel_x, pixel_y = axes.transData.transform((float(xdata), float(ydata)))
        return float(pixel_x), float(pixel_y)

    @staticmethod
    def _is_left_mouse_event(event: object) -> bool:
        button = getattr(event, "button", None)
        return button in {MouseButton.LEFT, 1}

    @staticmethod
    def _scroll_direction(event: object) -> int:
        step = getattr(event, "step", None)
        if step:
            return 1 if step > 0 else -1
        button = getattr(event, "button", None)
        if button == "up":
            return 1
        if button == "down":
            return -1
        return 0

    def _register_drop_target(
        self,
        target: tk.Widget,
        *,
        feedback_surface: tk.Widget | None = None,
    ) -> None:
        if target not in self._drop_targets:
            self._drop_targets.append(target)
        surface = feedback_surface or target
        self._drop_feedback_surfaces[str(target)] = surface
        if DND_FILES is None:
            return

        try:
            target.drop_target_register(DND_FILES)
            target.dnd_bind("<<Drop>>", self._handle_folder_drop)
            target.dnd_bind("<<DragEnter>>", self._handle_drag_enter)
            target.dnd_bind("<<DragLeave>>", self._handle_drag_leave)
        except (AttributeError, tk.TclError):
            if target is getattr(self, "drop_label", None):
                self.drop_label.configure(
                    text="Drag-and-drop failed to initialize; use Browse buttons…",
                )
            self._set_drop_surface_active(surface, active=False, warning=True)

    def _drop_surface_for_event(self, event: object) -> tk.Widget:
        widget = getattr(event, "widget", None)
        return self._drop_feedback_surfaces.get(
            str(widget),
            getattr(self, "drop_label", self.compact_input_target),
        )

    @staticmethod
    def _set_drop_surface_active(
        surface: tk.Widget,
        *,
        active: bool,
        warning: bool = False,
    ) -> None:
        background = (
            "#3a2f16"
            if warning
            else "#1e3a5f"
            if active
            else "#202838"
        )
        border = "#f59e0b" if warning else "#60a5fa" if active else "#3b4a63"
        try:
            surface.configure(
                background=background,
                highlightbackground=border,
            )
        except tk.TclError:
            return

    def _handle_drag_enter(self, event: object) -> None:
        self._set_drop_surface_active(
            self._drop_surface_for_event(event),
            active=True,
        )

    def _handle_drag_leave(self, event: object) -> None:
        self._set_drop_surface_active(
            self._drop_surface_for_event(event),
            active=False,
        )

    def _handle_folder_drop(self, event: object) -> None:
        self._set_drop_surface_active(
            self._drop_surface_for_event(event),
            active=False,
        )
        if self._busy:
            self.status_var.set("Please wait for the current operation to finish.")
            return
        paths = self._parse_dropped_paths(getattr(event, "data", ""))
        inputs = [
            path
            for path in paths
            if path.is_dir() or self._is_vector_file_path(path)
        ]
        if not inputs:
            messagebox.showerror(
                "Invalid drop",
                "Drop a folder that contains JPGs, a KML file, or a KMZ file.",
                parent=self.root,
            )
            return

        input_path = inputs[0]
        self._set_input_path(input_path)
        if len(inputs) > 1:
            self.status_var.set(f"Using first dropped input: {input_path}")
        else:
            self.status_var.set(f"Input set: {input_path}")

    def _browse_parent(self) -> None:
        folder = filedialog.askdirectory(
            title="Choose parent folder containing JPGs",
            parent=self.root,
        )
        if not folder:
            return
        self._set_input_path(Path(folder))

    def _browse_kmz(self) -> None:
        initial = self.parent_var.get().strip()
        if initial:
            initial_path = self._path_from_text(initial)
            initial_dir = str(
                initial_path.parent if initial_path.is_file() else initial_path
            )
        else:
            initial_dir = str(Path.cwd())
        kmz_path = filedialog.askopenfilename(
            title="Choose KML or KMZ vector input",
            filetypes=[
                ("KML/KMZ files", "*.kml *.kmz"),
                ("KML files", "*.kml"),
                ("KMZ files", "*.kmz"),
                ("All files", "*.*"),
            ],
            initialdir=initial_dir,
            parent=self.root,
        )
        if not kmz_path:
            return
        self._set_input_path(Path(kmz_path))

    def _browse_output(self) -> None:
        initial = self.output_var.get().strip()
        DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        initial_path = self._resolve_output_path(initial) if initial else None
        initial_dir = str(initial_path.parent if initial_path else DEFAULT_OUTPUT_DIR)
        initial_file = initial_path.name if initial_path else "jpg_camera_boundary.kmz"
        output = filedialog.asksaveasfilename(
            title="Save KMZ boundary",
            defaultextension=".kmz",
            filetypes=[("KMZ files", "*.kmz"), ("All files", "*.*")],
            initialdir=initial_dir,
            initialfile=initial_file,
            parent=self.root,
        )
        if output:
            self._set_output_path(Path(output))

    def _view_output_folder(self) -> None:
        try:
            folder = self._current_output_folder()
            self._open_output_folder(folder)
            self.status_var.set(f"Opened output folder: {folder}")
        except Exception as error:
            messagebox.showerror(
                "Open output folder failed",
                str(error),
                parent=self.root,
            )

    def _current_output_folder(self) -> Path:
        output_text = self.output_var.get().strip()
        if not output_text:
            parent_text = self.parent_var.get().strip()
            parent_folder = self._path_from_text(parent_text) if parent_text else None
            output_path = self._default_output_path(parent_folder)
            self._set_output_path(output_path)
            return output_path.parent

        output_path = self._resolve_output_path(output_text)
        if output_path.exists() and output_path.is_dir():
            return output_path
        return output_path.parent

    def _open_output_folder(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self._open_folder(folder)

    def _open_folder(self, folder: Path) -> None:
        folder = folder.resolve()
        if sys.platform.startswith("win"):
            os.startfile(str(folder))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])

    def _set_output_path(self, output_path: Path, *, sync_name: bool = True) -> None:
        output_path = Path(output_path)
        self._updating_output_fields = True
        try:
            self.output_var.set(str(output_path))
            if sync_name:
                self.output_name_var.set(output_path.stem)
        finally:
            self._updating_output_fields = False
        self._refresh_shape_label_default()
        self._invalidate_cache()
        self._refresh_stale_from_signature("Output-derived label changed.")
        self._refresh_drawer_summaries()

    def _sync_output_name_from_path(self) -> None:
        output_text = self.output_var.get().strip()
        if not output_text:
            return

        self._updating_output_fields = True
        try:
            self.output_name_var.set(self._resolve_output_path(output_text).stem)
        finally:
            self._updating_output_fields = False

    def _on_output_changed(self, *_args: object) -> None:
        if self._updating_output_fields:
            return
        self._sync_output_name_from_path()
        self._refresh_shape_label_default()
        self._invalidate_cache()
        self._refresh_stale_from_signature("Output-derived label changed.")
        self._refresh_drawer_summaries()

    def _on_output_name_changed(self, *_args: object) -> None:
        if self._updating_output_fields:
            return

        output_name = self.output_name_var.get().strip()
        if not output_name:
            self._invalidate_cache()
            self._refresh_stale_from_signature("Output-derived label changed.")
            self._refresh_drawer_summaries()
            return

        output_text = self.output_var.get().strip()
        if output_text:
            output_folder = self._resolve_output_path(output_text).parent
        else:
            output_folder = DEFAULT_OUTPUT_DIR
        self._set_output_path(
            output_folder / self._filename_from_output_name(output_name),
            sync_name=False,
        )

    def _on_input_changed(self, *_args: object) -> None:
        self._update_outline_mode_state()
        self._invalidate_cache()
        current_text = self.parent_var.get().strip()
        if current_text != self._last_input_text:
            self._last_input_text = current_text
            self._clear_preview_for_input_change()
        self._refresh_input_shell_state()
        self._refresh_drawer_summaries()

    def _on_buffer_changed(self, *_args: object) -> None:
        self._invalidate_cache()
        self._mark_preview_stale("Buffer changed.")
        self._refresh_drawer_summaries()

    def _on_outline_mode_changed(self, *_args: object) -> None:
        self._invalidate_cache()
        self._mark_preview_stale("Outline mode changed.")
        self._refresh_drawer_summaries()

    def _on_section_options_changed(self, *_args: object) -> None:
        self._update_section_control_state()
        self._refresh_shape_label_default()
        self._invalidate_cache()
        self._mark_preview_stale("Section settings changed.")
        self._refresh_drawer_summaries()

    def _on_shape_label_changed(self, *_args: object) -> None:
        if self._updating_shape_label:
            return
        self._shape_label_touched = True
        self._invalidate_cache()
        self._mark_preview_stale("Shape label changed.")
        self._refresh_drawer_summaries()

    def _on_split_direction_changed(self, *_args: object) -> None:
        self._update_section_control_state()
        self._invalidate_cache()
        self._mark_preview_stale("Split direction changed.")
        self._refresh_drawer_summaries()

    def _on_vector_simplification_changed(self, *_args: object) -> None:
        self._invalidate_cache()
        self._mark_preview_stale("Vector simplification changed.")
        self._refresh_drawer_summaries()

    def _update_section_control_state(self) -> None:
        multiple_sections = self._current_section_count_for_state() > 1
        enabled = multiple_sections and not self._busy
        state = "normal" if enabled else "disabled"
        widgets = self._section_multiple_widgets or [
            self.overlap_label,
            self.overlap_entry,
            self.shape_label_label,
            self.shape_label_entry,
            self.split_direction_label,
            self.split_direction_combo,
        ]
        for widget in widgets:
            if isinstance(widget, ttk.Combobox):
                widget.configure(state="readonly" if enabled else "disabled")
            else:
                widget.configure(state=state)
        custom_enabled = enabled and self.split_direction_var.get() == "Custom"
        custom_state = "normal" if custom_enabled else "disabled"
        custom_widgets = self._custom_direction_widgets or [
            self.split_direction_custom_label,
            self.split_direction_custom_entry,
        ]
        for widget in custom_widgets:
            widget.configure(state=custom_state)
        if hasattr(self, "quick_overlap_label"):
            if multiple_sections:
                self.quick_overlap_label.grid()
                self.quick_overlap_entry.grid()
            else:
                self.quick_overlap_label.grid_remove()
                self.quick_overlap_entry.grid_remove()
            self._refresh_action_bar_layout()

    def _update_outline_mode_state(self) -> None:
        input_text = self.parent_var.get().strip()
        is_vector_file = False
        if input_text:
            input_path = self._path_from_text(input_text)
            is_vector_file = self._is_vector_file_path(input_path)
        outline_enabled = not is_vector_file and not self._busy
        for widget in self._folder_only_widgets or [
            self.outline_mode_label,
            self.outline_mode_combo,
        ]:
            if isinstance(widget, ttk.Combobox):
                widget.configure(state="readonly" if outline_enabled else "disabled")
            else:
                widget.configure(state="normal" if outline_enabled else "disabled")
        simplify_state = "normal" if is_vector_file and not self._busy else "disabled"
        for widget in self._vector_only_widgets or [
            self.simplify_vector_label,
            self.simplify_vector_checkbutton,
        ]:
            widget.configure(state=simplify_state)

    def _current_section_count_for_state(self) -> int:
        try:
            return int(self.section_count_var.get().strip())
        except ValueError:
            return 1

    def _refresh_shape_label_default(self, force: bool = False) -> None:
        if not force and self._shape_label_touched and self.shape_label_var.get().strip():
            return
        self._updating_shape_label = True
        try:
            self.shape_label_var.set(self._default_shape_label())
        finally:
            self._updating_shape_label = False
        if force:
            self._shape_label_touched = False

    def _scan_clicked(self) -> None:
        try:
            (
                input_path,
                buffer_ft,
                section_count,
                overlap_ft,
                shape_label,
                outline_mode,
                split_direction_deg,
                simplify_vector_output,
                _,
            ) = (
                self._read_inputs(require_output=False)
            )
        except BoundaryError as error:
            messagebox.showerror("Invalid input", str(error), parent=self.root)
            return

        self._start_preview_generation(
            input_path,
            buffer_ft,
            section_count,
            overlap_ft,
            shape_label,
            outline_mode,
            split_direction_deg,
            simplify_vector_output,
        )

    def _start_preview_generation(
        self,
        input_path: Path,
        buffer_ft: float,
        section_count: int,
        overlap_ft: float,
        shape_label: str,
        outline_mode: str,
        split_direction_deg: float | None,
        simplify_vector_output: bool,
    ) -> None:
        self._set_busy(True, "Reading input and building preview...")
        worker = threading.Thread(
            target=self._scan_worker,
            args=(
                input_path,
                buffer_ft,
                section_count,
                overlap_ft,
                shape_label,
                outline_mode,
                split_direction_deg,
                simplify_vector_output,
            ),
            daemon=True,
        )
        worker.start()

    def _export_clicked(self) -> None:
        try:
            (
                input_path,
                buffer_ft,
                section_count,
                overlap_ft,
                shape_label,
                outline_mode,
                split_direction_deg,
                simplify_vector_output,
                output_path,
            ) = self._read_inputs(require_output=True)
        except BoundaryError as error:
            messagebox.showerror("Invalid input", str(error), parent=self.root)
            return

        if output_path.exists():
            overwrite = messagebox.askyesno(
                "Overwrite KMZ?",
                f"The output file already exists:\n\n{output_path}\n\nOverwrite it?",
                parent=self.root,
            )
            if not overwrite:
                return

        settings = self._settings_key(
            input_path,
            buffer_ft,
            section_count,
            overlap_ft,
            shape_label,
            outline_mode,
            split_direction_deg,
            GENERATION_PROFILE_EXPORT,
            simplify_vector_output=simplify_vector_output,
        )
        cached_result = (
            self._cached_result if self._cached_settings == settings else None
        )

        self._set_busy(True, "Exporting KMZ...")
        worker = threading.Thread(
            target=self._export_worker,
            args=(
                input_path,
                buffer_ft,
                section_count,
                overlap_ft,
                shape_label,
                outline_mode,
                split_direction_deg,
                simplify_vector_output,
                output_path,
                cached_result,
            ),
            daemon=True,
        )
        worker.start()

    def _scan_worker(
        self,
        input_path: Path,
        buffer_ft: float,
        section_count: int,
        overlap_ft: float,
        shape_label: str,
        outline_mode: str,
        split_direction_deg: float | None,
        simplify_vector_output: bool,
    ) -> None:
        try:
            result = generate_boundary_from_input(
                input_path,
                buffer_ft,
                section_count=section_count,
                overlap_ft=overlap_ft,
                shape_label=shape_label,
                outline_mode=outline_mode,
                split_direction_deg=split_direction_deg,
                generation_profile=GENERATION_PROFILE_PREVIEW,
                simplify_vector_output=simplify_vector_output,
            )
        except Exception as error:
            self._queue.put(("error", error))
            return
        self._queue.put(("scan_done", result))

    def _export_worker(
        self,
        input_path: Path,
        buffer_ft: float,
        section_count: int,
        overlap_ft: float,
        shape_label: str,
        outline_mode: str,
        split_direction_deg: float | None,
        simplify_vector_output: bool,
        output_path: Path,
        cached_result: BoundaryResult | None,
    ) -> None:
        try:
            result = cached_result or generate_boundary_from_input(
                input_path,
                buffer_ft,
                section_count=section_count,
                overlap_ft=overlap_ft,
                shape_label=shape_label,
                outline_mode=outline_mode,
                split_direction_deg=split_direction_deg,
                generation_profile=GENERATION_PROFILE_EXPORT,
                simplify_vector_output=simplify_vector_output,
            )
            saved_path = save_kmz(result, output_path)
        except Exception as error:
            self._queue.put(("error", error))
            return
        self._queue.put(("export_done", (result, saved_path)))

    def _drain_queue(self) -> None:
        while True:
            try:
                kind, payload = self._queue.get_nowait()
            except queue.Empty:
                break

            if kind == "scan_done":
                result = payload
                assert isinstance(result, BoundaryResult)
                self._sync_effective_buffer(result)
                self._cached_result = result
                self._cached_settings = self._settings_key(
                    result.metadata.source_folder,
                    result.metadata.buffer_ft,
                    result.metadata.section_count,
                    result.metadata.overlap_ft,
                    result.metadata.shape_label,
                    result.metadata.outline_mode,
                    result.metadata.requested_split_direction_deg,
                    result.metadata.generation_profile,
                    simplify_vector_output=result.metadata.vector_simplification_enabled,
                )
                self._write_status(format_summary(result.metadata))
                self._draw_preview(result)
                self._last_displayed_result = result
                self._mark_preview_current()
                self._set_busy(False, self._ready_status(result, "Preview ready."))
                self._set_fullscreen_status(
                    self._ready_status(result, "Preview ready.")
                )
            elif kind == "export_done":
                result, saved_path = payload
                assert isinstance(result, BoundaryResult)
                saved_path = Path(saved_path)
                self._sync_effective_buffer(result)
                self._cached_result = result
                self._cached_settings = self._settings_key(
                    result.metadata.source_folder,
                    result.metadata.buffer_ft,
                    result.metadata.section_count,
                    result.metadata.overlap_ft,
                    result.metadata.shape_label,
                    result.metadata.outline_mode,
                    result.metadata.requested_split_direction_deg,
                    result.metadata.generation_profile,
                    simplify_vector_output=result.metadata.vector_simplification_enabled,
                )
                self._write_status(
                    format_summary(result.metadata)
                    + f"\n\nSaved KMZ: {saved_path}"
                )
                self._draw_preview(result)
                self._last_displayed_result = result
                self._mark_preview_current()
                self._set_busy(False, self._ready_status(result, "KMZ exported."))
                self._set_fullscreen_status(
                    self._ready_status(result, "KMZ exported.")
                )
                self._show_export_success(saved_path)
            elif kind == "error":
                error = payload
                self._write_status(str(error))
                self._mark_preview_stale("Preview generation failed.")
                self._preview_error = str(error)
                error_status = f"Error: {error}"
                self._set_busy(False, error_status)
                self._set_fullscreen_status(error_status)
                messagebox.showerror(
                    "Boundary generation failed",
                    str(error),
                    parent=self.root,
                )

        self.root.after(100, self._drain_queue)

    def _show_export_success(self, saved_path: Path) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.withdraw()
        dialog.title("KMZ exported")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.columnconfigure(0, weight=1)
        style_app_toplevel(dialog)

        content = ttk.Frame(dialog, padding=(20, 16, 20, 12))
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)

        ttk.Label(content, text="Saved:").grid(row=0, column=0, sticky="w")
        ttk.Label(
            content,
            text=str(saved_path),
            justify="left",
            wraplength=460,
        ).grid(row=1, column=0, sticky="ew", pady=(8, 16))

        buttons = ttk.Frame(content)
        buttons.grid(row=2, column=0, sticky="e")

        def view_saved_folder() -> None:
            try:
                self._open_output_folder(saved_path.parent)
                self.status_var.set(f"Opened output folder: {saved_path.parent}")
            except Exception as error:
                messagebox.showerror(
                    "Open output folder failed",
                    str(error),
                    parent=dialog,
                )

        ttk.Button(
            buttons,
            text="View Output Folder",
            command=view_saved_folder,
        ).grid(row=0, column=0, padx=(0, 8))
        ok_button = ttk.Button(buttons, text="OK", command=dialog.destroy)
        ok_button.grid(row=0, column=1)

        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.bind("<Return>", lambda _event: dialog.destroy())
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        self._center_child_window(dialog)
        apply_native_chrome(dialog)
        dialog.deiconify()
        dialog.grab_set()
        ok_button.focus_set()

    def _center_child_window(self, window: tk.Toplevel) -> None:
        clamp_child_geometry(self.root, window)

    def _read_inputs(
        self,
        require_output: bool,
        *,
        section_count_text: str | None = None,
        overlap_text: str | None = None,
        shape_label_text: str | None = None,
        split_direction_label: str | None = None,
        split_direction_degrees_text: str | None = None,
    ) -> tuple[Path, float, int, float, str, str, float | None, bool, Path | None]:
        input_text = self.parent_var.get().strip()
        if not input_text:
            raise BoundaryError("Choose a JPG folder, KML file, or KMZ file.")

        input_path = self._path_from_text(input_text)
        if not input_path.exists():
            raise BoundaryError(f"Input path does not exist: {input_path}")
        if not (
            input_path.is_dir()
            or self._is_vector_file_path(input_path)
        ):
            raise BoundaryError("Input must be a folder of JPGs, KML file, or KMZ file.")

        buffer_text = self.buffer_var.get().strip()
        try:
            buffer_ft = float(buffer_text)
        except ValueError as exc:
            raise BoundaryError("Buffer must be a number in feet.") from exc
        if buffer_ft < 0:
            raise BoundaryError("Buffer must be 0 or greater.")

        section_text = (
            self.section_count_var.get()
            if section_count_text is None
            else section_count_text
        ).strip()
        try:
            section_count = int(section_text)
        except ValueError as exc:
            raise BoundaryError("# of Shapes must be a whole number.") from exc
        if section_count < 1 or section_count > MAX_SECTION_COUNT:
            raise BoundaryError(f"# of Shapes must be between 1 and {MAX_SECTION_COUNT}.")

        overlap_ft = 0.0
        if section_count > 1:
            overlap_value_text = (
                self.overlap_var.get()
                if overlap_text is None
                else overlap_text
            ).strip()
            try:
                overlap_ft = float(overlap_value_text)
            except ValueError as exc:
                raise BoundaryError("Overlap must be a number in feet.") from exc
            if overlap_ft < 0:
                raise BoundaryError("Overlap must be 0 or greater.")

        output_path: Path | None = None
        output_text = self.output_var.get().strip()
        if not output_text:
            current_output_path = self._default_output_path(input_path)
            self._set_output_path(current_output_path)
        else:
            current_output_path = self._resolve_output_path(output_text)

        output_name = self.output_name_var.get().strip()
        if output_name:
            current_output_path = (
                current_output_path.parent
                / self._filename_from_output_name(output_name)
            )
            if str(current_output_path) != self.output_var.get().strip():
                self._set_output_path(current_output_path, sync_name=False)

        shape_label = ""
        if section_count > 1:
            shape_label = (
                self.shape_label_var.get()
                if shape_label_text is None
                else shape_label_text
            ).strip()
            if not shape_label:
                shape_label = current_output_path.stem
                if shape_label_text is None:
                    self._refresh_shape_label_default(force=True)
        split_direction_deg = self._selected_split_direction(
            section_count,
            split_direction_label=split_direction_label,
            split_direction_degrees_text=split_direction_degrees_text,
        )

        if require_output:
            output_path = current_output_path

        outline_mode = self._selected_outline_mode(input_path)
        simplify_vector_output = (
            self.simplify_vector_var.get()
            if self._is_vector_file_path(input_path)
            else False
        )
        return (
            input_path,
            buffer_ft,
            section_count,
            overlap_ft,
            shape_label,
            outline_mode,
            split_direction_deg,
            bool(simplify_vector_output),
            output_path,
        )

    def _draw_preview(self, result: BoundaryResult) -> None:
        if result is not self._map_result_reference:
            self._accepted_result_generation += 1
            self._active_result_generation = self._accepted_result_generation
            self._map_result_reference = result
        if self._main_map_surface is None:
            return
        self._draw_preview_on_axes(
            result,
            self.axes,
            self.figure,
            self.canvas,
            self.preview_key_content,
            self._main_map_surface,
        )
        self._draw_fullscreen_preview(result)

    def _draw_preview_on_axes(
        self,
        result: BoundaryResult,
        axes: object,
        figure: Figure,
        canvas: FigureCanvasTkAgg | None,
        key_content: ttk.Frame | None,
        surface: _PreviewMapSurface,
    ) -> None:
        self._reset_preview_map_surface(surface)
        axes.clear()
        style_matplotlib_axes(figure, axes)
        key_entries: list[tuple[str, str, str, float]] = []
        if result.metadata.input_type == "JPG folder":
            point_artist = axes.scatter(
                result.projected_points[:, 0],
                result.projected_points[:, 1],
                s=4,
                color="#1f77b4",
                linewidths=0,
                label="JPG GPS points",
                zorder=25,
            )
            point_artist.set_path_effects(
                [
                    patheffects.Stroke(
                        linewidth=2.0,
                        foreground=PALETTE.BACKGROUND_DEEP,
                    ),
                    patheffects.Normal(),
                ]
            )
            key_entries.append(("JPG GPS points", "#1f77b4", "point", 1.0))
        else:
            bx, by = self._preview_polygon_xy(result.base_polygon_projected)
            source_label = (
                "Buffered source LineStrings"
                if "polyline" in result.metadata.input_type.lower()
                else "Source polygon"
            )
            source_line = axes.plot(
                bx,
                by,
                color="#1f77b4",
                linewidth=1.4,
                linestyle=":",
                label=source_label,
                zorder=20,
            )[0]
            self._style_preview_vector_artist(source_line, 1.4)
            key_entries.append((source_label, "#1f77b4", ":", 1.4))

        if result.sections:
            x, y = self._preview_polygon_xy(result.final_polygon_projected)
            parent_line = axes.plot(
                x,
                y,
                color="#9ca3af",
                linewidth=1.4,
                linestyle="--",
                label="Parent outline",
                zorder=20,
            )[0]
            self._style_preview_vector_artist(parent_line, 1.4)
            key_entries.append(("Parent outline", "#9ca3af", "--", 1.4))
            section_colors = [
                "#d62728",
                "#2ca02c",
                "#1f77b4",
                "#9467bd",
                "#ff7f0e",
                "#17becf",
                "#8c564b",
                "#e377c2",
                "#7f7f7f",
                "#bcbd22",
            ]
            for section in result.sections:
                color = section_colors[(section.index - 1) % len(section_colors)]
                sx, sy = self._preview_polygon_xy(section.polygon_projected)
                section_line = axes.plot(
                    sx,
                    sy,
                    color=color,
                    linewidth=1.8,
                    label=section.display_name,
                    zorder=22,
                )[0]
                self._style_preview_vector_artist(section_line, 1.8)
                axes.fill(sx, sy, color=color, alpha=0.08, zorder=10)
                key_entries.append((section.display_name, color, "-", 1.8))
        else:
            x, y = self._preview_polygon_xy(result.final_polygon_projected)
            boundary_line = axes.plot(
                x,
                y,
                color="#d62728",
                linewidth=2.0,
                label="KMZ boundary",
                zorder=22,
            )[0]
            self._style_preview_vector_artist(boundary_line, 2.0)
            axes.fill(x, y, color="#d62728", alpha=0.08, zorder=10)
            key_entries.append(("KMZ boundary", "#d62728", "-", 2.0))

        self._fit_preview_axes_to_result(result, axes)
        axes.set_aspect("equal", adjustable="datalim")
        axes.set_axis_off()
        axes.format_coord = lambda _x, _y: ""
        figure.subplots_adjust(left=0.0, right=1.0, bottom=0.0, top=1.0)
        result_generation = self._active_result_generation
        epsg = (
            int(result.metadata.epsg)
            if result_generation is not None
            else None
        )
        self._bind_preview_map_surface(
            surface,
            result_generation,
            epsg,
        )
        self._update_preview_key(key_content, key_entries)
        if canvas is not None:
            canvas.draw_idle()
        self._schedule_basemap_refresh(surface)

    @staticmethod
    def _style_preview_vector_artist(artist: object, linewidth: float) -> None:
        artist.set_path_effects(
            [
                patheffects.Stroke(
                    linewidth=linewidth + 2.2,
                    foreground=PALETTE.BACKGROUND_DEEP,
                    alpha=0.9,
                ),
                patheffects.Normal(),
            ]
        )

    def _update_preview_key(
        self,
        key_content: ttk.Frame | None,
        entries: list[tuple[str, str, str, float]],
    ) -> None:
        if key_content is None:
            return
        scroll_handler = self._preview_key_scroll_handler(key_content)
        for child in key_content.winfo_children():
            child.destroy()

        if not entries:
            empty_label = ttk.Label(
                key_content,
                text="Key appears after preview.",
                foreground=PALETTE.TEXT_MUTED,
                wraplength=PREVIEW_KEY_WRAP_LENGTH,
            )
            empty_label.grid(
                row=0,
                column=0,
                columnspan=2,
                sticky="w",
                padx=6,
                pady=6,
            )
            empty_label.bind("<MouseWheel>", scroll_handler, add="+")
            return

        for row, (label, color, line_style, line_width) in enumerate(entries):
            swatch = tk.Canvas(
                key_content,
                width=42,
                height=18,
                highlightthickness=0,
                borderwidth=0,
            )
            style_tk_canvas(swatch, surface="surface")
            if line_style == "point":
                swatch.create_oval(17, 6, 25, 14, fill=color, outline=color)
            else:
                dash = self._preview_key_dash(line_style)
                line_options: dict[str, object] = {
                    "fill": color,
                    "width": max(1, int(round(line_width * 2))),
                }
                if dash is not None:
                    line_options["dash"] = dash
                swatch.create_line(4, 9, 38, 9, **line_options)
            swatch.grid(row=row, column=0, sticky="nw", padx=(6, 4), pady=3)
            swatch.bind("<MouseWheel>", scroll_handler, add="+")
            key_label = ttk.Label(
                key_content,
                text=label,
                wraplength=PREVIEW_KEY_WRAP_LENGTH,
                justify="left",
            )
            key_label.grid(row=row, column=1, sticky="w", padx=(0, 6), pady=3)
            key_label.bind("<MouseWheel>", scroll_handler, add="+")

    @staticmethod
    def _preview_key_dash(line_style: str) -> tuple[int, int] | None:
        if line_style == ":":
            return (2, 3)
        if line_style == "--":
            return (7, 4)
        return None

    def _fit_preview_axes_to_result(self, result: BoundaryResult, axes: object) -> None:
        bounds = self._preview_result_bounds(result)
        if bounds is None:
            axes.relim()
            axes.autoscale_view()
            return

        min_x, min_y, max_x, max_y = bounds
        width = max(max_x - min_x, 1.0)
        height = max(max_y - min_y, 1.0)
        x_padding = width * PREVIEW_LIMIT_PADDING_RATIO
        y_padding = height * PREVIEW_LIMIT_PADDING_RATIO
        axes.set_xlim(min_x - x_padding, max_x + x_padding, auto=True)
        axes.set_ylim(min_y - y_padding, max_y + y_padding, auto=True)

    @staticmethod
    def _preview_result_bounds(
        result: BoundaryResult,
    ) -> tuple[float, float, float, float] | None:
        bounds: list[tuple[float, float, float, float]] = []
        for polygon in (result.base_polygon_projected, result.final_polygon_projected):
            if polygon is not None and not polygon.is_empty:
                bounds.append(tuple(float(value) for value in polygon.bounds))
        bounds.extend(
            tuple(float(value) for value in section.polygon_projected.bounds)
            for section in result.sections
            if not section.polygon_projected.is_empty
        )
        if result.projected_points.size:
            x_values = result.projected_points[:, 0]
            y_values = result.projected_points[:, 1]
            bounds.append(
                (
                    float(x_values.min()),
                    float(y_values.min()),
                    float(x_values.max()),
                    float(y_values.max()),
                )
            )
        if not bounds:
            return None
        return (
            min(item[0] for item in bounds),
            min(item[1] for item in bounds),
            max(item[2] for item in bounds),
            max(item[3] for item in bounds),
        )

    @staticmethod
    def _preview_polygon_xy(polygon) -> tuple[list[float], list[float]]:
        x_values, y_values = polygon.exterior.xy
        x_list = list(x_values)
        y_list = list(y_values)
        if len(x_list) <= PREVIEW_MAX_PLOT_POINTS:
            return x_list, y_list

        step = max(1, math.ceil((len(x_list) - 1) / (PREVIEW_MAX_PLOT_POINTS - 1)))
        decimated_x = x_list[::step]
        decimated_y = y_list[::step]
        if decimated_x[-1] != x_list[-1] or decimated_y[-1] != y_list[-1]:
            decimated_x.append(x_list[-1])
            decimated_y.append(y_list[-1])
        return decimated_x, decimated_y

    def _draw_empty_preview(self) -> None:
        self._active_result_generation = None
        self._map_result_reference = None
        if self._main_map_surface is not None:
            self._draw_empty_preview_on_axes(
                self.axes,
                self.figure,
                getattr(self, "canvas", None),
                self._main_map_surface,
            )
        self._update_preview_key(getattr(self, "preview_key_content", None), [])
        if (
            self._fullscreen_window_exists()
            and self._fullscreen_axes is not None
            and self._fullscreen_figure is not None
            and self._fullscreen_canvas is not None
            and self._fullscreen_map_surface is not None
        ):
            self._draw_empty_preview_on_axes(
                self._fullscreen_axes,
                self._fullscreen_figure,
                self._fullscreen_canvas,
                self._fullscreen_map_surface,
            )
            self._update_preview_key(self._fullscreen_key_content, [])

    def _draw_empty_preview_on_axes(
        self,
        axes: object,
        figure: Figure,
        canvas: FigureCanvasTkAgg | None,
        surface: _PreviewMapSurface,
    ) -> None:
        self._reset_preview_map_surface(surface)
        axes.clear()
        style_matplotlib_axes(figure, axes)
        axes.set_axis_off()
        axes.format_coord = lambda _x, _y: ""
        axes.text(
            0.5,
            0.5,
            "Preview will appear after Update Preview",
            ha="center",
            va="center",
            transform=axes.transAxes,
            color=PALETTE.TEXT_SECONDARY,
        )
        figure.subplots_adjust(left=0.0, right=1.0, bottom=0.0, top=1.0)
        if canvas is not None:
            canvas.draw_idle()

    def _open_fullscreen_preview(self) -> None:
        if self._fullscreen_window_exists():
            assert self._fullscreen_window is not None
            self._maximize_fullscreen_window(self._fullscreen_window)
            self._fullscreen_window.lift()
            self._fullscreen_window.focus_force()
            return

        window = tk.Toplevel(self.root)
        window.withdraw()
        window.title("Preview Inspector")
        window.minsize(640, 420)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)
        style_app_toplevel(window)
        self._fullscreen_window = window

        controls = ttk.Frame(window, padding=(8, 6))
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(11, weight=1)

        self._fullscreen_section_count_var = tk.StringVar(
            master=window,
            value=self.section_count_var.get(),
        )
        self._fullscreen_overlap_var = tk.StringVar(
            master=window,
            value=self.overlap_var.get(),
        )
        self._fullscreen_shape_label_var = tk.StringVar(
            master=window,
            value=self.shape_label_var.get(),
        )
        self._fullscreen_split_direction_var = tk.StringVar(
            master=window,
            value=self.split_direction_var.get(),
        )
        self._fullscreen_split_direction_degrees_var = tk.StringVar(
            master=window,
            value=self.split_direction_degrees_var.get(),
        )
        self._fullscreen_status_var = tk.StringVar(master=window, value="Ready.")
        self._fullscreen_imagery_status_var = tk.StringVar(master=window, value="")

        section_count_label = ttk.Label(controls, text="# Shapes")
        section_count_label.grid(row=0, column=0, sticky="w")
        section_spinbox = ttk.Spinbox(
            controls,
            from_=1,
            to=MAX_SECTION_COUNT,
            textvariable=self._fullscreen_section_count_var,
            width=5,
        )
        section_spinbox.grid(row=0, column=1, sticky="w", padx=(4, 12))

        overlap_label = ttk.Label(controls, text="Overlap")
        overlap_label.grid(row=0, column=2, sticky="w")
        overlap_entry = ttk.Entry(
            controls,
            textvariable=self._fullscreen_overlap_var,
            width=8,
        )
        overlap_entry.grid(row=0, column=3, sticky="w", padx=(4, 12))

        shape_label = ttk.Label(controls, text="Label")
        shape_label.grid(row=0, column=4, sticky="w")
        shape_entry = ttk.Entry(
            controls,
            textvariable=self._fullscreen_shape_label_var,
            width=26,
        )
        shape_entry.grid(row=0, column=5, sticky="ew", padx=(4, 12))

        split_label = ttk.Label(controls, text="Direction")
        split_label.grid(row=0, column=6, sticky="w")
        self._fullscreen_split_direction_combo = ttk.Combobox(
            controls,
            textvariable=self._fullscreen_split_direction_var,
            values=SPLIT_DIRECTION_OPTIONS,
            state="readonly",
            width=20,
        )
        self._fullscreen_split_direction_combo.grid(
            row=0,
            column=7,
            sticky="w",
            padx=(4, 12),
        )

        self._fullscreen_split_direction_custom_label = ttk.Label(
            controls,
            text="Degrees",
        )
        self._fullscreen_split_direction_custom_label.grid(row=0, column=8, sticky="w")
        self._fullscreen_split_direction_custom_entry = ttk.Entry(
            controls,
            textvariable=self._fullscreen_split_direction_degrees_var,
            width=8,
        )
        self._fullscreen_split_direction_custom_entry.grid(
            row=0,
            column=9,
            sticky="w",
            padx=(4, 12),
        )

        self._fullscreen_apply_button = ttk.Button(
            controls,
            text="Apply Preview",
            command=self._apply_fullscreen_preview,
        )
        self._fullscreen_apply_button.grid(row=0, column=10, sticky="w", padx=(0, 8))
        fullscreen_status_label = ttk.Label(
            controls,
            textvariable=self._fullscreen_status_var,
        )
        fullscreen_status_label.grid(
            row=0,
            column=11,
            sticky="w",
        )
        fullscreen_close_button = ttk.Button(
            controls,
            text="Close",
            command=self._close_fullscreen_preview,
        )
        fullscreen_close_button.grid(row=0, column=12, sticky="e", padx=(8, 0))

        self._fullscreen_section_widgets = [
            overlap_label,
            overlap_entry,
            shape_label,
            shape_entry,
            split_label,
            self._fullscreen_split_direction_combo,
        ]
        self._fullscreen_mutation_widgets = [
            section_spinbox,
            overlap_entry,
            shape_entry,
            self._fullscreen_split_direction_combo,
            self._fullscreen_split_direction_custom_entry,
        ]
        self._fullscreen_section_count_var.trace_add(
            "write",
            lambda *_args: self._update_fullscreen_control_state(),
        )
        self._fullscreen_split_direction_var.trace_add(
            "write",
            lambda *_args: self._update_fullscreen_control_state(),
        )
        self._update_fullscreen_control_state()

        plot_frame = ttk.Frame(window)
        plot_frame.grid(row=1, column=0, sticky="nsew")
        plot_frame.columnconfigure(0, weight=1)
        plot_frame.columnconfigure(1, weight=0)
        plot_frame.rowconfigure(0, weight=1)

        self._fullscreen_figure = Figure(figsize=(12, 8), dpi=100)
        self._fullscreen_axes = self._fullscreen_figure.add_subplot(111)
        self._fullscreen_canvas = FigureCanvasTkAgg(
            self._fullscreen_figure,
            master=plot_frame,
        )
        fullscreen_canvas_widget = self._fullscreen_canvas.get_tk_widget()
        style_tk_canvas(fullscreen_canvas_widget, PALETTE.BACKGROUND_DEEP)
        fullscreen_canvas_widget.grid(row=0, column=0, sticky="nsew")
        (
            self._fullscreen_key_frame,
            self._fullscreen_key_canvas,
            self._fullscreen_key_content,
        ) = self._create_preview_key_panel(plot_frame)
        self._fullscreen_key_canvas.bind(
            "<MouseWheel>",
            self._scroll_fullscreen_preview_key,
        )
        self._fullscreen_key_content.bind(
            "<MouseWheel>",
            self._scroll_fullscreen_preview_key,
        )
        self._fullscreen_key_frame.grid(row=0, column=1, sticky="ns", padx=(8, 8))

        fullscreen_toolbar_frame = ttk.Frame(window, style="Toolbar.TFrame")
        fullscreen_toolbar_frame.grid(row=2, column=0, sticky="ew")
        fullscreen_toolbar_frame.columnconfigure(0, weight=1)
        self._fullscreen_toolbar = NavigationToolbar2Tk(
            self._fullscreen_canvas,
            fullscreen_toolbar_frame,
            pack_toolbar=False,
        )
        self._fullscreen_toolbar.update()
        self._disable_toolbar_coordinate_message(self._fullscreen_toolbar)
        style_navigation_toolbar(self._fullscreen_toolbar)
        self._fullscreen_toolbar.grid(row=0, column=0, sticky="ew")
        fullscreen_view_controls = ttk.Frame(
            fullscreen_toolbar_frame,
            style="Toolbar.TFrame",
        )
        fullscreen_view_controls.grid(row=0, column=1, sticky="e", padx=(8, 6))
        self._fullscreen_imagery_checkbutton = ttk.Checkbutton(
            fullscreen_view_controls,
            text="World Imagery",
            variable=self.world_imagery_var,
            style="Surface.TCheckbutton",
        )
        self._fullscreen_imagery_checkbutton.grid(row=0, column=0, sticky="e")
        self._fullscreen_imagery_status_label = ttk.Label(
            fullscreen_view_controls,
            textvariable=self._fullscreen_imagery_status_var,
            style="Surface.Secondary.TLabel",
            anchor="e",
            width=20,
        )
        self._fullscreen_imagery_status_label.grid(
            row=0,
            column=1,
            sticky="e",
            padx=(8, 0),
        )

        inspector_layout_state: dict[str, bool | None] = {"compact": None}

        def resize_inspector_key_labels() -> None:
            if (
                self._fullscreen_key_canvas is None
                or self._fullscreen_key_content is None
            ):
                return
            try:
                key_width = int(self._fullscreen_key_canvas.cget("width"))
            except (tk.TclError, TypeError, ValueError):
                return
            wraplength = max(48, key_width - 60)
            for child in self._fullscreen_key_content.winfo_children():
                try:
                    if (
                        child.winfo_class() == "TLabel"
                        and int(float(child.cget("wraplength"))) != wraplength
                    ):
                        child.configure(wraplength=wraplength)
                except (tk.TclError, TypeError, ValueError):
                    continue

        def layout_inspector(event: object | None = None) -> None:
            if (
                event is not None
                and getattr(event, "widget", None) is not window
            ):
                return
            if (
                self._fullscreen_window is not window
                or self._fullscreen_key_frame is None
                or self._fullscreen_key_canvas is None
            ):
                return
            width = int(getattr(event, "width", window.winfo_width()))
            compact = width < 1200
            key_width = 120 if width <= 900 else PREVIEW_KEY_PANEL_WIDTH
            self._fullscreen_key_frame.configure(width=key_width)
            self._fullscreen_key_canvas.configure(width=key_width)
            resize_inspector_key_labels()
            if inspector_layout_state["compact"] == compact:
                return
            inspector_layout_state["compact"] = compact
            for column in range(13):
                controls.columnconfigure(column, weight=0)
            if compact:
                controls.columnconfigure(5, weight=1)
                section_count_label.grid_configure(
                    row=0,
                    column=0,
                    columnspan=1,
                    sticky="w",
                    padx=0,
                )
                section_spinbox.grid_configure(
                    row=0,
                    column=1,
                    columnspan=1,
                    sticky="w",
                    padx=(4, 12),
                )
                overlap_label.grid_configure(
                    row=0,
                    column=2,
                    columnspan=1,
                    sticky="w",
                    padx=0,
                )
                overlap_entry.grid_configure(
                    row=0,
                    column=3,
                    columnspan=1,
                    sticky="w",
                    padx=(4, 12),
                )
                shape_label.grid_configure(
                    row=0,
                    column=4,
                    columnspan=1,
                    sticky="w",
                    padx=0,
                )
                shape_entry.grid_configure(
                    row=0,
                    column=5,
                    columnspan=1,
                    sticky="ew",
                    padx=(4, 0),
                )
                split_label.grid_configure(
                    row=1,
                    column=0,
                    columnspan=1,
                    sticky="w",
                    padx=0,
                    pady=(5, 0),
                )
                self._fullscreen_split_direction_combo.grid_configure(
                    row=1,
                    column=1,
                    columnspan=2,
                    sticky="w",
                    padx=(4, 12),
                    pady=(5, 0),
                )
                self._fullscreen_split_direction_custom_label.grid_configure(
                    row=1,
                    column=3,
                    columnspan=1,
                    sticky="w",
                    padx=0,
                    pady=(5, 0),
                )
                self._fullscreen_split_direction_custom_entry.grid_configure(
                    row=1,
                    column=4,
                    columnspan=1,
                    sticky="w",
                    padx=(4, 12),
                    pady=(5, 0),
                )
                self._fullscreen_apply_button.grid_configure(
                    row=2,
                    column=0,
                    columnspan=2,
                    sticky="w",
                    padx=(0, 8),
                    pady=(5, 0),
                )
                fullscreen_status_label.grid_configure(
                    row=2,
                    column=2,
                    columnspan=3,
                    sticky="w",
                    padx=0,
                    pady=(5, 0),
                )
                fullscreen_close_button.grid_configure(
                    row=2,
                    column=5,
                    columnspan=1,
                    sticky="e",
                    padx=(8, 0),
                    pady=(5, 0),
                )
                return

            controls.columnconfigure(11, weight=1)
            section_count_label.grid_configure(
                row=0, column=0, columnspan=1, sticky="w", padx=0, pady=0
            )
            section_spinbox.grid_configure(
                row=0,
                column=1,
                columnspan=1,
                sticky="w",
                padx=(4, 12),
                pady=0,
            )
            overlap_label.grid_configure(
                row=0, column=2, columnspan=1, sticky="w", padx=0, pady=0
            )
            overlap_entry.grid_configure(
                row=0,
                column=3,
                columnspan=1,
                sticky="w",
                padx=(4, 12),
                pady=0,
            )
            shape_label.grid_configure(
                row=0, column=4, columnspan=1, sticky="w", padx=0, pady=0
            )
            shape_entry.grid_configure(
                row=0,
                column=5,
                columnspan=1,
                sticky="ew",
                padx=(4, 12),
                pady=0,
            )
            split_label.grid_configure(
                row=0, column=6, columnspan=1, sticky="w", padx=0, pady=0
            )
            self._fullscreen_split_direction_combo.grid_configure(
                row=0,
                column=7,
                columnspan=1,
                sticky="w",
                padx=(4, 12),
                pady=0,
            )
            self._fullscreen_split_direction_custom_label.grid_configure(
                row=0, column=8, columnspan=1, sticky="w", padx=0, pady=0
            )
            self._fullscreen_split_direction_custom_entry.grid_configure(
                row=0,
                column=9,
                columnspan=1,
                sticky="w",
                padx=(4, 12),
                pady=0,
            )
            self._fullscreen_apply_button.grid_configure(
                row=0,
                column=10,
                columnspan=1,
                sticky="w",
                padx=(0, 8),
                pady=0,
            )
            fullscreen_status_label.grid_configure(
                row=0,
                column=11,
                columnspan=1,
                sticky="w",
                padx=0,
                pady=0,
            )
            fullscreen_close_button.grid_configure(
                row=0,
                column=12,
                columnspan=1,
                sticky="e",
                padx=(8, 0),
                pady=0,
            )

        window.bind("<Configure>", layout_inspector, add="+")
        self._fullscreen_key_content.bind(
            "<Configure>",
            lambda _event: resize_inspector_key_labels(),
            add="+",
        )
        layout_inspector()

        self._fullscreen_surface_serial += 1
        self._fullscreen_map_surface = self._create_preview_map_surface(
            f"inspector:{self._fullscreen_surface_serial}",
            self._fullscreen_axes,
            self._fullscreen_figure,
            self._fullscreen_canvas,
            self._fullscreen_imagery_status_var,
        )
        self._fullscreen_event_cids = self._register_preview_canvas_interactions(
            self._fullscreen_canvas,
            self._fullscreen_axes,
            self._fullscreen_toolbar,
        )

        window.bind("<Escape>", lambda _event: self._close_fullscreen_preview())
        window.protocol("WM_DELETE_WINDOW", self._close_fullscreen_preview)
        self._draw_fullscreen_preview()
        window.update_idletasks()
        clamp_child_geometry(self.root, window)
        apply_native_chrome(window)
        self._maximize_fullscreen_window(window)
        window.deiconify()
        window.focus_set()

    def _apply_fullscreen_preview(self) -> None:
        if self._busy:
            return
        if not self._fullscreen_controls_ready():
            return

        assert self._fullscreen_section_count_var is not None
        assert self._fullscreen_overlap_var is not None
        assert self._fullscreen_shape_label_var is not None
        assert self._fullscreen_split_direction_var is not None
        assert self._fullscreen_split_direction_degrees_var is not None
        try:
            (
                input_path,
                buffer_ft,
                section_count,
                overlap_ft,
                shape_label,
                outline_mode,
                split_direction_deg,
                simplify_vector_output,
                _,
            ) = self._read_inputs(
                require_output=False,
                section_count_text=self._fullscreen_section_count_var.get(),
                overlap_text=self._fullscreen_overlap_var.get(),
                shape_label_text=self._fullscreen_shape_label_var.get(),
                split_direction_label=self._fullscreen_split_direction_var.get(),
                split_direction_degrees_text=(
                    self._fullscreen_split_direction_degrees_var.get()
                ),
            )
        except BoundaryError as error:
            self._set_fullscreen_status(str(error))
            messagebox.showerror(
                "Invalid input",
                str(error),
                parent=self._fullscreen_window or self.root,
            )
            return

        self.section_count_var.set(str(section_count))
        self.overlap_var.set(self._fullscreen_overlap_var.get().strip())
        if section_count > 1:
            self.shape_label_var.set(shape_label)
            self._fullscreen_shape_label_var.set(shape_label)
        self.split_direction_var.set(self._fullscreen_split_direction_var.get())
        self.split_direction_degrees_var.set(
            self._fullscreen_split_direction_degrees_var.get().strip()
        )
        self._set_fullscreen_status("Reading input and building preview...")
        self._start_preview_generation(
            input_path,
            buffer_ft,
            section_count,
            overlap_ft,
            shape_label,
            outline_mode,
            split_direction_deg,
            simplify_vector_output,
        )

    def _fullscreen_controls_ready(self) -> bool:
        return (
            self._fullscreen_window_exists()
            and self._fullscreen_section_count_var is not None
            and self._fullscreen_overlap_var is not None
            and self._fullscreen_shape_label_var is not None
            and self._fullscreen_split_direction_var is not None
            and self._fullscreen_split_direction_degrees_var is not None
        )

    def _update_fullscreen_control_state(self) -> None:
        if not self._fullscreen_window_exists():
            return

        if self._busy:
            for widget in (
                self._fullscreen_mutation_widgets
                + self._fullscreen_section_widgets
            ):
                try:
                    widget.configure(state="disabled")
                except tk.TclError:
                    continue
            if self._fullscreen_split_direction_custom_label is not None:
                self._fullscreen_split_direction_custom_label.configure(
                    state="disabled"
                )
            if self._fullscreen_apply_button is not None:
                self._fullscreen_apply_button.configure(state="disabled")
            return

        if self._fullscreen_apply_button is not None:
            self._fullscreen_apply_button.configure(state="normal")

        enabled = True
        try:
            assert self._fullscreen_section_count_var is not None
            enabled = int(self._fullscreen_section_count_var.get().strip()) > 1
        except (AssertionError, ValueError):
            enabled = True

        section_state = "normal" if enabled else "disabled"
        for widget in self._fullscreen_section_widgets:
            if isinstance(widget, ttk.Combobox):
                widget.configure(state="readonly" if enabled else "disabled")
            else:
                widget.configure(state=section_state)

        custom_enabled = (
            enabled
            and self._fullscreen_split_direction_var is not None
            and self._fullscreen_split_direction_var.get() == "Custom"
        )
        custom_state = "normal" if custom_enabled else "disabled"
        if self._fullscreen_split_direction_custom_label is not None:
            self._fullscreen_split_direction_custom_label.configure(state=custom_state)
        if self._fullscreen_split_direction_custom_entry is not None:
            self._fullscreen_split_direction_custom_entry.configure(state=custom_state)

    def _draw_fullscreen_preview(self, result: BoundaryResult | None = None) -> None:
        if not self._fullscreen_window_exists():
            return
        if (
            self._fullscreen_axes is None
            or self._fullscreen_figure is None
            or self._fullscreen_canvas is None
            or self._fullscreen_map_surface is None
        ):
            return

        preview_result = result or self._cached_result or self._last_displayed_result
        self._set_fullscreen_status(self._preview_status_text())
        if preview_result is None:
            self._draw_empty_preview_on_axes(
                self._fullscreen_axes,
                self._fullscreen_figure,
                self._fullscreen_canvas,
                self._fullscreen_map_surface,
            )
            self._update_preview_key(self._fullscreen_key_content, [])
            return

        self._draw_preview_on_axes(
            preview_result,
            self._fullscreen_axes,
            self._fullscreen_figure,
            self._fullscreen_canvas,
            self._fullscreen_key_content,
            self._fullscreen_map_surface,
        )

    def _set_fullscreen_status(self, status: str) -> None:
        if self._fullscreen_status_var is not None:
            self._fullscreen_status_var.set(status)

    def _fullscreen_window_exists(self) -> bool:
        if self._fullscreen_window is None:
            return False
        try:
            return bool(self._fullscreen_window.winfo_exists())
        except tk.TclError:
            return False

    def _maximize_fullscreen_window(self, window: tk.Toplevel) -> None:
        work_area = get_window_work_area(window)
        zoom_contained = False
        try:
            window.state("zoomed")
            window.update_idletasks()
            outer_bounds = get_outer_window_bounds(window)
            zoom_contained = (
                outer_bounds is not None
                and outer_bounds.is_within(work_area)
            )
        except tk.TclError:
            zoom_contained = False

        if zoom_contained:
            return

        try:
            window.state("normal")
            window.update_idletasks()
        except tk.TclError:
            pass
        fit_window_to_work_area(
            window,
            work_area,
            max_fraction=0.94,
        )

    def _close_fullscreen_preview(self) -> None:
        map_surface = self._fullscreen_map_surface
        if map_surface is not None:
            self._reset_preview_map_surface(map_surface, deregister=True)
            for cid in map_surface.observer_event_cids:
                try:
                    map_surface.canvas.mpl_disconnect(cid)
                except Exception:
                    pass
            map_surface.observer_event_cids = []

        if self._fullscreen_canvas is not None:
            for cid in self._fullscreen_event_cids:
                try:
                    self._fullscreen_canvas.mpl_disconnect(cid)
                except Exception:
                    pass

        window = self._fullscreen_window
        self._fullscreen_window = None
        self._fullscreen_event_cids = []
        self._fullscreen_figure = None
        self._fullscreen_axes = None
        self._fullscreen_canvas = None
        self._fullscreen_map_surface = None
        self._fullscreen_toolbar = None
        self._fullscreen_imagery_checkbutton = None
        self._fullscreen_imagery_status_label = None
        self._fullscreen_key_frame = None
        self._fullscreen_key_canvas = None
        self._fullscreen_key_content = None
        self._fullscreen_status_var = None
        self._fullscreen_imagery_status_var = None
        self._fullscreen_section_count_var = None
        self._fullscreen_overlap_var = None
        self._fullscreen_shape_label_var = None
        self._fullscreen_split_direction_var = None
        self._fullscreen_split_direction_degrees_var = None
        self._fullscreen_apply_button = None
        self._fullscreen_section_widgets = []
        self._fullscreen_mutation_widgets = []
        self._fullscreen_split_direction_combo = None
        self._fullscreen_split_direction_custom_label = None
        self._fullscreen_split_direction_custom_entry = None
        self._preview_pan_start = None

        if window is not None:
            try:
                window.destroy()
            except tk.TclError:
                pass

    def _write_status(self, text: str) -> None:
        self._details_text = text
        self.details_button.configure(state="normal" if text.strip() else "disabled")

    def _show_details(self) -> None:
        if not self._details_text.strip():
            messagebox.showinfo(
                "Boundary Details",
                "No preview or export details yet.",
                parent=self.root,
            )
            return

        detail_window = tk.Toplevel(self.root)
        detail_window.withdraw()
        detail_window.title("Boundary Details")
        detail_window.minsize(640, 420)
        detail_window.transient(self.root)
        style_app_toplevel(detail_window)

        detail_window.columnconfigure(0, weight=1)
        detail_window.rowconfigure(0, weight=1)

        text_frame = ttk.Frame(detail_window, padding=10)
        text_frame.grid(row=0, column=0, sticky="nsew")
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)

        details_text = tk.Text(text_frame, wrap="word", height=18)
        style_tk_text(details_text)
        scrollbar = ttk.Scrollbar(
            text_frame,
            orient="vertical",
            command=details_text.yview,
        )
        details_text.configure(yscrollcommand=scrollbar.set)
        details_text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        details_text.insert("1.0", self._details_text)
        details_text.configure(state="disabled")

        ttk.Button(
            detail_window,
            text="Close",
            command=detail_window.destroy,
        ).grid(row=1, column=0, sticky="e", padx=10, pady=(0, 10))
        self._center_child_window(detail_window)
        apply_native_chrome(detail_window)
        detail_window.deiconify()

    def _set_busy(self, busy: bool, status: str) -> None:
        self._busy = busy
        if busy:
            self._preview_error = ""
            for widget in (
                self._all_mutation_widgets
                + self._busy_action_widgets
                + self._fullscreen_mutation_widgets
            ):
                try:
                    widget.configure(state="disabled")
                except tk.TclError:
                    continue
            if self._fullscreen_apply_button is not None:
                self._fullscreen_apply_button.configure(state="disabled")
            self.busy_progress.grid()
            self.busy_progress.start(12)
        else:
            self.busy_progress.stop()
            self.busy_progress.grid_remove()
            for widget in self._all_mutation_widgets:
                try:
                    widget.configure(
                        state="readonly"
                        if isinstance(widget, ttk.Combobox)
                        else "normal"
                    )
                except tk.TclError:
                    continue
            for widget in self._busy_action_widgets:
                try:
                    widget.configure(state="normal")
                except tk.TclError:
                    continue
            for widget in self._fullscreen_mutation_widgets:
                try:
                    widget.configure(
                        state="readonly"
                        if isinstance(widget, ttk.Combobox)
                        else "normal"
                    )
                except tk.TclError:
                    continue
            if self._fullscreen_apply_button is not None:
                self._fullscreen_apply_button.configure(state="normal")
            self._update_outline_mode_state()
            self._update_section_control_state()
            self._update_fullscreen_control_state()
            self.details_button.configure(
                state="normal" if self._details_text.strip() else "disabled"
            )
        self.status_var.set(status)
        self._refresh_preview_state_badge()

    def _invalidate_cache(self) -> None:
        self._cached_result = None
        self._cached_settings = None

    def _set_input_path(self, input_path: Path) -> None:
        self.parent_var.set(str(input_path))
        self._set_output_path(self._default_output_path(input_path))
        self._update_outline_mode_state()
        self._invalidate_cache()

    def _selected_outline_mode(self, input_path: Path) -> str:
        if self._is_vector_file_path(input_path):
            return OUTLINE_MODE_SOURCE_POLYGON
        label = self.outline_mode_var.get().strip() or "Auto"
        if label not in OUTLINE_MODE_LABELS:
            raise BoundaryError("Choose a valid outline mode.")
        return OUTLINE_MODE_LABELS[label]

    @staticmethod
    def _is_vector_file_path(path: Path) -> bool:
        return Path(path).is_file() and Path(path).suffix.lower() in {".kml", ".kmz"}

    def _selected_split_direction(
        self,
        section_count: int,
        *,
        split_direction_label: str | None = None,
        split_direction_degrees_text: str | None = None,
    ) -> float | None:
        if section_count <= 1:
            return None
        label = (
            self.split_direction_var.get()
            if split_direction_label is None
            else split_direction_label
        ).strip() or "Auto"
        if label == "Auto":
            return None
        if label == "0 deg / East-West":
            return 0.0
        if label == "90 deg / North-South":
            return 90.0
        if label != "Custom":
            raise BoundaryError("Choose a valid split direction.")

        value_text = (
            self.split_direction_degrees_var.get()
            if split_direction_degrees_text is None
            else split_direction_degrees_text
        ).strip()
        if not value_text:
            raise BoundaryError("Enter a custom split direction in degrees.")
        try:
            value = float(value_text)
        except ValueError as exc:
            raise BoundaryError("Custom split direction must be a number of degrees.") from exc
        if not math.isfinite(value):
            raise BoundaryError("Custom split direction must be finite.")
        return value % 180.0

    @staticmethod
    def _ready_status(result: BoundaryResult, base_status: str) -> str:
        if result.metadata.polyline_buffer_adjustment_reason:
            return f"{base_status} Auto buffer set."
        if result.metadata.fallback_reason:
            return f"{base_status} Auto fallback used."
        return base_status

    def _sync_effective_buffer(self, result: BoundaryResult) -> None:
        if not result.metadata.polyline_buffer_adjustment_reason:
            return
        selected_buffer = result.metadata.polyline_selected_buffer_ft or result.metadata.buffer_ft
        self.buffer_var.set(self._format_buffer_field_value(selected_buffer))

    @staticmethod
    def _format_buffer_field_value(value: float) -> str:
        rounded = round(float(value))
        if math.isclose(float(value), rounded, abs_tol=1e-9):
            return str(int(rounded))
        return f"{float(value):.2f}".rstrip("0").rstrip(".")

    def _parse_dropped_paths(self, data: str) -> list[Path]:
        if not data:
            return []

        try:
            raw_paths = self.root.tk.splitlist(data)
        except tk.TclError:
            raw_paths = (data,)

        return [self._path_from_text(raw_path) for raw_path in raw_paths if raw_path]

    def _resolve_output_path(self, output_text: str) -> Path:
        output_path = self._path_from_text(output_text)
        if not output_path.is_absolute():
            output_path = APP_ROOT / output_path
        return output_path

    @staticmethod
    def _path_from_text(path_text: str) -> Path:
        cleaned = BoundaryKmzApp._strip_wrapping_quotes(path_text)
        if cleaned.lower().startswith("file:"):
            parsed = urlparse(cleaned)
            cleaned = unquote(parsed.path)
            if parsed.netloc:
                cleaned = f"//{parsed.netloc}{cleaned}"
            if sys.platform.startswith("win") and len(cleaned) >= 3:
                if cleaned[0] == "/" and cleaned[2] == ":":
                    cleaned = cleaned[1:]
        return Path(cleaned).expanduser()

    @staticmethod
    def _strip_wrapping_quotes(path_text: str) -> str:
        cleaned = path_text.strip()
        if len(cleaned) >= 2 and cleaned[0] == cleaned[-1]:
            if cleaned[0] in {"'", '"'}:
                cleaned = cleaned[1:-1].strip()
        return cleaned

    @staticmethod
    def _settings_key(
        input_path: Path,
        buffer_ft: float,
        section_count: int,
        overlap_ft: float,
        shape_label: str,
        outline_mode: str,
        split_direction_deg: float | None,
        generation_profile: str = GENERATION_PROFILE_EXPORT,
        *,
        simplify_vector_output: bool = True,
    ) -> tuple[str, float, int, float, str, str, str, str, str]:
        return (
            str(Path(input_path).resolve()).lower(),
            float(buffer_ft),
            int(section_count),
            float(overlap_ft),
            shape_label.strip(),
            BoundaryKmzApp._settings_outline_key(outline_mode),
            (
                "auto"
                if split_direction_deg is None
                else f"{float(split_direction_deg) % 180.0:.6f}"
            ),
            generation_profile,
            "simplify" if simplify_vector_output else "preserve",
        )

    @staticmethod
    def _settings_outline_key(outline_mode: str) -> str:
        if outline_mode in {OUTLINE_MODE_SOURCE_POLYGON, "source_linework"}:
            return "source_vector"
        return outline_mode

    @staticmethod
    def _default_output_path(input_path: Path | None = None) -> Path:
        DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        if input_path is None:
            output_name = "jpg_camera_boundary.kmz"
        else:
            path = Path(input_path)
            folder_name = path.stem if path.is_file() else path.name
            folder_name = folder_name or "jpg_camera_boundary"
            output_name = (
                f"{BoundaryKmzApp._safe_filename_stem(folder_name)}_boundary.kmz"
            )
        return DEFAULT_OUTPUT_DIR / output_name

    @staticmethod
    def _safe_filename_stem(value: str) -> str:
        invalid = '<>:"/\\|?*'
        safe = "".join("_" if char in invalid else char for char in value).strip()
        return safe or "jpg_camera_boundary"

    @staticmethod
    def _filename_from_output_name(output_name: str) -> str:
        stem = BoundaryKmzApp._strip_wrapping_quotes(output_name)
        if stem.lower().endswith(".kmz"):
            stem = stem[:-4]
        return f"{BoundaryKmzApp._safe_filename_stem(stem)}.kmz"

    def _default_shape_label(self) -> str:
        output_text = self.output_var.get().strip()
        if not output_text:
            return "jpg_camera_boundary"
        return self._resolve_output_path(output_text).stem or "jpg_camera_boundary"


def main() -> None:
    root = _create_root()
    root.withdraw()
    work_area = get_launch_work_area(root)
    app = BoundaryKmzApp(root)
    root.update_idletasks()
    fit = apply_initial_geometry(root, work_area)
    app._set_window_fit_warning(fit)
    apply_native_chrome(root)
    root.deiconify()
    root.mainloop()


def _create_root() -> tk.Tk:
    if TkinterDnD is not None:
        try:
            return TkinterDnD.Tk()
        except tk.TclError:
            pass
    return tk.Tk()


if __name__ == "__main__":
    main()
