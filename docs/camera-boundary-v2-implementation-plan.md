# Camera Boundary V2 Implementation Plan

Planning status: implementation blueprint only. Do not edit source files until this plan is approved or revised.

Repository root:

```text
C:\Users\rbake\Desktop\VS Code Shortcuts\Create-Polygon-Border-From-JPGs
```

Current branch observed during planning:

```text
Testing-New-Methods...origin/Testing-New-Methods
?? agent_prompt_templates/
```

The untracked `agent_prompt_templates/` directory existed before this plan file was created and is not part of the implementation allow-list unless explicitly approved later.

## 1. Executive Summary

The new version should replace the single default JPG outline method with an auto-selected outline engine. The current repo builds a JPG boundary from GPS points using a Shapely concave hull, then applies simplification, optional buffering, optional section splitting, preview, and KMZ export. That path should remain as the conservative fallback.

The new engine should add:

- A camera-position preflight classifier.
- Route-aware outline generation for perimeter/corridor-style capture paths.
- Lawnmower outer-envelope outline generation that ignores interior row-turn noise.
- Mixed-section handling for inputs containing both linear/perimeter and lawnmower sections.
- Projected geometry hardening adapted from `Buffer-Zone-Generator`, including higher buffer resolution, geometry cleanup, and segment densification before export.
- Explicit GUI controls and details output so users can see the selected strategy, confidence, and fallback reason.

The primary risk is incorrect automatic classification. The implementation must be conservative: if confidence is low, the current concave hull path remains the output.

## 2. Current Repository Findings

| Finding | Evidence | Status | Relevance |
|---|---|---|---|
| JPG inputs are discovered recursively and filtered by `.jpg`/`.jpeg`. | `src/jpg_boundary_kmz_core.py`, `find_jpgs` | Verified from code | Preflight and ordering must use the same input set. |
| GPS points currently store only path, latitude, and longitude. | `src/jpg_boundary_kmz_core.py`, `GpsPoint` | Verified from code | Capture order metadata needs a model extension or separate structure. |
| The current JPG boundary is built from projected unique GPS points using `concave_hull`. | `src/jpg_boundary_kmz_core.py`, `generate_boundary`, `raw_hull = concave_hull(...)` | Verified from code | This remains the fallback strategy. |
| Current simplification is containment-preserving against camera points. | `src/jpg_boundary_kmz_core.py`, `_simplify_with_containment` | Verified from code | New strategies must preserve or intentionally explain containment behavior. |
| Current buffer resolution is `BUFFER_QUAD_SEGS = 8`. | `src/jpg_boundary_kmz_core.py`, module constant | Verified from code | The other repo uses a higher buffer resolution. |
| Current KMZ polygon input path reads exactly one source polygon and rejects holes. | `src/jpg_boundary_kmz_core.py`, `generate_boundary_from_kmz`, `_read_single_polygon_from_kmz` | Verified from code | V2 changes must not regress KMZ input behavior. |
| Current section splitting works from one parent polygon. | `src/jpg_boundary_kmz_core.py`, `_build_sections`, `_partition_connected_polygon` | Verified from code | New outline strategies must produce section-compatible polygons. |
| GUI calls `generate_boundary_from_input` directly for scan/export. | `src/jpg_boundary_kmz_gui.py`, `_scan_worker`, `_export_worker` | Verified from code | GUI mode options must flow through this boundary. |
| The root launcher inserts `src` on `sys.path` and imports `jpg_boundary_kmz_gui.main`. | `run_jpg_boundary_gui.py` | Verified from code | New modules in `src/` can be imported like existing modules. |
| No `tests/` directory currently exists in this repo. | `rg --files` from repo root | Verified from repository listing | New testing structure must be created. |
| Existing dependency list already includes `numpy`, `scipy`, `shapely`, and `pyproj`. | `requirements_jpg_boundary_kmz.txt` | Verified from code | Planned algorithms should avoid new dependencies initially. |
| Shapely 2.0.7 is installed locally and supports `segmentize`. | `python -c "import shapely; ..."` | Verified in local environment | Segment densification can be implemented without adding dependencies on this machine. |
| `Buffer-Zone-Generator` buffers projected line geometry using `quad_segs=64`, then `buffer(0)`, then `segmentize(10m)`. | `C:\Users\rbake\Desktop\VS Code Shortcuts\Buffer-Zone-Generator\src\buffer_zone_generator\geometry.py`, `build_buffer_geometry` | Verified from code | These are the strongest directly transferable improvements. |
| `Buffer-Zone-Generator` validates exported shape deviation with projected Hausdorff distance. | `C:\Users\rbake\Desktop\VS Code Shortcuts\Buffer-Zone-Generator\src\buffer_zone_generator\verification.py`, `verify_generated_output` | Verified from code | Use the same idea for regression tests and candidate scoring diagnostics. |

External source notes:

- Shapely documents `buffer` and its `quad_segs`, `cap_style`, `join_style`, and `mitre_limit` behavior: <https://shapely.readthedocs.io/en/stable/reference/shapely.buffer.html>
- Shapely documents `segmentize` as adding vertices so line segments do not exceed a maximum length: <https://shapely.readthedocs.io/en/stable/reference/shapely.segmentize.html>
- Shapely documents `concave_hull`, which is the current fallback basis: <https://shapely.readthedocs.io/en/stable/reference/shapely.concave_hull.html>

## 3. Exact Impacted Files And Symbols

### Existing Files To Modify

