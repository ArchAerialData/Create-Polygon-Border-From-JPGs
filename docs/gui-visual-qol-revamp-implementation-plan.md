# GUI Visual and Quality-of-Life Revamp Implementation Plan

Plan date: 2026-07-23

Repository: `Create-Polygon-Border-From-JPGs`

Branch audited: `Testing-New-Methods` at `38fd82b`

Plan scope: GUI presentation, window placement, and GUI-only quality-of-life behavior

Required planning guide: `agent_prompt_templates/extremely-detailed-planning/detailed-planning-requirements.md`

## 1. Executive summary

### 1.1 Outcome

Revamp the existing Tkinter GUI into a dark, blue-accented, preview-first, single-page workspace without changing any boundary-generation, geometry, sectioning, KML/KMZ parsing, cache-key/export-reuse contract, or export logic.

The implementation will:

- Keep the current Tkinter/ttk, Matplotlib TkAgg, and `tkinterdnd2` stack.
- Add no GUI framework, browser runtime, web assets, package manager, or runtime dependency.
- Reuse the AALLC template only for its visual vocabulary:
  - layered dark surfaces;
  - blue actions and focus states;
  - compact collapsed settings;
  - summary/status chips;
  - approximately 8 px corner treatment;
  - a permanently visible action region.
- Replace the vertically stacked, always-visible form with:
  - a compact top input strip after an input is selected;
  - a large preview canvas that owns nearly all remaining space;
  - an on-demand settings drawer over the preview;
  - a collapsible overlay legend instead of a permanent 340 px side panel;
  - a fixed bottom action bar containing quick settings, status, `Update Preview`, and `Export KMZ`.
- Keep the initial drag/drop and browse experience prominent while no input is selected, then collapse it after selection without removing drag/drop or manual path editing.
- Fit and center the initial window inside the selected monitor's taskbar-safe work area, including monitors with negative coordinates and the 680 px-tall work area present on this machine.
- Add an in-window focus mode while retaining, restyling, and work-area-clamping the existing detachable Preview Inspector so its separate-window/multi-monitor capability is not lost.
- Add explicit “Preview out of date” feedback when any preview-affecting value changes; regeneration remains user-triggered and never runs on every keystroke.
- Preserve the existing worker thread, queue payloads, cache-key/export-reuse contract, preview/export generation profiles, overwrite, success-dialog, and output-path behavior. The only cache-lifecycle addition is an explicitly authorized GUI correctness fix: buffer edits invalidate the cached result just as the other preview-affecting controls already do.

### 1.2 Why this approach

The current application is already a local Tk utility with a working Matplotlib preview, native dialogs, drag/drop, and 99 passing tests. A framework migration would recreate those integrations and increase packaging and regression risk without improving the protected processing core.

The AALLC reference is a PyWebView/HTML/Bootstrap application (`../AALLC-GUI-Template/gui/app.py:9,40-59`; `../AALLC-GUI-Template/runtime/pyproject.toml:7-10`). Its visual ideas are useful, but its sidebar, API bridge, JavaScript controllers, Poetry runtime, vendor bundles, and hard-coded `1280x800` window are not compatible building blocks for this small single-page utility.

The selected design therefore treats the current GUI controller as the integration boundary and adds two narrowly scoped GUI support modules:

- `src/jpg_boundary_gui_theme.py` for centralized visual tokens and ttk/Tk styling.
- `src/jpg_boundary_gui_window.py` for pure/testable monitor work-area and window-geometry logic.

### 1.3 Non-negotiable protected contract

The following must remain semantically unchanged:

1. `generate_boundary_from_input(...)` receives the same values and generation profile it receives today.
2. `save_kmz(...)` remains the only KMZ-write path.
3. Preview generation uses `GENERATION_PROFILE_PREVIEW`.
4. Export generation uses `GENERATION_PROFILE_EXPORT`.
5. Export reuses a cached result only when the complete export settings key matches.
6. Folder, KML, and KMZ inputs retain their current validation and routing.
7. Vector simplification remains off by default in the GUI.
8. Existing output name/path synchronization remains intact.
9. Existing section count, overlap, label, and split-direction semantics remain intact.
10. No source file in the protected core/module list in Section 7 may be modified.

### 1.4 Fixed design decisions

These are resolved implementation requirements, not open questions.

| ID | Decision | Rationale |
| --- | --- | --- |
| FD-01 | Retain Tkinter/ttk, Matplotlib TkAgg, and `tkinterdnd2`. | Lowest-risk path; all three are already integrated and tested. |
| FD-02 | Add no third-party dependency and do not change `requirements_jpg_boundary_kmz.txt`. | Keeps the app portable and avoids DnD/root-class and packaging conflicts. |
| FD-03 | Use one canonical set of existing Tk variables for quick controls and the settings drawer. | Prevents the synchronization risk created by the Inspector's duplicate variables. |
| FD-04 | Use an explicit `Update Preview` action; do not auto-run generation on text changes. | Generation can be expensive and the current queue has no request-generation token. |
| FD-05 | Preserve the currently drawn preview after a settings edit, but show a text-and-color stale badge until preview succeeds. | Avoids a blank workspace while preventing an old preview from appearing current. |
| FD-06 | Clear the preview when the selected input itself changes. | Prevents geometry from the previous source being mistaken for the new input. |
| FD-07 | Add in-window focus mode and retain the detachable Preview Inspector in this revamp. Restyle and clamp the Inspector, but do not decommission it without a separately approved future scope. | Preserves every current GUI capability, including detaching the preview to another monitor, while providing the requested single-page workflow. |
| FD-08 | Keep `Update Preview` and `Export KMZ` mapped in a fixed bottom row in every shell state and at every client size at or above the adaptive minimum. | Directly satisfies the permanent-action requirement with a measurable lower bound. |
| FD-09 | Keep the main page scroll-free. Only the open settings drawer may gain an internal scrollbar when the monitor is too short to show all expanded content. | Preserves the requested single-page feel without making controls unreachable on the 680 px work area. |
| FD-10 | Initial placement uses the monitor under the pointer at launch, then a nearest/primary fallback; it uses the monitor work area, not raw screen bounds. | Best matches “this monitor,” double-click launch behavior, taskbars, and this machine's negative-coordinate display layout. |
| FD-11 | Do not change process DPI-awareness mode in this scope. | The current process is DPI-unaware; changing the coordinate model at the same time as layout/placement would add avoidable risk. |
| FD-12 | Use the AALLC palette as a starting point but replace low-contrast informational text with a lighter blue. | The template's `#3a7ca5` is only 3.82:1 on `#1a1a1a`; `#60a5fa` is 6.85:1. |
| FD-13 | Preserve browse, drop, pasted/typed path, details, output-folder, Save As, overwrite, and completion-dialog capabilities. | They are current user-visible functionality even when moved into compact or on-demand UI. |
| FD-14 | Treat the monitor containing the pointer at startup as the launch monitor on Windows, with deterministic nearest/primary and Tk fallbacks. | This is the chosen interpretation of “this monitor”; it is documented behavior, not a claim that every keyboard/terminal launch originates at the pointer. |
| FD-15 | Output name/path edits retain today's cache invalidation. They leave the preview current only when the effective shape label is unchanged; when default-label synchronization changes `shape_label_var`, mark the preview/key stale. | Output destination alone is not geometry, but the verified `_refresh_shape_label_default` cascade can change section labels shown in the preview/key. |
| FD-16 | A buffer edit calls the existing `_invalidate_cache` path and marks the preview stale without starting work. | This closes a verified GUI cache-lifecycle gap while leaving `_settings_key`, worker arguments, generation profiles, and export reuse decisions unchanged. |

### 1.5 Target single-page layout

The target layout is deliberately small in hierarchy and contains no sidebar or tabs.

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ JPG Boundary to KMZ   Input: …\Flight_01  [Change] [Key] [Settings] [Focus]│
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  [compact Matplotlib toolbar]                         ┌───────────────────┐ │
│                                                      │ Settings          │ │
│                        PREVIEW                       │ Geometry          │ │
│                                                      │ Sections          │ │
│  Empty state only:                                   │ Output            │ │
│  Drop folder/KML/KMZ                                 │                   │ │
│  [Browse Folder] [Browse KML/KMZ]                    │ [Close]           │ │
│                                                      └───────────────────┘ │
│                                              [collapsible Key overlay]       │
├─────────────────────────────────────────────────────────────────────────────┤
│ Ready / Preview out of date  Buffer [0] Shapes [1] Overlap [50]            │
│                      [Details] [Update Preview] [Export KMZ]                │
└─────────────────────────────────────────────────────────────────────────────┘
```

Responsive behavior:

- Wide/normal: the bottom bar is a single compact row.
- Narrow: re-grid the same status/quick-control and action groups into two fixed-height rows; actions occupy the second row and never enter a scroll container.
- Short: the preview shrinks, the action bar remains mapped, and only drawer content may scroll internally.
- Empty input: the centered drop/browse surface is visible over the preview.
- Selected input: the large drop surface disappears; a compact input strip remains a drop target and exposes change/browse/manual-edit access.
- Focus mode: hides nonessential title copy and maximizes the preview inside the same root window, but keeps the input affordance, settings/key/Inspector actions, status, quick controls, update, and export actions.

Measurable layout contract with Settings/Key overlays closed:

- “Supported size” means every Tk client size at or above the adaptive minimum returned by `calculate_adaptive_minimum`, through the selected monitor's work area, at 100%, 125%, 150%, and 200% Windows scaling.
- `Update Preview` and `Export KMZ` must be mapped, enabled/disabled according to current state, and completely inside client bounds throughout that supported range.
- At a `1440 x 741` client, the preview workspace must be at least `1360 x 520`.
- At a `1440 x 612` client, the preview workspace must be at least `1360 x 390`.
- At the nominal `960 x 600` adaptive minimum, the preview workspace must be at least `900 x 350`; if a smaller work area forces a lower adaptive minimum, action visibility and control reachability take precedence over this last preview-size target.
- Opening a drawer/key overlays the preview instead of reducing its allocated grid row/column, and closing it restores the entire visible preview without changing axes limits.

## 2. Current repository findings

### 2.1 Repository and entrypoint findings

| Finding | Direct evidence | Verification |
| --- | --- | --- |
| The application is one Tkinter/ttk class. | `src/jpg_boundary_kmz_gui.py:65-2263`, `BoundaryKmzApp` | Verified directly from code. |
| The root launcher only adds `src` to `sys.path` and calls `jpg_boundary_kmz_gui.main`. | `run_jpg_boundary_gui.py:1-14` | Verified directly from code. |
| The batch launcher calls the source launcher through whichever `python` is on `PATH`. | `run_jpg_boundary_gui.bat:1-3` | Verified directly from code. |
| Root creation prefers `TkinterDnD.Tk()` and safely falls back to `tk.Tk()`. | `src/jpg_boundary_kmz_gui.py:18-22,2272-2278`, `_create_root` | Verified directly from code. |
| There is no `pyproject.toml`, lockfile, packaging spec, GUI asset directory, or theme module in this repository. | Repository inventory from `rg --files` and root `Get-ChildItem -Force` | Verified directly from repository. |
| Runtime dependencies are a short text list and already include Matplotlib and `tkinterdnd2`. | `requirements_jpg_boundary_kmz.txt:1-8` | Verified directly from code. |
| VS Code points editor tooling at ArcGIS Pro's Python, but the batch launcher does not read that setting and invokes the first `python` on `PATH`. | `.vscode/settings.json:2`; `run_jpg_boundary_gui.bat:1-3` | Verified directly from code/config. |
| The audited PATH launcher/test interpreter is CPython 3.13.3 at `C:\Program Files\Python313\python.exe`. | `Get-Command python`; `python -B -c "import sys; print(sys.executable); print(sys.version.split()[0])"` | Verified directly from the 2026-07-23 runtime; Phase 0 must re-record it before implementation. |
| The README promises that launchers resolve files relative to the app and the app folder is portable. | `README_JPG_BOUNDARY_KMZ.md:9-32` | Verified directly from repository documentation and launcher code. |

Initial window sizing belongs in the GUI, not the launcher. Neither launcher contains window APIs or layout configuration.

Targeted runtime searches across `src`, both launcher layers, requirements, and README found no environment-variable/config loader, feature flag, CLI argument parser, HTTP/service framework, API payload, database/ORM, schema/migration, or JSON/YAML/TOML runtime configuration path. Repository inventory also found no CI pipeline, packaging build, or lockfile; only `requirements_jpg_boundary_kmz.txt` is dependency configuration. These absences were verified directly with `rg`, not inferred from filenames. The relevant integration surfaces are therefore the Tk event loop, worker queue, filesystem inputs/outputs, Matplotlib, optional `tkinterdnd2`, OS dialogs/folder opening, and the imported core functions already traced below.

### 2.2 Startup clipping: reproduced cause

The root currently sets only:

- title at `src/jpg_boundary_kmz_gui.py:68`;
- `root.minsize(980, 720)` at `:69`.

It never sets an initial geometry, monitor, work-area clamp, or position.

A read-only runtime probe on 2026-07-23 produced:

```text
Tk screen:        2048 x 864
Monitor work area: 2048 x 824
Requested client: 1213 x 1007
Actual client:    1213 x 1007
Tk scaling:       1.3330053300533005
```

The requested client height exceeds the taskbar-safe work area by 183 px before window decorations. A separate probe measured approximately 39 px of vertical non-client decoration, so the full window exceeds the work area by roughly 222 px. This directly explains the hidden bottom.

The machine exposes seven monitors:

- six work areas at 2048 x 824;
- one work area at 2560 x 680;
- several monitors with negative X and/or Y coordinates.

The fixed 720 px client minimum cannot fit inside the 680 px work area after title-bar decoration.

The only current monitor-related logic belongs to the separate preview window:

- Windows maximize attempt: `src/jpg_boundary_kmz_gui.py:1969-1974`, `_maximize_fullscreen_window`;
- fallback to raw `winfo_screenwidth/height` and `+0+0`: `:1976-1979`.

That fallback is primary-screen-oriented, does not reserve the taskbar, and mishandles negative-coordinate launch monitors.

Microsoft documents that `MONITORINFO.rcWork` is the taskbar-safe work rectangle and may contain negative virtual-screen coordinates. `GetCursorPos` returns the pointer in screen coordinates, and `MonitorFromPoint` can select the containing/nearest monitor rather than assuming the primary display:

- [Microsoft `GetCursorPos`](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getcursorpos)
- [Microsoft `MonitorFromPoint`](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-monitorfrompoint)
- [Microsoft `MonitorFromWindow`](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-monitorfromwindow)
- [Microsoft `MONITORINFO` and `rcWork`](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-monitorinfo)
- [Microsoft `GetWindowRect`](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getwindowrect)

Tk's official `wm geometry` documentation defines a `+x` prefix as a left-edge offset and a `-x` prefix as a right-edge offset. Therefore an absolute negative virtual-screen coordinate must be placed in the `+x` field as `+-N`; this plan also verified that behavior with a local Tk probe:

- [Tk 8.6 `wm geometry` manual](https://www.tcl-lang.org/man/tcl8.6/TkCmd/wm.htm)
- [Python `tkinter.Wm.wm_geometry`](https://docs.python.org/3/library/tkinter.html#tkinter.Wm.wm_geometry)

Tk geometry width/height are client requests while taskbar safety concerns the decorated outer window. Microsoft documents that `GetWindowRect` returns outer screen-coordinate bounds, is DPI-virtualized, and includes invisible resize borders. That makes it the conservative final containment check in this DPI-unaware process.

### 2.3 Why controls consume the current window

`BoundaryKmzApp._build_ui` is one fixed vertical stack at `src/jpg_boundary_kmz_gui.py:145-465`.

Always-visible elements are:

1. Input path and two browse buttons (`:154-186`).
2. Large drag/drop panel (`:378-399`).
3. Buffer (`:188-200`).
4. Outline mode (`:202-217`).
5. Output file name (`:219-238`).
6. Output path and output buttons (`:240-272`).
7. Vector simplification (`:274-287`).
8. Two-row Sections form (`:289-376`).
9. Action/status row (`:401-431`).
10. Preview (`:433-465`).

Only the preview grid row expands (`root_frame.rowconfigure(9, weight=1)` at `:152`).

The preview also permanently reserves a nominal 340 px key panel:

- constants: `PREVIEW_KEY_PANEL_WIDTH` and `PREVIEW_KEY_WRAP_LENGTH` at `:55-56`;
- key frame/canvas/scrollbar: `:467-507`;
- placement beside the canvas: `:445-450`.

Runtime measurements found:

- at the largest current client height that fits the primary work area, the controls consume about 451 px and the preview canvas is about 800 x 277;
- at the current minimum, the canvas is about 567 x 213;
- the key consumes about 377 px including its scrollbar/padding.

This verifies the reported space problem directly.

### 2.4 Current canonical GUI state

The correct reusable state model already exists:

- input: `parent_var`;
- buffer: `buffer_var`;
- output name/path: `output_name_var`, `output_var`;
- outline: `outline_mode_var`;
- sections: `section_count_var`, `overlap_var`, `shape_label_var`, `split_direction_var`, `split_direction_degrees_var`;
- vector simplification: `simplify_vector_var`;
- status: `status_var`.

Evidence: `src/jpg_boundary_kmz_gui.py:71-87`.

Traces are registered at `:131-140`. Most preview-affecting changes invalidate the cache at `:907-930`, but `buffer_var` currently has no trace. That is a verified GUI-state gap:

- changing only buffer can leave `_cached_result` available to the separate Inspector;
- export remains safe because `_export_clicked` compares the complete settings key at `:1062-1075`;
- the displayed preview remains visually unchanged and has no stale-state message.

The revamp will add a buffer trace and explicit stale/clean display state without changing the export cache contract.

### 2.5 Existing control-state contracts

These behaviors must be retained:

| Contract | Direct evidence |
| --- | --- |
| Sections-dependent fields enable only when count is greater than one. | `src/jpg_boundary_kmz_gui.py:932-947`, `_update_section_control_state` |
| Custom degrees enable only for `Custom`. | `:944-947`, `_selected_split_direction` at `:2100-2136` |
| Vector files disable JPG outline selection. | `:949-960`, `_update_outline_mode_state` |
| Vector simplification is available only for KML/KMZ input and defaults false. | `:82,949-960,1377-1382` |
| Output name edits preserve the selected folder and update `.kmz` path. | `:858-905` |
| Shape label defaults follow output naming until explicitly edited. | `:968-977` |
| Input selection resets the default output path. | `:2082-2086` |
| Relative output paths resolve from `APP_ROOT`, not the shell directory. | `:2170-2174` |

Moving controls does not authorize changing any of these rules.

### 2.6 Input, browse, and drag/drop contracts

The drop implementation is optional and widget-specific:

- `_register_drop_target`: `src/jpg_boundary_kmz_gui.py:735-748`;
- `_handle_folder_drop`: `:756-776`;
- folder browse: `_browse_parent` at `:778-783`;
- KML/KMZ browse: `_browse_kmz` at `:784-805`;
- Tcl list parsing, quote stripping, and `file://` normalization: `:2159-2195`.

