# Vertex editing implementation plan

Status: draft for iteration; editing functionality has not been implemented.
Prepared: September 15, 2026.

## 1. Objective and scope

Let users select each imported KML/KMZ polyline independently and move, insert,
or delete its vertices. Let users edit the final boundary polygon or each
exported section polygon, then save a KMZ containing those accepted vertices.
Use visible vertex handles similar to the interaction in the supplied Metashape
screenshots, within the existing Tk/Matplotlib app.

This plan is separate from the completed toolbar alignment fix. That fix
recalculates layout after expansion, when the hidden toolbar has its real width.
Keep the default collapse behavior, AALLC titles, green New Input button, and
remembered browsing directory throughout the editing work.

### Required first release

- Select one source line, final boundary, or exported section at a time.
- Move a vertex by dragging; insert a vertex on an edge; delete a selected vertex.
- Apply Edits, Cancel Edits, Undo, Redo, and Reset with explicit scope.
- Regenerate boundaries from accepted source-line edits.
- Export accepted boundary/section edits without regeneration or simplification.
- Validate geometry, preserve source files, and protect edits from stale workers.
- Synchronize the main preview and Inspector; allow only one edit transaction.
- Keep navigation, imagery, section settings, and existing exports working.

### Separate extension, after the required release

Saving/reopening an editable project containing inputs, settings, and manual
edits is a different operation from exporting a KMZ. Task 14 specifies this
extension so it can be promoted into the first release if desired. The required
release persists accepted output polygons in KMZ; it does not claim to persist
editable input lines or undo history after application exit.

Not included in this plan's first release: snapping, linked/shared-edge editing,
multi-vertex selection, merging/splitting source features, drawing new features,
polygon holes, editing JPG EXIF/GPS, or overwriting imported KML/KMZ files.
Final boundaries generated from JPGs remain eligible for boundary editing.

## 2. Verified starting points

Source links are relative to this document for repository portability. Line
numbers are an inspection snapshot; use the named symbols after files change.

| Source | Verified behavior and consequence |
| --- | --- |
| [Vector input](../src/kml_vector_input.py), `VectorInputGeometry`, lines 16–23; `_extract_line_strings`, lines 118–130 | Stores each LineString separately, but no per-feature IDs or names. Introduce identity without merging identical or touching lines. |
| [Geometry core](../src/jpg_boundary_kmz_core.py), `BoundarySection` / `BoundaryResult`, lines 159–177 | Stores projected and WGS84 polygon copies; edits must keep both representations consistent. |
| [Geometry core](../src/jpg_boundary_kmz_core.py), `generate_boundary_from_vector_geometry`, line 472 | Can build boundaries from in-memory vector input, providing a route for source edits. |
| [GUI](../src/jpg_boundary_kmz_gui.py), `_generate_for_request`, line 3437 | Currently reloads the file on generation and checks file identity. An edited input snapshot needs a distinct route and revision checks. |
| [GUI](../src/jpg_boundary_kmz_gui.py), `_export_worker`, line 3478; [core](../src/jpg_boundary_kmz_core.py), `save_kmz`, line 875 | Export normally regenerates; the writer rejects preview-profile results. A manual export path must explicitly validate accepted geometry. |
| [Geometry core](../src/jpg_boundary_kmz_core.py), lines 722–759 and 889–905 | Export generation may simplify vertices. With sections present, the writer exports sections, not the parent outline. |
| [GUI](../src/jpg_boundary_kmz_gui.py), `_draw_preview_on_axes`, line 3766; `_preview_polygon_xy`, line 4072 | Full redraw clears axes; large polygons are visually decimated. Neither the drawn line nor a redraw loop is a suitable authoritative editing model. |
| [Compatibility classifier](../src/polyline_compatibility.py), `classify_per_side_input`, line 22 | Per-side eligibility depends on inventory, source format, line validity, direction, and open/simple lines. Recheck after source edits. |
| [Geometry core](../src/jpg_boundary_kmz_core.py), `_require_single_exterior_polygon`, line 1367 | Its helper can repair geometry and fill interiors. Do not use it as validation-only acceptance of manual edits. |
| [Geometry core](../src/jpg_boundary_kmz_core.py), `_polygon_to_kml_coords`, line 1612 | Export rejects invalid, empty, hole-bearing polygons and nonfinite/out-of-range WGS84 coordinates. Atomic KMZ replacement already exists. |
| [GUI](../src/jpg_boundary_kmz_gui.py), `_apply_fullscreen_preview`, line 4633 | Inspector Apply currently regenerates from settings; it must use the same edit-protection rules as the main window. |
| [Export tests](../tests/test_kmz_export_contract.py) | Existing tests inspect ZIP/KML coordinates and compare reprojected geometry in both hemispheres. Extend this contract for manual edits. |