`src/jpg_boundary_kmz_core.py`

- `GpsPoint`
- `BoundaryMetadata`
- `BoundaryResult`
- `generate_boundary`
- `generate_boundary_from_input`
- `generate_boundary_from_kmz`
- `save_kmz`
- `format_summary`
- `_read_gps_point`
- `_ensure_polygon`
- `_simplify_with_containment`
- buffer call sites using `BUFFER_QUAD_SEGS`

Reason: this is the central boundary generation and KMZ export module.

`src/jpg_boundary_kmz_gui.py`

- `BoundaryKmzApp.__init__`
- `_build_ui`
- `_read_inputs`
- `_scan_worker`
- `_export_worker`
- `_draw_preview`
- `_settings_key`

Reason: outline mode, classifier details, and cache invalidation need to be surfaced in the GUI.

`README_JPG_BOUNDARY_KMZ.md`

- Behavior section
- Sources section
- Dependency/usage notes if mode controls are added

Reason: user-visible behavior changes must be documented.

### New Files To Create

`src/geometry_hardening.py`

- projected buffer helper
- geometry cleanup helper
- export densification helper
- polygon validation helpers

Reason: isolate transferable `Buffer-Zone-Generator` geometry improvements from strategy logic.

`src/camera_preflight.py`

- preflight metrics dataclasses
- capture order selection
- heading/distance/row metrics
- pattern classifier
- mixed-section detection helpers

Reason: keep classification deterministic and testable.

`src/outline_strategies.py`

- candidate dataclasses
- concave fallback strategy wrapper
- route-aware strategy
- lawnmower outer-envelope strategy
- mixed-section strategy orchestration
- candidate scoring and rejection reasons

Reason: keep strategy-specific geometry out of the GUI and core orchestration.

`tests/test_geometry_hardening.py`

Reason: prove densification, cleanup, and buffer behavior.

`tests/test_camera_preflight.py`

Reason: prove classifier behavior on synthetic camera patterns.

`tests/test_outline_strategies.py`

Reason: prove strategy selection and shape construction.

`tests/test_core_regression.py`

Reason: protect existing JPG/KMZ flows.

`tests/geometry_test_utils.py`

Reason: shared synthetic point-cloud and polygon builders for deterministic test cases. This avoids duplicating fragile test setup across classifier, strategy, and regression tests.

`docs/camera-boundary-v2-implementation-plan.md`

Reason: this planning artifact. Future revisions are allowed only when planning changes are intentional.

### Proposed Internal API Contracts

These contracts are implementation targets. They are not current code.

`OutlineMode`

- `auto`
- `concave_hull`
- `route_aware`
- `lawnmower_envelope`

The GUI should display human-friendly labels, but the core should use stable string values. If an unknown value reaches the core, the core must raise `BoundaryError` with a clear message instead of silently falling back.

`CameraPreflightResult`

- `pattern`: one of `boundary_trace`, `lawnmower`, `mixed`, `scatter_unknown`
- `confidence`: float from `0.0` through `1.0`
- `order_source`: `exif_datetime`, `filename`, or `input_sort`
- `metrics`: serializable diagnostic values for details output
- `section_breaks`: ordered point-index break candidates
- `warnings`: human-readable reasons that lower confidence

`OutlineCandidate`

- `strategy`: stable strategy identifier
- `polygon_projected`: projected Shapely polygon
- `confidence`: strategy confidence
- `score`: comparable numeric score
- `accepted`: boolean
- `rejection_reasons`: list of specific failed gates
- `diagnostics`: serializable values for details output

`BoundaryMetadata` additions should remain backward-compatible with existing formatting code. New fields should have simple scalar or string values, not nested Shapely objects or NumPy arrays.

## 4. Risk Matrix

| Risk | Severity | Likelihood | Mitigation | Detection |
|---|---:|---:|---|---|
| Auto classifier incorrectly treats perimeter/corridor data as lawnmower and shrinks output. | High | Medium | Require high classifier confidence; fallback to concave hull if uncertain. | Synthetic tests and real sample review. |
| Lawnmower outer-envelope misses concave notches or complex corners. | High | Medium | Preserve corner candidates and compare against concave hull coverage/area. | Candidate scoring diagnostics. |
| Mixed-section splitting creates disconnected artifacts. | High | Medium | Validate each section and union result; reject disconnected candidates unless intended. | Geometry validity tests. |
| Capture order is wrong due to missing EXIF timestamps. | Medium | Medium | Track order source; fallback to filename order; avoid route-aware strategy if order quality is poor. | Preflight details output. |
| Densified KMZ files become too large. | Medium | Low | Use configurable max segment length; report vertex count; default 10m or coarser if needed. | Vertex-count tests and manual export review. |
| Existing KMZ polygon input regresses. | High | Low | Keep KMZ path separate; add regression test. | `test_kmz_input_still_works`. |
| GUI cache returns stale results after mode change. | Medium | Medium | Include outline mode and strategy parameters in cache key. | GUI smoke test. |
| New modules introduce circular imports. | Medium | Low | Keep dependencies directional: core imports strategy modules; strategy modules do not import GUI. | `compileall`. |
| Dependency/version mismatch on another machine without Shapely `segmentize`. | Medium | Medium | Detect capability or pin/version-document Shapely 2.x if needed. | startup/test failure with clear message. |

## 5. Assumptions And Unknowns

