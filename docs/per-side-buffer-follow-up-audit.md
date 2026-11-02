# Per-side buffer follow-up audit

Status: complete. All three original attribution cases and the reproduced audit
findings are resolved. No implementation blockers remain.
Date: September 11, 2026.
Baseline: commit `d9d7f89`, clean working tree before this audit.

## Scope and method

Reviewed per-side geometry, compatibility and import routing, asynchronous result
handling, input validation, direction rendering, export writes, attribution layout,
and GUI shutdown. Reproduced defects with deterministic regression tests before
applying fixes. Existing field defaults, eligibility policy, unified Auto behavior,
and sectioning algorithms remain as documented in the
[implementation plan](per-side-buffer-implementation-plan.md).

## Findings closed

| Finding | Reproduction | Fix and regression coverage |
| --- | --- | --- |
| Tiny side widths could falsely report disconnected geometry. | Seed 92026, route 9, 0.005/0.01 ft: the rounded endpoint and corridor met only at a point after precision-grid union. | Caps overlap inward by a bounded seam tolerance, capped at a quarter of the endpoint segment. No side value or forward cap extent is increased. Forty seeded routes × five width pairs now verify valid connected geometry, source coverage, and reversal invariance. |
| A corrupt same-path reload retained old compatibility. | Import eligible KMZ, enable per-side, corrupt the file, then Update Preview. | Parsing failures publish an ineligible result before the processing error; both checkboxes and side state reset. One error dialog remains. |
| A late result could be labelled current for newer settings. | Change the right-side variable after submission but before consuming the worker result. | Worker requests capture the complete control signature. Results for earlier settings remain visibly stale and cannot overwrite edited values with Auto output. |
| Controls could bind to another Tk interpreter. | Leave a host Tk root alive, then open the app: invoking the checkbox changes its widget state but not the app variable. The broader GUI run reproduced this as disconnected side fields. | All main-window variables explicitly name the app root as their master. A two-root regression checks checkbox toggles, field edits, synchronization, and restoration of the unified value. |
| A JPG directory ending in `.kmz` was routed to the vector loader. | Import a directory whose name ends in the vector extension. | Directory classification takes precedence, matching the backend's existing import routing. |
| Non-finite overlap and invalid backend section parameters reached geometry. | `nan`/`inf` overlap, fractional or Boolean section counts, non-finite split angles. | GUI rejects non-finite overlap before submission. Shared backend section validation rejects invalid counts and distances for both vector and JPG paths. JPG buffer/simplification checks also reject non-finite values. |
| A failed export could replace a good KMZ with partial data. | Inject a disk-write error after the writer produces partial bytes. | Generate the archive in a temporary file beside the destination, close it, then replace the destination. Failure preserves the old file and removes the partial file. |
| Direction arrows cut across corners. | Put a 90-degree vertex at an arrow's target fraction. | Each arrow shaft stays within one original nonzero segment; source coordinates and direction remain unchanged. |
| Attribution text collided with the scale bar in three existing cases. | Existing 500-character unbroken credit test: main Settings, main Key, Inspector Key. Native-window checks also reproduced a 125% DPI overflow. | Replace percentage padding with measured pixel padding and reserve only open overlays. Overflowing credits can use a full-width band above an open panel; normal credits restore the panel. The Inspector minimum scales with Tk's fonts and controls. Full credit text remains at 9 pt. Tests check the background box against the scale and panels, including actual mapped windows. |
| Closing/opening a panel needed attribution reflow without a new imagery response. | Toggle Settings/Key with a loaded long credit and no new basemap frame. | A coalesced idle update rewraps the existing attribution as panels change. |
| Progress/layout callbacks could outlive their window. | Close the app while the progress bar and layout updates are active. | Stop the progress timer and cancel owned queue/layout callbacks during shutdown. The queue poll also retains one scheduled callback instead of accumulating poll chains. |
| Native footer hit-testing was intermittent. | An integrated run returned no window for an active footer control; a focused run also reproduced the failure. | Place the test window explicitly on-screen, keep it above unrelated windows, and process native events after mode changes before checking hit targets. The original hit-test assertion remains; four consecutive focused runs passed. |

