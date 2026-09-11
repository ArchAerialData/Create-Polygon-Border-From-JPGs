# Per-side buffer implementation plan

Status: implemented September 11, 2026. No implementation blockers remain.
The completion record below documents delivered behavior, verification, known
issues, and follow-up suggestions. The numbered sections retain the agreed design.

This plan incorporates the user's final correction: copy the full unified
distance into each side. It extends the earlier
[feasibility study](per-side-buffer-feasibility.md) with the zero-value default
and detailed implementation behavior.

## Completion record

All six implementation steps are complete:

- Added immutable buffer settings, precise default copying, finite/nonnegative
  validation, and the explicit 200/200 ft unified-zero default.
- Added the shared import-time compatibility classifier and diagnostic CLI.
  Original XML geometry inventory prevents mixed KMZs from passing eligibility
  after the loader's usual LineString precedence.
- Implemented asymmetric side buffers and rounded endpoints. Equal sides use
  the strict existing buffer builder, preserving exact unified geometry without
  Auto adjustment. Distances remain independent of section count and overlap.
- Integrated prepared vector input, active settings, cache keys, metadata, KMZ
  descriptions, Inspector Apply, and export coverage safeguards.
- Added synchronized controls in Boundary settings and the footer, source direction
  arrows in both previews, mode-aware summaries, input reset, and tagged worker
  results that reject stale input generations and changed files.
- Verified real KMZ output, keyboard mode changes, compact layouts, and saved
  exports; updated the README and this record.

### Verified behavior and evidence

- New automated coverage comprises **22 test methods** across
  `test_buffer_settings`, `test_polyline_compatibility`, `test_gui_per_side_buffer`,
  `test_per_side_core`, and `PerSidePolylineTests` in `test_polyline_boundary`.
  Checks include tiny fractional widths, equal-side equivalence, swapped/reversed
  routes, rounded endpoint extents, duplicate coordinates, hairpins, one zero side,
  disconnected buffers, eligibility failure, A → B → A stale results, changed-file
  cache rejection, synchronized fields, active summaries, and Inspector/export
  settings. A worker test also verifies one vector-file parse per request.
- Synthetic preview/export checks cover **1, 3, 4, 8, and 12 sections**, each at
  0 and 50 ft overlap. Preview section unions match the parent; exported sections
  are valid and retain source coverage. Saved KML coordinates are reprojected and
  compared with the generated polygons. Export diagnostics stay within the
  existing 5 ft deviation and 1% area-change limits.
- The actual `C52 + C53.kmz` is eligible: six original open polylines. Unified
  350 ft and per-side 350/350 ft produce exactly equal projected geometry.
  **350/150 ft passed all 20 combinations** of the same five section counts,
  two overlap settings, and preview/export profiles. The four-section, 50 ft
  overlap KMZ was saved to a temporary directory; source data was not modified.
- GUI layout checks cover 720×500, 960×600, 1100×760, and 1500×820 with Tk scales
  1.333, 1.667, and 2.0 across the selected cases. Repeated toggles exclude hidden
  controls from layout and check that visible footer controls receive pointer
  hits. Native screenshots additionally verified both editor locations at
  1500×900, wrapped side fields at 720×500, and restored unified fields at 960×600.
  Space-key toggles transfer focus to Left or the restored unified field.
- Initial baseline: **236 tests**, one skipped, with three failing subcases of
  the existing extreme-attribution layout test. The first integrated run executed
  **257 tests**, with exactly the same three subcase failures and one skip.
  The final full-suite run executed **258 tests in 111.055 seconds**, with the
  same three failing subcases and one skip. **All 22 new feature tests pass.**
  No new regression failures were introduced. `git diff --check` passed and the
  changed Python sources parsed successfully.

Local diagnostic artifacts (temporary, not repository dependencies):

- Customer validation and sample KMZ:
  `C:/Users/rbake/AppData/Local/Temp/codex-per-side-c52-7a56fztg/`.
- Full-suite logs: `codex-per-side-full-tests.log` and
  `codex-per-side-final-tests.log` in the same Windows Temp directory.
- Final native screenshots: `codex-shot-2026-09-11_14-07-19.png`,
  `codex-shot-2026-09-11_14-07-20.png`, and
  `codex-shot-2026-09-11_14-07-22.png` in Windows Temp.

