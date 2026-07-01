# Preview Zoom And Pan Open Questions

Status: resolved decision worksheet.

This file records decisions for the preview zoom and pan follow-up. The main implementation plan is:

```text
docs\preview-zoom-and-pan\preview-zoom-and-pan-implementation-plan.md
```

Execution runbook:

```text
docs\preview-zoom-and-pan\preview-zoom-and-pan-implementation-orchestrator.md
```

## Fixed Decisions

Resolved answers:

```text
D1: Use Matplotlib's built-in NavigationToolbar2Tk for v1.
D2: Reset the preview view to fit on every new Scan / Preview redraw.
D3: Do not add custom mouse-wheel zoom in v1.
D4: Do not add persistent zoom state or new app settings in v1.
D5: Do not change geometry, sectioning, simplification, export, or cache behavior.
D6: Do not launch, inspect, or interact with Metashape for implementation or validation.
```

## Assumption And Unknown Status

| Item | Classification | Status |
|---|---|---|
| Existing preview is Matplotlib/Tk based. | Verified from code | `src/jpg_boundary_kmz_gui.py` imports and uses `FigureCanvasTkAgg`. |
| Matplotlib is already available as a dependency. | Verified from repo | `requirements_jpg_boundary_kmz.txt` lists `matplotlib`. |
| Existing GUI tests can instantiate the app. | Verified from tests | `tests/test_gui_input.py` uses `_create_root` and `_app`. |
| Built-in toolbar is acceptable for v1. | Resolved product decision | Use `NavigationToolbar2Tk`; do not build custom controls. |
| Reset-to-fit is acceptable for each new preview. | Resolved product decision | Redraws should not preserve stale pan/zoom state. |
| Mouse-wheel zoom and persistent viewport are out of scope. | Resolved product decision | Record as future follow-ups only. |
| No geometry/export changes are needed. | Verified from scope | Feature is GUI inspection only; geometry files are excluded from allow-list. |
| Metashape is not needed for implementation or validation. | Verified from scope | Preview is local Tk/Matplotlib UI only. |

Unresolved decisions:

- None.

## D1. Which Preview Navigation UI Should V1 Use?

### Context

The app already embeds Matplotlib through `FigureCanvasTkAgg` in `src/jpg_boundary_kmz_gui.py`. Matplotlib is already listed in `requirements_jpg_boundary_kmz.txt`, and the preview currently has no toolbar or custom interaction handlers.

### Options

Option A: Use Matplotlib's built-in `NavigationToolbar2Tk`.

Impact:

- Provides Home, Back, Forward, Pan, Zoom, and Save controls with minimal custom code.
- Uses an existing runtime dependency.
- Keeps the first implementation low-risk and easy to validate.

Option B: Build custom preview controls.

Impact:

- Allows tighter UI control and app-specific button labels.
- Requires custom event handling and more tests.
- Higher risk for a first pass.

Option C: Use toolbar plus custom mouse-wheel zoom.

Impact:

- Improves convenience.
- Adds custom event handling on top of the toolbar.
- Better suited for a follow-up after toolbar behavior is stable.

### Resolved Decision

Option A. Use `NavigationToolbar2Tk` for v1.

## D2. What Happens To The View On A New Scan / Preview?

### Context

Users may zoom into one generated result, then change inputs or section settings and run Scan / Preview again. Preserving stale axes could hide the new result or make it look blank.

### Options

Option A: Reset to fit on every redraw.

Impact:

- Every new preview starts fully framed.
- Lower risk of confusing hidden geometry.
- Users can zoom again after the new result appears.

Option B: Preserve the previous view when possible.

Impact:

- Useful for comparing very small setting changes.
- Risky when geometry extents change substantially.
- Requires more state management.

### Resolved Decision

Option A. Every new Scan / Preview redraw resets the view to fit the generated output.

## D3. Should Mouse-Wheel Zoom Be Included?

### Resolved Decision

No. V1 should not include custom mouse-wheel zoom. Record it as a future enhancement if the built-in toolbar is not sufficient.

## D4. Should Zoom/Pan State Be Persisted?

### Resolved Decision

No. Zoom/pan is transient view state only. It must not affect cached preview/export settings and must not persist between app launches.

## D5. Should This Change Affect Geometry Or Export?

### Resolved Decision

No. This task is GUI inspection only. It must not change JPG generation, KML/KMZ parsing, buffering, simplification, sectioning, KMZ export, or output geometry.

## D6. Is Metashape Required For Validation?

### Resolved Decision

No. No implementation step, test, manual check, or gate requires opening, inspecting, automating, or touching any Metashape process, project, task queue, or project artifact.

## Future Follow-Ups

- Mouse-wheel zoom.
- Custom icon buttons or a smaller toolbar.
- Persistent view state for comparing repeated scans.
- A dedicated reset-view button if the Matplotlib toolbar is visually too broad.