## Verification

- Before fixes: full suite ran **258 tests in 114.762 seconds**, reproducing the
  same three attribution subcase failures; one opt-in live-service test skipped.
- Added twelve audit test methods in [test_per_side_audit.py](../tests/test_per_side_audit.py).
  They include **200 deterministic route/width combinations**, each also checked
  with reversed coordinates and swapped side distances. Width pairs include a
  zero side, 0.005/0.01 ft, 350/150 ft, and a 1/2000 ft ratio.
- Neighboring per-side GUI/core and polyline checks also passed during development.
  Export failure tests cover both partial archive writes and a locked destination;
  both preserve the existing file and clean up the temporary archive.
- Final focused per-side GUI and audit run: **20 tests passed in 26.669 seconds**,
  including the multiple-root regression and the native display checks.
- Rechecked the actual `C52 + C53.kmz` at 350/150 ft for **1, 4, and 12 sections**,
  each at 0/50 ft overlap in preview and export: all **12 combinations passed**.
  Verified source coverage, unchanged entered widths, preview union agreement,
  successful temporary exports, and cleanup of intermediate archive files.
  Customer input was read only; test outputs were temporary.
- Native screenshot inspection at **125% scaling** checked Settings and Key at
  960×600, with active 350/150 ft side fields, and the Inspector at its scaled
  800×525 minimum. The full 500-character credit remains visible without touching
  the scale bar or panels. The mapped-window regression also checks that ordinary
  credits restore the full panel height.
  Screenshots in Windows Temp: `codex-shot-2026-09-11_15-10-58.png`,
  `codex-shot-2026-09-11_15-11-00.png`, and `codex-shot-2026-09-11_15-11-01.png`.
- Final integrated run: **270 tests in 141.902 seconds; zero failures, one skip**.
  The skip is the opt-in live Esri smoke test. All three original attribution
  cases pass, including the stronger background-box collision assertions.
  `git diff --check` passed. No Tk progress-bar or owned callback teardown errors
  appeared; Matplotlib's informational aspect-limit notices remain.

Reproduce from the repository root:

```powershell
python -B -m unittest tests.test_per_side_audit -v
python -B -m unittest tests.test_gui_input.GuiInputTests.test_attribution_remains_unobstructed_with_overlays_at_minimum_layout -v
python -B -m unittest discover -s tests
git diff --check
```

Local logs: `%TEMP%/codex-per-side-audit-baseline.log`,
`%TEMP%/codex-per-side-audit-focused.log`, and
`%TEMP%/codex-per-side-audit-final.log`. These are diagnostic artifacts, not runtime
dependencies.

## Remaining limits and follow-ups

- Compatibility remains restricted to supported open polyline-only KMZs. KML
  support, explicit direction reversal, and closed-ring semantics are separate
  feature decisions.
- Disconnected output for genuinely insufficient widths still reports a normal
  error; the numerical seam fix does not join separate source routes or enlarge
  entered side distances.
- This is a bounded regression audit, not a proof for every possible geometry,
  coordinate system, display size, or filesystem failure. The seeded fixtures
  and customer case provide repeatable coverage of the supported workflow.
- Pathologically long credits consume substantial map/panel space in a small
  window. Expand the window for comfortable settings editing in that situation;
  ordinary provider credits retain the normal layout.
- Optional live Esri testing requires `JPG_BOUNDARY_LIVE_ESRI_TEST=1` and network
  access. Ordinary tests use deterministic service responses.

## Implementation references

- [Polyline buffering and caps](../src/polyline_boundary.py)
- [Validation and KMZ export](../src/jpg_boundary_kmz_core.py)
- [Worker state, arrows, attribution, and shutdown](../src/jpg_boundary_kmz_gui.py)
- [Original attribution regression](../tests/test_gui_input.py)