### Implementation adjustments

- Core integration tests live in new `tests/test_per_side_core.py`, keeping
  feature coverage separate from the existing regression module. Inventory
  regressions live with the compatibility tests; existing loader and GUI test
  files required no changes for this feature.
- Legacy GUI callers still accept a scalar unified buffer. The worker snapshot
  always carries a typed immutable `BufferSettings`; per-side requests never
  depend on the inactive scalar. Metadata fields are appended to preserve the
  ordering of older positional fields.
- Wrapping footer fields now uses a separate frame per row, with explicit
  stacking above those frames. Shared grid columns had stretched unrelated rows,
  and the first visual check exposed the newer frames covering their controls.
  The compact header's button gaps were reduced slightly to retain preview space.
- File identity checks apply to vector files. JPG folders retain their existing
  caching policy so exporting into a source folder does not invalidate a result
  merely by changing the directory modification time.
- No new dependency, route-merging algorithm, third endpoint field, or change
  to unified Auto/splitting algorithms was needed. Pre-existing workspace changes,
  including tracked bytecode, were preserved; checks used `python -B`.

### Known issues and follow-up suggestions

- **Pre-existing test issue:** at system-aware 125% scaling, the attribution
  collision test with a 500-character unbroken credit string fails for main
  Settings, main Key, and Inspector Key. These failures were reproduced before
  implementation and are outside this feature. Resolve the credit/scale-bar
  layout in a separate UI patch.
- The combined GUI test run also emits nonfatal Tk progress-bar callback messages
  during test-window teardown, plus Matplotlib aspect-limit notices. Individual
  feature runs pass; cleaning up the test harness's remaining timers is a useful
  follow-up. These messages are retained in the full-suite log.
- Per-side availability intentionally excludes KML, mixed geometry, closed rings,
  and self-crossing individual lines. Pure KML polylines are the simplest future
  extension; rings require a separate inside/outside policy.
- Left/right follows each original line independently. A future Swap sides action
  or explicit direction reversal could help files with inconsistent source
  direction; no direction is guessed or rewritten now.
- Eligibility does not guarantee every width/count combination will yield one
  connected polygon or a valid split. Per-side mode reports such failures and
  keeps the entered values. The existing bounded section search remains in use.
- Simplification can preserve all vertices when removing them would lose source
  coverage, especially along a zero-width side. This is intentional.
- At the minimum 720×500 window, footer controls remain usable but the map is
  necessarily small. A larger window or Focus Preview gives more inspection space.

No user clarification, permission, or external service is needed for this release.

## 1. Behavior to implement

Expose an optional **Per-side buffer** checkbox for compatible, polyline-only KMZ
inputs. It starts unchecked. Show synchronized copies in Boundary settings and
the footer, beside the active buffer controls.

### Defaults and mode changes

| Current unified value | Left after enabling | Right after enabling | Unified value after disabling |
| --- | --- | --- | --- |
| 350 ft | 350 ft | 350 ft | 350 ft |
| 461 ft | 461 ft | 461 ft | 461 ft |
| 0.005 ft | 0.005 ft | 0.005 ft | 0.005 ft |
| 0 ft, including `0.0` or `-0` | 200 ft | 200 ft | Original zero value |
| Empty, invalid, negative, NaN, or infinity | Stay in unified mode; explain invalid value | — | Unchanged |

Initialization copies a validated value and performs no division. The 200/200 ft
rule is an explicit usability default when the unified value is zero.

The current unified distance is applied to **each** side of a line. Consequently,
350 → 350/350 preserves the existing buffer geometry. This equivalence is an
acceptance requirement for positive unified values. Describe the initialization
and the zero-value exception briefly in the checkbox help text.

Implementation rules:

- On every off → on transition, read the current displayed unified value and seed
  both fields according to the table. If Auto has already updated that value,
  use the displayed effective value. Do not seed from a stale worker request.
- Save the unified field text independently. Side edits never overwrite it.
  On → off restores that text, rather than deriving a new value from the sides.
  Re-enabling reseeds from the restored unified value, replacing earlier side edits.
- Preserve fractional values when copying; do not round them through the current
  two-decimal display formatter. Copy the validated editor text into both fields.
- Allow one side to be zero if the other is positive. Two manually entered zeros
  are an invalid per-side width; show normal field validation before generation.