A drop accepts an existing directory or existing `.kml`/`.kmz`, uses the first valid item, updates input/output, and does not auto-run preview.

Because bindings are applied to `self.drop_label`, the new large empty-state target and compact selected-input target must both be registered explicitly. Hiding or recreating the large target must not remove the compact target's DnD bindings.

### 2.7 Preview and interaction contracts

The renderer is already separated from core processing:

- main rendering: `_draw_preview` and `_draw_preview_on_axes`, `src/jpg_boundary_kmz_gui.py:1395-1490`;
- key rendering: `_update_preview_key`, `:1492-1536`;
- fit and result bounds: `:1546-1592`;
- preview decimation: `_preview_polygon_xy`, `:1595-1608`;
- empty state: `:1610-1650`.

Interaction commitments:

- Matplotlib toolbar exists (`:451-458`);
- four callbacks are registered (`:521-554`);
- wheel zoom is cursor-centered (`:556-596`);
- direct left-drag pans (`:598-688`);
- direct pan defers to active toolbar modes (`:698-733`);
- redraw resets to full result bounds (`:1483-1488`).

The current repository's prior preview decision record also treats view state as transient and outside cache persistence:

- `docs/preview-zoom-and-pan/preview-zoom-and-pan-open-questions.md:111-131`.

The layout may reparent or overlay the canvas/toolbar, but these behaviors cannot regress.

### 2.8 Existing Preview Inspector: useful behavior, problematic structure

`_open_fullscreen_preview` at `src/jpg_boundary_kmz_gui.py:1652-1826` creates a separate maximized `Toplevel`.

It duplicates:

- five new StringVars at `:1671-1691`;
- section count, overlap, label, direction, degrees, Apply Preview, and Close at `:1693-1769`;
- a second Figure, canvas, key, toolbar, and four event bindings at `:1789-1820`;
- synchronization back into canonical state at `_apply_fullscreen_preview`, `:1828-1888`;
- lifecycle cleanup at `:1983-2018`.

It omits buffer, outline mode, output name/path, vector simplification, input change/drop, details, and export.

The implementation will preserve the Inspector as a detachable secondary preview, including its independent section-edit/apply workflow and its ability to occupy another monitor. It will be restyled and opened/clamped through the new work-area helper. In-window focus mode is an additional single-page convenience, not a replacement. The Inspector's duplicate state/canvas is a known maintenance cost, but removing it is explicitly outside this non-regression revamp.

### 2.9 Backend and thread boundary

The GUI imports a narrow set from the core at `src/jpg_boundary_kmz_gui.py:24-33`:

- `BoundaryError`;
- `BoundaryResult`;
- generation-profile constants;
- `MAX_SECTION_COUNT`;
- `format_summary`;
- `generate_boundary_from_input`;
- `save_kmz`.

The protected flow is:

```text
GUI variables
  -> _read_inputs
  -> _scan_clicked / _export_clicked
  -> daemon worker
  -> generate_boundary_from_input
  -> queue.Queue
  -> _drain_queue on Tk main thread
  -> cache/status/details/preview or save confirmation
```

Direct evidence:

- input validation/conversion: `_read_inputs`, `:1283-1393`;
- preview click/start: `:979-1035`;
- export validation/overwrite/cache decision: `:1037-1094`;
- core preview call: `:1108-1118`;
- core export call and save: `:1138-1149`;
- queue handling: `:1155-1218`;
- settings key: `:2198-2224`.

The core dispatch contract is in `src/jpg_boundary_kmz_core.py:355-400`, and `save_kmz` rejects preview-quality results at `:798-806`.

All Tk widget changes and Matplotlib draws must remain on the main thread. Workers must continue to call core functions and enqueue results only.

### 2.10 Existing test baseline

Read-only validation on 2026-07-23:

```text
python -B -m unittest tests.test_gui_input
Ran 27 tests — OK

python -B -m unittest discover -s tests
Ran 99 tests — OK
```

Current GUI coverage:

- parsing, settings keys, and control state: `tests/test_gui_input.py:34-209`;
- preview layout and interactions: `:211-378`;
- Inspector lifecycle and Apply Preview synchronization: `:380-545`;
- polyline automatic buffer synchronization: `:546-571`.

The exact-grid assertion at `tests/test_gui_input.py:220-233` must be replaced with behavior-based shell/action/preview assertions because the requested redesign intentionally changes grid positions.

### 2.11 Reference-template findings

Selective reuse is supported by direct evidence:

| Reusable concept | Template evidence | Adaptation |
| --- | --- | --- |
| Dark surface and semantic color tokens | `../AALLC-GUI-Template/gui/static/css/docker-theme.css:2-20` | Copy values into Python token names, not CSS files. |
| System/Segoe UI font stack | `../AALLC-GUI-Template/gui/static/css/docker-theme.css:26-31` | Use Tk named fonts with system fallback. |
| 8 px cards and 10 px advanced panels | `../AALLC-GUI-Template/gui/static/css/docker-theme.css:324-330,501-506` | Use consistent rounded visual surfaces where Tk rendering supports them. |
| Compact collapsed settings and summary chips | `../AALLC-GUI-Template/gui/index.html:1692-1716`; `../AALLC-GUI-Template/gui/static/css/docker-theme.css:554-617,877-949` | Settings drawer plus compact quick controls and stale/clean chips. |
| Fixed/sticky actions | `../AALLC-GUI-Template/gui/index.html:1961-1969`; `../AALLC-GUI-Template/gui/static/css/docker-theme.css:2136-2156` | Non-expanding bottom grid row, not copied CSS. |
| Focus/disabled/modified states | `../AALLC-GUI-Template/gui/static/css/docker-theme.css:539-545,913-949` | ttk style maps plus text labels, not color alone. |

Explicit non-reuse:

- `pywebview`, `LocalTemplateAPI`, `api_bridge.js`;
- HTML/JS/CSS frontend;
- Bootstrap, Font Awesome, Flatpickr, DOMPurify, vendor assets;
- Poetry runtime and `launch.ps1`;
- sidebar or multi-page navigation;
- AALLC logos/branding;
- template drag/drop bridge;
- fixtures, synthetic backend, browser tests, report/email/KMZ workbench controllers;
- animated gradients.

The template does not solve window placement:

- `../AALLC-GUI-Template/gui/app.py:43-50` hard-codes 1280 x 800;
- `../AALLC-GUI-Template/config/launch_settings.json:2-6` repeats that size but is not referenced by runtime code.

### 2.12 Styling implementation evidence

Python's official ttk documentation states that widget behavior and appearance are separated and that `ttk.Style.configure`, `map`, `layout`, `element_create`, and theme methods are the supported styling mechanisms:

- [Python `tkinter.ttk` documentation](https://docs.python.org/3.13/library/tkinter.ttk.html)

Matplotlib's supported Tk embedding pattern uses the same `FigureCanvasTkAgg` and `NavigationToolbar2Tk(..., pack_toolbar=False)` already present:

- [Matplotlib “Embed in Tk”](https://matplotlib.org/stable/gallery/user_interfaces/embedding_in_tk_sgskip.html)

The revamp will style the existing embedding rather than replace it.

On Windows, the title bar is OS-owned rather than a ttk widget. Microsoft exposes non-client styling through `DwmSetWindowAttribute`, including dark-mode/caption/text attributes. The plan uses these attributes as a best-effort visual enhancement with a no-op fallback; OS-owned file pickers and message boxes remain system-themed:

- [Microsoft `DwmSetWindowAttribute`](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/nf-dwmapi-dwmsetwindowattribute)
- [Microsoft `DWMWINDOWATTRIBUTE`](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute)

### 2.13 Target palette and contrast

| Token | Value | Use | Verified contrast |
| --- | --- | --- | --- |
| `BACKGROUND` | `#1a1a1a` | Root and preview shell | — |
| `BACKGROUND_DEEP` | `#0f0f0f` | Preview canvas and deepest surfaces | — |
| `SURFACE` | `#2a2a2a` | Drawer, action bar, cards | — |
| `SURFACE_RAISED` | `#303030` | Inputs/hovered surfaces | — |
| `BORDER` | `#404040` | Separators and idle input borders | — |
| `PRIMARY` | `#314dec` | Primary buttons and selected states | White text: 6.17:1 |
| `FOCUS_INFO` | `#60a5fa` | Focus rings, links, informational text | On background: 6.85:1 |
| `TEXT` | `#ffffff` | Primary text | On surface: 14.35:1 |
| `TEXT_SECONDARY` | `#b3b3b3` | Supporting text | On surface: 6.85:1 |
| `TEXT_MUTED` | `#858585` | Nonessential muted text | On background: 4.72:1 |
| `SUCCESS` | `#10b981` | Success state | Text state also includes wording/icon. |
| `WARNING` | `#f59e0b` | Stale/warning state | Text state also includes wording/icon. |
| `ERROR` | `#ef4444` | Error state | Text state also includes wording/icon. |

Contrast was calculated locally from the template values. Normal text must meet at least 4.5:1 per [WCAG 2.2, Success Criterion 1.4.3](https://www.w3.org/TR/WCAG22/#contrast-minimum). The template's `#3a7ca5` remains suitable for decoration but will not be used for small informational text on `#1a1a1a`.

## 3. Exact impacted files and symbols

### 3.1 Planned architecture

```text
run_jpg_boundary_gui.py / run_jpg_boundary_gui.bat        (unchanged)
                         |
                         v
src/jpg_boundary_kmz_gui.py
  - existing state and callbacks
  - preview-first shell builders
  - drawer/key/focus/empty-state coordination
  - explicit stale/clean GUI state
  - unchanged core invocation contract
       |                         |
       v                         v
src/jpg_boundary_gui_theme.py   src/jpg_boundary_gui_window.py
  - tokens/styles                 - WorkArea / WindowGeometry
  - Tk/ttk/Matplotlib surfaces    - Windows rcWork provider
  - rounded-style fallback        - platform fallback and clamp
       |
       v
src/jpg_boundary_kmz_core.py and geometry modules          (unchanged)
```

### 3.2 `src/jpg_boundary_gui_window.py` — new

Required symbols:

- `@dataclass(frozen=True) WorkArea`
  - `left`, `top`, `right`, `bottom`;
  - `__post_init__` raises `ValueError` when `right <= left` or `bottom <= top`;
  - validated `width` and `height` properties;
  - provider functions catch invalid OS rectangles and continue to the next fallback rather than exposing the exception at startup.
- `@dataclass(frozen=True) WindowGeometry`
  - client `width`, `height` plus outer-border origin `x`, `y`;
  - `to_tk_geometry()` returns the exact absolute-position form `f"{width}x{height}+{x}+{y}"`; negative coordinates therefore serialize as `+-N`, not Tk's edge-relative `-N`.
- `@dataclass(frozen=True) OuterWindowBounds`
  - `left`, `top`, `right`, `bottom`, width/height, and `is_within(work_area)`.
- `@dataclass(frozen=True) WindowFitResult`
  - final `WindowGeometry`, optional measured `OuterWindowBounds`, `contained`, `used_reserve_fallback`, and optional warning text;
  - lets startup remain non-throwing when the compositor does not converge while tests/manual validation can still fail on a false containment result.
- `get_launch_work_area(root: tk.Misc) -> WorkArea`
  - Windows provider using `ctypes` and the pointer monitor;
  - root-monitor then primary-monitor fallback;
  - final conservative Tk primary-screen fallback at origin `(0, 0)`.
- `get_window_work_area(window: tk.Misc) -> WorkArea`
  - query the monitor containing/nearest the supplied parent/child window;
  - use this for child dialogs and the retained Inspector, never the launch pointer.
- `_get_windows_cursor_work_area() -> WorkArea | None`
  - use `GetCursorPos`, `MonitorFromPoint(..., MONITOR_DEFAULTTONEAREST)`, and `GetMonitorInfoW`;
  - return `None` on any API/structure failure.
- `_get_windows_window_work_area(window: tk.Misc) -> WorkArea | None`
  - use `winfo_id`, `MonitorFromWindow(..., MONITOR_DEFAULTTONEAREST)`, and `GetMonitorInfoW`;
  - return `None` on invalid/unavailable handles.
- `_get_windows_primary_work_area() -> WorkArea | None`
  - use a primary-monitor Win32 fallback and `GetMonitorInfoW`;
  - no imported third-party package;
  - return `None` on any API/structure failure.
- `_get_tk_primary_fallback(root: tk.Misc) -> WorkArea`
  - return `(0, 0, winfo_screenwidth(), winfo_screenheight())`;
  - never use `winfo_vroot*` as a placement rectangle because the virtual-desktop union can span gaps and multiple monitors.
- `_get_windows_outer_bounds(window: tk.Misc) -> OuterWindowBounds | None`
  - resolve the decorated wrapper HWND and call `GetWindowRect`;
  - return DPI-virtualized outer bounds including invisible resize borders.
- `get_toplevel_hwnd(window: tk.Misc) -> int | None`
  - after `update_idletasks()`, parse `window.frame()` with `int(value, 0)` as Tk's decorated outer-frame HWND;
  - if `frame()` is unavailable/invalid, call pointer-width-safe `GetParent(window.winfo_id())`; use the content HWND only when no outer wrapper is returned;
  - share this helper with outer-bounds measurement and native-chrome styling.
- `_fit_realized_window_to_work_area(window, work_area, desired_client_geometry) -> WindowFitResult`
  - apply provisional client geometry while withdrawn, call `update_idletasks()`, measure outer bounds, translate/resize the client request, and remeasure;
  - use at most three bounded measured passes;
  - if measurement is unavailable or does not converge, apply one conservative geometry calculated with a `32 x 64` total frame reserve, make one final best-effort measurement, and return its status without raising;
  - live containment failure fails the implementation phase/manual release gate, not the user's launcher.

Win32 interop contract:

- define exact `ctypes` `POINT`, `RECT`, and `MONITORINFO` structures and initialize `MONITORINFO.cbSize = ctypes.sizeof(MONITORINFO)`;
- assign `argtypes` and `restype` for `GetCursorPos`, `MonitorFromPoint`, `MonitorFromWindow`, and `GetMonitorInfoW`;
- assign pointer-width-safe prototypes for `GetWindowRect` and `GetParent`;
- represent `HWND`/`HMONITOR` with pointer-width-safe `wintypes.HANDLE`/`wintypes.HWND`, never default `c_int`;
- provider-success tests use a fake monitor handle greater than `0xFFFFFFFF` so 64-bit truncation is detected.
- `calculate_initial_geometry(work_area, ideal_width=1440, ideal_height=900, max_fraction=0.90) -> WindowGeometry`
  - pure, deterministic, unit tested.
- `calculate_adaptive_minimum(work_area, base_width=960, base_height=600) -> tuple[int, int]`
  - never returns a minimum larger than the planned initial client dimensions.
- `apply_initial_geometry(root, work_area=None) -> WindowFitResult`
  - calculates provisional client size, then calls the realized-window fitting helper while the root is withdrawn;
  - sets an adaptive minimum no larger than the final fitted client;
  - returns final geometry, measured containment status, fallback usage, and diagnostic warning for tests/startup status.
- `clamp_child_geometry(parent, child, work_area=None) -> WindowFitResult`
  - centers child relative to parent;
  - resolves the parent/child monitor through `get_window_work_area`, not the launch pointer;
  - uses the same realized outer-bounds fitting helper before an app-owned Toplevel is shown;
  - clamps the complete decorated child rectangle inside that monitor's work area.

Fixed geometry algorithm:

1. Query the pointer with `GetCursorPos`, select its containing/nearest monitor with `MonitorFromPoint`, and read that monitor's `rcWork` on Windows.
2. If the pointer query fails, use `MonitorFromWindow` for the withdrawn root; then use the Win32 primary monitor; if Win32 calls fail, use Tk's primary `winfo_screenwidth/height` at `(0, 0)`.
3. Never center against `winfo_vroot*`: this machine reports origin `(-2562,-1080)` and size `7175 x 2880`, i.e. bounds `(-2562,-1080)-(4613,1800)`, which include inter-monitor gaps and can center a window across no single physical work area.
4. Use 90% of work-area width/height as the provisional maximum client target.
5. Use the smaller of:
   - design ideal 1440 x 900;
   - 90% work area.
6. Apply the provisional geometry while withdrawn and realize layout with `update_idletasks()`.
7. Resolve the decorated wrapper HWND and measure the outer rectangle with `GetWindowRect`.
8. Center the measured outer width/height within `rcWork`; if outer dimensions exceed the work area, reduce the requested client dimension by the exact overflow, apply, and remeasure. Repeat for no more than three measured passes.
9. Set adaptive minimum to at most 960 x 600 and never larger than the final fitted client.
10. Serialize absolute placement as `f"{width}x{height}+{x}+{y}"`. Example: provisional `x=-999` becomes `...+-999...`; do not use `{x:+d}` or `...-999...`.
11. Before deiconify, record whether the final measured outer bounds are wholly inside `rcWork`. If measurement is unavailable or three passes do not converge, apply the conservative reserved geometry once and return a nonfatal warning/result flag. `main()` still opens the app and surfaces the concise warning in status text; the live containment test/manual release gate must fail until the supported environment produces contained bounds.
12. Do not persist coordinates or assume the same monitor topology next launch.

Expected examples:

| Work area | Provisional client size | Final requirement |
| --- | --- | --- |
| `(0,0)-(2048,824)` | `1440 x 741` | Measured outer frame is centered and wholly contained. |
| `(-1559,1080)-(1001,1760)` | `1440 x 612` | With observed `16 x 39` total non-client extent, final outer size is `1456 x 651` and a centered client request is approximately `1440x612+-1007+1094`; final `GetWindowRect.bottom <= 1760`. |
| `(2560,13)-(4608,837)` | `1440 x 741` | Measured outer frame is centered in the positive-offset `rcWork`. |

No DPI-awareness API will be called in this phase. All coordinates stay within the process's current virtualized coordinate model.

### 3.3 `src/jpg_boundary_gui_theme.py` — new

Required symbols:

- `@dataclass(frozen=True) GuiPalette`
  - token values from Section 2.13.
- `PALETTE`
  - the single exported palette instance.
- `apply_gui_theme(root: tk.Misc) -> ttk.Style`
  - select a cross-platform stylable parent theme such as `clam`;
  - define named styles rather than modifying widgets ad hoc;
  - configure normal, hover, pressed, focused, selected, readonly, and disabled maps.
- `style_matplotlib_figure(figure, axes=None) -> None`
  - dark figure/axes backgrounds;
  - readable empty text;
  - no change to geometry lines or bounds.
- `style_matplotlib_axes(figure, axes) -> None`
  - reapply axes/figure face colors and text defaults immediately after every `axes.clear()`;
  - called from both result and empty-state draw paths for the main preview and retained Inspector.
- `style_tk_text(text_widget) -> None`
  - details text colors, selection color, insertion cursor, borders.
- `style_tk_canvas(canvas, surface=...) -> None`
  - key/drop/overlay canvas backgrounds and highlight behavior.
- `install_rounded_button_elements(style, root) -> bool`
  - image-backed ttk button backgrounds with approximately 8 px visual corners while retaining `ttk.Button` keyboard semantics;
  - return false and fall back to flat padded ttk styles if unsupported at runtime;
  - retain image references for the life of the root.
- `apply_windows_native_chrome(root: tk.Misc) -> bool`
  - use `get_toplevel_hwnd` from the window module so DWM targets Tk's decorated wrapper rather than the inner content HWND;
  - after the root/Toplevel HWND exists, call `DwmSetWindowAttribute` in this fixed order: `DWMWA_CAPTION_COLOR` (35, `BACKGROUND` as `COLORREF`), `DWMWA_TEXT_COLOR` (36, `TEXT`), then `DWMWA_USE_IMMERSIVE_DARK_MODE` (20, true);
  - do not use undocumented attribute 19; Microsoft documents 20/35/36 for supported Windows 11 builds;
  - return true if at least one supported call returns `S_OK`; return false without raising on non-Windows, unsupported attributes, invalid handles, missing DWM, or failed HRESULTs;
  - apply to the root and custom app-owned Toplevels only;
  - set exact `DwmSetWindowAttribute` `argtypes`/`restype`, including pointer-width-safe `HWND`, `DWORD`, value pointer, size, and `HRESULT`.

Required style names:

- `App.TFrame`
- `Surface.TFrame`
- `Raised.TFrame`
- `ActionBar.TFrame`
- `Drawer.TFrame`
- `App.TLabel`
- `Secondary.TLabel`
- `Muted.TLabel`
- `Title.TLabel`
- `Status.TLabel`
- `Stale.Status.TLabel`
- `Success.Status.TLabel`
- `App.TEntry`
- `App.TCombobox`
- `App.TSpinbox`
- `App.TCheckbutton`
- `Secondary.TButton`
- `Primary.TButton`
- `Success.TButton`
- `Ghost.TButton`
- `Toolbar.TFrame`
- `App.Vertical.TScrollbar`
- `Busy.Horizontal.TProgressbar`

Visual requirements:

- approximately 8 px corner treatment on action buttons/surfaces where the Tk theme engine supports it;
- no custom widget may remove keyboard focus, `.invoke()`, disabled state, or command semantics;
- when image-backed rounding is unavailable, the fallback is a flat padded ttk button with high-contrast focus border, not a new GUI dependency;
- style the ttk Combobox popdown Listbox through root-scoped Tk option-database colors so opening a combo does not reveal a default white list;
- app-owned Details, export-success, Settings, Key, and Inspector surfaces are part of the dark-theme contract;
- native file dialogs and native message boxes are explicitly exempt because the OS owns their content; they must remain correctly parented and functional;
- status meaning is never color-only;
- no required animation.

### 3.4 `src/jpg_boundary_kmz_gui.py` — modified GUI composition

#### 3.4.1 Initialization changes

Modify `BoundaryKmzApp.__init__` at current `:66-143` to:

- apply the centralized theme before building widgets;
- initialize shell-only state:
  - `_settings_drawer_open`;
  - `_legend_open`;
  - `_focus_mode`;
  - `_preview_stale`;
  - `_has_selected_input`;
  - `_last_displayed_result`;
  - `_all_mutation_widgets`;
  - `_section_multiple_widgets`;
  - `_custom_direction_widgets`;
  - `_vector_only_widgets`;
  - `_folder_only_widgets`;
  - `_busy_action_widgets`;
  - `_drop_targets`;
- keep all existing canonical Tk variables and default values;
- add `buffer_var.trace_add("write", ...)`;
- add only GUI state traces; do not change `_settings_key`;
- remove the fixed `root.minsize(980, 720)` from `BoundaryKmzApp.__init__`;
- do not withdraw, deiconify, or otherwise change window state inside `BoundaryKmzApp.__init__`, so test/caller-owned withdrawn roots remain withdrawn;
- stage startup only in `jpg_boundary_kmz_gui.main`: create root, `withdraw()`, capture launch work area, construct `BoundaryKmzApp`, call `update_idletasks()`, apply the measured/retried or conservative-reserve geometry and adaptive minimum, surface any nonfatal fit warning in the existing status area, apply best-effort native chrome, then `deiconify()` and enter `mainloop()`;
- leave both launcher files and `_create_root` unchanged;
- bind shortcuts after widget creation;
- preserve `root.after(100, self._drain_queue)`.

#### 3.4.2 Replace monolithic layout with private shell builders

Refactor `_build_ui` at current `:145-465` into private methods within the same class:

- `_build_app_shell`
- `_build_top_input_strip`
- `_build_preview_workspace`
- `_build_empty_input_overlay`
- `_build_settings_drawer`
- `_build_geometry_settings`
- `_build_section_settings`
- `_build_output_settings`
- `_build_preview_key_overlay`
- `_build_action_bar`
- `_register_keyboard_shortcuts`

This is an internal GUI refactor only. Existing variables and callback functions remain the source of state and behavior.

#### 3.4.3 Top input strip

Empty state:

- show a centered rounded drop surface inside the preview;
- retain separate `Browse Folder...` and `Browse KML/KMZ...` actions;
- retain a manually editable path entry in the drawer;
- make browse available even when DnD is absent.

Selected state:

- hide the large drop surface with `place_forget`/`grid_remove`, not destruction;
- show an ellipsized path summary;
- expose `Change Input`, `Settings`, `Key`, and `Focus Preview`;
- keep the compact strip registered for folder/KML/KMZ drops;
- clicking path/edit opens the drawer to the input/geometry group;
- preserve typed/pasted-path access.

Exact transition rule:

- `_has_selected_input` is presentation state equal to `bool(parent_var.get().strip())`; it does not pre-validate the filesystem path or alter `_read_inputs`;
- `_on_input_changed` calls `_refresh_input_shell_state` after its existing outline/cache work;
- any non-empty browsed, dropped, typed, or pasted value selects the compact state and remains editable in the drawer;
- clearing the entry returns to the large empty drop/browse surface;
- an invalid non-empty value stays in compact/editable state and receives the existing validation error only when the user requests work.

DnD failure:

- use the same current browse fallback;
- style warning through theme tokens;
- do not disable browse.

DnD refactor boundary:

- change `_register_drop_target` to accept a target widget and register both the empty-state surface and compact selected-input hit area;
- change drag-enter/leave feedback to style `event.widget` or its explicitly mapped feedback surface, never hard-code `self.drop_label`;
- keep `_handle_folder_drop` parsing/first-valid-input semantics unchanged apart from the explicit busy guard;
- test real registration/binding calls and visual enter/leave feedback for both targets, not merely membership in `_drop_targets`.

#### 3.4.4 Preview workspace

- The Matplotlib canvas is the only expanding grid cell.
- Retain one persistent main Figure/canvas/toolbar and the existing four custom main interaction callbacks; the detachable Inspector retains its intentional independent set.
- Move the toolbar to a compact overlay/edge region; do not recreate it when drawers toggle.
- Apply dark styling to:
  - Figure and axes;
  - empty-state text;
  - Tk canvas wrapper;
  - toolbar frame/buttons/status background;
  - key canvases/swatches.
- Because `axes.clear()` resets axes presentation (`_draw_preview_on_axes` and `_draw_empty_preview_on_axes` currently clear at GUI `:1413,1636`), call `style_matplotlib_axes(...)` immediately after each clear before adding artists/text.
- Preserve all current plotted geometry, fit, equal-aspect, decimation, and event handling.
- Keep `axes.set_axis_off()` and hidden coordinate message.
- Do not add basemaps, network access, or new preview data.

The current hard-coded plot colors may be adjusted only for dark-background visibility. Section index-to-color mapping and labels must stay stable during a session, and color must not convey section identity without its text key.

#### 3.4.5 Legend/key overlay

- Replace the permanent 340 px column with a top/right overlay.
- Closed by default after launch.
- `Key` toggle is always available.
- The overlay remains vertically scrollable for up to `MAX_SECTION_COUNT` entries.
- Settings and Key are mutually exclusive: opening Key closes Settings first, and opening Settings closes Key first.
- Key scrolling binds `<MouseWheel>` only to the key canvas/content while the pointer is inside it; never use `bind_all`.
- Toggling the key must not resize/reset/recreate the preview or register duplicate callbacks.
- The key updates through the existing `_update_preview_key` data.
- Focus mode retains the key toggle.

#### 3.4.6 Settings drawer

The drawer overlays the right side of the preview and never changes the root page hierarchy.

Groups:

1. Input and geometry:
   - editable input path;
   - Browse Folder;
   - Browse KML/KMZ;
   - Buffer;
   - Outline mode;
   - vector simplification.
2. Sections:
   - number of shapes;
   - overlap;
   - shape label;
   - split direction;
   - custom degrees.
3. Output:
   - output file name;
   - output KMZ path;
   - Save As;
   - View Output Folder.

Rules:

- use existing variables directly; do not mirror/copy them;
- at most one group is expanded at a time at every size, while all groups may be collapsed;
- group summaries remain visible when collapsed;
- section and vector enable/disable rules use existing update methods;
- invalid values are not silently corrected before `_read_inputs`;
- drawer closes via button or Escape;
- opening the drawer first closes Key, so there is exactly one top/right overlay and no ambiguous z-order;
- opening/closing does not regenerate preview;
- an internal scrollbar appears only when content cannot fit; the main page never scrolls.
- drawer wheel handling is scoped to the drawer canvas/content while the pointer is inside; never use `bind_all`, and opening/closing the drawer must not intercept Matplotlib wheel zoom over the preview.

#### 3.4.7 Fixed action bar

Always mapped:

- concise status/stale indicator;
- Buffer quick entry;
- Shapes quick spinbox;
- Overlap quick entry when shapes > 1;
- Details;
- Update Preview;
- Export KMZ.

All quick controls bind to the canonical variables used by the drawer.

Responsive mechanism:

- define `ACTION_BAR_MIN_BREAKPOINT = 1120` in Tk client pixels;
- after styles/fonts exist and `update_idletasks()` has populated requested sizes, calculate `_action_bar_breakpoint = max(ACTION_BAR_MIN_BREAKPOINT, left_group.winfo_reqwidth() + right_group.winfo_reqwidth() + 32)`; this lets 150–200% scaling remain in the safe two-row layout when controls need it;
- bind a root-only `<Configure>` handler `_on_root_configure`;
- ignore child-widget configure events; on each root-only configure event, recalculate the requested-width breakpoint from the current requested group widths, then re-grid only when the resulting one-row/two-row mode differs from the active mode;
- at width >= the computed breakpoint, grid status/quick controls left and actions right in one row;
- below the computed breakpoint, re-grid the same widget groups into two fixed rows with actions fully visible on the second row;
- never destroy/recreate controls, variables, Matplotlib objects, or callbacks during a breakpoint change;
- Tk grid does not wrap automatically, so no implicit wrapping behavior is assumed.

Action requirements:

- `Update Preview` calls the existing `_scan_clicked`;
- `Export KMZ` calls the existing `_export_clicked`;
- `Details` calls `_show_details`;
- status text truncates/ellipsizes visually but the full summary remains in Details;
- busy state shows an indeterminate progress bar and disables mutable controls/actions except safe window/view toggles;
- success, warning/stale, error, and busy states have text plus color;
- actions remain inside client bounds for every size in the measurable supported range defined in Section 1.5.

#### 3.4.8 Stale-preview state

Add GUI-only methods:

- `_mark_preview_stale(reason: str = "")`
- `_mark_preview_current()`
- `_refresh_preview_state_badge()`
- `_clear_preview_for_input_change()`
- `_preview_control_signature() -> tuple[str, ...]`
  - raw canonical input/buffer/outline/section/overlap/effective-shape-label/split/simplification values;
  - excludes output path and output file name themselves;
  - avoids validation dialogs or numeric coercion on every keystroke.

Rules:

- any preview-affecting setting change invalidates cache and marks stale;
- buffer now participates through the existing `_invalidate_cache` method; this is the sole newly authorized cache-lifecycle change;
- output path/name changes continue invalidating cache eligibility as today; after `_refresh_shape_label_default`, compare `_preview_control_signature()` with the signature captured at the last successful draw;
- if an output edit leaves a user-touched/effective shape label unchanged, keep displayed geometry current; if default-label synchronization changes the effective shape label, mark the preview/key stale;
- input change clears canvas/key and sets empty/loading copy for the new input;
- the last drawn preview remains visible for non-input setting edits;
- successful `scan_done` or `export_done` marks the displayed result current;
- error leaves the previous image visible but displays an error/stale state;
- no trace starts a worker automatically.

The implementation must explicitly distinguish:

- `_cached_result`: eligibility for core-result reuse;
- `_last_displayed_result`: what is currently drawn;
- `_last_displayed_signature`: raw canonical preview-control state captured after a successful draw;
- `_preview_stale`: whether current controls differ from the displayed result.

This separation is GUI-only and prevents cache invalidation from erasing useful visual context.

#### 3.4.9 Focus mode and Inspector preservation

New methods:

- `_toggle_focus_mode`
- `_enter_focus_mode`
- `_exit_focus_mode`

In-window focus-mode behavior:

- before entry, save the root's current `state()` and geometry plus the mapped state of nonessential shell rows;
- request Windows `state("zoomed")`, call `update_idletasks()`, and verify the decorated outer rectangle is contained by the current monitor's `rcWork`; if zoom is unsupported or containment fails, restore normal state and apply a measured, work-area-clamped 94% fallback geometry;
- collapse nonessential title copy while retaining a compact input affordance, Settings, Key, Open Inspector, status, quick controls, Update Preview, and Export KMZ;
- when the root was not already maximized, the main preview workspace area must grow by at least 10% in the current monitor work area; when it was already maximized, it must not shrink;
- same one-canvas pan/zoom/toolbar behavior;
- current cached/displayed result remains visible;
- all settings are available through the drawer;
- Update Preview and Export remain visible;
- legend remains available;
- Escape exits focus mode after closing any open overlay;
- the main canvas, canonical variables, and event bindings are reused rather than duplicated.
- exit restores the exact pre-focus root state/geometry and shell-row visibility after `update_idletasks()`.

Detachable Inspector requirements:

- retain `_fullscreen_*` fields and every current Inspector method;
- retain the current independent section variables, `Apply Preview`, canvas, toolbar, key, pan/zoom, and close behavior;
- restyle its ttk, raw Tk, and Matplotlib surfaces through the same theme;
- place/maximize it on the parent/current monitor's `rcWork`, never at hard-coded `+0+0`;
- keep an `Open Inspector` action reachable from the preview header/toolbar in both normal and focus modes;
- preserve the current rule that reopening an existing Inspector lifts/focuses it;
- when `_cached_result` is cleared by an edit, `_draw_fullscreen_preview` falls back to `_last_displayed_result` and shows the same stale/error text; `_cached_result` remains reserved for reuse eligibility, while opening the Inspector never erases useful last-drawn context;
- keep all five current Inspector tests and add work-area/theme/reopen coverage;
- do not decommission or consolidate the Inspector in this scope. Any future removal requires a separate approved plan because a detached window is itself current functionality.

#### 3.4.10 Dialog placement and parenting

- Keep current dialog content and decisions.
- Pass the root as parent for GUI-owned message boxes/file dialogs where Tk supports it.
- For app-owned Toplevels (Details, export success, Inspector), create withdrawn, build, `update_idletasks`, apply native chrome, fit the decorated outer bounds with the shared helper on the parent monitor, then deiconify.
- Replace `_center_child_window` with the measured decorated-frame clamping helper.
- Native message/file dialogs remain OS-positioned but receive `parent=self.root`; their contents are not custom-themed/clamped.
- Do not change file dialog return values or overwrite semantics.

#### 3.4.11 Busy-state hardening

`_set_busy` currently disables only scan/export/expand plus outline/simplification (`src/jpg_boundary_kmz_gui.py:2061-2076`). Buffer and section fields remain editable during a worker.

The revamp will:

- register every editable field in `_all_mutation_widgets` and every mutating command in `_busy_action_widgets`: input/output entries, quick/drawer settings, Change Input, both Browse actions, Save As, Update Preview, Export, and retained Inspector Apply controls;
- disable those widgets while busy;
- add an early `_busy` guard to `_handle_folder_drop` because disabling a widget does not suppress its `dnd_bind`; a busy drop must leave `parent_var`, output defaults, preview, and worker state unchanged and show a concise wait status;
- keep safe visual toggles such as Key available;
- prevent a control edit from making an in-flight result immediately stale;
- restore each control through the existing mode/section enablement methods, not blindly to normal.

No worker cancellation, request token, retry, or concurrency protocol is added.

Duplicate quick/drawer widgets share variables but still need state applied to every instance. Define these GUI-only registries:

- `_all_mutation_widgets`;
- `_section_multiple_widgets` for every drawer/action-bar control enabled only when shapes > 1;
- `_custom_direction_widgets`;
- `_vector_only_widgets`;
- `_folder_only_widgets`;
- `_busy_action_widgets`.

Refactor `_update_section_control_state` and `_update_outline_mode_state` to iterate these registries while preserving their current rules. `_set_busy(False)` calls those dependency methods after clearing `_busy`; it never blindly assigns `"normal"` to the entire registry.

#### 3.4.12 Keyboard behavior

Fixed shortcuts:

- `F5`: Update Preview.
- `Ctrl+Enter`: Update Preview from the drawer.
- `Ctrl+E`: Export KMZ.
- `Ctrl+,`: toggle Settings.
- `Ctrl+L`: open Settings and focus input path.
- `Escape`: close topmost overlay, then exit focus mode.

Shortcuts must:

- return `"break"` when handled;
- do nothing unsafe while busy;
- not intercept ordinary typing in entries;
- preserve standard Tab/Shift+Tab traversal and visible focus.

### 3.5 Protected symbols in `src/jpg_boundary_kmz_gui.py`

The file is allow-listed because the UI lives there, but these symbols are contract-protected:

| Symbol | Allowed change |
| --- | --- |
| `_read_inputs` | Function AST must remain byte-for-byte semantic-equivalent to the Phase 0 baseline; no body edit is authorized. |
| `_scan_clicked` | Normalized function AST must remain identical; the sole permitted raw-AST addition is `parent=self.root` on existing `messagebox` calls. |
| `_start_preview_generation` | Function AST must remain identical to the Phase 0 baseline. |
| `_export_clicked` | Normalized function AST must remain identical; the sole permitted raw-AST addition is `parent=self.root` on existing validation/overwrite `messagebox` calls. |
| `_scan_worker` | Function AST must remain identical to the Phase 0 baseline. |
| `_export_worker` | Function AST must remain identical to the Phase 0 baseline. |
| `_drain_queue` | May update new GUI state/widgets, but payload types and core-result handling remain unchanged. |
| `_settings_key` | Function AST must remain identical to the Phase 0 baseline. |
| `_selected_outline_mode` | Function AST must remain identical to the Phase 0 baseline. |
| `_selected_split_direction` | Function AST must remain identical to the Phase 0 baseline. |
| `_resolve_output_path`, `_default_output_path`, output-name helpers | Function ASTs must remain identical to the Phase 0 baseline. |
| `_parse_dropped_paths`, `_path_from_text`, `_strip_wrapping_quotes` | Function ASTs must remain identical to the Phase 0 baseline. |
| `_draw_preview_on_axes`, bounds/decimation methods | Appearance-only color/background changes; geometry selection, bounds, aspect, labels, and decimation remain. |

The Phase 0 AST baseline and final audit cover these exact methods:

```text
_read_inputs
_scan_clicked
_start_preview_generation
_export_clicked
_scan_worker
_export_worker
_selected_outline_mode
_selected_split_direction
_parse_dropped_paths
_path_from_text
_strip_wrapping_quotes
_resolve_output_path
_settings_key
_settings_outline_key
_default_output_path
_safe_filename_stem
_filename_from_output_name
_default_shape_label
```

The audit parses the current file and `git show <phase-0-commit>:src/jpg_boundary_kmz_gui.py`, removes only `parent=` keywords from calls whose receiver is exactly `messagebox` or `filedialog`, compares `ast.dump(..., include_attributes=False)` for each named `BoundaryKmzApp` method, and fails on any missing or other changed node. Dedicated dialog tests require every newly added parent value to be exactly `self.root`. Phase 0 must stop if this GUI file is already dirty; therefore the recorded commit is a valid protected-body baseline rather than an assumption about `HEAD`.

### 3.6 `tests/test_gui_input.py` — modified

Keep existing behavior tests except exact layout/Inspector implementation assertions that the approved redesign supersedes.

Changes:

- replace exact current grid row/column assertions with preview-expansion and permanent-action visibility contracts;
- retain and adapt separate-Inspector behavior tests for styling and work-area-safe placement;
- add focus-mode, stale-state, compact-input, drawer, key overlay, busy-state, DnD target, theme, shortcut, and canonical-variable tests;
- retain all input parsing, settings-key, enablement, preview geometry, pan/zoom, and automatic-buffer tests.

### 3.7 `tests/test_gui_window.py` — new

Pure tests for:

- normal work area;
- negative-coordinate monitor;
- 680 px-tall work area;
- top/side taskbar offsets;
- work-area-provider failure;
- signed Tk geometry formatting;
- adaptive minimum;
- child centering/clamping.

No test will depend on this machine's actual seven-monitor arrangement.

### 3.8 `README_JPG_BOUNDARY_KMZ.md` — modified

Update only user-facing GUI instructions:

- new preview-first layout;
- empty/selected input states;
- Settings and Key overlays;
- quick controls and explicit stale-preview/update flow;
- focus mode, retained detachable Inspector, and shortcuts;
- monitor-aware startup;
- internal drawer-scroll fallback;
- unchanged processing/export behavior and dependencies.

Do not rewrite backend behavior sections except to remove stale GUI wording.

## 4. Risk matrix

| ID | Risk | Likelihood | Impact | Evidence | Mitigation / gate |
| --- | --- | --- | --- | --- | --- |
| R-01 | UI refactor changes arguments passed to core. | Low | Critical | Core calls at GUI `:1108-1118,1138-1149`. | Mock/capture route tests plus full core suite; protected symbol contract. |
| R-02 | Preview-quality result reaches export. | Low | Critical | Profile/cache key at `:1062-1075,2198-2224`; core guard at core `:798-806`. | Do not edit key semantics; retain existing core regression tests. |
| R-03 | Vector simplification default changes. | Low | High | GUI false at `:82`; core default true at core `:355-365`. | Assert default false and exact worker argument. |
| R-04 | DnD disappears when the large drop panel is hidden. | Medium | High | Registration is widget-specific at GUI `:735-743`. | Register both persistent targets; mock/functional tests before phase pass. |
| R-05 | Drawer, legend, or focus mode recreates the main canvas and duplicates Matplotlib callbacks. | Medium | High | Four main callbacks at `:521-554`; the retained Inspector intentionally owns its own independent callbacks at `:1816-1820`. | Reuse one persistent main canvas; assert four main IDs after repeated toggles and retain the Inspector's separate lifecycle tests. |
| R-06 | Monitor sizing still covers taskbar due client/non-client difference. | Medium | High | Measured 16 x 39 total non-client extent; a provisional 1440 x 612 client centered by client bounds alone clips the 680 px work area by 5 px. | Withdrawn `GetWindowRect` fit/retry shared by root/Toplevels, conservative 32 x 64 reserve fallback, nonfatal fit result/warning, and strict live/manual outer-bounds release gate. |
| R-07 | Negative monitor coordinates format incorrectly. | Medium | High | Multiple monitors have negative origins; Microsoft `rcWork` permits negatives. | Signed-geometry unit tests and negative-monitor launch smoke. |
| R-08 | Mixed-DPI virtualization causes wrong placement. | Medium | High | Current process DPI-awareness is 0; Tk scaling 1.333. | Do not change awareness; keep all APIs in current coordinate context; multi-DPI manual gate. |
| R-09 | Hard minimum still cannot fit 680 px monitor. | Medium | High | Current 720 px minimum is too tall. | Adaptive <=600 px client minimum and explicit 680 px unit/manual tests. |
| R-10 | Theme styles ttk but leaves raw Tk/Matplotlib surfaces light. | High | Medium | Raw widgets at GUI `:387-397,476-505,1512-1518,2042-2053`; Figure at `:439`. | Theme audit checklist across ttk, raw Tk, toolbar, dialogs, Matplotlib. |
| R-11 | Image-backed rounded styles lose focus/disabled semantics. | Medium | Medium | ttk behavior relies on state maps. | Use `ttk.Button`; fall back to flat style; keyboard `.invoke()` and state tests. |
| R-12 | Stale badge and cache state diverge, especially for the newly covered buffer trace and output-derived shape-label cascade. | Medium | High | Current invalidation at `:881-930`, buffer trace gap at `:131-140`, default-label sync at `:858-905,968-977`, and cache at `:2078-2080`. | Explicit displayed/cache/signature/stale state model; buffer-only, touched/default-label output, and export-route transition tests. |
| R-13 | User edits settings while generation is running. | Medium | Medium | Current `_set_busy` leaves several inputs enabled. | Disable registered mutable controls, then restore dependency-aware states. |
| R-14 | Long input/output paths force controls/actions off-screen. | Medium | Medium | Current entries expand horizontally; screenshot shows long path. | Ellipsized summary, flexible grid weights, drawer wrapping, bounds tests. |
| R-15 | Up to 100 section labels overwhelm preview. | Medium | Medium | `MAX_SECTION_COUNT=100` in core `:59`; scrollable key exists. | Overlay remains scrollable; closed default; test many entries. |
| R-16 | Focus-mode work accidentally regresses the detachable Inspector or its multi-monitor use. | Medium | High | Existing Inspector at GUI `:1652-2018`; 5 current tests. | Retain all Inspector methods/capabilities in scope, preserve/adapt all 5 tests, and add placement/theme/reopen checks; no decommission is authorized. |
| R-17 | Parentless dialogs open on another monitor. | Medium | Medium | Several dialogs do not consistently pass parent; centering is unclamped. | Parent/clamp GUI-owned dialogs and manual multi-monitor validation. |
| R-18 | Main page needs a scrollbar at low height. | Medium | Medium | One monitor work area is 680 px. | Fixed top/preview/action rows; only drawer content may scroll. |
| R-19 | New module import breaks launcher portability. | Low | High | Launcher adds `src` directly to `sys.path`. | Modules live directly in `src`; launch from repo and external CWD smoke. |
| R-20 | New dependency is accidentally introduced. | Low | Medium | Current short requirements file. | Requirements excluded; import inventory and diff gate. |
| R-21 | Existing user modification is overwritten. | Low | High | Planning guide is already modified in worktree. | Preserve it; implementation diff scope gate. |
| R-22 | Details/output dialogs regress due restyling. | Medium | Medium | Dialogs at GUI `:1220-1281,2024-2059`. | Dialog lifecycle/manual tests; preserve commands and text. |
| R-23 | Settings edits auto-trigger expensive work. | Low | High | Current explicit scan; queue lacks request ID. | Fixed decision: traces only mark stale; no debounce/auto-generation. |

## 5. Assumptions and unknowns

### 5.1 Assumption register

| ID | Statement | Classification | Evidence / treatment |
| --- | --- | --- | --- |
| A-01 | The current core/output behavior is the contract to preserve. | Verified from code | README behavior and 99 passing tests; user explicitly protected it. |
| A-02 | Tk/ttk is the safest compatible styling base. | Verified from code | Current root, variables, DnD, Matplotlib, dialogs, and tests all use Tk. |
| A-03 | No new dependency is required to achieve the requested theme/layout. | Likely but not fully proven | ttk exposes styles/state maps; a forced-failure flat fallback and phase gate isolate platform-specific rounded rendering. |
| A-04 | Pointer-monitor selection will normally match the user's intended launch monitor. | Likely but not fully proven | It fits double-click use but is not guaranteed for keyboard/terminal launch; FD-14 makes it documented chosen behavior and supplies root/nearest/primary fallbacks. |
| A-05 | Runtime display topology must not be hard-coded. | Verified from code and direct runtime evidence | Tk/Win32 expose dynamic coordinates; seven monitors and negative coordinates were observed and can change. |
| A-06 | A `960 x 600` nominal client minimum is usable after the preview-first redesign. | Likely but not fully proven | Exact preview/action thresholds, hidden-root bounds tests, and the 680 px monitor manual gate must prove it before Phase 3 can pass. |
| A-07 | Drawer-only scrolling can keep the main page scroll-free. | Likely but not fully proven | The fixed shell design isolates overflow to one overlay; compact-height layout and keyboard-reachability gates validate it. |
| A-08 | Work-area clamping in the current DPI coordinate model fixes the clipping defect without changing process DPI awareness. | Likely but not fully proven | Exact unit geometry and 100–200% manual scaling gates isolate this environment-sensitive assumption; no awareness-mode change is authorized. |
| A-09 | Retaining the detachable Inspector alongside focus mode avoids a current-capability regression. | Verified from code | The Inspector is a distinct `Toplevel` with independent controls/canvas and can be placed separately; no decommission is authorized. |
| A-10 | The palette can be adapted for contrast instead of copied literally. | Verified from code and local calculation | Low-contrast template info blue is replaced by `#60a5fa`; calculations are recorded in Section 2.13. |

### 5.2 Unknowns isolated by validation

There are no unknowns requiring user input.

Platform-rendered details that cannot be proven statically—title-bar extent, ttk image-element rendering, toolbar appearance, and mixed-DPI movement—are not allowed to change scope or contracts. They have deterministic fallbacks and explicit phase-gate tests:

- measured outer-frame fitting with a conservative 32 x 64 non-client reserve when measurement is unavailable;
- flat padded button style if rounded image elements fail;
- existing toolbar behavior retained if full dark icon treatment is not reliable;
- no DPI-awareness-mode change;
- existing Inspector retained unconditionally; focus-mode failure rolls back only the new focus feature.

These are implementation validation conditions, not open architectural decisions.

## 6. Edge cases and failure modes

| Scenario | Required behavior | Validation |
| --- | --- | --- |
| No input selected | Large drop/browse state visible; Update/Export remain visible but validation prevents work. | GUI test + manual smoke. |
| Empty manual path | Existing `BoundaryError` text remains. | Existing/new route test. |
| Nonexistent path | Existing error remains; no worker starts. | Existing `_read_inputs` behavior test. |
| Unsupported file | Only directory/KML/KMZ accepted; browse/drop wording remains accurate. | DnD/input tests. |
| Quoted path, Tcl brace list, `file://` URI | Existing normalization retained. | Extend DnD regression matrix. |
| Multiple dropped inputs | First valid input selected; status explains selection. | DnD handler test. |
| `tkinterdnd2` missing/fails | Plain Tk root opens; browse remains available; warning styled. | Mock import/registration failure test and manual fallback. |
| Drop target hidden after selection | Compact input strip remains registered. | Registration test after state transition. |
| Very long input path | Header summary ellipsizes; full value remains editable in drawer. | Compact-size bounds test. |
| Buffer invalid/negative | Existing validation message; stale badge remains. | Existing `_read_inputs` test plus stale transition. |
| Buffer changed alone | Cache invalidated and preview marked stale. | New regression test. |
| JPG folder selected | Outline enabled; vector simplification disabled. | Existing tests. |
| KML/KMZ selected | Outline disabled; vector simplification enabled; default remains false. | Existing tests plus style state. |
| Section count 1 | Overlap/label/direction/degrees disabled; overlap quick control hidden/disabled. | Existing/new state tests. |
| Section count >1 | Section fields enabled; overlap visible. | State tests. |
| Invalid section count text | Fields remain safely accessible; `_read_inputs` reports current error. | Negative GUI test. |
| Custom degrees empty/nonfinite/text | Existing validation and modulo-180 normalization retained. | Existing tests. |
| Shape label/output name very long | Drawer entry remains usable; action bar does not expand off-screen. | Compact-size manual/test. |
| Output path empty/relative | Existing default and APP_ROOT resolution retained. | Existing path tests/regression suite. |
| Output parent unwritable | Existing worker/error message path retained; UI exits busy state. | Manual negative smoke or mocked queue error. |
| Output exists | Existing overwrite confirmation remains. | Mock dialog route test. |
| User cancels browse/save | No value or state corruption. | Mock dialog tests. |
| Preview settings edited | Old image stays visible with “Preview out of date”; no worker auto-starts. | Stale-state test. |
| Output name/path edited with touched label | Cache invalidation remains; effective shape label is unchanged, so displayed geometry stays current. | Output-only touched-label test. |
| Output name/path edited with untouched/default label | Default shape label changes; displayed labels/key are marked stale until regeneration. | Output-derived-label test. |
| Input changed | Previous preview/key cleared. | Input-transition test. |
| Preview fails | Previous non-input preview may stay visible but error/stale text appears; actions restore. | Queue error test. |
| Export after stale preview | Export uses current settings and export profile, never stale preview profile. | Existing core regression plus route capture. |
| Auto-selected polyline buffer | Canonical buffer field updates; stale state ends after result is drawn. | Existing `test_scan_done_auto_selected_polyline_buffer_updates_buffer_field`. |
| Repeated drawer/key toggles | Values persist; exactly four preview event IDs; view limits do not reset. | New repeated-toggle tests. |
| Focus mode entered/exited repeatedly | One persistent main canvas, one main toolbar, one main callback set; settings/actions/Inspector access stay available. | Focus lifecycle tests. |
| Inspector opened/reopened/moved separately | Current detached canvas, independent section Apply flow, and lift/focus behavior remain; window is taskbar-safe on its selected monitor. | Existing Inspector tests + new placement smoke. |
| Maximum 100 sections | Key scrolls; preview remains responsive; drawer/actions stay visible. | Synthetic key test/manual. |
| Dense polygon | Existing preview decimation and closure retained. | Existing decimation test. |
| Long corridor | Equal map scale and full axes retained. | Existing long-corridor tests adapted to one canvas. |
| Worker active | All mutable inputs and generation/export actions disabled; safe view toggles remain. | Busy-state test. |
| App closed during worker | Preserve daemon behavior; no new blocking join. | Manual smoke; no protocol change. |
| Primary monitor work area | Outer window remains visible above taskbar. | Manual outer-bounds check. |
| Negative-origin monitor | Signed geometry places window on that monitor. | Pure test + manual launch. |
| 680 px work area | Window fits; action bar visible; drawer internal scroll works if needed. | Pure + hidden-root + manual tests. |
| Top/side taskbar | `rcWork` origin respected. | Pure work-area test. |
| Monitor disconnect/topology change | Each launch recomputes; provider failure falls back; no persisted invalid coordinates. | Provider-failure test/manual RDP reconnect. |
| Mixed DPI | No awareness-mode change; window remains usable after move/relaunch. | Manual 100/125/150/200% matrix. |
| Theme engine cannot create rounded elements | Flat themed ttk fallback; full functionality remains. | Forced-failure test. |
| Outer-frame measurements do not converge | Apply conservative reserved geometry, return a warning/result flag, and still launch; supported-environment containment remains a release gate. | Nonconverging-provider unit test + live/manual containment gate. |
| Theme applied to disabled controls | Disabled and readonly remain distinguishable and legible. | Style lookup + manual contrast check. |
| Keyboard-only use | Focus visible; shortcuts work; no focus trap in drawer/overlay. | Keyboard manual matrix + event tests. |

## 7. Strict file allow-list

The implementation may touch only these files.

| Exact path | Change | Reason | Required tests | Risk | Rollback |
| --- | --- | --- | --- | --- | --- |
| `src/jpg_boundary_gui_window.py` | Create | Isolate testable work-area/geometry logic from GUI controller. | `tests.test_gui_window`; launcher smoke | Medium | Delete module and remove its GUI import/calls. |
| `src/jpg_boundary_gui_theme.py` | Create | Centralize palette, ttk maps, raw Tk, and Matplotlib styling without dependency. | Theme/style tests in `tests.test_gui_input`; visual smoke | Medium | Delete module and remove its GUI import/calls. |
| `src/jpg_boundary_kmz_gui.py` | Modify | Recompose layout, add overlay/focus/stale/busy/placement GUI behavior, apply theme. | `tests.test_gui_input`; full suite; manual matrix | High | Revert phase-specific hunks; existing monolithic UI/Inspector remains reference. |
| `tests/test_gui_window.py` | Create | Pure regression coverage for monitor and geometry edge cases. | Run file directly and full suite | Low | Delete test file with window module rollback. |
| `tests/test_gui_input.py` | Modify | Replace obsolete structural assertions and add GUI/QOL parity coverage. | Run file directly and full suite | Medium | Revert new/replaced GUI tests with corresponding UI rollback. |
| `README_JPG_BOUNDARY_KMZ.md` | Modify | Document the new GUI workflow, sizing behavior, and shortcuts. | Documentation review; command/path verification | Low | Revert GUI wording. |

The plan itself is a permitted planning artifact and is not an implementation target.

### 7.1 Explicitly excluded files

No implementation edit is allowed in:

- `src/jpg_boundary_kmz_core.py`
- `src/camera_preflight.py`
- `src/geometry_hardening.py`
- `src/kml_vector_input.py`
- `src/natural_sectioning.py`
- `src/outline_strategies.py`
- `src/polyline_boundary.py`
- `src/section_ordering.py`
- `run_jpg_boundary_gui.py`
- `src/run_jpg_boundary_gui.py`
- `run_jpg_boundary_gui.bat`
- `requirements_jpg_boundary_kmz.txt`
- `.vscode/**`
- `outputs/**`
- `test_data/**`
- `agent_prompt_templates/**`
- existing prior planning/validation documents
- every file under `../AALLC-GUI-Template/**`

No copied CSS, JavaScript, HTML, image, font, vendor asset, sample data, or AALLC branding file is allowed.

If implementation discovers a need to touch another file, stop, revise this plan and allow-list, audit the impact, and re-certify readiness before touching it.

## 8. Implementation phases with gates

Repository inventory found no configured linter, type checker, packaging build, CI pipeline, or project-level formatter. Accordingly, each code phase uses an in-memory Python `compile(...)` command as its syntax/build gate and `git diff --check` as its formatting gate; there is no honest lint/type command to invent. Each phase below states its exact applicable commands. No downstream phase begins until every command, expected output, manual acceptance item, and pass criterion in the current phase succeeds.

### Phase 0 — Baseline and scope lock

Goal: prove the starting point and preserve user changes before implementation.

Allowed repository files: none.

Sole external artifact: `$env:TEMP\jpg-boundary-gui-protected-38fd82b.json`.

Tasks:

1. Record:
   - `git status --short --branch`;
   - `git diff -- agent_prompt_templates/extremely-detailed-planning/detailed-planning-requirements.md`;
   - current commit;
   - `Get-Command python | Select-Object -ExpandProperty Source`;
   - `python -B -c "import sys; print(sys.executable); print(sys.version.split()[0])"`.
2. Confirm the existing planning-guide modification belongs to the user and is not altered.
3. Run the required test commands below.
4. Confirm baseline remains 27 GUI tests and 99 total tests unless the repository changes before implementation.
5. Require `src/jpg_boundary_kmz_gui.py` to match the recorded Phase 0 commit so the protected-method AST audit has an authoritative baseline.
6. Use baseline-aware `git diff 38fd82b --exit-code -- <protected paths>` for all excluded production modules and launcher/requirements/config files.
7. Capture a file path/length/SHA-256 manifest for ignored `outputs/**` and `test_data/**` into the system temp directory, not the repository:

```powershell
@'
import hashlib
import json
import tempfile
from pathlib import Path

workspace = Path.cwd().resolve()
manifest = Path(tempfile.gettempdir()) / "jpg-boundary-gui-protected-38fd82b.json"
protected = []
for root_name in ("outputs", "test_data"):
    root = workspace / root_name
    if root.exists():
        protected.extend(path for path in root.rglob("*") if path.is_file())
protected.append(
    workspace
    / "agent_prompt_templates"
    / "extremely-detailed-planning"
    / "detailed-planning-requirements.md"
)
entries = [
    {
        "path": path.relative_to(workspace).as_posix(),
        "length": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    for path in sorted(protected)
]
manifest.write_text(json.dumps(entries, indent=2), encoding="utf-8")
print(manifest)
'@ | python -B -
```

Required tests:

```powershell
python -B -m unittest tests.test_gui_input
python -B -m unittest discover -s tests
```

Required lint/type/build commands:

```powershell
git diff 38fd82b --exit-code -- src/jpg_boundary_kmz_gui.py
git status --short --untracked-files=all
```

Also run the exact “Protected GUI-method AST check” command printed in Phase 5 before any edit; it must print `Protected GUI method ASTs unchanged`. No code file changes in Phase 0, so Python compile, lint, type, and build steps are not applicable; the repository has no configured linter, type checker, or build tool.

Expected output:

- current dirty state documented;
- both test commands pass;
- temp manifest exists and contains only relative protected paths/hashes;
- no implementation file changed.

Failure conditions:

- baseline tests fail;
- new unrelated worktree changes overlap allow-listed files;
- a protected file is already modified without ownership/context.

Pass criteria:

- baseline is understood and cleanly attributable.

Rollback/recovery:

- no repository changes exist to roll back;
- if Phase 0 aborts after manifest creation, resolve `[System.IO.Path]::GetFullPath((Join-Path ([System.IO.Path]::GetTempPath()) "jpg-boundary-gui-protected-38fd82b.json"))`, verify its parent is exactly `[System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())` and its leaf name is exactly `jpg-boundary-gui-protected-38fd82b.json`, then remove only that manifest with `Remove-Item -LiteralPath`;
- stop and investigate the failure before any implementation edit.

### Phase 1 — Window work-area foundation

Goal: fix initial monitor/taskbar fit through isolated, tested geometry logic.

Allowed files:

- `src/jpg_boundary_gui_window.py`
- `src/jpg_boundary_kmz_gui.py`
- `tests/test_gui_window.py`
- `tests/test_gui_input.py`

Tasks:

1. Implement `WorkArea`, `WindowGeometry`, exact absolute `+{x}+{y}` formatting, pure size/minimum calculations.
2. Implement pointer-, window-, and primary-monitor Windows `rcWork` lookup with safe exception/fallback behavior.
3. Implement conservative Tk primary-screen fallback at `(0, 0)`; do not use virtual-root union geometry.
4. Stage withdraw/build/geometry/deiconify only in `main()` without changing `_create_root` or `BoundaryKmzApp` caller-owned window state.
5. Replace fixed `980x720` minimum with adaptive maximum-safe minimum.
6. Clamp GUI-owned child windows through the same helper.
7. Add pure and hidden-root tests.
8. Add a nonconverging-measurement test proving startup receives a nonfatal conservative fallback result rather than an assertion/exception.

Required tests:

```powershell
python -B -m unittest tests.test_gui_window
python -B -m unittest tests.test_gui_input
```

Required lint/type/build commands:

```powershell
python -B -c "from pathlib import Path; files=['src/jpg_boundary_gui_window.py','src/jpg_boundary_kmz_gui.py','tests/test_gui_window.py','tests/test_gui_input.py']; [compile(Path(f).read_text(encoding='utf-8'), f, 'exec') for f in files]"
git diff --check
git status --short --untracked-files=all
```

Expected output:

- normal, negative, offset-taskbar, provider-failure, and 680 px work areas produce final measured/reserved outer bounds wholly inside one work area;
- exact negative placement strings contain `+-N` for negative absolute coordinates;
- app-created test roots remain withdrawn when `BoundaryKmzApp` is instantiated directly;
- no launcher change.

Failure conditions:

- computed initial/minimum size exceeds work area;
- negative coordinates serialize as edge-relative `-N` rather than absolute `+-N`;
- fallback centers in a virtual-root union rather than one real/primary screen;
- child placement uses the launch pointer instead of the parent window's monitor;
- DnD root fallback fails;
- nonconverging outer-frame measurement raises or prevents startup instead of returning the conservative fallback result;
- `BoundaryKmzApp` deiconifies a caller-owned withdrawn root;
- test requires a real monitor arrangement;
- existing GUI tests regress outside intentional geometry expectations.

Pass criteria:

- all commands pass;
- real hidden-root `GetWindowRect` assertion and manual launches on primary/680 px-height displays keep the entire decorated outer window and action area within `rcWork`.

Rollback/recovery:

- remove window-helper import/calls and module/tests; restore original minimum temporarily.

### Phase 2 — Central theme and complete dark-surface coverage

Goal: create the dark/blue visual system without altering layout behavior yet.

Allowed files:

- `src/jpg_boundary_gui_theme.py`
- `src/jpg_boundary_kmz_gui.py`
- `tests/test_gui_input.py`

Tasks:

1. Add palette and named ttk styles.
2. Add state maps for hover, pressed, focus, readonly, disabled, selected.
3. Add safe rounded-button style creation and flat fallback.
4. Apply theme to current ttk controls.
5. Apply explicit styling to current raw Tk drop label, canvases, details text, combo popdown, Matplotlib figure/axes after every clear, key swatches, and toolbar container.
6. Add best-effort wrapper-HWND DWM native-chrome styling with exact pointer-width prototypes and a nonfatal fallback.
7. Ensure status/error/success text is not color-only.
8. Add style existence, state, redraw-cycle, pointer-width DWM success, and forced-fallback tests.

Required tests:

```powershell
python -B -m unittest tests.test_gui_input
```

Required lint/type/build commands:

```powershell
python -B -c "from pathlib import Path; files=['src/jpg_boundary_gui_theme.py','src/jpg_boundary_kmz_gui.py','tests/test_gui_input.py']; [compile(Path(f).read_text(encoding='utf-8'), f, 'exec') for f in files]"
git diff --check
git status --short --untracked-files=all
```

Expected output:

- no white/light orphan surface in app-owned client surfaces: root content, Inspector content, Details, custom export-success dialog, preview shell, combo popdown, or Matplotlib axes after redraw;
- Windows title bars use the best-effort DWM path when supported; native file/message dialogs remain system-owned and functional;
- primary/secondary/disabled/focus states remain recognizable;
- ttk command/keyboard semantics remain.

Failure conditions:

- theme fails on plain `tk.Tk` or `TkinterDnD.Tk`;
- readonly/disabled text becomes unreadable;
- toolbar or canvas rendering breaks;
- DWM failure escapes into startup or an app-owned Toplevel lifecycle;
- `axes.clear()` or Combobox popdown restores an unthemed light surface;
- rounding implementation requires a new dependency.

Pass criteria:

- automated tests pass;
- manual visual audit at 100% and 125% scaling passes;
- fallback style works when rounded-element creation is forced to fail.

Rollback/recovery:

- remove theme application and module/tests; no processing logic is involved.

### Phase 3 — Preview-first single-page shell

Goal: deliver the large-preview layout with compact input, settings drawer, overlay key, and permanent actions.

Allowed files:

- `src/jpg_boundary_kmz_gui.py`
- `src/jpg_boundary_gui_theme.py`
- `tests/test_gui_input.py`

Tasks:

1. Split `_build_ui` into private shell builders.
2. Make the preview the sole expanding content cell.
3. Add empty-input drop/browse overlay.
4. Add compact selected-input strip and persistent DnD target.
5. Add on-demand settings drawer with the three fixed groups.
6. Move key into a toggleable overlay.
7. Add fixed action bar with quick canonical controls.
8. Preserve one persistent main Figure/canvas/toolbar and exactly four custom main callback IDs; the retained Inspector keeps its intentional independent Figure/canvas/toolbar/callback set.
9. Add responsive fixed-row behavior and drawer-only scroll fallback.
10. Retain and restyle the existing Inspector; do not change its independent Apply workflow.

Required tests:

```powershell
python -B -m unittest tests.test_gui_input
python -B -m unittest tests.test_gui_window
python -B -m unittest discover -s tests
```

Required lint/type/build commands:

```powershell
python -B -c "from pathlib import Path; files=['src/jpg_boundary_gui_theme.py','src/jpg_boundary_kmz_gui.py','tests/test_gui_input.py']; [compile(Path(f).read_text(encoding='utf-8'), f, 'exec') for f in files]"
git diff --check
git status --short --untracked-files=all
```

Expected output:

- empty state is obvious;
- selected input collapses the large drop surface;
- preview gains the majority of the client area;
- all controls remain reachable without main-page scroll;
- update/export actions remain mapped at every size at or above the adaptive minimum;
- settings/key toggles do not reset view or variables.

Failure conditions:

- any current input/browse/drop/output capability is lost;
- actions move outside client bounds;
- the main page requires a scrollbar;
- callback count grows after toggles;
- full suite regression occurs in core modules.

Pass criteria:

- all tests pass;
- at `1440 x 741`, `1440 x 612`, and nominal `960 x 600` target clients, the action bar is fully visible and the preview meets the exact Section 1.5 workspace thresholds;
- manual drag/drop and browse work before and after input compaction.

Rollback/recovery:

- restore previous `_build_ui` and theme placements while retaining Phase 1 sizing if independently passing.

### Phase 4 — Stale state, busy hardening, shortcuts, focus mode, and Inspector preservation

Goal: finish GUI-only QOL while preserving and validating the existing detachable Inspector.

Allowed files:

- `src/jpg_boundary_kmz_gui.py`
- `tests/test_gui_input.py`

Tasks:

1. Add buffer trace and cached/displayed/signature/stale state.
2. Distinguish input-change clear, settings-change stale display, touched-label output edits, and output-derived label changes.
3. Update `_drain_queue` to transition GUI state on success/error without changing payload contracts.
4. Populate all six widget-state registries, dependency-safely freeze every mutation route, and guard DnD during work.
5. Add fixed shortcuts and focus visibility.
6. Add in-window focus mode.
7. Retain/restyle every `_fullscreen_*` field/method, clamp/maximize the Inspector through the work-area helper, and fall back to `_last_displayed_result` when cache eligibility was invalidated.
8. Preserve/adapt the five current Inspector tests and add focus/Inspector coexistence tests.

Required tests:

```powershell
python -B -m unittest tests.test_gui_input
python -B -m unittest tests.test_core_regression
python -B -m unittest discover -s tests
```

Required lint/type/build commands:

```powershell
python -B -c "from pathlib import Path; files=['src/jpg_boundary_kmz_gui.py','tests/test_gui_input.py']; [compile(Path(f).read_text(encoding='utf-8'), f, 'exec') for f in files]"
git diff --check
git status --short --untracked-files=all
```

Expected output:

- edits clearly mark preview stale and do not auto-run;
- successful update clears stale;
- export continues using current export-profile settings;
- busy state is coherent;
- focus mode reuses the main canvas/state while the detachable Inspector remains independently functional.

Failure conditions:

- stale state clears incorrectly;
- output-only edits with an unchanged effective label mark geometry stale, or a derived-label change fails to mark preview/key stale;
- worker/core argument route changes;
- settings can be mutated while busy;
- focus mode or restyling loses any Inspector capability;
- repeated focus cycles duplicate main event handlers;
- Inspector reopen/apply/pan/zoom or placement regresses.

Pass criteria:

- all automated commands pass;
- focus-mode and Inspector coexistence checklists pass;
- all five adapted existing Inspector behavior tests pass and the Inspector remains present.

Rollback/recovery:

- revert stale/busy/focus changes independently;
- revert focus-mode work independently; retain the existing Inspector throughout.

### Phase 5 — Documentation and release validation

Goal: prove the GUI revamp is complete, portable, and core-neutral.

Allowed files:

- `README_JPG_BOUNDARY_KMZ.md`
- `tests/test_gui_window.py`
- `tests/test_gui_input.py`

Tasks:

1. Update README GUI instructions/dependencies.
2. Run the complete automated matrix.
3. Execute manual monitor, scaling, input, preview, export, and keyboard matrix.
4. Review diff and protected modules.
5. Confirm no implementation-introduced repository temp/generated artifacts, no production debug/placeholder/TODO/mock logic, and no sidecar for this plan.

Required tests:

```powershell
python -B -m unittest tests.test_gui_window
python -B -m unittest tests.test_gui_input
python -B -m unittest tests.test_core_regression
python -B -m unittest discover -s tests
```

Required lint/type/build commands:

```powershell
python -B -c "from pathlib import Path; files=['src/jpg_boundary_gui_window.py','src/jpg_boundary_gui_theme.py','src/jpg_boundary_kmz_gui.py','tests/test_gui_window.py','tests/test_gui_input.py']; [compile(Path(f).read_text(encoding='utf-8'), f, 'exec') for f in files]"
git diff 38fd82b --check --
git status --short --untracked-files=all
python -B -c "from pathlib import Path; files=['src/jpg_boundary_gui_window.py','src/jpg_boundary_gui_theme.py','tests/test_gui_window.py']; bad=[f'{p}:{i}' for p in files for i,line in enumerate(Path(p).read_text(encoding='utf-8').splitlines(),1) if line.endswith((' ', '\t'))]; assert not bad, f'Trailing whitespace in new files: {bad}'"
```

Tracked + untracked strict allow-list check:

```powershell
@'
import subprocess

BASELINE_COMMIT = "38fd82b"
ALLOWED = {
    "src/jpg_boundary_gui_window.py",
    "src/jpg_boundary_gui_theme.py",
    "src/jpg_boundary_kmz_gui.py",
    "tests/test_gui_window.py",
    "tests/test_gui_input.py",
    "README_JPG_BOUNDARY_KMZ.md",
    "docs/gui-visual-qol-revamp-implementation-plan.md",
    "agent_prompt_templates/extremely-detailed-planning/detailed-planning-requirements.md",
}
REQUIRED_IMPLEMENTATION = {
    "src/jpg_boundary_gui_window.py",
    "src/jpg_boundary_gui_theme.py",
    "src/jpg_boundary_kmz_gui.py",
    "tests/test_gui_window.py",
    "tests/test_gui_input.py",
    "README_JPG_BOUNDARY_KMZ.md",
}

def git_paths(*args):
    output = subprocess.check_output(["git", *args], text=True, encoding="utf-8")
    return {line.replace("\\", "/") for line in output.splitlines() if line}

tracked = git_paths("diff", "--name-only", BASELINE_COMMIT, "--")
untracked = git_paths("ls-files", "--others", "--exclude-standard")
changed = tracked | untracked
unexpected = sorted(changed - ALLOWED)
missing = sorted(REQUIRED_IMPLEMENTATION - changed)
assert not unexpected, f"Non-allow-listed paths changed: {unexpected}"
assert not missing, f"Expected implementation paths missing: {missing}"
print("Strict allow-list OK:")
for path in sorted(changed):
    print(path)
'@ | python -B -
```

Protected-file check:

```powershell
git diff 38fd82b --exit-code -- src/jpg_boundary_kmz_core.py src/camera_preflight.py src/geometry_hardening.py src/kml_vector_input.py src/natural_sectioning.py src/outline_strategies.py src/polyline_boundary.py src/section_ordering.py run_jpg_boundary_gui.py src/run_jpg_boundary_gui.py run_jpg_boundary_gui.bat requirements_jpg_boundary_kmz.txt .vscode/settings.json
```

Ignored/user-modified protected-manifest comparison and safe cleanup:

```powershell
@'
import hashlib
import json
import tempfile
from pathlib import Path

workspace = Path.cwd().resolve()
manifest = Path(tempfile.gettempdir()) / "jpg-boundary-gui-protected-38fd82b.json"
if not manifest.is_file():
    raise SystemExit(f"Missing Phase 0 protected manifest: {manifest}")
protected = []
for root_name in ("outputs", "test_data"):
    root = workspace / root_name
    if root.exists():
        protected.extend(path for path in root.rglob("*") if path.is_file())
protected.append(
    workspace
    / "agent_prompt_templates"
    / "extremely-detailed-planning"
    / "detailed-planning-requirements.md"
)
current = [
    {
        "path": path.relative_to(workspace).as_posix(),
        "length": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    for path in sorted(protected)
]
baseline = json.loads(manifest.read_text(encoding="utf-8"))
if current != baseline:
    raise SystemExit("Protected outputs/test_data/planning-guide manifest changed")
manifest.unlink()
print("Protected manifest unchanged and removed")
'@ | python -B -
```

Protected GUI-method AST check:

```powershell
@'
import ast
import subprocess
from pathlib import Path

BASELINE_COMMIT = "38fd82b"
SOURCE_PATH = "src/jpg_boundary_kmz_gui.py"
PROTECTED = {
    "_read_inputs",
    "_scan_clicked",
    "_start_preview_generation",
    "_export_clicked",
    "_scan_worker",
    "_export_worker",
    "_selected_outline_mode",
    "_selected_split_direction",
    "_parse_dropped_paths",
    "_path_from_text",
    "_strip_wrapping_quotes",
    "_resolve_output_path",
    "_settings_key",
    "_settings_outline_key",
    "_default_output_path",
    "_safe_filename_stem",
    "_filename_from_output_name",
    "_default_shape_label",
}

class NormalizeAllowedDialogParent(ast.NodeTransformer):
    def visit_Call(self, node):
        self.generic_visit(node)
        receiver = node.func.value if isinstance(node.func, ast.Attribute) else None
        if isinstance(receiver, ast.Name) and receiver.id in {"messagebox", "filedialog"}:
            node.keywords = [
                keyword for keyword in node.keywords if keyword.arg != "parent"
            ]
        return node

def protected_nodes(source):
    tree = NormalizeAllowedDialogParent().visit(ast.parse(source))
    app = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "BoundaryKmzApp"
    )
    methods = {
        node.name: node
        for node in app.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing = sorted(PROTECTED - methods.keys())
    assert not missing, f"Missing protected methods: {missing}"
    return {
        name: ast.dump(methods[name], include_attributes=False)
        for name in PROTECTED
    }

baseline = subprocess.check_output(
    ["git", "show", f"{BASELINE_COMMIT}:{SOURCE_PATH}"],
    text=True,
    encoding="utf-8",
)
current = Path(SOURCE_PATH).read_text(encoding="utf-8")
assert protected_nodes(current) == protected_nodes(baseline), (
    "A protected processing/routing/path method changed"
)
print("Protected GUI method ASTs unchanged")
'@ | python -B -
```

Expected output:

- full suite passes;
- strict checker prints only six allow-listed implementation paths plus the main plan and pre-existing planning-guide modification;
- no protected diff;
- protected ignored/user-modified manifest matches and its exact temp manifest is removed after success;
- protected GUI-method audit prints `Protected GUI method ASTs unchanged`;
- manual matrix passes.

Failure conditions:

- any protected file differs;
- tracked, staged, or untracked scope contains a path outside the exact checker allow-list;
- `outputs/**`, `test_data/**`, or the pre-existing planning-guide modification differs from its Phase 0 manifest;
- any protected GUI method is missing or has a different AST from audited commit `38fd82b`;
- dependency/launcher changes appear;
- a core regression fails;
- a monitor/scaling case clips permanent actions;
- README describes behavior not delivered.

Pass criteria:

- every post-implementation checklist item in Section 11 is checked.

Rollback/recovery:

- revert the failing phase only; the phases deliberately isolate geometry, theme, shell, and QOL changes.
- retain the Phase 0 manifest while investigating a failed comparison; if the implementation run is abandoned, validate its exact temp parent/leaf as specified in Phase 0 and remove only that manifest so no stale validation artifact survives.

## 9. Testing and regression matrix

### 9.1 New window-geometry tests

Command for every row: `python -B -m unittest tests.test_gui_window`

| File | Required test | Scenario | Expected result | Failure condition |
| --- | --- | --- | --- | --- |
| `tests/test_gui_window.py` | `test_initial_geometry_fits_standard_work_area` | 2048 x 824 work area | Centered geometry and outer safety margin | Any edge exceeds planned safe area |
| `tests/test_gui_window.py` | `test_initial_geometry_fits_short_work_area` | 2560 x 680 work area | Height about 612; minimum <=600 | 720 px minimum or clipping |
| `tests/test_gui_window.py` | `test_apply_geometry_clamps_mock_nonclient_frame_on_short_work_area` | Provisional `1440 x 612` yields `1456 x 651` outer in `(-1559,1080)-(1001,1760)` | Remeasured final outer is contained; client request approximately `1440x612+-1007+1094` | Final `right>1001`/`bottom>1760` or no second pass |
| `tests/test_gui_window.py` | `test_outer_measurement_failure_uses_conservative_frame_reserve` | `GetWindowRect` unavailable | 32 x 64 reserve produces contained fallback request | Raw client-center placement is used |
| `tests/test_gui_window.py` | `test_nonconverging_outer_measurement_returns_fallback_without_exception` | Three inconsistent/non-contained mocked outer rectangles | `WindowFitResult.used_reserve_fallback` is true, reserved request fits the 32 x 64 contract, warning is present, and no exception escapes | Assertion/exception prevents launch or the last unsafe measured request is returned unchanged |
| `tests/test_gui_window.py` | `test_geometry_preserves_negative_monitor_origin` | Negative X/Y `rcWork` | Signed position remains on monitor | Position coerced to primary/zero |
| `tests/test_gui_window.py` | `test_geometry_respects_offset_work_area` | Top/side taskbar origin | Center uses `rcWork` origin | Uses raw monitor origin |
| `tests/test_gui_window.py` | `test_geometry_string_formats_absolute_coordinates` | `(x,y)=(120,80)`, `(-1000,80)`, `(120,-500)`, `(-1000,-500)` | Exact strings `400x300+120+80`, `400x300+-1000+80`, `400x300+120+-500`, `400x300+-1000+-500` | Bare edge-relative `-N`, `{x:+d}` output, or any other string |
| `tests/test_gui_window.py` | `test_adaptive_minimum_never_exceeds_initial_geometry` | Small work areas | Minimum <= initial client | Root becomes impossible to fit |
| `tests/test_gui_window.py` | `test_work_area_rejects_nonpositive_dimensions` | Zero/negative width or height | `WorkArea` raises `ValueError` | Invalid rectangle instance is created |
| `tests/test_gui_window.py` | `test_invalid_provider_rectangle_uses_next_fallback` | OS provider returns zero/negative rectangle | Provider returns none and resolver selects the next valid fallback | Invalid rectangle escapes or startup fails |
| `tests/test_gui_window.py` | `test_provider_failure_uses_tk_fallback` | Win32 cursor/window providers raise/return none | Valid `(0,0)` primary-screen fallback; vroot is not queried | App fails to open or uses virtual union |
| `tests/test_gui_window.py` | `test_tk_primary_fallback_never_queries_virtual_root` | Mock wide/gapped virtual root plus primary dimensions | Resolver uses `(0,0,screen_width,screen_height)` only | `winfo_vroot*` is called or gap-centered |
| `tests/test_gui_window.py` | `test_cursor_monitor_lookup_uses_nearest_fallback` | Mock cursor/Win32 monitor handles | Pointer monitor is selected; invalid point uses nearest | Primary/raw screen is used despite a valid target monitor |
| `tests/test_gui_window.py` | `test_windows_monitor_provider_preserves_pointer_width_handle` | Mock `HMONITOR > 0xFFFFFFFF` | Full handle reaches `GetMonitorInfoW`; valid `rcWork` returns | Handle is truncated or provider falls back |
| `tests/test_gui_window.py` | `test_root_monitor_lookup_follows_cursor_failure` | `GetCursorPos` fails | Root-window monitor supplies `rcWork` | Provider fails before root fallback |
| `tests/test_gui_window.py` | `test_child_work_area_uses_parent_monitor_not_pointer_monitor` | Parent and pointer on different monitors | Child resolves/clamps to parent monitor | Child follows launch/current pointer |
| `tests/test_gui_window.py` | `test_child_geometry_is_clamped_inside_parent_monitor` | Large details/success child near edge | Complete child remains in work area | Child opens off-screen |
| `tests/test_gui_window.py` | `test_hidden_root_outer_bounds_fit_current_work_area_on_windows` | Real withdrawn Tk root and current Win32 work area | Final `GetWindowRect` is wholly inside selected `rcWork`; skip only off-Windows/no display | Any outer edge exceeds work area |

### 9.2 GUI shell/theme/QOL tests

Command for every row: `python -B -m unittest tests.test_gui_input`

| File | Required/existing test | Scenario | Expected result | Failure condition |
| --- | --- | --- | --- | --- |
| `tests/test_gui_input.py` | Existing `test_read_inputs_accepts_kml_file` | Vector input parsing | Same tuple values and simplification behavior | Parsed values/defaults differ |
| `tests/test_gui_input.py` | `test_app_initialization_preserves_caller_withdrawn_root` | Construct app with withdrawn test root | Root remains withdrawn | `BoundaryKmzApp` unexpectedly deiconifies caller root |
| `tests/test_gui_input.py` | `test_main_applies_geometry_before_deiconify` | Mock root/app lifecycle | Order is create → withdraw → build → idle/layout → measured/retried geometry → native chrome → deiconify → mainloop | Flash-prone or test-breaking order is used |
| `tests/test_gui_input.py` | `test_main_surfaces_nonfatal_window_fit_warning_and_still_opens` | Mock `WindowFitResult(contained=False, used_reserve_fallback=True, warning=...)` | Existing status area shows concise warning and lifecycle reaches deiconify/mainloop | Fit result raises, suppresses launch, or warning is hidden |
| `tests/test_gui_input.py` | Existing `test_custom_split_direction_is_normalized`, `test_invalid_custom_split_direction_raises` | Split validation | Current modulo/error behavior remains | Normalization or error behavior changes |
| `tests/test_gui_input.py` | Existing `test_settings_key_includes_split_direction`, `test_settings_key_normalizes_vector_outline_modes`, `test_settings_key_includes_generation_profile`, `test_settings_key_includes_vector_simplification_toggle` | Cache-key semantics | Exact existing distinctions remain | Any key field/normalization/profile distinction changes |
| `tests/test_gui_input.py` | Existing `test_vector_input_disables_outline_mode`, `test_folder_input_disables_vector_simplification_toggle`, `test_split_direction_controls_only_enable_for_multiple_sections` | Dependency states | Current enabled/disabled rules remain after reparenting | Any control enters a state forbidden by current rules |
| `tests/test_gui_input.py` | `test_shell_uses_preview_as_only_expanding_content` | App initialization | Preview cell owns the expanding row/column | A settings/input/action row consumes expansion weight |
| `tests/test_gui_input.py` | `test_permanent_actions_are_mapped_in_empty_state` | No input | Update and Export are mapped and in bounds | Either action is hidden or outside client |
| `tests/test_gui_input.py` | `test_permanent_actions_are_mapped_in_selected_state` | Input selected | Actions remain mapped and in bounds | Either action is hidden or outside client |
| `tests/test_gui_input.py` | `test_action_bar_crosses_computed_breakpoint_without_recreating_widgets` | Resize around computed threshold repeatedly | Same widgets re-grid between two/one rows only on transitions | Widgets recreate, thrash, or actions leave bounds |
| `tests/test_gui_input.py` | `test_action_bar_breakpoint_expands_for_large_requested_widths` | Mock 200%-scale left/right requested widths above 1120 | Computed breakpoint grows and two-row bar remains in bounds | Fixed 1120 threshold clips/wraps controls |
| `tests/test_gui_input.py` | `test_preview_workspace_meets_normal_target` | `1440 x 741` client | Workspace >= `1360 x 520`; actions in bounds | Threshold/action contract fails |
| `tests/test_gui_input.py` | `test_preview_workspace_meets_short_target` | `1440 x 612` client | Workspace >= `1360 x 390`; actions in bounds | Threshold/action contract fails |
| `tests/test_gui_input.py` | `test_preview_workspace_meets_nominal_minimum_target` | `960 x 600` client | Workspace >= `900 x 350`; actions in bounds | Threshold/action contract fails |
| `tests/test_gui_input.py` | `test_empty_input_shows_drop_overlay` | Initial state | Large drop/browse surface visible | No obvious drop/browse path |
| `tests/test_gui_input.py` | `test_selected_input_compacts_drop_overlay` | `_set_input_path` | Large surface hidden; compact strip visible | Input surface still consumes preview or disappears entirely |
| `tests/test_gui_input.py` | `test_typed_input_compacts_and_clearing_restores_empty_overlay` | Type/paste non-empty path then clear | Compact editable state, then large empty state; no validation runs automatically | Typed path is lost/inaccessible or clearing fails to restore |
| `tests/test_gui_input.py` | `test_empty_and_compact_drop_targets_register_and_style_event_widget` | Initial/compacted states plus drag enter/leave | Both widgets receive DnD bindings and only active event surface changes feedback style | A target is unbound or code still hard-codes old label |
| `tests/test_gui_input.py` | `test_drop_registration_failure_keeps_browse_available` | Mock `drop_target_register`/`dnd_bind` failure | App opens, warning is styled, both Browse actions work | Startup fails or browse is disabled |
| `tests/test_gui_input.py` | `test_drop_is_ignored_while_busy` | Invoke DnD handler during worker | Input/output/defaults remain unchanged; wait status shown | Canonical state changes under in-flight result |
| `tests/test_gui_input.py` | `test_drawer_reuses_canonical_variables` | Edit quick/drawer controls | Both reflect identical canonical Tk variable values | Duplicate/desynchronized state appears |
| `tests/test_gui_input.py` | `test_dependency_states_cover_quick_and_drawer_widget_registries` | Change input type, shapes, split mode, and busy state | Every duplicated control follows vector/folder/multiple/custom rules | One copy remains enabled/disabled incorrectly |
| `tests/test_gui_input.py` | `test_drawer_toggle_preserves_values_and_view_limits` | Repeated open/close | Values and axes limits unchanged | Toggle resets data or view |
| `tests/test_gui_input.py` | `test_key_toggle_preserves_view_and_callback_count` | Repeated open/close | Four main event IDs; no view reset | Callback count grows or limits reset |
| `tests/test_gui_input.py` | `test_settings_and_key_overlays_are_mutually_exclusive` | Cross-toggle Settings/Key | Exactly one overlay is mapped; Escape target is deterministic | Both overlap or z-order is ambiguous |
| `tests/test_gui_input.py` | `test_overlay_wheel_binding_does_not_steal_preview_zoom` | Open/close each overlay; wheel over preview | Main axes zoom exactly as before | Overlay/global binding consumes preview wheel |
| `tests/test_gui_input.py` | `test_key_overlay_remains_scrollable_with_maximum_sections` | Render `MAX_SECTION_COUNT` entries | Key scrollregion covers all 100 items; actions remain visible | Entries/actions are clipped or page expands |
| `tests/test_gui_input.py` | `test_theme_defines_required_named_styles` | Theme setup | Every Section 3.3 style resolves | A style is absent or invalid |
| `tests/test_gui_input.py` | `test_theme_fallback_retains_button_invoke_and_disabled_state` | Rounded-element creation fails | Flat style works; command/state preserved | Startup/command/state fails |
| `tests/test_gui_input.py` | `test_raw_tk_and_matplotlib_surfaces_use_dark_tokens` | App initialization/draw | No default white main surface | Raw Tk/Matplotlib surface remains unthemed |
| `tests/test_gui_input.py` | `test_matplotlib_theme_survives_result_empty_result_clear_cycles` | Draw result, empty state, result | Axes/figure remain dark after every `axes.clear()` | A redraw restores default light axes |
| `tests/test_gui_input.py` | `test_windows_native_chrome_failure_is_nonfatal` | Mock non-Windows, invalid HWND, and failed DWM HRESULT | Helper returns false and app/Toplevel remains functional | Exception or startup/dialog failure |
| `tests/test_gui_input.py` | `test_windows_native_chrome_targets_pointer_width_wrapper_hwnd` | Content HWND has >32-bit wrapper parent | DWM receives full wrapper HWND and fixed 35→36→20 attribute order | Child/truncated handle or wrong order is used |
| `tests/test_gui_input.py` | `test_buffer_change_invalidates_cache_and_marks_preview_stale` | Edit buffer only | Cache cleared; stale true; no worker | Cache survives, badge stays current, or worker starts |
| `tests/test_gui_input.py` | `test_output_change_with_touched_shape_label_keeps_geometry_current` | Edit output name/path after a user-touched label | Existing cache invalidation occurs; effective label/signature stays unchanged and badge stays current | Displayed geometry is labeled stale or label changes |
| `tests/test_gui_input.py` | `test_output_change_with_default_shape_label_marks_preview_stale` | Edit output name/path while label follows default | Derived shape label changes and preview/key become stale | Badge remains current despite changed displayed labels |
| `tests/test_gui_input.py` | `test_setting_change_keeps_displayed_result_and_marks_stale` | Edit sections | Canvas result remains; stale badge visible | Canvas clears or still claims current |
| `tests/test_gui_input.py` | `test_input_change_clears_previous_preview` | Change source | Old canvas/key removed | Old-source geometry remains visible |
| `tests/test_gui_input.py` | `test_scan_done_marks_preview_current` | Queue scan result | Stale false; displayed result updated | Result remains stale or is not drawn |
| `tests/test_gui_input.py` | `test_error_keeps_safe_state_and_restores_actions` | Queue error | Busy false; prior safe display plus error/stale text | UI remains busy/blank or error is hidden |
| `tests/test_gui_input.py` | `test_update_preview_routes_existing_arguments` | Click Update with mocked start | Existing parsed values and route remain unchanged | Any worker/core argument differs |
| `tests/test_gui_input.py` | `test_export_action_uses_existing_export_handler` | Invoke Export button | `_export_clicked` remains the direct command | A parallel/new export path is used |
| `tests/test_gui_input.py` | `test_scan_validation_dialog_receives_root_parent` | Mock invalid scan input | Existing error text/return path; `parent is app.root` | Wrong/no parent or worker starts |
| `tests/test_gui_input.py` | `test_export_validation_and_overwrite_dialogs_receive_root_parent` | Invalid export and existing-output confirm/cancel | Every dialog gets root parent; cancel prevents worker; confirm preserves route | Wrong/no parent or overwrite semantics change |
| `tests/test_gui_input.py` | `test_browse_and_save_dialogs_receive_root_parent_and_preserve_cancel` | Cancel folder, KML/KMZ, and Save As pickers | Every picker gets root parent; canonical values remain unchanged | Wrong/no parent or cancellation mutates state |
| `tests/test_gui_input.py` | `test_busy_state_disables_all_mutable_controls` | `_set_busy(True)` | Input/settings/quick controls disabled | In-flight settings remain editable |
| `tests/test_gui_input.py` | `test_busy_state_disables_browse_save_input_output_and_inspector_apply` | `_set_busy(True)` | All mutation fields/actions are disabled; Key/view-only controls remain | Any named mutation route stays active |
| `tests/test_gui_input.py` | `test_busy_state_restores_dependency_aware_states` | `_set_busy(False)` | Vector/section rules reapplied | Controls are blindly enabled |
| `tests/test_gui_input.py` | `test_focus_mode_retains_actions_settings_key_toolbar_and_inspector` | Enter focus | Main canvas reused; all key actions and Inspector access remain | Canvas is recreated or capability disappears |
| `tests/test_gui_input.py` | `test_focus_mode_repeated_cycles_do_not_duplicate_callbacks` | Multiple cycles | Exactly four main callback IDs | Callback count grows |
| `tests/test_gui_input.py` | `test_focus_mode_restores_preentry_geometry_state_and_shell_rows` | Enter/exit from normal and already-maximized root | Normal state/geometry/rows restore; maximized view never shrinks | Root/shell remains altered |
| `tests/test_gui_input.py` | `test_escape_closes_overlay_before_exiting_focus` | Overlay + focus | Correct close order | Focus exits first or Escape traps focus |
| `tests/test_gui_input.py` | `test_shortcuts_do_not_start_work_while_busy` | Shortcut during worker | No second worker | Concurrent worker starts |
| `tests/test_gui_input.py` | Existing `test_preview_toolbar_is_initialized`, `test_preview_interaction_callbacks_are_registered` | Main toolbar/callback initialization | Existing toolbar and four main callbacks remain | Toolbar/callback behavior regresses |
| `tests/test_gui_input.py` | Existing `test_preview_scroll_inside_axes_changes_limits`, `test_preview_scroll_outside_axes_is_ignored`, `test_preview_left_drag_pans_and_release_clears_state`, `test_preview_left_drag_defers_to_active_toolbar_mode`, `test_preview_left_drag_same_pixel_does_not_accumulate_motion` | Main canvas interaction | Current pan/zoom/tool-mode semantics remain | Any interaction assertion fails |
| `tests/test_gui_input.py` | Existing `test_preview_polygon_xy_decimates_large_polygon_and_preserves_closure` | Dense preview | Decimation and ring closure remain | Too many points or open ring |
| `tests/test_gui_input.py` | Existing `test_preview_long_corridor_uses_full_axes_with_equal_map_scale` | Main canvas long corridor | Full axes and equal scale remain | Crop/distortion occurs |
| `tests/test_gui_input.py` | Existing `test_fullscreen_preview_opens_canvas_toolbar_and_controls` | Open detached Inspector | Canvas, toolbar, section controls, key, and close exist | Existing Inspector capability is absent |
| `tests/test_gui_input.py` | Existing `test_fullscreen_preview_draws_cached_result` | Inspector with cached result | Current result is drawn | Inspector opens empty/wrong |
| `tests/test_gui_input.py` | `test_inspector_opens_last_displayed_stale_result_after_cache_invalidation` | Edit preview setting, then open Inspector | Last drawn result remains visible with stale text; no cache reuse implied | Inspector is blank or labels result current |
| `tests/test_gui_input.py` | Existing `test_fullscreen_long_corridor_uses_full_axes_with_equal_map_scale` | Inspector long corridor | Full axes and equal scale remain | Crop/distortion occurs |
| `tests/test_gui_input.py` | Existing `test_fullscreen_apply_syncs_controls_and_starts_preview` | Inspector Apply | Current synchronization/start route remains | Apply flow changes or fails |
| `tests/test_gui_input.py` | Existing `test_fullscreen_direct_pan_uses_independent_canvas` | Inspector pan | Detached canvas remains independent and pannable | Main/Inspector state is conflated |
| `tests/test_gui_input.py` | `test_inspector_reopen_lifts_existing_window` | Open Inspector twice | Existing window is lifted/focused, not duplicated | A second Toplevel/canvas is created |
| `tests/test_gui_input.py` | `test_inspector_uses_work_area_safe_geometry` | Mock negative/short parent monitor | Inspector remains within `rcWork` | Hard-coded primary/full-screen geometry is used |
| `tests/test_gui_input.py` | Existing/adapted `test_scan_done_auto_selected_polyline_buffer_updates_buffer_field` | Queue result auto-updates `buffer_var` and fires new trace | Effective buffer sync remains, cache is populated, displayed signature captures the effective value, and `_preview_stale is False` after draw | Trace clears fresh cache or leaves successful result stale |
| `tests/test_gui_input.py` | `test_export_done_marks_display_current_and_preserves_export_contract` | Queue an `export_done` payload | Result draws/current signature captures, busy clears, success route uses saved path | Stale state/queue payload/export behavior changes |

### 9.3 Core/integration regression tests

| File | Existing test/suite | Scenario | Expected result | Failure condition | Exact command |
| --- | --- | --- | --- | --- | --- |
| `tests/test_core_regression.py` | `CoreRegressionTests.test_vector_preview_profile_skips_export_simplification` | Preview-quality vector result | Preview skips export simplification and cannot be saved | Preview is export-simplified or `save_kmz` accepts it | `python -B -m unittest tests.test_core_regression.CoreRegressionTests.test_vector_preview_profile_skips_export_simplification` |
| `tests/test_core_regression.py` | `CoreRegressionTests.test_export_profile_after_preview_still_simplifies_and_saves` | Export after preview | Export-quality regeneration simplifies and saves | Preview cache is incorrectly exported or save fails | `python -B -m unittest tests.test_core_regression.CoreRegressionTests.test_export_profile_after_preview_still_simplifies_and_saves` |
| `tests/test_core_regression.py` | `CoreRegressionTests.test_kmz_input_still_works` | Existing KMZ path | Same result contract | KMZ route regresses | `python -B -m unittest tests.test_core_regression.CoreRegressionTests.test_kmz_input_still_works` |
| `tests/test_core_regression.py` | `CoreRegressionTests.test_kml_polyline_input_routes_to_linework_buffer` | KML line input | Existing buffer route and metadata | Input routes to wrong core path | `python -B -m unittest tests.test_core_regression.CoreRegressionTests.test_kml_polyline_input_routes_to_linework_buffer` |
| `tests/test_core_regression.py` | `CoreRegressionTests` (all existing methods) | Folder/KML/KMZ dispatch, profiles, simplification, sectioning, saves, negative modes | All existing assertions pass | Any existing core regression fails | `python -B -m unittest tests.test_core_regression` |
| `tests/test_kml_vector_input.py` | `KmlVectorInputTests` (all existing methods) | KML/KMZ parsing and malformed inputs | All current parse/error behavior remains | Any parser assertion fails | `python -B -m unittest tests.test_kml_vector_input` |
| `tests/test_polyline_boundary.py` | `PolylineBoundaryTests` (all existing methods) | Line buffering, zero buffer, holes, disconnection | All current geometry/error behavior remains | Any buffer assertion fails | `python -B -m unittest tests.test_polyline_boundary` |
| `tests/test_natural_sectioning.py`, `tests/test_section_ordering.py` | `NaturalSectioningTests`, `NaturalPairOrientationTests`, `BranchedSectionOrderingTests` | Shapes, overlap, direction, labels/order | All section behavior remains | Any section/order assertion fails | `python -B -m unittest tests.test_natural_sectioning tests.test_section_ordering` |
| `tests/test_outline_strategies.py`, `tests/test_camera_preflight.py` | `OutlineStrategyTests`, `CameraPreflightTests` | JPG outline strategy/preflight | All camera classification/outline behavior remains | Any outline/preflight assertion fails | `python -B -m unittest tests.test_outline_strategies tests.test_camera_preflight` |
| `tests/test_geometry_hardening.py` | `GeometryHardeningTests` (all existing methods) | Geometry cleanup/export safety | All hardening behavior remains | Any geometry assertion fails | `python -B -m unittest tests.test_geometry_hardening` |
| `tests/**` | Full discovery suite | All adjacent workflows and backward compatibility | Complete suite passes | Any discovered test errors/fails | `python -B -m unittest discover -s tests` |

### 9.4 Manual GUI validation matrix

#### Startup and monitors

- From the repository root, run each command separately, confirm the same themed GUI opens without an import error, verify initial bounds/actions, and close it before the next command:

```powershell
python -B .\run_jpg_boundary_gui.py
python -B .\src\run_jpg_boundary_gui.py
.\run_jpg_boundary_gui.bat
```

- From an external current directory, repeat every entry point by absolute path:

```powershell
Push-Location ([System.IO.Path]::GetTempPath())
try {
    python -B 'C:\Users\rbake\Desktop\VS Code Shortcuts\Create-Polygon-Border-From-JPGs\run_jpg_boundary_gui.py'
    python -B 'C:\Users\rbake\Desktop\VS Code Shortcuts\Create-Polygon-Border-From-JPGs\src\run_jpg_boundary_gui.py'
    & 'C:\Users\rbake\Desktop\VS Code Shortcuts\Create-Polygon-Border-From-JPGs\run_jpg_boundary_gui.bat'
} finally {
    Pop-Location
}
```

Run those three external-CWD commands one at a time (close each GUI before continuing); the block shows the exact paths, not a request to run three blocking GUI processes simultaneously.

- Launch the batch entry point on:
  - primary 2048 x 824 work area;
  - positive-offset monitor;
  - negative-offset monitor;
  - 2560 x 680 work area.
- Confirm selected monitor, centered placement, title bar, bottom action bar, and taskbar are all visible; run `test_hidden_root_outer_bounds_fit_current_work_area_on_windows` on that configuration as the exact `GetWindowRect` containment assertion.
- Repeat with taskbar bottom, top, and side if configuration is available.
- Move/relaunch at 100%, 125%, 150%, and 200% scaling.
- Change primary monitor or reconnect via RDP; verify fallback remains in bounds.

#### Layout and state

- Empty state: drop, Browse Folder, Browse KML/KMZ, Settings, actions.
- Select each input type; verify compact strip and retained drop.
- Resize to compact, normal, and wide clients; verify no main scroll and permanent actions.
- Open each drawer group on the 680 px work area; verify drawer-only scroll when needed.
- Toggle Key and Focus repeatedly; verify no view reset or duplicate behavior.
- Test long paths and labels.

#### Functional parity

- Before export smoke testing, create a unique directory outside the repository:

```powershell
$validationRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("JpgBoundaryGuiValidation-" + [guid]::NewGuid().ToString("N"))
$null = New-Item -ItemType Directory -Path $validationRoot
```

- Folder preview with each outline mode.
- KML polygon and KML/KMZ line input.
- Buffer 0 and positive buffer.
- Vector simplify off/on.
- One shape and multiple shapes.
- Overlap and each split-direction mode, including invalid custom values.
- Preview, pan, wheel zoom, toolbar pan/zoom/home/save.
- View Details.
- Save As and View Output Folder.
- Existing-output overwrite cancel/confirm.
- Successful export and completion dialog, with Save As pointed only to `$validationRoot\gui-validation.kmz`; verify the file exists and opens/has expected metadata.
- Core/permission error and UI recovery.
- Do not write validation output under repository `outputs/**` or `test_data/**`.
- After validation, resolve both paths, verify `$validationRoot` is a direct child of the system temp directory and has the `JpgBoundaryGuiValidation-` prefix, then remove only that exact directory:

```powershell
$resolvedTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$resolvedValidation = [System.IO.Path]::GetFullPath($validationRoot)
$expectedPrefix = Join-Path $resolvedTemp "JpgBoundaryGuiValidation-"
if (-not $resolvedValidation.StartsWith($expectedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to clean unexpected validation path: $resolvedValidation"
}
Remove-Item -LiteralPath $resolvedValidation -Recurse -Force
```

#### Keyboard/accessibility

- Tab and Shift+Tab through visible controls.
- Focus indication on dark surfaces.
- F5, Ctrl+Enter, Ctrl+E, Ctrl+comma, Ctrl+L, Escape.
- Verify disabled/readonly text is readable.
- Verify stale/success/error is communicated in text, not color only.

### 9.5 Required test-category accounting

| Category | Coverage | Applicability/result |
| --- | --- | --- |
| Unit tests | Section 9.1 pure geometry/provider tests; Section 9.2 state/style helpers | Required |
| Integration tests | GUI button/dialog/queue routes in Section 9.2; core module suites in Section 9.3 | Required |
| Regression tests | Every existing GUI test retained/adapted plus complete 99-test baseline successor | Required |
| Smoke tests | Batch launcher, external-CWD launcher, monitor, DnD/browse, preview, and temp export matrix | Required |
| CLI/API tests | No CLI arguments, HTTP API, service, or payload schema exists; both launcher entry points remain unchanged and receive smoke coverage | Not applicable beyond launcher smoke |
| Fixture updates | No fixture update is needed; `test_data/**` is protected/excluded | Not applicable and forbidden |
| Negative/error paths | Invalid input/value, DnD absence, Win32/DWM failure, overwrite cancel, permission/core error, busy drop, and provider fallback | Required |
| Backward compatibility | Protected AST/body audit, protected-file diff, all core suites, full discovery, and retained Inspector behavior | Required |

## 10. Pre-implementation checklist

- [x] Planning guide read in full.
- [x] Current branch and dirty status documented.
- [x] Pre-existing user modification to the planning guide documented and protected.
- [x] Repository files, launchers, requirements, GUI, core imports, tests, and prior preview contracts inspected.
- [x] No runtime environment variable/config-key contract exists; no new one is introduced.
- [x] Dependency file inspected; no lockfile, packaging build, configured linter/type checker/formatter, or CI pipeline exists.
- [x] Current startup clipping reproduced and measured.
- [x] Current seven-monitor work areas and negative coordinates inspected.
- [x] Current DPI-awareness/scaling state inspected.
- [x] Current GUI and full test baselines pass.
- [x] Reference template guide, runtime, layout patterns, palette, and launcher sizing inspected.
- [x] GUI framework choice resolved.
- [x] Dependency choice resolved.
- [x] Monitor-selection and sizing behavior resolved.
- [x] Single-page layout, drawer, key, action, stale, and focus behavior resolved.
- [x] Core/backend protected boundary defined.
- [x] Strict file allow-list complete.
- [x] Explicit excluded-file list complete.
- [x] Phase gates, failure conditions, and rollback defined.
- [x] Automated and manual test matrix defined.
- [x] Edge cases and regression risks reviewed.
- [x] No secret, credential, remote-system write, or source-data mutation is involved; the only validation writes are the exact system-temp manifest and unique system-temp export directory defined in Sections 8 and 9.
- [x] No unresolved item requires an open-decisions sidecar.
- [x] No temporary open-decisions sidecar was created; no stale reference requires deletion.
- [x] Full-plan audit completed for internal consistency.
- [x] Final readiness certification in Section 14 is `YES`.

At implementation start, re-run Phase 0. A later conflicting worktree change invalidates this checklist until re-audited.

## 11. Post-implementation validation checklist

### Automated

- [ ] `python -B -m unittest tests.test_gui_window` passes.
- [ ] `python -B -m unittest tests.test_gui_input` passes.
- [ ] `python -B -m unittest tests.test_core_regression` passes.
- [ ] `python -B -m unittest discover -s tests` passes.
- [ ] In-memory compile command passes without writing bytecode.
- [ ] `git diff --check` passes.

### Scope and contract

- [ ] `git status --short --untracked-files=all`, baseline `git diff 38fd82b --name-only`, and `git ls-files --others --exclude-standard` are reconciled by the exact strict allow-list script.
- [ ] Baseline-aware protected-file `git diff 38fd82b --exit-code -- <protected paths>` passes, including `.vscode/settings.json`.
- [ ] Phase 0 vs Phase 5 path/length/SHA-256 manifest proves `outputs/**`, `test_data/**`, and the user's planning-guide modification are unchanged; the exact temp manifest is then removed.
- [ ] Protected GUI-method AST audit against `38fd82b` passes.
- [ ] No core import signature or call argument changed.
- [ ] Preview/export generation-profile separation remains.
- [ ] Full `_settings_key` semantics remain.
- [ ] Vector simplification GUI default remains false.
- [ ] No runtime dependency or launcher changed.
- [ ] Core public interfaces and naming conventions remain consistent; the currently absent runtime config structures/keys, database schemas/migrations, CLI arguments, service/HTTP APIs, and API payload schemas remain absent.
- [ ] No AALLC file/asset/code bundle was copied.
- [ ] No implementation-introduced repository temp/generated artifact or production debug/placeholder/TODO/mock logic remains; intentional test mocks are permitted.
- [ ] No open-decisions sidecar for this plan or stale reference to one exists; unrelated prior decision records remain untouched.

### GUI acceptance

- [ ] Startup fits the taskbar-safe work area on primary, negative-offset, and 680 px-height monitors.
- [ ] Initial placement is centered on the selected launch monitor.
- [ ] Main page has no scrollbar.
- [ ] Settings are reachable; drawer-only scroll appears only when required.
- [ ] Empty-state drop/browse works.
- [ ] Selected-input compaction works and retains a drop target.
- [ ] Preview workspace meets the exact `1360 x 520`, `1360 x 390`, and nominal `900 x 350` thresholds at the Section 1.5 client sizes.
- [ ] Key overlay no longer permanently consumes 340+ px.
- [ ] Update Preview and Export KMZ are visible in every state and supported size.
- [ ] All current input/output/section controls remain accessible.
- [ ] All current dialogs/actions remain functional.
- [ ] Preview stale/current/error/busy states are explicit.
- [ ] Setting edits do not auto-run preview.
- [ ] Busy state prevents conflicting edits/actions.
- [ ] Pan, wheel zoom, toolbar modes, full fit, decimation, and equal aspect remain.
- [ ] Focus mode reuses the main canvas/state without regressing the retained detachable Inspector.
- [ ] Inspector open/reopen, independent Apply, pan/zoom, key, close, theme, and work-area placement pass.
- [ ] Theme covers ttk, raw Tk, Matplotlib, toolbar, Details, and success dialog.
- [ ] Focus, disabled, readonly, success, warning, and error states remain legible.
- [ ] Keyboard traversal and shortcuts pass.

### Documentation

- [ ] README matches delivered UI and shortcuts.
- [ ] README dependency list remains accurate.
- [ ] README continues to describe the app as portable and core behavior accurately.

## 12. Rollback/recovery plan

### 12.1 Phase-level rollback

| Phase | Revert | Preserved data/output impact |
| --- | --- | --- |
| 1 Window geometry | Remove helper import/calls/module/tests; restore previous root minimum. | No user data or generated output involved. |
| 2 Theme | Remove style application/module/tests. | No user data or generated output involved. |
| 3 Shell | Restore prior `_build_ui` and drop/key placements while retaining independently validated Phase 1 sizing and Phase 2 theme. | Canonical variables and core are unchanged. |
| 4 QOL/focus/Inspector styling | Revert stale/busy/shortcut/focus and Inspector presentation/placement hunks; restore the original Inspector presentation. | Cache is in-memory only; no output migration. |
| 5 Documentation | Revert README wording. | No runtime impact. |

### 12.2 Failure isolation

- Monitor-provider failure falls back to the Tk primary-screen rectangle at `(0, 0)` and never to the virtual-root union; outer-frame measurement/nonconvergence falls back to the conservative reserved geometry and a nonfatal warning/result flag.
- Rounded ttk element failure falls back to flat named styles.
- DnD registration failure retains browse actions.
- Focus-mode failure removes only the new focus feature; the existing separate Inspector remains available throughout.
- Drawer height failure permits internal drawer scrolling while action bar stays fixed.
- Any core regression stops the phase; no “temporary” core patch is authorized.
- The Phase 0 protected manifest remains available through failure investigation; after a successful comparison, or when an implementation run is explicitly abandoned, remove only its validated exact system-temp path.

### 12.3 Output and migration considerations

- There is no database, schema, API, persistent settings file, migration, or server.
- Existing KMZ outputs require no cleanup or conversion.
- Window position/size is not persisted, so rollback cannot strand an off-screen saved geometry.
- Theme state, overlay state, and stale state are in-memory only.
- No generated file format or name changes.

### 12.4 Recovery verification

After rollback:

```powershell
python -B -m unittest tests.test_gui_input
python -B -m unittest discover -s tests
git diff --check
git status --short --untracked-files=all
```

Confirm protected files and outputs remain unchanged.

## 13. Blockers or items requiring clarification

There are no unresolved questions, decisions, assumptions requiring confirmation, approvals, blockers, missing evidence, ambiguities, or required user inputs.

No temporary open-decisions sidecar was created because every material implementation choice has a fixed, evidence-backed requirement and fallback in this plan.

## 14. Final readiness assessment

The plan was audited end to end against the required 14-section format, current repository evidence, the template evidence, the current runtime/monitor environment, the passing test baseline, the file allow-list, phase gates, tests, edge cases, rollback, and protected backend contract.

```text
Implementation Ready: YES
No unresolved questions, decisions, assumptions requiring confirmation, approvals, blockers, missing evidence, ambiguities, or required user input remain.
```