Matplotlib's [official polygon editor example](https://matplotlib.org/stable/gallery/event_handling/poly_editor.html)
demonstrates dragging and inserting/deleting vertices. It is an interaction
reference, not a complete application model, validation layer, or export solution.

## 3. Proposed decisions to settle during iteration

These are recommendations, not additional requirements already approved by the
user. Task 1 records the chosen behavior before implementation depends on it.

| Decision | Proposed default | Reason / alternative |
| --- | --- | --- |
| Editing entry point | An Edit dropdown in the expandable controls; active-edit strip stays visible while editing | Offers Edit Input Lines and Edit Boundaries without crowding normal navigation. Collapsing cannot hide Apply/Cancel. |
| Selecting a feature | Click geometry or choose a named feature from a list; show handles only for the selection | Overlapping lines remain separately selectable. Generate labels when imported names are missing. |
| Source regeneration timing | Regenerate on Apply Edits, not on every drag frame | Avoid repeated expensive buffer/section generation. |
| What a boundary target is | Single final polygon, or individual exported sections when sectioning is active | A parent-only edit would otherwise have no effect on section export. Editing the parent and resectioning is a later feature. |
| Upstream changes after manual boundary edits | Explicit Rebuild boundary / Keep edits choice before replacing anything | Rebuild uses accepted source edits; Keep restores prior generation settings or cancels the pending change. Do not geometrically transplant old vertex deltas. |
| Invalid edit | Show the invalid draft; disable Apply with a specific reason; Cancel/Undo remain available | Do not silently repair, simplify, or discard the user's intended shape. |
| Coverage and overlap | Warn on measurable changes; require explicit acknowledgement of manual exceptions before Apply/export | Independent edits may intentionally depart from generated buffer/overlap constraints. Linked topology enforcement would be larger scope. |
| Editing surfaces | Same model in main preview and Inspector, one transaction owner at a time | Prevent divergent edits and contradictory history. Other surface reflects accepted geometry. |
| Persistence | Required: exact edited polygon KMZ. Optional Task 14: editable project file | A polygon KMZ cannot restore source-line edits and settings by itself. |
| Reset | Reset selected draft feature to geometry at transaction entry; undoable | Discard all accepted manual boundaries is a separate explicit rebuild action. |
| Undo limit | Propose 100 commands, with a memory cap selected from large-data tests | A drag counts once. Never silently drop the saved/dirty marker when history is trimmed. |

## 4. Architecture and behavioral requirements

### Authoritative state

Keep geometry and history outside Tk variables and Matplotlib artists:

1. Immutable imported source snapshot, inventory, CRS, and feature identities.
2. Accepted source revision, including edited lines and unchanged input features.
3. Generated result plus the source/settings revisions used to produce it.
4. Accepted manual boundary/section snapshot, if present.
5. At most one draft transaction, with selected target and command history.
6. Export snapshot and the exact accepted revision it represents.

Track exported-output cleanliness separately from persistence of editable source
state. Exporting polygon KMZs does not save source-line edits, settings, or history;
New Input/close must still identify session-only work that would be lost.

Use full coordinates in one fixed projected CRS for editing. Convert to WGS84
through one core acceptance/export function using `always_xy=True`. Keep the
CRS stable during an editing document's lifetime; reject edits outside its
supported projection domain with clear feedback rather than switching zones
mid-drag. Preserve vertex order and line direction. Represent a ring's closure
implicitly in the editor so the first and last visible handle are one vertex.

Workers receive immutable snapshots. A monotonic document revision accompanies
all generation requests, export requests, caches, and completion messages.
Undo/redo also increments that revision. A completion from before an edit, undo,
new input, or rebuild cannot become the current preview or mark it as saved.

### Required state transitions