- Positive side distances are authoritative. Do not silently increase or rebalance
  either side. Preserve the existing zero/Auto behavior when unified mode is active.
- Changing mode or distances updates controls and summaries immediately and marks
  the preview stale. Geometry follows the existing Update Preview/F5 workflow.
  Importing a new input still starts its normal automatic unified preview.
- A new input, a cleared input, or loss of compatibility resets to unified mode
  and clears the previous input's side state.

### Field visibility and scaling

Enabled: completely remove the unified label, entry, grid allocation, and tab stop;
show Left (ft) and Right (ft). Disabled: remove both side groups and restore the
unified group. Keep the checkbox available while the input remains compatible.

Use one shared mode variable and one shared variable per distance for both editor
locations. Guard programmatic variable changes so one toggle does not trigger
duplicate transitions or partial cache invalidation.

Build layout from an explicit list of active field groups. The current footer
loops over every `_quick_field_groups` item and re-grids it, so merely hiding an
entry would be insufficient. Hidden groups must be excluded from measurement
and placement. Recalculate the footer breakpoint, row wrapping, settings scroll
region, and preview layout after a mode change in a coalesced idle update.

Reuse existing rounded controls, white labels, spacing, and DPI handling. Keep
overlap, shape label, shape count, and export actions accessible. Hidden widgets
must not regain focus or reappear during busy-state restoration. Move focus to
Left when enabling and to the unified field when disabling from the keyboard.

## 2. Import-time compatibility helper

Add `src/polyline_compatibility.py`: a small reusable module called directly from
the import worker, with an optional command-line entry point for diagnostics.
The GUI must not launch a subprocess to classify each input.

Proposed API: `classify_per_side_input(parsed_input) -> PolylineCompatibility`.
Return an immutable result containing eligibility, a stable reason code, a short
explanation, and the source-line count. Associate it with the import generation
and source identity in the worker result envelope.

Initial eligibility:

- The selected input is a readable, valid **KMZ**, using the same selected KML
  document and parsing policy as the normal import path.
- It contains at least one usable LineString, and every source line is open,
  individually simple, has positive length, and has finite valid coordinates.
- It contains no competing geometry: polygons, points, LinearRings, tracks, or
  other unsupported geometry. Unresolved NetworkLinks and spatial overlays also
  make it ineligible. Styles, names, ordinary folders, Document, and MultiGeometry
  containers are permitted.
- Multiple lines, point intersections, and branch junctions are allowed. They
  retain their individual source directions. No automatic route merging,
  direction guessing, or movement of source coordinates is introduced.

Folders of JPGs, KML files, polygon-only or mixed inputs, closed/self-crossing
lines, malformed inputs, and unsupported geometry keep the checkbox hidden.
KML polyline support can be enabled later through the eligibility policy without
redesigning the geometry code.

Extend `VectorInputGeometry` with additive geometry-inventory/capability data.
Count geometry in the original XML before the loader's existing LineString
precedence discards polygons. Do not infer compatibility from the filename or
`source_line_count` alone. Keep ordinary import behavior unchanged for ineligible
files: unsupported per-side input is not automatically an invalid unified input.

Parse once per import request, then reuse the parsed object for classification
and preview generation. The classifier checks input structure; it does not run
buffer searches, sectioning, imagery requests, or export simplification.

Eligibility does **not** promise that every edited width will produce one connected
polygon. Copying a working positive unified value must retain connectivity, but
later reducing a side can disconnect a narrow corridor. Honor the entered values
and explain the geometry failure; the only automatic 200/200 replacement is the
user's unified-zero case.

### Async behavior

1. At input change, increment the input generation, clear eligibility, hide both
   checkboxes, and reset per-side state immediately.
2. A worker reads the selected vector input, classifies it, and posts a tagged
   compatibility result before starting heavier preview geometry.
3. The UI applies the result only when its generation and source identity still
   match. Eligible controls may appear while generation is busy, but remain disabled.
4. Eligibility survives a later geometry failure, allowing the user to try another
   width once busy state ends. Parsing failure leaves it hidden without a second
   duplicate error dialog.
5. Check file identity before reusing a prepared input or cached export. If the
   source changed, re-read/reclassify it. Discard outdated results and callbacks
   after input changes or window closure. No filesystem watcher is needed.