| Item | Classification | Notes |
|---|---|---|
| Current concave hull behavior is acceptable as fallback. | Verified from code and existing README behavior | Existing docs say the outline is intentionally generalized. |
| New modules can live directly under `src/`. | Verified from launcher/import pattern | Existing files import sibling modules from `src`. |
| Synthetic tests are enough for implementation gates. | Likely but not fully proven | Real sample validation is still needed before production confidence. |
| JPG filenames are often capture-order sorted. | Unverified risk | Must not be treated as guaranteed. |
| EXIF `DateTimeOriginal` is available in many target images. | Unverified risk | Current code does not read it. |
| Representative real JPG folders are available outside the repo. | Blocker requiring clarification for final tuning | Needed for threshold calibration. |
| The output should remain one parent polygon before optional section splitting. | Likely but not fully proven | Existing splitting assumes one connected parent polygon. |
| Adding an `Outline mode` GUI option is acceptable. | Likely but not fully proven | User requested a new version using all techniques; exact UI label not confirmed. |

## 6. Edge Cases And Failure Modes

### Input Edge Cases

- No JPGs found.
- Fewer than 3 geotagged JPGs.
- Fewer than 3 unique projected GPS points.
- Duplicate GPS points from hover/camera burst.
- Missing EXIF GPS.
- Missing EXIF timestamp.
- Timestamp order conflicts with filename order.
- Outlier GPS points far from the main cluster.
- Large gaps between flight sections.
- Multiple disjoint job areas in one folder.
- Very large folders with thousands of images.
- JPG paths with spaces or non-ASCII characters.

### Geometry Edge Cases

- L-shaped or U-shaped boundary trace.
- Intersections or crossing capture paths.
- Lawnmower rows inside an irregular boundary.
- Mixed data containing a corridor/perimeter section plus a lawnmower block.
- Curved rows or non-parallel rows.
- Interior row turns near the edge that look like corners.
- Sparse camera positions at real corners.
- Tiny sliver polygons after union or intersection.
- MultiPolygon output where single connected output is expected.
- Simplification or cleanup removing necessary concavity.
- Buffering at zero distance.

### GUI/Workflow Edge Cases

- Scan with `Auto`, then export after changing mode.
- Scan/export cache invalidation after changing section count or overlap.
- KMZ input selected while outline mode controls are visible.
- Existing saved output path overwrite confirmation.
- Drag/drop path handling remains unchanged.

## 7. Strict File Allow-List

No files outside this table may be edited, created, deleted, moved, formatted, or regenerated unless this plan is revised first.

| Path | Change Type | Reason | Related Tests | Risk | Rollback Notes |
|---|---|---|---|---|---|
| `docs/camera-boundary-v2-implementation-plan.md` | Create/modify | Planning artifact | Documentation review | Low | Revert file only. |
| `src/geometry_hardening.py` | Create | Shared projected cleanup/densify helpers | `tests/test_geometry_hardening.py` | Medium | Remove imports and file. |
| `src/camera_preflight.py` | Create | Camera pattern analysis and classification | `tests/test_camera_preflight.py` | High | Disable Auto and remove imports. |
| `src/outline_strategies.py` | Create | Candidate outline generation and scoring | `tests/test_outline_strategies.py` | High | Force concave strategy and remove imports. |
| `src/jpg_boundary_kmz_core.py` | Modify | Orchestrate strategies and export hardening | All test files | High | Restore old `generate_boundary` path. |
| `src/jpg_boundary_kmz_gui.py` | Modify | Add outline mode and diagnostics | Core tests plus manual smoke | Medium | Remove mode UI and pass default. |
| `README_JPG_BOUNDARY_KMZ.md` | Modify | Document new modes and sources | Documentation review | Low | Revert README changes. |
| `tests/test_geometry_hardening.py` | Create | Validate geometry helper behavior | `python -m unittest ...` | Low | Delete test file. |
| `tests/test_camera_preflight.py` | Create | Validate classifier behavior | `python -m unittest ...` | Medium | Delete test file. |
| `tests/test_outline_strategies.py` | Create | Validate outline algorithms | `python -m unittest ...` | High | Delete test file. |
| `tests/test_core_regression.py` | Create | Protect existing workflows | `python -m unittest ...` | Medium | Delete test file. |
| `tests/geometry_test_utils.py` | Create | Shared synthetic fixtures and assertions | Used by all test files | Low | Delete test helper and inline fixtures if needed. |
| `requirements_jpg_boundary_kmz.txt` | Conditional modify | Only if no runtime fallback for Shapely versions without `segmentize` is implemented | Full test suite and install check | Medium | Revert requirement change and use runtime fallback instead. |

Explicitly excluded unless the plan is revised:

- `outputs/`
- `__pycache__/`
- `src/__pycache__/`
- `run_jpg_boundary_gui.py`
- `src/run_jpg_boundary_gui.py`
- `run_jpg_boundary_gui.bat`
- `agent_prompt_templates/`
- files in `C:\Users\rbake\Desktop\VS Code Shortcuts\Buffer-Zone-Generator`

## 8. Implementation Phases With Gates

### Phase 0: Baseline And Guardrails

Goal: establish current state without modifying source code.

Allowed files touched:

- None.

Tasks:

- Record `git status --short --branch`.
- Confirm Shapely version and `segmentize` availability.
- Run baseline compile check.
- Document untracked files.

Commands:

```powershell
git status --short --branch
python -c "import shapely; from shapely.geometry import Polygon; print(shapely.__version__); print(hasattr(Polygon([(0,0),(1,0),(1,1),(0,0)]), 'segmentize'))"
python -m compileall src
```