| Action | Required outcome |
| --- | --- |
| Enter Edit Boundaries | Copy full displayed output geometry into a draft; do not rebuild or simplify it on entry. |
| Enter Edit Input Lines | Copy accepted lines into a draft with original identities/directions. |
| Drag / insert / delete | Update draft and selected artists; preserve current map extent. |
| Apply boundary edits | Validate; update both CRS representations and statistics; accept one revision; enable direct manual export. |
| Apply source edits | Validate and classify; generate from the candidate source snapshot. Commit source/result together only on success. On failure keep the draft editable and old accepted result available. |
| Cancel edits | Restore transaction-entry geometry, selection state, and history boundary; no regeneration. |
| Change generation settings | If manual boundaries exist, resolve the rebuild choice before accepting changes or clearing geometry. |
| Export during a draft | Require Apply Edits or Cancel Edits first; never export an ambiguous mixture. |
| Export accepted manual boundaries | Validate snapshot and write those vertices directly; no generation, simplification, densification, or repair. |
| New Input / close with dirty edits | Offer the applicable Apply/export/discard/cancel choices; do not lose edits silently. |
| Collapse controls while editing | Preserve a visible Apply/Cancel strip and selected feature information. |

Retain the normal generated export path and its quality checks. Do not bypass
the preview-profile rejection by merely changing a metadata string. Add an
explicit manual export snapshot type with validation and provenance; share the
low-level KMZ writer only after the relevant path has passed its own checks.

## 5. Expected file changes

Names marked **new** are proposed files, not existing APIs. Keep each module's
scope narrow and avoid enlarging the GUI controller with geometry/history logic.
If implementation reveals another necessary file, update this list and explain
the dependency before making that change.

| File | Planned responsibility |
| --- | --- |
| `src/geometry_editing.py` **new** | Pure models, feature/vertex IDs, edit commands, history, validation, coverage diagnostics, accepted snapshots. No Tk imports. |
| `src/jpg_boundary_gui_editor.py` **new** | Hit testing, handles, drag controller, mode ownership, callbacks, draft artist updates. |
| `src/kml_vector_input.py` | Preserve feature identities/names with backward-compatible defaults and existing line precedence. |
| `src/jpg_boundary_kmz_core.py` | Prepare/validate manual export snapshots, CRS conversion, metadata, shared atomic writer. |
| `src/jpg_boundary_kmz_gui.py` | Editing entry points, document state, revisions, workers, main/Inspector integration, rebuild and dirty-state flows. |
| `src/polyline_compatibility.py` | Only if needed to expose reusable candidate-input checks; preserve current per-side policy. |
| `src/polyline_boundary.py` | Only if pinned-CRS generation requires passing the document CRS through the line-buffer builder; preserve the default automatic CRS choice for ordinary callers. |
| `src/jpg_boundary_gui_theme.py` | Only necessary edit-mode/handle/invalid-state styling; reuse existing buttons and colors where possible. |
| `src/editing_project.py` **new; optional Task 14** | Versioned project serialization and atomic save/load. |
| `tests/test_geometry_editing.py` **new** | Pure state, commands, undo/redo, validation, coverage diagnostics. |
| `tests/test_gui_vertex_editing.py` **new** | Pointer/keyboard behavior, mode conflicts, layout, main/Inspector lifecycle. |
| `tests/test_manual_geometry_export.py` **new** | Exact vertex round trips, metadata, explicit export routing, failure atomicity. |
| `tests/test_editing_project.py` **new; optional Task 14** | Persistence round trips, version/error handling, missing sources. |
| `tests/test_kml_vector_input.py`, `tests/test_polyline_compatibility.py` | Feature identity preservation and candidate per-side validation. |
| `tests/test_kmz_export_contract.py`, `tests/test_gui_input.py`, `tests/test_gui_per_side_buffer.py`, `tests/test_workspace_followup.py` | Integration regressions in existing workflows. |
| `tests/preview_gui.py` | Deterministic synthetic editing states for visual inspection. |
| `README_JPG_BOUNDARY_KMZ.md` | User workflow, shortcuts, rebuild semantics, export/persistence distinctions. |
| This plan; `docs/vertex-editing-validation-notes.md` **new** | Decisions, completed tasks, tested commands/results, limitations and evidence. |

No new dependency is currently expected. Do not edit tracked bytecode, real
survey inputs, unrelated generated output, or unrelated geometry algorithms.

## 6. Sequential implementation tasks

Execute tasks in order. Each task's acceptance checks are a completion gate.
Record actual results in validation notes; do not mark a task complete from code
inspection alone. The required feature is complete after Task 13. Task 14 is a
separate optional extension.