Cache input classification by resolved path, size, modification timestamp, and
input generation. Capture/check identity around the read. This is a cache
invalidation mechanism; worker generations remain the authority for UI state.

The optional CLI accepts an input path and prints the classification as JSON.
It uses the same loader and classifier as the app; it does not maintain a second
KMZ parser or a separate eligibility policy.

## 3. Geometry and direction rules

Use the two-field construction already demonstrated in the feasibility study:
buffer each original projected line on its left and right, then union the results.
Left/right follows the original coordinate order, with arrows in the main preview
and Inspector while per-side mode is active. Directions are independent of output
section ordering. Explain “Left/right follows the arrows” in the controls' help.

No third endpoint field in this release. Join side offsets with a rounded cap:

- radius and forward extension = `(left + right) / 2`;
- lateral center shift toward the left = `(left - right) / 2`.

Use the first/last nonzero source segment to orient each endpoint, accounting for
duplicate consecutive coordinates without rewriting the imported source overlay.
Equal side distances produce ordinary round-ended buffering at that side distance.
Route equal explicit side values through the strict existing buffer builder;
do not invoke Auto to increase them.

Keep disabled/unified mode on the current geometry path. For asymmetric output,
retain source coverage, valid positive area, one connected exterior-only polygon,
projection, sectioning, and export rules. Use bounded geometric tolerances for cap
union; validate the prototype's one-micrometre precision grid against supported
small widths before adopting it. Do not bridge missing coverage through a convex
hull or discard meaningful disconnected components.

Buffer the full source before splitting. Section count and overlap must not change
the chosen side distances or parent outline. Invalid distance pairs fail with a
useful message suggesting larger side distances, without silently modifying fields.

Preview and export share the same buffer settings and parent construction. Retain
the existing 5 ft maximum export simplification deviation and 1% area-delta limits.
Additionally validate per-side source coverage after simplification, especially
when one side is zero; reduce simplification or preserve original vertices if
needed to satisfy those constraints.

## 4. State and backend integration

Add a small typed `BufferSettings` value in `src/buffer_settings.py` containing the
active mode and its distances. Keep the saved unified editor text in GUI state;
it is not an active distance when per-side mode is enabled. Provide pure validation
and initialization helpers that can be tested without Tk.

Preserve legacy core calls that supply `buffer_ft`. Add an optional keyword-only
buffer-settings argument to the relevant vector generation entry points; absent
that argument, construct unified settings from `buffer_ft`. An explicit settings
object is the active geometry request. Validate eligibility in the backend as well
as in the GUI so direct API calls cannot apply per-side mode to unsupported inputs.

Introduce a prepared-vector generation path so the worker can classify and generate
from the same parsed input. Existing path-based entry points continue to read and
delegate to that path. Keep this refactor limited to input preparation.

Thread the immutable settings value through `_read_inputs`, preview/export worker
requests, Inspector Apply, and the preview-state signature. Add mode and active
distances to `_settings_key`; inactive saved values must not invalidate current
geometry. Use tagged request snapshots/results rather than reconstructing an
asymmetric request from the legacy scalar buffer metadata.

Add explicit mode/left/right fields to result metadata and KMZ descriptions.
Unified metadata retains its existing numeric `buffer_ft`. In per-side results,
use `buffer_ft=None` and make its consumers mode-aware; do not invent a misleading
single distance. Defaults on new metadata fields keep existing unified result
construction compatible. `_sync_effective_buffer` must update only unified results;
it must never overwrite the two side fields or the saved unified editor value.

Details, drawer summaries, status/signature handling, main preview, and Inspector
must all use the active/displayed mode consistently. A stale displayed result must
not be relabeled as newly generated geometry just because the fields changed.

## 5. Reviewed files and expected change list

All paths below are relative to the repository root:
`C:/Users/rbake/Desktop/VS Code Shortcuts/Create-Polygon-Border-From-JPGs`.
The table records the planned scope; the completion record identifies the final
file organization and tests actually added.