Expected output:

- Branch is known.
- Existing untracked files are documented.
- `compileall` succeeds.

Failure conditions:

- Source does not compile.
- Shapely lacks `segmentize` and no fallback decision is made.

Pass/fail criteria:

- Pass only if baseline is understood and no implementation file has been touched.

Rollback/recovery:

- No rollback required because no source files are changed.

### Phase 1: Geometry Hardening Foundation

Goal: port only the safe geometry foundation from `Buffer-Zone-Generator`.

Allowed files touched:

- `src/geometry_hardening.py`
- `src/jpg_boundary_kmz_core.py`
- `tests/test_geometry_hardening.py`

Tasks:

- Add constants such as `EXPORT_MAX_SEGMENT_M = 10.0` and `BUFFER_QUAD_SEGS = 64` or equivalent helper defaults.
- Add helper to clean constructive geometry with `buffer(0)` when needed.
- Add helper to segmentize projected polygons before WGS84 transformation/export.
- Add a runtime capability check or dependency version decision for Shapely `segmentize`.
- Replace repeated buffer call parameters in core with helper calls where safe.
- Preserve existing zero-buffer behavior.

Required tests:

- `test_segmentize_caps_projected_segments`
- `test_buffer_cleanup_returns_valid_polygon`
- `test_zero_buffer_does_not_create_extra_shape`

Commands:

```powershell
python -m unittest tests.test_geometry_hardening
python -m compileall src
```

Expected outputs:

- Valid polygons after cleanup.
- Densified geometry has no long exterior segments above the configured max, within tolerance.
- Existing functions still import.

Failure conditions:

- Densification changes geometry area beyond a small tolerance.
- KMZ input path breaks.
- Implementation relies on `segmentize` without either a version guard or a documented/pinned dependency requirement.

Pass/fail criteria:

- Unit tests pass.
- Compile check passes.
- Diff only includes allow-listed files for this phase.

Rollback/recovery:

- Remove helper usage from core and return to direct `.buffer(...)` calls.

### Phase 2: Camera Preflight Classifier

Goal: classify camera-position patterns before building an outline.

Allowed files touched:

- `src/camera_preflight.py`
- `src/jpg_boundary_kmz_core.py`
- `tests/test_camera_preflight.py`

Tasks:

- Add dataclasses:
  - `CameraOrder`
  - `CameraPreflightMetrics`
  - `CameraPattern`
  - `CameraPreflightResult`
- Compute:
  - median nearest-neighbor spacing
  - ordered segment distances
  - ordered segment headings
  - heading-change distribution
  - dominant heading clusters
  - row spacing estimates
  - gap candidates
  - outlier candidates
- Classify:
  - `boundary_trace`
  - `lawnmower`
  - `mixed`
  - `scatter_unknown`
- Include confidence score and rejection/fallback reasons.
- Extend GPS reading only if needed to capture EXIF date/time. If EXIF timestamp support is implemented, avoid breaking existing GPS-only behavior.

Required tests:

- `test_detects_lawnmower_parallel_rows`
- `test_detects_boundary_trace`
- `test_detects_scatter_unknown`
- `test_identifies_large_gap_candidates`
- `test_missing_capture_order_uses_filename_fallback`

Commands:

```powershell
python -m unittest tests.test_camera_preflight
python -m compileall src
```

Expected outputs:

- Classifier returns deterministic classifications for synthetic datasets.
- Low-confidence ambiguous patterns return `scatter_unknown` or fallback-worthy results.

Failure conditions:

- Ambiguous synthetic cases are classified as high-confidence lawnmower.
- Missing timestamps fail JPG processing.

Pass/fail criteria:

- Tests pass.
- No GUI changes yet.
- Existing core flow can still generate boundaries.

Rollback/recovery:

- Stop importing/running preflight in core; leave module unused or remove it.

### Phase 3: Outline Strategy Engine

Goal: generate and score multiple candidate polygons, then select the safest strategy.

Allowed files touched:

- `src/outline_strategies.py`
- `src/geometry_hardening.py`
- `src/camera_preflight.py`
- `src/jpg_boundary_kmz_core.py`
- `tests/test_outline_strategies.py`
- `tests/test_core_regression.py`

Tasks:

- Add candidate dataclass with:
  - strategy name
  - polygon
  - confidence
  - score
  - rejection reasons
  - diagnostic metrics
- Implement strategy functions:
  - current concave hull wrapper
  - route-aware buffered path
  - lawnmower outer-envelope
  - mixed-section union
- Implement scoring:
  - geometry validity
  - area plausibility
  - required point coverage
  - perimeter/area compactness
  - row-turn noise penalty
  - Hausdorff-style comparison where useful
- Implement hard acceptance gates before numeric scoring:
  - geometry must be non-empty and valid after repair
  - polygon must cover required boundary/control points unless a documented strategy intentionally ignores interior lawnmower points
  - area must be within configured min/max ratios relative to the concave fallback
  - selected candidate must not introduce unsupported holes
  - selected candidate must be section-compatible, or section splitting must be explicitly disabled with a clear error
- Select Auto result:
  - accept high-confidence non-concave candidate only if it passes all safety gates
  - otherwise return concave hull fallback

Required tests:

- `test_lawnmower_uses_outermost_cameras`
- `test_lawnmower_rejects_low_confidence_rows`
- `test_route_trace_preserves_l_shape_corner`
- `test_route_trace_rejects_bad_order`
- `test_auto_falls_back_to_concave_when_uncertain`
- `test_candidate_rejected_when_area_ratio_is_implausible`
- `test_candidate_rejected_when_required_points_are_not_covered`
- `test_candidate_rejected_when_geometry_is_disconnected_for_sections`
- `test_kmz_input_still_works`
- `test_existing_concave_mode_still_generates_polygon`

Commands:

```powershell
python -m unittest tests.test_outline_strategies tests.test_core_regression
python -m compileall src
```

Expected outputs:

- Route-aware mode preserves synthetic non-linear corners better than concave fallback.
- Lawnmower mode ignores interior row cameras.
- Auto mode is conservative.

Failure conditions:

- Auto mode produces invalid geometry.
- Existing KMZ polygon workflow changes unexpectedly.
- Section splitting receives a disconnected polygon unexpectedly.

Pass/fail criteria:

- All strategy and regression tests pass.
- Core metadata includes selected strategy and fallback reason.

Rollback/recovery:

- Force strategy selection to concave fallback.
- Keep new modules but bypass them until fixed.

### Phase 4: GUI And User-Facing Details

Goal: expose the new engine safely in the desktop app.

Allowed files touched:

- `src/jpg_boundary_kmz_gui.py`
- `src/jpg_boundary_kmz_core.py`
- `README_JPG_BOUNDARY_KMZ.md`
- `tests/test_core_regression.py`

Tasks:

- Add `Outline mode` control:
  - `Auto`
  - `Concave hull`
  - `Route-aware`
  - `Lawnmower outer envelope`
- Pass selected mode into `generate_boundary_from_input`.
- Include mode in `_settings_key`.
- Show in details:
  - selected strategy
  - preflight classification
  - confidence
  - order source
  - fallback reason
  - candidate summary
- Keep KMZ input behavior clear; either disable mode controls for KMZ input or report that KMZ uses source polygon mode.

Required tests:

- Existing core tests.
- Manual GUI smoke test.

Commands:

```powershell
python -m unittest discover -s tests
python -m compileall src
python .\run_jpg_boundary_gui.py
```

Expected outputs:

- GUI launches.
- Scan/preview works with default `Auto`.
- Changing mode invalidates cache.
- Export creates KMZ.

Failure conditions:

- GUI cannot launch.
- Export uses stale cached strategy after mode change.

Pass/fail criteria:

- Tests pass.
- Manual scan/export succeeds on available sample.

Rollback/recovery:

- Remove mode UI and pass default concave/Auto behavior from core.

### Phase 5: Regression, Calibration, And Documentation

Goal: harden behavior against real and synthetic examples.

Allowed files touched:

- `README_JPG_BOUNDARY_KMZ.md`
- `tests/test_geometry_hardening.py`
- `tests/test_camera_preflight.py`
- `tests/test_outline_strategies.py`
- `tests/test_core_regression.py`
- implementation files already touched in prior phases, if fixes are required

Tasks:

- Add or refine synthetic fixtures.
- Add real-sample notes if representative folders are provided.
- Document mode behavior and known limits.
- Confirm sources in README.
- Review final diff against allow-list.
- Review candidate diagnostics for at least one accepted non-concave candidate and one fallback case.

Commands:

```powershell
python -m unittest discover -s tests
python -m compileall src
git diff --name-only
```

Expected outputs:

- All tests pass.
- Diff is allow-listed only.
- README describes current behavior accurately.

Failure conditions:

- Real samples show repeated false positives.
- README claims behavior not verified by tests or samples.

Pass/fail criteria:

- Ready only if the classifier is conservative on ambiguous data.

Rollback/recovery:

- Leave new code behind a default concave mode if Auto is not reliable.

## 9. Testing And Regression Matrix