### Task 1 — Freeze scope and establish a baseline

Depends on: none.

Steps:
1. Review Section 3 decisions and mark each Accepted, Revised, or Deferred.
2. Record Python/library versions and relevant existing tests before edits.
3. Create synthetic fixtures: two separately selectable lines, coincident lines,
   branched/near-touching routes, a polygon, multiple overlapping sections, a
   dense polygon above 2,500 vertices, and northern/southern hemisphere cases.
4. Add the validation-notes file and record the chosen coordinate/coverage
   tolerances and performance measurement environment.

Requirements: scope distinguishes output KMZ from editable-project persistence;
no real input file is modified. Existing test failures are documented separately.

Acceptance: every first-release behavior has a test scenario and task owner;
open product decisions do not remain hidden assumptions in later tasks.

### Task 2 — Introduce editable geometry and stable identity

Depends on: Task 1. Files: input parser, `geometry_editing.py`, parser/model tests.

Steps:
1. Add immutable feature records with ID, display name, kind, coordinates, and
   source provenance. Preserve old constructors through defaulted fields.
2. Preserve placemark identity/name where available. Assign document-local IDs
   when absent or duplicated; do not use mutable coordinates as identity.
3. Distinguish every LineString, including multiple lines in a MultiGeometry and
   identical line geometries. Preserve their original ordering/direction.
4. Assign section identities for one generation; allocate new identities after
   resectioning rather than pretending old sections still match.
5. Represent vertex identities independently of list indices and ring closure.

Requirements: KML/KMZ precedence and geometry inventory remain unchanged;
existing non-editor callers continue to work; original snapshots are immutable.

Acceptance: selection identity survives moving/inserting/deleting other vertices;
duplicate names/geometries remain separate; parser and compatibility tests pass.

### Task 3 — Add edit transactions and command history

Depends on: Task 2. Files: `geometry_editing.py`, pure model tests.

Steps:
1. Implement begin, move, insert, delete, reset, undo, redo, cancel, and accept
   operations over immutable snapshots, with explicit valid target kinds.
2. Track draft changes separately from accepted document revisions.
3. Coalesce pointer motion into one command per completed drag; ignore no-op
   drags. A new command after Undo clears the redo branch.
4. Enforce minimum geometry: two distinct line points; three distinct polygon
   vertices plus implicit closure. Prevent deleting the closure independently.
5. Track dirty/exported revisions independently of history truncation.
6. Retain accepted-operation history across Apply. Undo/Redo of an accepted
   boundary edit restores geometry, statistics, and provenance together; source
   operations restore their coherent source/result pair. A successful rebuild or
   new edit clears incompatible redo entries. Define New Input as a document
   history boundary after resolving dirty state.

Requirements: commands do not mutate original inputs or invoke generation;
Cancel restores transaction-entry geometry exactly; revision numbers never rewind.

Acceptance: command sequences, boundary cases, repeated undo/redo, reset/cancel,
redo invalidation, history across Apply, and history limits have meaningful
state-based tests. Export does not mark session-only source edits as persisted.

### Task 4 — Validate drafts and accepted geometry without repair

Depends on: Task 3. Files: editing model, core conversion helpers, tests.

Steps:
1. Validate finite coordinates, minimum distinct vertices, nonzero line length,
   positive polygon area, ring closure, no interiors, and polygon validity.
2. Provide reasons tied to the selected feature and invalid edge/vertex where
   possible. Keep invalid drafts visible and Apply disabled.
3. Transform candidates into WGS84; check finite longitude/latitude bounds and
   inverse-transform consistency within the documented numerical tolerance.
4. Reuse per-side classification for line candidates. Preserve line direction
   and reject unsupported candidate geometry without silently changing mode.
5. Calculate section-union gaps/excess relative to the generated parent and
   changes to overlap/source coverage, with a numerical-noise tolerance.

Requirements: never call `make_valid`, buffer-based repair, simplification, or
hole filling to accept manual coordinates. Unified-line edits follow current
generator policy; per-side-specific restrictions must not be imposed globally.

Acceptance: bow ties, collapsed edges, nonfinite/out-of-range coordinates,
per-side closed/self-crossing lines, and intentional overlap changes produce
the documented outcomes. Valid coordinates and ordering remain unchanged.

### Task 5 — Make accepted manual geometry exportable