| File | Planned change and reason |
| --- | --- |
| `src/buffer_settings.py` **new** | Typed active settings, finite/nonnegative validation, precise value-copy and zero-default helpers. |
| `src/polyline_compatibility.py` **new** | Shared lightweight classifier and optional diagnostic CLI. |
| `src/kml_vector_input.py` | Extend parsed geometry inventory while retaining existing source geometry and import precedence. |
| `src/polyline_boundary.py` | Add asymmetric side/cap construction and strict validation; retain unified Auto behavior. |
| `src/jpg_boundary_kmz_core.py` | Prepared vector input, typed settings plumbing, mode-aware metadata/descriptions, section/export integration and coverage safeguards. |
| `src/jpg_boundary_kmz_gui.py` | Async compatibility state, shared controls, mode transitions, active-group layout, request/cache integration, direction arrows, summaries and busy-state behavior. |
| `tests/test_buffer_settings.py` **new** | Defaults, precision, validation and active settings semantics. |
| `tests/test_polyline_compatibility.py` **new** | Eligibility rules, reason codes, CLI agreement and non-mutating classification. |
| `tests/test_kml_vector_input.py` | Inventory and mixed-input precedence regressions. |
| `tests/test_polyline_boundary.py` | Asymmetric distances, endpoints, coverage and unified equivalence. |
| `tests/test_core_regression.py` | Preview/export, splitting, zero-side simplification and backward-compatible core calls. |
| `tests/test_per_side_core.py` **new, implementation adjustment** | Actual home for per-side core, saved-export, source-coverage and section-union regressions. |
| `tests/test_gui_input.py` | Integrate updated request/metadata shapes with existing GUI regressions. |
| `tests/test_gui_per_side_buffer.py` **new** | Toggle, eligibility, async state, layout and field-sync tests using the current Tk test harness. |
| `README_JPG_BOUNDARY_KMZ.md` | User-facing availability, defaults, direction and endpoint behavior. |
| `docs/per-side-buffer-implementation-plan.md` | Record implementation evidence and any justified plan changes. |
| `docs/per-side-buffer-feasibility.md` | Keep initialization guidance consistent with this plan. |

Relevant existing symbols reviewed include `load_vector_input`, `VectorInputGeometry`,
`_project_linework`, `build_polyline_boundary_with_recommended_buffer`,
`generate_boundary_from_vector_file`, `_build_geometry_settings`, `_build_action_bar`,
`_refresh_action_bar_layout`, `_read_inputs`, `_scan_worker`, `_export_worker`,
`_drain_queue`, `_set_input_path`, `_sync_effective_buffer`, and `_settings_key`.

Reuse `geometry_hardening.py`, the natural/recursive splitters, existing theme,
window/DPI utilities, and basemap behavior. Their algorithms and dependencies are
outside the expected edits. Preserve all pre-existing workspace changes, including
tracked bytecode; implementation checks use `python -B`.

## 6. Implementation order and verification

| Step | Work | Primary risk | Verification before proceeding |
| --- | --- | --- | --- |
| 1 | Capture working-tree/test baseline; add settings and compatibility helpers. | Misclassifying mixed KMZ or changing ordinary import behavior. | Helper/loader tests and current pure-polyline KMZ classification. |
| 2 | Implement side buffers and automatic caps using projected source directions. | Reversed sides, endpoint cracks, geometry loss, precision collapse. | Measured synthetic geometries, reversal invariance, equal-side/unified equivalence, source coverage. |
| 3 | Integrate prepared input, settings, metadata and export in core. | Wrong cache reuse, split-dependent widths, simplified output losing source coverage. | Core preview/export and section-union regressions. |
| 4 | Add tagged import classification and synchronized GUI mode controls. | Stale eligibility, partial state transitions, hidden controls restored by layout/busy code. | Out-of-order queue, input reset, toggling, invalid input, and widget-state tests. |
| 5 | Reflow both editor locations; add arrow/help/summary behavior. | Clipped controls, blank rows, wrong focus, misleading stale-preview labels. | Small-window/DPI layout checks, main/Inspector rendering and manual keyboard check. |
| 6 | Run integrated checks, inspect current customer KMZ, update documentation. | Regression hidden by unrelated baseline failures or untested export path. | Compare with baseline, inspect rendered geometry and saved temporary KMZ, final diff review. |

## 7. Acceptance tests

**Settings and transitions:** verify every row of the defaults table from both
checkbox locations; side edits synchronize; disabling restores unified text;
re-enabling reseeds; new input resets. Test busy state, cancellation, invalid
numbers, tiny fractional values, one zero side, and two manually entered zeros.
No division-by-zero exceptions, NaN coordinates, duplicate callbacks, or unwanted
Auto width changes are acceptable.