| Test File | Test Name | Scenario | Expected Result | Failure Condition | Command |
|---|---|---|---|---|---|
| `tests/test_geometry_hardening.py` | `test_segmentize_caps_projected_segments` | Densify projected polygon | Exterior segments within configured limit | Long segment remains | `python -m unittest tests.test_geometry_hardening` |
| `tests/test_geometry_hardening.py` | `test_buffer_cleanup_returns_valid_polygon` | Constructive geometry cleanup | Valid polygon/MultiPolygon | Invalid output | same |
| `tests/test_geometry_hardening.py` | `test_zero_buffer_does_not_create_extra_shape` | Zero buffer path | Geometry unchanged except validation | Area/shape changes unexpectedly | same |
| `tests/test_camera_preflight.py` | `test_detects_lawnmower_parallel_rows` | Synthetic parallel rows | `lawnmower` with high confidence | Unknown or boundary trace | `python -m unittest tests.test_camera_preflight` |
| `tests/test_camera_preflight.py` | `test_detects_boundary_trace` | Synthetic ordered perimeter | `boundary_trace` | Lawnmower classification | same |
| `tests/test_camera_preflight.py` | `test_detects_scatter_unknown` | Random/scattered points | `scatter_unknown` or low confidence | High-confidence strategy | same |
| `tests/test_camera_preflight.py` | `test_identifies_large_gap_candidates` | Two clusters in order | Gap candidates returned | No gap detected | same |
| `tests/test_camera_preflight.py` | `test_missing_capture_order_uses_filename_fallback` | No timestamps | Deterministic filename order | Crash or random order | same |
| `tests/test_outline_strategies.py` | `test_lawnmower_uses_outermost_cameras` | Interior rows and outer rows | Exterior envelope ignores interior turn noise | Zigzag boundary | `python -m unittest tests.test_outline_strategies` |
| `tests/test_outline_strategies.py` | `test_lawnmower_rejects_low_confidence_rows` | Irregular rows | Candidate rejected | Bad lawnmower accepted | same |
| `tests/test_outline_strategies.py` | `test_route_trace_preserves_l_shape_corner` | Ordered L-shaped route | Corner preserved | Corner rounded away/excluded | same |
| `tests/test_outline_strategies.py` | `test_route_trace_rejects_bad_order` | Same points shuffled | Route strategy rejected | Bad route accepted | same |
| `tests/test_outline_strategies.py` | `test_auto_falls_back_to_concave_when_uncertain` | Ambiguous pattern | Concave fallback selected | Auto selects risky strategy | same |
| `tests/test_outline_strategies.py` | `test_candidate_rejected_when_area_ratio_is_implausible` | Candidate much smaller/larger than fallback | Candidate rejected with reason | Implausible candidate accepted | same |
| `tests/test_outline_strategies.py` | `test_candidate_rejected_when_required_points_are_not_covered` | Candidate excludes required controls | Candidate rejected with reason | Missing coverage accepted | same |
| `tests/test_outline_strategies.py` | `test_candidate_rejected_when_geometry_is_disconnected_for_sections` | Section request against disconnected candidate | Candidate rejected or clear error | Silent bad section output | same |
| `tests/test_core_regression.py` | `test_kmz_input_still_works` | Existing KMZ input workflow | Source polygon path works | KMZ mode fails | `python -m unittest tests.test_core_regression` |
| `tests/test_core_regression.py` | `test_existing_concave_mode_still_generates_polygon` | Synthetic JPG/GPS points | Valid polygon result | No polygon or invalid polygon | same |
| `tests/test_core_regression.py` | `test_sections_still_split_connected_polygon` | Multi-section output | Connected sections created | disconnected section failure | same |
| `tests/test_core_regression.py` | `test_unknown_outline_mode_raises_boundary_error` | Invalid mode string | Clear `BoundaryError` | Silent fallback or crash | same |

Full validation command:

```powershell
python -m unittest discover -s tests
```

## 10. Pre-Implementation Checklist

- [ ] Confirm branch with `git status --short --branch`.
- [ ] Confirm untracked files and decide whether to leave them untouched.
- [ ] Confirm all allow-listed files still exist or are intentionally new.
- [ ] Confirm Shapely version and `segmentize` support.
- [ ] Confirm no dependency updates are needed.
- [ ] Confirm current source compiles with `python -m compileall src`.
- [ ] Confirm no existing tests are hidden outside repo listing.
- [ ] Confirm no implementation files outside allow-list will be touched.
- [ ] Confirm final fallback behavior is the current concave hull path.
- [ ] Confirm whether real sample JPG folders are available for calibration.

## 11. Post-Implementation Validation Checklist

- [ ] `python -m unittest discover -s tests` passes.
- [ ] `python -m compileall src` passes.
- [ ] `python .\run_jpg_boundary_gui.py` launches.
- [ ] Manual scan/preview succeeds for at least one JPG folder if available.
- [ ] Manual export succeeds for at least one JPG folder if available.
- [ ] Manual KMZ input scan/export succeeds if sample KMZ is available.
- [ ] `git diff --name-only` contains only allow-listed files.
- [ ] No `outputs/` files are modified.
- [ ] No `__pycache__/` files are committed or intentionally modified.
- [ ] No temporary debug prints, TODO placeholders, or mock-only behavior remain.
- [ ] README matches implemented behavior.
- [ ] Details output reports selected strategy, confidence, and fallback reason.
- [ ] Public launch commands remain unchanged.

## 12. Rollback And Recovery Plan

Phase 1 rollback:

- Remove `geometry_hardening` imports.
- Restore direct `.buffer(...)` behavior in `jpg_boundary_kmz_core.py`.
- Delete `tests/test_geometry_hardening.py` if no longer relevant.

Phase 2 rollback:

- Stop calling camera preflight from core.
- Keep current GPS-only `GpsPoint` if timestamp changes are problematic.
- Delete or ignore `camera_preflight.py`.

Phase 3 rollback:

- Force outline mode to concave fallback.
- Keep candidate modules unused until fixed.
- Confirm old `generate_boundary` behavior with regression tests.

Phase 4 rollback:

- Remove GUI mode controls.
- Restore cache key to previous inputs.
- Keep metadata additions only if backward-compatible.

Phase 5 rollback:

- Revert documentation and test refinements that do not match final behavior.

General recovery:

- No database, migration, cloud, deployment, or generated-output recovery is needed.
- Any generated KMZs during manual tests should be treated as disposable and should not be committed.
- If validation fails after partial implementation, do not continue to downstream phases until the current phase passes or is rolled back.

## 13. Blockers Or Items Requiring Clarification

- Representative real JPG folders are needed for final Auto threshold tuning:
  - perimeter/boundary trace
  - pure lawnmower
  - mixed route plus lawnmower
  - complex corners/intersections
- Acceptance criteria should be clarified:
  - visual inspection only
  - maximum boundary deviation
  - area tolerance
  - point containment
  - comparison against hand-drawn/reference KMZ