Depends on: Task 4. Files: core, editing model, manual/export contract tests.

Steps:
1. Add an explicit immutable manual export snapshot containing accepted output
   features, CRS, revision, validation result, and manual-edit provenance.
2. Convert accepted projected coordinates once into export coordinates. Update
   actual vertex counts, areas, validity/connectivity diagnostics, and descriptions.
3. Distinguish original generation settings from properties of the edited output;
   do not claim the manual outline still meets its original buffer distance or
   simplification guarantees. Preserve base-section area as provenance if retained.
4. Share the atomic low-level KMZ writer while leaving generated preview-profile
   rejection intact. Export sections when present and the final polygon otherwise.
5. Add a direct export route that cannot call regeneration, simplification,
   densification, or repair on a manual snapshot.

Requirements: validation occurs before destination replacement; output names,
styles, WGS84 coordinates, and normal generated export behavior stay compatible.

Acceptance: unzip KMZ and compare ordered coordinate sequences and vertex counts
against the accepted snapshot, allowing only closure and documented floating-point
conversion tolerance. Use the existing 1e-5 m round-trip tolerance as the initial
reference. Check single/multiple polygons in both hemispheres and prove forbidden
generation/simplification functions were not called. Failed writes preserve an
existing output file. Do not use the current single-polygon loader to verify a
multi-section export; inspect every KML Polygon in the archive.

### Task 6 — Add explicit selection and edit-mode controls

Depends on: Task 5. Files: GUI editor/controller, theme if needed, GUI tests.

Steps:
1. Add Edit Input Lines / Edit Boundaries entry points and a named feature selector.
2. Offer only real editable targets: imported lines, single final boundary, or
   exported sections. The parent reference outline is not a section-edit target.
3. Highlight the selected feature and render its full-resolution vertex handles.
4. Add Apply Edits, Cancel Edits, Undo, Redo, Reset, and inline validation feedback.
5. Keep transaction controls visible when the general toolbar is collapsed.

Requirements: no handles for unselected features; overlapping features can be
selected through the list. Normal mouse navigation is unchanged outside edit mode.

Acceptance: main preview supports all target kinds, missing line input disables
line editing clearly, and controls fit existing small-window/large-text layouts.

### Task 7 — Implement move, insert, and delete interactions

Depends on: Task 6. Files: GUI editor, pure command module, interaction tests.

Steps:
1. Hit-test handles/segments in screen pixels with a DPI-aware radius so zoom
   does not change click usability; map hits back to authoritative vertex IDs.
2. Drag a selected vertex in projected map coordinates. Insert at the closest
   position on the selected segment; support the closing polygon segment.
3. Wire Delete and explicit toolbar actions. Keep typing shortcuts scoped to
   the canvas/editor so text fields retain normal editing behavior.
4. Update selected artists incrementally during drag without clearing axes,
   fitting the view, or triggering a full basemap request on every motion event.
5. Handle release outside axes, Escape, focus loss, and window close without a
   stuck drag or partial history entry. Escape cancels the active gesture first.

Requirements: edit and navigation modes cannot own the same gesture. Use a
separate navigation gesture or explicit navigation mode while editing. Full
geometry is preserved even when normal preview drawing decimates it.

Acceptance: move/insert/delete work at multiple zooms and DPI settings; ring
closure stays consistent; map extent is stable; large polygons retain all
untouched vertices; one drag gives one undo step; mode cleanup is verified.

### Task 8 — Integrate accepted boundary edits with app state

Depends on: Task 7. Files: GUI controller/core interface and GUI/export tests.

Steps:
1. Carry immutable geometry snapshots and document revisions into requests and
   completion checks before enabling asynchronous editing/export integration.
   Source regeneration in Task 9 must use these checks from its first implementation.
2. On Apply, validate the draft and any acknowledged coverage exceptions, then
   accept one manual snapshot and update the displayed result/statistics.
3. Route Export KMZ to the accepted manual snapshot while in manual-boundary
   state. Preserve the ordinary generated route for unedited results.
4. Require resolution of an open draft before export. Keep the export revision
   distinct from newer edits so an old completion cannot mark them as saved.
5. Resolve manual edits before Update Preview, buffer/section changes, New Input,
   source reload, or other regeneration entry points.
6. For Keep edits, cancel the pending regeneration/change and restore consistent
   controls. For Rebuild, use accepted source geometry and discard manual output
   only after the replacement succeeds; failures retain the accepted outline.