**Compatibility:** pure single/multiple open lines and branches are eligible;
folder/KML/polygon/mixed/closed/self-crossing/malformed inputs are not. Include
nested MultiGeometry, styles, line-plus-point, line-plus-polygon, tracks, missing
coordinates, and an unreadable/deleted file. Check eligibility before preview
completion and after a geometry failure. Repeated changes A → B → A must reject
an old response for the first A. A source modified at the same path must be
reclassified before cached reuse.

**Geometry:** straight line, 90-degree turn, hairpin, very short segment, duplicate
endpoint vertices, branches, differing path directions, gaps, a large side ratio,
and zero on one side. Measure left/right extents on a straight segment, automatic
cap extension and shift, valid polygon output, and source coverage. Reversing all
source paths while swapping left/right must preserve the resulting shape within
the documented precision tolerance. Unified mode must retain current geometry.

**Sections/export:** exercise 1, 3, 4, 8 and 12 sections on representative corridors
at zero and nonzero overlap. Verify unchanged asymmetric parent and distances,
valid connected sections, expected labels/count, and section union matching the
parent before simplification. Check main preview, Inspector and saved KMZ agree
with the active mode; ensure simplified export meets geometry and coverage limits.

**GUI:** test 720×500, 960×600 and 1500×820, plus current larger-font/DPI test
configurations. Toggle repeatedly with settings open/closed and in Focus Preview.
Only active controls should occupy layout space or receive focus. Footer fields
wrap, action buttons remain usable, and settings scrollbars update without empty
reserved rows. Verify mode/distance changes invalidate geometry cache; inactive
saved unified text does not. Keep compatibility controls hidden for noncandidates.

**Current customer example:** inspect
`A:/z_TemporaryDailes_z/Stevens Daily Metashapes/GFT/_Shapes/C52 + C53.kmz`
locally when available. Verify 350 → 350/350 → saved 350 with unchanged geometry;
verify 0 → 200/200 → saved 0;
then test 350/150 with four sections and 50 ft overlap. Use a temporary output
directory. Do not modify the source KMZ or add customer geometry to the repository.
Use portable synthetic fixtures for committed tests. If the optional customer
path is unavailable later, report that limitation and complete portable checks.

Commands, run from the repository root (new test modules become available during implementation):

```powershell
# Capture baseline before code changes, and compare again after implementation.
python -B -m unittest discover -s tests

# Focused feature and neighboring backend checks.
python -B -m unittest tests.test_buffer_settings tests.test_polyline_compatibility tests.test_kml_vector_input tests.test_polyline_boundary tests.test_per_side_core tests.test_natural_sectioning tests.test_core_regression -v

# GUI integration and existing window behavior.
python -B -m unittest tests.test_gui_per_side_buffer tests.test_gui_input tests.test_gui_window -v

# Source/change review.
git diff --check
git status --short
```

The preceding backend patch passed 42 focused tests. A prior full run recorded
an unrelated extreme-attribution GUI layout failure at system-aware 125% scaling.
Re-establish the current baseline before implementing this feature; do not assume
all tests pass or change unrelated tests just to obtain a green result. Any
feature-caused failure must be fixed. Existing unrelated failures must be compared
and reported explicitly.

## 8. Completion criteria and remaining decisions

Implementation can proceed without further product decisions using this plan.
Defaults are fixed to the user's latest instructions. KMZ-only availability,
per-original-line direction arrows, automatic rounded endpoints, restoring the
saved unified value, reseeding on each enable, and the existing manual preview
update workflow are the selected first-release behaviors.

Finish only when feature tests pass, no new regressions are introduced, both GUI
locations behave consistently, preview/export invariants are verified, and the
changed-file review matches this scope. Update the plan if a code finding requires
a different file or design. Ask the user only if implementation would require a
materially different behavior or an unavailable external requirement; routine
implementation and verification decisions remain automated.

## References

- [Feasibility evidence and geometry-library sources](per-side-buffer-feasibility.md)
- [Current buffer and section hardening](polyline-buffer-hardening.md)
- [Existing GUI workflow and validation notes](gui-workspace-refresh.md)