- Confirm whether GUI should expose advanced threshold settings or keep them internal.
- Confirm whether KMZ polygon input should show outline mode controls as disabled or hide them.
- Confirm whether output vertex count/file size has a practical upper bound.
- Decide whether Shapely should be pinned to `>=2.0` or whether the implementation must include a manual segment densification fallback.

## 14. Final Readiness Assessment

Ready to begin Phase 0 through Phase 2 after approval.

Not ready to declare the Auto strategy production-grade until real sample folders are used to calibrate classifier thresholds. The implementation should therefore default to conservative fallback behavior and record enough diagnostics to explain every Auto decision.

## 15. Plan Audit And Hardening Addendum

This addendum audits the plan document using the repository-local guideline at `agent_prompt_templates/detailed-implementation-audit/post_implementation_audit.md`. Because no V2 implementation has been coded yet, this is a pre-implementation audit of the blueprint, not a code audit of completed source changes.

### 15.1 Executive Summary

Audit result: the plan is viable but needed hardening before implementation. The weak spots were missing internal API contracts, missing hard candidate rejection gates, insufficient dependency-version handling for `segmentize`, and incomplete user-required decisions. This addendum patches those planning gaps.

Readiness after audit: ready to begin Phase 0 through Phase 2, with open user decisions still required before final Auto-mode calibration.

### 15.2 Original Requirement Compliance Review

| Requirement | Audit Result | Evidence | Patch Required |
|---|---|---|---|
| Use the detailed planning guideline. | Satisfied | Plan includes discovery, evidence, assumptions, allow-list, phase gates, tests, validation, rollback. | No |
| Adapt useful logic from `Buffer-Zone-Generator`. | Satisfied but hardened | Plan references projected buffer, `buffer(0)`, `segmentize(10m)`, and Hausdorff-style verification from the other repo. | Yes, dependency guard added. |
| Improve accuracy around non-linear/complex camera positions. | Partially satisfied by design | Route-aware, lawnmower, and mixed strategies are planned but not implemented. | Yes, hard acceptance gates added. |
| Avoid lawnmower row-end artifacts. | Partially satisfied by design | Lawnmower outer-envelope strategy is planned. | Yes, additional tests and rejection gates added. |
| Include explicit references and allow-lists. | Satisfied | Plan has evidence and strict allow-list. | Yes, test helper and conditional requirements row added. |
| Include user-required open decisions. | Satisfied after audit | See section 15.12. | Yes |

### 15.3 Files Inspected

| File | What Was Verified | Status |
|---|---|---|
| `docs/camera-boundary-v2-implementation-plan.md` | Full plan content, phases, allow-list, tests, blockers. | Verified directly |
| `agent_prompt_templates/detailed-implementation-audit/post_implementation_audit.md` | Audit requirements and final output format. | Verified directly |
| `src/jpg_boundary_kmz_core.py` | Current key symbols: `GpsPoint`, `BoundaryMetadata`, `BoundaryResult`, `generate_boundary`, `generate_boundary_from_input`, `generate_boundary_from_kmz`, `save_kmz`, `format_summary`, `_read_gps_point`, `_simplify_with_containment`, `_ensure_polygon`, `BUFFER_QUAD_SEGS`. | Verified directly |
| `src/jpg_boundary_kmz_gui.py` | GUI integration points: `BoundaryKmzApp`, `_build_ui`, `_scan_worker`, `_export_worker`, `_read_inputs`, `_draw_preview`, `_settings_key`. | Verified directly |
| `requirements_jpg_boundary_kmz.txt` | Existing dependencies are unpinned package names. | Verified directly |
| `C:\Users\rbake\Desktop\VS Code Shortcuts\Buffer-Zone-Generator\src\buffer_zone_generator\geometry.py` | Transferable buffer hardening: `quad_segs=64`, `buffer(0)`, `segmentize(MAX_EXPORT_SEGMENT_M)`. | Verified directly |
| `C:\Users\rbake\Desktop\VS Code Shortcuts\Buffer-Zone-Generator\src\buffer_zone_generator\verification.py` | Hausdorff-style output verification pattern. | Verified directly |

### 15.4 Issues Found

| Issue | Severity | Status | Patch Applied |
|---|---:|---|---|
| Plan named new modules but did not define stable internal contracts. | High | Confirmed planning gap | Added proposed internal API contracts. |
| Plan relied on `segmentize` without deciding version pin vs fallback. | Medium | Confirmed planning gap | Added conditional requirement allow-list and Phase 1 failure condition. |
| Plan had scoring ideas but no hard acceptance gates before scoring. | High | Confirmed planning gap | Added required acceptance gates in Phase 3. |
| Plan duplicated synthetic fixture needs across tests without a helper file. | Low | Likely maintainability issue | Added `tests/geometry_test_utils.py` to allow-list. |
| Plan did not require tests for invalid outline mode. | Medium | Confirmed gap | Added regression test requirement. |
| Plan did not require diagnostics review for both accepted and fallback Auto decisions. | Medium | Confirmed gap | Added Phase 5 task. |
| Open user decisions existed but were not presented as an answerable checklist. | Medium | Confirmed gap | Added section 15.12. |

### 15.5 Patches Applied To The Plan

