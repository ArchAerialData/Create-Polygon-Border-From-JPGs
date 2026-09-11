# Boundary workspace UI refresh

## Scope

Presentation and desktop interaction only. Geometry generation, EXIF/vector
parsing, sectioning, KMZ serialization, and imagery fetching are unchanged by
this refresh. The earlier closed-loop polygon patch remains separate in the
working tree. No web runtime or new direct dependency is introduced.

## Reference applications

Read-only references supplied by the user:

- `AALLC-GUI-Template/gui/static/css/docker-theme.css`: charcoal surfaces,
  `#314dec` primary blue, white/secondary text, and semantic success colors.
- `AALLC-GUI-Template/gui/static/css/header-theme.css`: `#012458` navy brand
  header and separation between branding and workspace controls.
- `client_portal_v2/static/css/components/buttons.css`: consistent action
  sizing, visible keyboard focus, and container-based wrapping.
- `client_portal_v2/static/css/components/date-range.css`: grouped fields in
  panels constrained to the available viewport, with internal scrolling.
- `client_portal_v2/static/reports/tracker.js` and `tracker.css`: explicit
  loading states within the preview surface, with the surrounding shell intact.

The user confirmed `C:\Users\rbake\Documents\GitHub\client_portal_v2` as the
intended portal reference. Its source files were not modified. Web-specific
components were translated into existing native Tk controls rather than
embedding those applications or copying their runtime dependencies.

## Implementation

- `src/jpg_boundary_gui_theme.py` owns shared typography, color tokens,
  button and field states, and scalable checkbox indicators. Native widget semantics
  and fallback styling are retained.
- `src/jpg_boundary_gui_controls.py` contains the native Input dropdown and
  hover/focus help. No processing logic lives in these components.
- `src/jpg_boundary_kmz_gui.py` owns the new shell and contextual settings,
  measured responsive layouts, busy feedback, duplicate-submit guards, and
  nonmodal export completion linked to the actual saved destination.
- The worker arguments, generation profiles, cache keys, and export calls
  retain their existing behavior. New inputs automatically generate a preview;
  subsequent settings edits are applied with Update Preview.

## Validation

Imported KML/KMZ linework is retained in `BoundaryResult.source_lines_projected`
in the result CRS. Both preview surfaces draw the original features separately
above the buffered output and include them in the legend. No file reread is
needed when redrawing or opening Inspector; export geometry still comes from
the existing final polygon and sections. The GUI now defaults the vector
simplification checkbox to enabled, matching the core API's existing default.

The footer includes Buffer, Shapes, Overlap, and Shape label using the canonical
variables and worker-disabled states. The controls stay visible and wrap rather
than disappearing on compact layouts. Original settings pages are preserved.
Source geometry round-trip checks cover KML/KMZ and preview/export profiles;
GUI checks cover separate source features on both canvases, synchronized footer
editing, default simplification/opt-out, and control bounds at different scales.
Offline screenshots were inspected at 1500×820 and 960×600.

At system-aware 125% scaling, the existing extreme-attribution test (500 repeated
W characters) overlaps the scale bar. This was reproduced by loading the
pre-change HEAD GUI in memory with the same DPI startup, independently of this
patch. The existing missing-KML-fixture failure is described below.
The latest full run executed 232 tests with one opt-in skip; failures were the
missing fixture and the three attribution subcases described above. The focused
source-overlay, footer, simplification-default, and responsive-layout checks pass.

Windows startup now selects system DPI awareness before Tk creates its first
window. Existing awareness chosen by an embedding host is respected; older
Windows APIs are fallbacks. System awareness is intentional for Tk 8.6's shared
font/image scale. Live per-monitor rescaling would additionally need rebuilding
those resources on monitor transitions and is not implemented here.

A fresh-process Windows check confirmed awareness `1` (system-aware), window
DPI `120`, system DPI `120`, and Tk resolution approximately `120` pixels/inch.
The embedded Matplotlib canvas reported a device pixel ratio of `1.25` and
figure DPI `125`, so no manual doubling of the preview resolution was added.
The rendered settings window was inspected using an OS screenshot. The new
fresh-process regression checks actual Windows DPI state, not mocked API calls.

Field labels now use a dedicated white style in normal and disabled states.
Loading via Browse, drop, or committing the input field resets buffer to zero
and outline mode to Auto, then starts the existing background preview worker.
Polygon inputs retain zero buffer; line inputs use the existing Auto search and
effective-buffer synchronization. Tests cover actual polygon and line geometry
through the worker/result queue, folder loading, typed-path and drop triggers,
and white disabled headings. Re-focusing an already loaded path preserves edits
and does not launch another preview.

Browse dialogs now start at This PC on Windows. Tk 8.6 normalizes bare shell
addresses, so the app creates a reusable empty shell namespace folder under
`%LOCALAPPDATA%/JpgBoundaryToKmz/Shell`. This follows Microsoft's
[shell namespace folder convention](https://learn.microsoft.com/en-us/windows/win32/shell/nse-junction).
It does not change Explorer preferences or the export destination. Windows Shell
resolved the location as `This PC` and enumerated its contents; both existing
browse-cancellation checks passed. If local application data is unwritable, or
on other platforms, browsing falls back to the home folder.

`python -B -m unittest discover -s tests` runs the offline regression suite.
The implementation run completed 225 tests: 223 passed, one live-service test
was skipped, and the missing-fixture test described below failed. Final targeted
checks for attribution, scaling, menus, and activity feedback also passed.
Focused UI checks are in `tests/test_gui_input.py`, including:

- Named menu selection and dismissal without invalidating the preview.
- View-menu dismissal and Escape behavior.
- Busy-state feedback, timer cleanup, and prevention of duplicate work.
- Nonmodal completion and opening the correct saved folder after a later edit.
- Control bounds at 720×500 and 960×600, plus larger text at 1100×760.
- Preview space, overflowing panels, imagery attribution, and existing input,
  Inspector, focus, keyboard, map navigation, and shared-state contracts.

An offline visual harness is available for manual review:

```powershell
python -B -m tests.preview_gui --state empty --geometry 1280x800+40+40
python -B -m tests.preview_gui --state sections --geometry 960x600+40+40
python -B -m tests.preview_gui --state busy --geometry 1100x760+40+40 --scale 2
```

It uses synthetic test data and turns imagery off before rendering. Other
states are `preview`, `boundary`, `output`, and `view`.

The polishing pass replaced nested accordion navigation with one focused page
per top-level settings menu. Labels sit above full-width fields; custom angles
appear only when relevant. Rounded image borders preserve the native Entry,
Combobox, and Spinbox controls, including arrow hit targets, keyboard editing,
disabled state, and focus. Explicit disabled-label background maps remove the
inherited light rectangles. Canvas and drop-target backgrounds use shared tokens,
including restoration of the correct surface after drag feedback.

The native computer-use capture backend cannot capture this Windows version
(`SetIsBorderRequired: No such interface supported`). The screenshot skill's OS
fallback was used to inspect the rendered boundary and disabled section pages at
1180×760, plus a scrolled custom-angle form at 960×600. Temporary review windows
were closed afterward. Widget tests also cover 720×500 and larger text scaling.
The welcome card now stays beside the settings panel, or gives way when the
remaining width is too small. The main map no longer repeats a caption behind it.

The checkout is missing the fixture required by
`test_problem_polyline_kml_auto_selects_regular_buffer`:
`test_data/new-failures-debugging/input-kml/photo_polylines_20260702_095008.kml`.
That pre-existing test failure is unrelated to the UI changes. The live Esri
smoke test remains opt-in.