Requirements: output naming changes do not erase geometry. Keep preview-current,
manual-edited, dirty, and exported indicators truthful and distinguishable.

Acceptance: Apply → Export round trip uses edited vertices; Cancel is exact;
settings/rebuild failure cannot destroy accepted work; UI actions and worker
tests demonstrate no silent replacement.

### Task 9 — Regenerate from edited source polylines

Depends on: Task 8. Files: GUI workers, core generation entry, compatibility tests.

Steps:
1. Pass candidate accepted source geometry to `generate_boundary_from_vector_geometry`
   rather than reparsing the original file for edited-source requests.
2. Preserve original source provenance/inventory and line IDs; update source
   coordinate statistics and recheck current per-side eligibility.
3. Generate once on Apply using the current buffer and section settings.
4. Commit edited source and its generated result atomically on success. On error,
   retain the prior accepted result and keep the proposed line edits recoverable.
5. If manual output edits exist, resolve the rebuild choice before replacing them.
   Undo of an accepted source operation restores its coherent source/result state.
6. Keep the document CRS promise: the existing generator chooses its projection
   from the input, which can change after moving coordinates. Either pass an
   explicit pinned CRS through generation or reproject every regenerated parent,
   source line, section, and point array into the document CRS before acceptance.
   Update EPSG/CRS-dependent metadata consistently and verify any directional
   diagnostics in that CRS; never relabel coordinates without transforming them.
   Record the selected approach and any additional helper dependencies in this plan.

Requirements: never write edited coordinates back to the imported file; untouched
lines retain coordinates and ordering; left/right direction remains stable.

Acceptance: independently edit each line including coincident features; compare
results to direct generation from equivalent in-memory geometry; test unified,
per-side, zero-buffer/Auto, and multiple-section cases, including failed rebuild.
Include a source edit near a UTM zone boundary and verify source handles, parent,
sections, imagery, metadata, and export remain in a consistent coordinate system.

### Task 10 — Harden revisions, cache keys, and asynchronous work

Depends on: Task 9. Files: GUI request/queue/cache logic and integration tests.

Steps:
1. Audit and complete the revision checks introduced in Task 8: immutable geometry
   snapshots plus document/source/manual revisions belong in every relevant
   request and cache identity, beyond the existing file stat identity.
2. Reject stale completions after edits, Undo/Redo, New Input, and A → B → A source
   changes. File identity alone cannot distinguish those editing states.
3. Keep Tk/artist operations on the UI thread. Workers cannot read live draft
   arrays or mutable Tk variables.
4. Ensure a saved older snapshot is reported as that revision only. Do not mark
   newer work clean or swap its current preview.
5. Preserve existing file-change detection for disk-backed generation; define
   the manual snapshot route independently so accepted output is not silently
   rebuilt from a changed source file.

Requirements: busy/disabled states recover after validation, generation, or write
errors; source metadata remains provenance rather than authority over manual output.

Acceptance: deterministic delayed-worker tests cover edit/undo/input-change races,
failed/canceled work, and stale export completion without real timing sleeps.

### Task 11 — Complete Inspector, navigation, and lifecycle integration

Depends on: Task 10. Files: GUI controller/editor and GUI integration tests.

Steps:
1. Bind both preview surfaces to the same accepted document. Permit a single
   draft owner; give the other surface clear read-only status during that draft.
2. Apply identical edit-protection rules to Inspector settings Apply and main
   Update Preview. Use distinct labels for settings Apply versus Apply Edits.
3. Preserve imagery, scale bars, direction arrows, selection, and extents across
   accepted edits; redraw only the affected layers where practical.
4. Resolve draft ownership on Inspector close, Focus mode, toolbar collapse,
   source visibility changes, New Input, and application shutdown.
5. Disconnect callbacks and release mouse locks, timers, and artists on exit.

Requirements: hiding the source layer cannot leave invisible editable handles;
no duplicated callbacks after reopening the Inspector or reentering edit mode.

Acceptance: both surfaces show the same accepted geometry; close/reopen and
repeated editing leave stable callback/artist counts; keyboard and pan/zoom
conflicts are covered along with existing collapse and responsive-layout tests.

### Task 12 — Verify the complete geometry/export workflow

Depends on: Task 11. Files: new and existing test modules, preview harness.