- Added proposed internal API contracts for `OutlineMode`, `CameraPreflightResult`, and `OutlineCandidate`.
- Added `tests/geometry_test_utils.py` to the allow-list.
- Added conditional `requirements_jpg_boundary_kmz.txt` allow-list row only for the Shapely `segmentize` decision.
- Removed `requirements_jpg_boundary_kmz.txt` from the unconditional exclusion list.
- Added Phase 1 requirement for a `segmentize` capability check or dependency version decision.
- Added Phase 3 hard candidate acceptance gates.
- Added additional strategy and regression tests for area ratio, required point coverage, disconnected section handling, and invalid outline mode.
- Added Phase 5 diagnostics review for accepted and fallback Auto decisions.
- Added this audit addendum and user-required open decisions.

### 15.6 Edge Cases And Failure Modes Reviewed

Additional audit emphasis beyond the original plan:

- Ambiguous patterns must not produce high-confidence non-concave outputs.
- Bad route order must not be accepted merely because points form a plausible shape.
- Lawnmower envelope must not exclude true perimeter corner points.
- Area ratio checks must prevent both under-coverage and excessive over-coverage.
- Required control-point coverage must be explicit and strategy-aware.
- MultiPolygon or disconnected candidates must not silently flow into section splitting.
- Unknown outline mode values must fail clearly.
- Shapely version mismatch must fail clearly or be handled with fallback code.

### 15.7 Tests Added Or Updated In The Plan

Planned tests added by this audit:

- `tests/test_outline_strategies.py::test_candidate_rejected_when_area_ratio_is_implausible`
- `tests/test_outline_strategies.py::test_candidate_rejected_when_required_points_are_not_covered`
- `tests/test_outline_strategies.py::test_candidate_rejected_when_geometry_is_disconnected_for_sections`
- `tests/test_core_regression.py::test_unknown_outline_mode_raises_boundary_error`

Planned helper added:

- `tests/geometry_test_utils.py`

### 15.8 Validation Commands Run During This Audit

Commands run:

```powershell
git status --short --branch
Get-Content -Raw agent_prompt_templates\detailed-implementation-audit\post_implementation_audit.md
Get-Content -Raw docs\camera-boundary-v2-implementation-plan.md
Select-String -Path src\jpg_boundary_kmz_core.py -Pattern "class GpsPoint|class BoundaryMetadata|class BoundaryResult|def generate_boundary\(|def generate_boundary_from_input|def generate_boundary_from_kmz|def save_kmz|def format_summary|def _read_gps_point|def _ensure_polygon|def _simplify_with_containment|BUFFER_QUAD_SEGS"
Select-String -Path src\jpg_boundary_kmz_gui.py -Pattern "class BoundaryKmzApp|def _build_ui|def _scan_worker|def _export_worker|def _read_inputs|def _draw_preview|def _settings_key"
Select-String -Path "C:\Users\rbake\Desktop\VS Code Shortcuts\Buffer-Zone-Generator\src\buffer_zone_generator\geometry.py" -Pattern "MAX_EXPORT_SEGMENT_M|def get_utm_epsg_for_lines|def build_buffer_geometry|buffer\(|buffer\(0\)|segmentize"
Select-String -Path "C:\Users\rbake\Desktop\VS Code Shortcuts\Buffer-Zone-Generator\src\buffer_zone_generator\verification.py" -Pattern "def verify_generated_output|hausdorff_distance|project_lines.distance"
```

No test suite was run during this audit because no source implementation exists yet and the only change is this plan document.

### 15.9 UI And Manual Verification Results

Not applicable yet. No GUI implementation has been changed. The plan now requires manual GUI smoke testing in Phase 4.

### 15.10 Regression Risk Assessment

The highest regression risks remain:

- Existing concave-hull JPG output changes unexpectedly.
- Existing single-polygon KMZ input behavior regresses.
- Section splitting receives unsupported disconnected or holed geometry.
- GUI cache returns stale results after outline mode changes.
- Unpinned Shapely dependency behaves differently on another machine.

The plan now includes explicit tests or phase gates for each risk.

### 15.11 Remaining Risks, Blockers, Or Unresolved Items

- Real-world classifier thresholds cannot be finalized from synthetic data alone.
- The correct default UI behavior for KMZ input and advanced thresholds requires a user decision.
- Dependency strategy for Shapely `segmentize` needs a user or implementation decision.
- Output vertex/file-size limits need a user decision if downstream tools have constraints.

### 15.12 User-Required Open Decisions

Please answer these before Phase 3 or Phase 4 implementation begins:

1. Should `Auto` be the default outline mode for JPG folders, with concave hull as fallback?
2. For KMZ polygon input, should the outline mode control be hidden, disabled with explanatory status text, or left visible but ignored?
3. Should advanced classifier thresholds be hidden/internal for now, or exposed in the GUI under an advanced section?
4. What acceptance target matters most for real outputs: visual inspection, maximum boundary deviation, area tolerance, point containment, or comparison against a hand-drawn/reference KMZ?
5. Do you have representative real JPG folders for perimeter trace, pure lawnmower, mixed route/lawnmower, and complex corners/intersections?
6. Should the project pin `shapely>=2.0` in `requirements_jpg_boundary_kmz.txt`, or should implementation include a manual densification fallback for older Shapely versions?
7. Is there a practical KMZ file-size or vertex-count ceiling we must stay below for Google Earth or downstream tools?
8. When Auto is uncertain, should it silently use concave fallback, or should the GUI show a warning that fallback was used?

### 15.13 Final Readiness Assessment

Ready to begin Phase 0 through Phase 2.

Not ready to close the overall V2 design until the user-required open decisions above are answered and representative real samples are used to calibrate Auto-mode behavior.
