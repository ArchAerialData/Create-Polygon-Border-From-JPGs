from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import math
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.parse import unquote, urlparse

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:
    DND_FILES = None
    TkinterDnD = None

from jpg_boundary_kmz_core import (
    BoundaryError,
    BoundaryResult,
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
SPLIT_DIRECTION_OPTIONS = (
    "Auto",
    "0 deg / East-West",
    "90 deg / North-South",
    "Custom",
)


class BoundaryKmzApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("JPG Boundary to KMZ")
        self.root.minsize(980, 720)

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
        self.status_var = tk.StringVar(value="Choose a JPG folder, KML, or KMZ file to begin.")
        self._updating_output_fields = False
        self._updating_shape_label = False
        self._shape_label_touched = False
        self._details_text = ""

        self._queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._cached_result: BoundaryResult | None = None
        self._cached_settings: tuple[str, float, int, float, str, str, str] | None = None
        self._busy = False

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
        self._update_outline_mode_state()
        self._update_section_control_state()
        self.root.after(100, self._drain_queue)

    def _build_ui(self) -> None:
        root_frame = ttk.Frame(self.root, padding=12)
        root_frame.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        root_frame.columnconfigure(1, weight=1)
        root_frame.rowconfigure(8, weight=1)

        ttk.Label(root_frame, text="Input folder, KML, or KMZ").grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 8),
            pady=4,
        )
        ttk.Entry(root_frame, textvariable=self.parent_var).grid(
            row=0,
            column=1,
            sticky="ew",
            pady=4,
        )
        input_buttons = ttk.Frame(root_frame)
        input_buttons.grid(
            row=0,
            column=2,
            sticky="ew",
            padx=(8, 0),
            pady=4,
        )
        input_buttons.columnconfigure(0, weight=1)
        input_buttons.columnconfigure(1, weight=1)
        ttk.Button(
            input_buttons,
            text="Browse Folder...",
            command=self._browse_parent,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(
            input_buttons,
            text="Browse KML/KMZ...",
            command=self._browse_kmz,
        ).grid(row=0, column=1, sticky="ew")

        ttk.Label(root_frame, text="Buffer (feet)").grid(
            row=2,
            column=0,
            sticky="w",
            padx=(0, 8),
            pady=4,
        )
        ttk.Entry(root_frame, textvariable=self.buffer_var, width=16).grid(
            row=2,
            column=1,
            sticky="w",
            pady=4,
        )

        self.outline_mode_label = ttk.Label(root_frame, text="Outline mode")
        self.outline_mode_label.grid(
            row=3,
            column=0,
            sticky="w",
            padx=(0, 8),
            pady=4,
        )
        self.outline_mode_combo = ttk.Combobox(
            root_frame,
            textvariable=self.outline_mode_var,
            values=list(OUTLINE_MODE_LABELS.keys()),
            state="readonly",
            width=28,
        )
        self.outline_mode_combo.grid(row=3, column=1, sticky="w", pady=4)

        ttk.Label(root_frame, text="Output file name").grid(
            row=4,
            column=0,
            sticky="w",
            padx=(0, 8),
            pady=4,
        )
        output_name_frame = ttk.Frame(root_frame)
        output_name_frame.grid(row=4, column=1, sticky="ew", pady=4)
        output_name_frame.columnconfigure(0, weight=1)
        ttk.Entry(
            output_name_frame,
            textvariable=self.output_name_var,
        ).grid(row=0, column=0, sticky="ew")
        ttk.Label(output_name_frame, text=".kmz").grid(
            row=0,
            column=1,
            sticky="w",
            padx=(6, 0),
        )

        ttk.Label(root_frame, text="Output KMZ").grid(
            row=5,
            column=0,
            sticky="w",
            padx=(0, 8),
            pady=4,
        )
        ttk.Entry(root_frame, textvariable=self.output_var).grid(
            row=5,
            column=1,
            sticky="ew",
            pady=4,
        )
        output_buttons = ttk.Frame(root_frame)
        output_buttons.grid(
            row=5,
            column=2,
            sticky="ew",
            padx=(8, 0),
            pady=4,
        )
        output_buttons.columnconfigure(0, weight=1)
        output_buttons.columnconfigure(1, weight=1)
        ttk.Button(
            output_buttons,
            text="Save As...",
            command=self._browse_output,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(
            output_buttons,
            text="View Output Folder",
            command=self._view_output_folder,
        ).grid(row=0, column=1, sticky="ew")

        sections_frame = ttk.LabelFrame(root_frame, text="Sections")
        sections_frame.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(8, 4))
        sections_frame.columnconfigure(5, weight=1)

        ttk.Label(sections_frame, text="# of Shapes").grid(
            row=0,
            column=0,
            sticky="w",
            padx=(8, 6),
            pady=8,
        )
        self.section_count_spinbox = ttk.Spinbox(
            sections_frame,
            from_=1,
            to=MAX_SECTION_COUNT,
            textvariable=self.section_count_var,
            width=8,
        )
        self.section_count_spinbox.grid(row=0, column=1, sticky="w", pady=8)

        self.overlap_label = ttk.Label(sections_frame, text="Overlap (feet)")
        self.overlap_label.grid(
            row=0,
            column=2,
            sticky="w",
            padx=(16, 6),
            pady=8,
        )
        self.overlap_entry = ttk.Entry(
            sections_frame,
            textvariable=self.overlap_var,
            width=10,
        )
        self.overlap_entry.grid(row=0, column=3, sticky="w", pady=8)

        self.shape_label_label = ttk.Label(sections_frame, text="Shape Label")
        self.shape_label_label.grid(
            row=0,
            column=4,
            sticky="w",
            padx=(16, 6),
            pady=8,
        )
        self.shape_label_entry = ttk.Entry(
            sections_frame,
            textvariable=self.shape_label_var,
        )
        self.shape_label_entry.grid(
            row=0,
            column=5,
            sticky="ew",
            padx=(0, 8),
            pady=8,
        )

        self.split_direction_label = ttk.Label(sections_frame, text="Split direction")
        self.split_direction_label.grid(
            row=1,
            column=0,
            sticky="w",
            padx=(8, 6),
            pady=(0, 8),
        )
        self.split_direction_combo = ttk.Combobox(
            sections_frame,
            textvariable=self.split_direction_var,
            values=SPLIT_DIRECTION_OPTIONS,
            state="readonly",
            width=20,
        )
        self.split_direction_combo.grid(row=1, column=1, sticky="w", pady=(0, 8))
        self.split_direction_custom_label = ttk.Label(
            sections_frame,
            text="Degrees",
        )
        self.split_direction_custom_label.grid(
            row=1,
            column=2,
            sticky="w",
            padx=(16, 6),
            pady=(0, 8),
        )
        self.split_direction_custom_entry = ttk.Entry(
            sections_frame,
            textvariable=self.split_direction_degrees_var,
            width=10,
        )
        self.split_direction_custom_entry.grid(row=1, column=3, sticky="w", pady=(0, 8))

        drop_frame = ttk.LabelFrame(root_frame, text="Drag and drop")
        drop_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 4))
        drop_frame.columnconfigure(0, weight=1)

        drop_text = (
            "Drop an input folder, KML, or KMZ here"
            if DND_FILES is not None
            else "Drag-and-drop is unavailable; use Browse Folder or Browse KML/KMZ..."
        )
        self.drop_label = tk.Label(
            drop_frame,
            text=drop_text,
            anchor="center",
            padx=16,
            pady=18,
            relief="groove",
            borderwidth=2,
            background="#f3f6f8",
            foreground="#1f2933",
        )
        self.drop_label.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        self._register_drop_target()

        button_frame = ttk.Frame(root_frame)
        button_frame.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(8, 4))
        button_frame.columnconfigure(3, weight=1)

        self.scan_button = ttk.Button(
            button_frame,
            text="Scan / Preview",
            command=self._scan_clicked,
        )
        self.scan_button.grid(row=0, column=0, padx=(0, 8))

        self.export_button = ttk.Button(
            button_frame,
            text="Export KMZ",
            command=self._export_clicked,
        )
        self.export_button.grid(row=0, column=1, padx=(0, 8))

        self.details_button = ttk.Button(
            button_frame,
            text="View Details",
            command=self._show_details,
            state="disabled",
        )
        self.details_button.grid(row=0, column=2, padx=(0, 8))

        ttk.Label(button_frame, textvariable=self.status_var).grid(
            row=0,
            column=3,
            sticky="w",
        )

        preview_frame = ttk.LabelFrame(root_frame, text="Preview")
        preview_frame.grid(row=8, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)

        self.figure = Figure(figsize=(8, 5), dpi=100)
        self.axes = self.figure.add_subplot(111)
        self._draw_empty_preview()
        self.canvas = FigureCanvasTkAgg(self.figure, master=preview_frame)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.grid(row=0, column=0, sticky="nsew")

    def _register_drop_target(self) -> None:
        if DND_FILES is None:
            return

        try:
            self.drop_label.drop_target_register(DND_FILES)
            self.drop_label.dnd_bind("<<Drop>>", self._handle_folder_drop)
            self.drop_label.dnd_bind("<<DragEnter>>", self._handle_drag_enter)
            self.drop_label.dnd_bind("<<DragLeave>>", self._handle_drag_leave)
        except (AttributeError, tk.TclError):
            self.drop_label.configure(
                text="Drag-and-drop failed to initialize; use Browse buttons...",
                background="#fff4e5",
            )

    def _handle_drag_enter(self, _event: object) -> None:
        self.drop_label.configure(background="#dbeafe")

    def _handle_drag_leave(self, _event: object) -> None:
        self.drop_label.configure(background="#f3f6f8")

    def _handle_folder_drop(self, event: object) -> None:
        self.drop_label.configure(background="#f3f6f8")
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
            )
            return

        input_path = inputs[0]
        self._set_input_path(input_path)
        if len(inputs) > 1:
            self.status_var.set(f"Using first dropped input: {input_path}")
        else:
            self.status_var.set(f"Input set: {input_path}")

    def _browse_parent(self) -> None:
        folder = filedialog.askdirectory(title="Choose parent folder containing JPGs")
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
        )
        if output:
            self._set_output_path(Path(output))

    def _view_output_folder(self) -> None:
        try:
            folder = self._current_output_folder()
            self._open_output_folder(folder)
            self.status_var.set(f"Opened output folder: {folder}")
        except Exception as error:
            messagebox.showerror("Open output folder failed", str(error))

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

    def _on_output_name_changed(self, *_args: object) -> None:
        if self._updating_output_fields:
            return

        output_name = self.output_name_var.get().strip()
        if not output_name:
            self._invalidate_cache()
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

    def _on_outline_mode_changed(self, *_args: object) -> None:
        self._invalidate_cache()

    def _on_section_options_changed(self, *_args: object) -> None:
        self._update_section_control_state()
        self._refresh_shape_label_default()
        self._invalidate_cache()

    def _on_shape_label_changed(self, *_args: object) -> None:
        if self._updating_shape_label:
            return
        self._shape_label_touched = True
        self._invalidate_cache()

    def _update_section_control_state(self) -> None:
        enabled = self._current_section_count_for_state() > 1
        state = "normal" if enabled else "disabled"
        for widget in (
            self.overlap_label,
            self.overlap_entry,
            self.shape_label_label,
            self.shape_label_entry,
        ):
            widget.configure(state=state)

    def _update_outline_mode_state(self) -> None:
        input_text = self.parent_var.get().strip()
        is_kmz = False
        if input_text:
            input_path = self._path_from_text(input_text)
            is_kmz = input_path.suffix.lower() == ".kmz"
        state = "disabled" if is_kmz else "readonly"
        self.outline_mode_combo.configure(state=state)
        self.outline_mode_label.configure(state="disabled" if is_kmz else "normal")

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
                _,
            ) = (
                self._read_inputs(require_output=False)
            )
        except BoundaryError as error:
            messagebox.showerror("Invalid input", str(error))
            return

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
                output_path,
            ) = self._read_inputs(require_output=True)
        except BoundaryError as error:
            messagebox.showerror("Invalid input", str(error))
            return

        if output_path.exists():
            overwrite = messagebox.askyesno(
                "Overwrite KMZ?",
                f"The output file already exists:\n\n{output_path}\n\nOverwrite it?",
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
    ) -> None:
        try:
            result = generate_boundary_from_input(
                input_path,
                buffer_ft,
                section_count=section_count,
                overlap_ft=overlap_ft,
                shape_label=shape_label,
                outline_mode=outline_mode,
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
                self._cached_result = result
                self._cached_settings = self._settings_key(
                    result.metadata.source_folder,
                    result.metadata.buffer_ft,
                    result.metadata.section_count,
                    result.metadata.overlap_ft,
                    result.metadata.shape_label,
                    result.metadata.outline_mode,
                )
                self._write_status(format_summary(result.metadata))
                self._draw_preview(result)
                self._set_busy(False, self._ready_status(result, "Preview ready."))
            elif kind == "export_done":
                result, saved_path = payload
                assert isinstance(result, BoundaryResult)
                saved_path = Path(saved_path)
                self._cached_result = result
                self._cached_settings = self._settings_key(
                    result.metadata.source_folder,
                    result.metadata.buffer_ft,
                    result.metadata.section_count,
                    result.metadata.overlap_ft,
                    result.metadata.shape_label,
                    result.metadata.outline_mode,
                )
                self._write_status(
                    format_summary(result.metadata)
                    + f"\n\nSaved KMZ: {saved_path}"
                )
                self._draw_preview(result)
                self._set_busy(False, self._ready_status(result, "KMZ exported."))
                self._show_export_success(saved_path)
            elif kind == "error":
                error = payload
                self._set_busy(False, "Ready.")
                self._write_status(str(error))
                messagebox.showerror("Boundary generation failed", str(error))

        self.root.after(100, self._drain_queue)

    def _show_export_success(self, saved_path: Path) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("KMZ exported")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.columnconfigure(0, weight=1)

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
        dialog.grab_set()
        ok_button.focus_set()

    def _center_child_window(self, window: tk.Toplevel) -> None:
        self.root.update_idletasks()
        window.update_idletasks()

        parent_x = self.root.winfo_rootx()
        parent_y = self.root.winfo_rooty()
        parent_width = self.root.winfo_width()
        parent_height = self.root.winfo_height()
        window_width = window.winfo_width()
        window_height = window.winfo_height()

        x = parent_x + max((parent_width - window_width) // 2, 0)
        y = parent_y + max((parent_height - window_height) // 2, 0)
        window.geometry(f"+{x}+{y}")

    def _read_inputs(
        self,
        require_output: bool,
    ) -> tuple[Path, float, int, float, str, str, Path | None]:
        input_text = self.parent_var.get().strip()
        if not input_text:
            raise BoundaryError("Choose a JPG folder or an existing KMZ file.")

        input_path = self._path_from_text(input_text)
        if not input_path.exists():
            raise BoundaryError(f"Input path does not exist: {input_path}")
        if not (
            input_path.is_dir()
            or (input_path.is_file() and input_path.suffix.lower() == ".kmz")
        ):
            raise BoundaryError("Input must be a folder of JPGs or a KMZ file.")

        buffer_text = self.buffer_var.get().strip()
        try:
            buffer_ft = float(buffer_text)
        except ValueError as exc:
            raise BoundaryError("Buffer must be a number in feet.") from exc
        if buffer_ft < 0:
            raise BoundaryError("Buffer must be 0 or greater.")

        section_text = self.section_count_var.get().strip()
        try:
            section_count = int(section_text)
        except ValueError as exc:
            raise BoundaryError("# of Shapes must be a whole number.") from exc
        if section_count < 1 or section_count > MAX_SECTION_COUNT:
            raise BoundaryError(f"# of Shapes must be between 1 and {MAX_SECTION_COUNT}.")

        overlap_ft = 0.0
        if section_count > 1:
            overlap_text = self.overlap_var.get().strip()
            try:
                overlap_ft = float(overlap_text)
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
            shape_label = self.shape_label_var.get().strip()
            if not shape_label:
                shape_label = current_output_path.stem
                self._refresh_shape_label_default(force=True)

        if require_output:
            output_path = current_output_path

        outline_mode = self._selected_outline_mode(input_path)
        return (
            input_path,
            buffer_ft,
            section_count,
            overlap_ft,
            shape_label,
            outline_mode,
            output_path,
        )

    def _draw_preview(self, result: BoundaryResult) -> None:
        self.axes.clear()
        if result.metadata.input_type == "JPG folder":
            self.axes.scatter(
                result.projected_points[:, 0],
                result.projected_points[:, 1],
                s=4,
                color="#1f77b4",
                linewidths=0,
                label="JPG GPS points",
            )
        else:
            bx, by = result.base_polygon_projected.exterior.xy
            self.axes.plot(
                bx,
                by,
                color="#1f77b4",
                linewidth=1.4,
                linestyle=":",
                label="Source KMZ polygon",
            )

        if result.sections:
            x, y = result.final_polygon_projected.exterior.xy
            self.axes.plot(
                x,
                y,
                color="#9ca3af",
                linewidth=1.4,
                linestyle="--",
                label="Parent outline",
            )
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
                sx, sy = section.polygon_projected.exterior.xy
                self.axes.plot(
                    sx,
                    sy,
                    color=color,
                    linewidth=1.8,
                    label=section.display_name,
                )
                self.axes.fill(sx, sy, color=color, alpha=0.08)
        else:
            x, y = result.final_polygon_projected.exterior.xy
            self.axes.plot(x, y, color="#d62728", linewidth=2.0, label="KMZ boundary")
            self.axes.fill(x, y, color="#d62728", alpha=0.08)

        self.axes.set_aspect("equal", adjustable="box")
        self.axes.set_title("Camera Positions and Export Boundary")
        self.axes.set_xlabel("Projected X (meters)")
        self.axes.set_ylabel("Projected Y (meters)")
        self.axes.legend(
            loc="center left",
            bbox_to_anchor=(1.02, 0.5),
            fontsize="small",
            ncol=1,
            borderaxespad=0.0,
        )
        self.axes.grid(True, linewidth=0.3, alpha=0.35)
        self.figure.tight_layout(rect=(0.0, 0.0, 0.72, 1.0))
        self.canvas.draw_idle()

    def _draw_empty_preview(self) -> None:
        self.axes.clear()
        self.axes.set_title("Preview will appear after Scan / Preview")
        self.axes.set_xlabel("Projected X (meters)")
        self.axes.set_ylabel("Projected Y (meters)")
        self.axes.grid(True, linewidth=0.3, alpha=0.35)
        self.figure.tight_layout()

    def _write_status(self, text: str) -> None:
        self._details_text = text
        self.details_button.configure(state="normal" if text.strip() else "disabled")

    def _show_details(self) -> None:
        if not self._details_text.strip():
            messagebox.showinfo("Boundary Details", "No preview or export details yet.")
            return

        detail_window = tk.Toplevel(self.root)
        detail_window.title("Boundary Details")
        detail_window.minsize(640, 420)
        detail_window.transient(self.root)

        detail_window.columnconfigure(0, weight=1)
        detail_window.rowconfigure(0, weight=1)

        text_frame = ttk.Frame(detail_window, padding=10)
        text_frame.grid(row=0, column=0, sticky="nsew")
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)

        details_text = tk.Text(text_frame, wrap="word", height=18)
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

    def _set_busy(self, busy: bool, status: str) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.scan_button.configure(state=state)
        self.export_button.configure(state=state)
        if busy:
            self.outline_mode_combo.configure(state="disabled")
        else:
            self._update_outline_mode_state()
        self.status_var.set(status)

    def _invalidate_cache(self) -> None:
        self._cached_result = None
        self._cached_settings = None

    def _set_input_path(self, input_path: Path) -> None:
        self.parent_var.set(str(input_path))
        self._set_output_path(self._default_output_path(input_path))
        self._update_outline_mode_state()
        self._invalidate_cache()

    def _selected_outline_mode(self, input_path: Path) -> str:
        if input_path.is_file() and input_path.suffix.lower() == ".kmz":
            return OUTLINE_MODE_SOURCE_POLYGON
        label = self.outline_mode_var.get().strip() or "Auto"
        if label not in OUTLINE_MODE_LABELS:
            raise BoundaryError("Choose a valid outline mode.")
        return OUTLINE_MODE_LABELS[label]

    @staticmethod
    def _ready_status(result: BoundaryResult, base_status: str) -> str:
        if result.metadata.fallback_reason:
            return f"{base_status} Auto fallback used."
        return base_status

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
    ) -> tuple[str, float, int, float, str, str]:
        return (
            str(Path(input_path).resolve()).lower(),
            float(buffer_ft),
            int(section_count),
            float(overlap_ft),
            shape_label.strip(),
            outline_mode,
        )

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
    app = BoundaryKmzApp(root)
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