Steps:
1. Exercise input → generate → edit line → regenerate → edit output → export.
2. Cover one boundary and multiple sections, small/large inputs, both hemispheres,
   all editing operations, cancellation, undo/redo, and coverage acknowledgement.
3. Verify source bytes stay unchanged and export archive coordinates match every
   accepted output feature, including untouched ones and ring closure.
4. Measure dense-geometry drag responsiveness on the recorded environment; propose
   a p95 motion-to-paint target below 50 ms for the agreed representative fixture.
   Record actual measurements; optimize selection/artist updates if the target is
   missed rather than silently simplifying editable geometry.
5. Run related regression suites and the full suite. Record unrelated baseline
   failures without converting a rerun into a claimed clean full-suite result.

Requirements: visual checks include a real expanded/collapsed window, narrow and
large-text layouts, dark imagery, crossing/overlapping features, and the Inspector.

Acceptance: every required-release scenario passes or has an explicit documented
blocker. Export equality, no data loss, and valid geometry are mandatory gates.

### Task 13 — Document and release the required feature

Depends on: Task 12. Files: README, this plan, validation notes.

Steps:
1. Document selection, move/insert/delete, navigation gestures, shortcuts, undo,
   Apply/Cancel, rebuild choices, section warnings, and export behavior.
2. State that source files remain unchanged and exported polygon KMZs do not store
   editable input history. Explain any first-release session-only limitation.
3. Record completed tasks, exact verification commands/results, observed performance,
   screenshots or visual-check notes, and remaining optional work.
4. Audit the diff for unrelated changes, temporary fixtures, bytecode, and accidental
   changes to generated boundary algorithms.

Acceptance: the README describes the delivered behavior; the user can follow the
workflow end to end; no task is marked complete without its acceptance evidence.

### Task 14 — Optional: save and reopen editable projects

Depends on: Task 13, unless explicitly moved into the required release at Task 1.
Files: `editing_project.py`, GUI save/open integration, persistence tests/docs.

Steps:
1. Define a versioned format containing original/accepted source geometry, feature
   IDs, fixed CRS, generation settings, accepted output, manual provenance, and
   optional source path/content fingerprint. Do not serialize Tk/artist objects.
2. Save atomically beside the destination; validate schema and geometry before
   replacing live state on load. Reject unsupported versions without partial load.
3. Make the document self-contained for vector editing and accepted output export.
   Missing JPGs may block regeneration but must not block viewing/exporting saved
   accepted output; explain unavailable actions explicitly.
4. Add Save Project / Open Project and dirty-close handling. Undo history need not
   survive reopen in the first persistence version; document that choice.
5. Detect changed original sources and offer explicit reload without overwriting
   the saved snapshot automatically.

Acceptance: reopen reproduces accepted coordinates, identities, settings, and
manual-export results; interrupted save preserves the old file; corrupt/versioned
files, missing sources, relocated projects, and changed source files are tested.

## 7. Verification commands and completion record

Run from repository root using the configured Python environment. `-B` avoids
modifying tracked bytecode. New test files below become runnable when their
respective tasks create them.

```powershell
python -B -m unittest discover -s tests -p test_geometry_editing.py
python -B -m unittest discover -s tests -p test_gui_vertex_editing.py
python -B -m unittest discover -s tests -p test_manual_geometry_export.py
python -B -m unittest discover -s tests -p test_kml_vector_input.py
python -B -m unittest discover -s tests -p test_polyline_compatibility.py
python -B -m unittest discover -s tests -p test_gui_per_side_buffer.py
python -B -m unittest discover -s tests -p test_kmz_export_contract.py
python -B -m unittest discover -s tests -p test_gui_input.py
python -B -m unittest discover -s tests -p test_workspace_followup.py
python -B -m unittest discover -s tests
git diff --check
```

For each completed task, record: chosen decisions, files changed, commands and
results, geometry/export evidence, known limits, and the next dependency-ready
task. No editing task is marked complete in this draft.

### Separate toolbar fix delivered with this plan

- Reproduced hidden-width wrapping persisting after expansion.
- Added a deferred layout refresh on expansion so navigation and layer toggles
  return to the same row when space permits; narrow-window wrapping is retained.
- Passed the existing collapse/expand test enhanced with same-row and vertical
  center checks, the resize/state test, and the responsive/large-text layout test.
- This change does not implement any vertex-editing functionality.
