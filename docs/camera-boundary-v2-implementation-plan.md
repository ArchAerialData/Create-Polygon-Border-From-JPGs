# Camera Boundary V2 Authoritative Implementation Plan

Status: authoritative phased implementation guide. This document is the source of truth for implementing Camera Boundary V2 unless it is explicitly revised before or during implementation.

Repository root:

```text
C:\Users\rbake\Desktop\VS Code Shortcuts\Create-Polygon-Border-From-JPGs
```

Current repository status notes observed during planning and final review:

- Branch: `Testing-New-Methods...origin/Testing-New-Methods`.
- `agent_prompt_templates/` existed before this plan file was created and is not part of the implementation allow-list unless explicitly approved later.
- `test_data/` exists locally as read-only calibration data and must stay ignored by `.gitignore` so massive sample datasets are not tracked or committed.

## 0. Implementation Authority

This section controls implementation. If any historical planning or audit wording later in this document is less strict, this section wins.

### 0.1 Fixed Product Decisions

- JPG folders are the primary input for Camera Boundary V2.
- `Auto` is the default outline mode for JPG folders.
- The current concave-hull workflow remains the conservative fallback.
- Existing KMZ-as-primary input remains a legacy compatibility workflow and must not be broken.
- Human-made KMZs under `test_data\output-shape-examples` are validation/calibration references only. They must not cause generated output to expand into pipeline/system areas without JPG coverage.
- Advanced classifier thresholds stay internal for the first implementation. The backend must keep threshold constants centralized so a future GUI advanced section can expose them without rewriting strategy logic.
- Acceptance uses reference KMZ comparison when available, plus agent-performed visual/manual review and guardrail metrics. When no reference geometry is available, acceptance uses agent-performed visual/manual review, area plausibility, control-point coverage, and boundary-deviation diagnostics. Human review is required only when the orchestrator's human-blocking conditions are triggered.
- `requirements_jpg_boundary_kmz.txt` must pin `shapely>=2.0`.
- No hard KMZ file-size or vertex-count ceiling is required.
- If `Auto` falls back to concave hull, the GUI/details output must show a non-blocking fallback reason.

### 0.2 Implementation Constraints

- Use the existing direct `src/` module pattern; do not introduce packaging changes.
- Use Python `unittest`; do not introduce `pytest` or new test dependencies.
- Do not add runtime dependencies other than the `shapely>=2.0` pin.
- Treat `test_data/` as read-only input data.
- Keep the `.gitignore` rule for `test_data/`; `git status --short` must not list sample data files or folders.
- Do not write generated outputs into `test_data/`, `outputs/`, or source folders during tests. Tests must use temporary directories.
- Keep generated KMZs from manual validation disposable and uncommitted.
- Do not modify `run_jpg_boundary_gui.py`, `src/run_jpg_boundary_gui.py`, or `run_jpg_boundary_gui.bat`.
- Do not modify `agent_prompt_templates/`.
- Do not modify files in `C:\Users\rbake\Desktop\VS Code Shortcuts\Buffer-Zone-Generator`.

### 0.3 Required Module Boundaries

- `src/geometry_hardening.py` owns projected buffer helpers, `buffer(0)` cleanup, segment densification, and geometry validity helpers.
- `src/camera_preflight.py` owns camera order, spacing, heading, row, gap, and pattern classification metrics.
- `src/outline_strategies.py` owns outline candidate construction, strategy scoring, and hard candidate rejection gates.
- `src/jpg_boundary_kmz_core.py` owns orchestration, metadata, KMZ save behavior, legacy KMZ input compatibility, and public generation functions.
- `src/jpg_boundary_kmz_gui.py` owns UI controls, cached settings, preview, worker calls, and user-visible details/status text.
- Test helper code belongs in `tests/geometry_test_utils.py`; production modules must not import test helpers.

### 0.4 Hard Phase Gate Rules

- Phases must be implemented in order.
- Do not begin a downstream phase until every command and pass/fail criterion in the current phase passes.
- Passing phase gates are agent-verifiable and do not require human approval unless a human-blocking condition in `docs/camera-boundary-v2-implementation-orchestrator.md` is triggered.
- If a phase fails, patch within that phase's allow-list or revise this document before touching additional files.
- After each phase, run `git status --short` and `git diff --name-only` and confirm that only files allowed for that phase changed or remain untracked.
- After each phase, confirm `test_data/`, `outputs/`, `__pycache__/`, and non-allow-listed files were not modified.
- After each phase, confirm `git status --short` does not show `test_data/` or files below it.
- Any implementation that silently changes legacy KMZ-as-primary behavior fails the gate.
- Any implementation that lets `Auto` select invalid geometry, unsupported disconnected geometry, or a candidate outside JPG-covered areas fails the gate.
- Human review blocks progress only for the human-blocking conditions listed in `docs/camera-boundary-v2-implementation-orchestrator.md`.

### 0.5 Final Required Validation Commands

Run these before considering implementation complete:

```powershell
git status --short --branch
python -m unittest discover -s tests
python -m compileall src
python .\run_jpg_boundary_gui.py
git check-ignore -v test_data/
git diff --name-only
```

Manual validation is also required against:

- `test_data\jpgs\Lawn Mower JPGs`
- `test_data\output-shape-examples\Lawn Mower JPGs\Lawn Mower JPGs.kmz`
- `test_data\jpgs\Day 1 - 06-24`
- `test_data\output-shape-examples\Day 1 - 06-24\Day 1 - 06-24.kmz`

### 0.6 Testing And Evidence Authority

- Automated tests use `unittest` and live under `tests/`.
- Every test named in section 9 is required unless this document is revised before implementation.
- Phase 5 must create `docs/camera-boundary-v2-validation-notes.md`.
- `docs/camera-boundary-v2-validation-notes.md` must record the commands run, generated disposable output locations, real sample inputs used, reference KMZs used, selected strategies, fallback reasons, and pass/fail notes.
- Manual validation evidence is incomplete if `docs/camera-boundary-v2-validation-notes.md` does not mention both real datasets.
- A phase is failed if any required automated command fails, if changed files exceed that phase's allow-list, or if validation evidence required for that phase is missing.

## 1. Executive Summary

The new version must replace the single default JPG outline method with an auto-selected outline engine. The current repo builds a JPG boundary from GPS points using a Shapely concave hull, then applies simplification, user-selected buffering, user-selected section splitting, preview, and KMZ export. That path remains the conservative fallback.

The new engine must add:

- A camera-position preflight classifier.
- Route-aware outline generation for perimeter/corridor-style capture paths.
- Lawnmower outer-envelope outline generation that ignores interior row-turn noise.
- Mixed-section handling for inputs containing both linear/perimeter and lawnmower sections.
- Projected geometry hardening adapted from `Buffer-Zone-Generator`, including higher buffer resolution, geometry cleanup, and segment densification before export.
- Explicit GUI controls and details output so users can see the selected strategy, confidence, and fallback reason.

The primary risk is incorrect automatic classification. The implementation must be conservative: if confidence is low, the current concave hull path remains the output.

User decisions resolved on 2026-06-30:

- `Auto` is the default outline mode for JPG folders.
- V2 remains JPG-primary. KMZs are allowed only as reference/calibration geometry, and generated shapes must stay focused on areas with actual JPG coverage, not an entire client pipeline/system boundary.
- Existing KMZ-as-primary workflow remains a legacy compatibility path; it is not the focus of V2 camera-boundary inference.
- Advanced classifier thresholds stay internal for the first version, but backend structures must keep them easy to expose in the GUI later.
- Acceptance uses reference KMZ comparison when available; otherwise use agent-performed visual/manual review plus guardrail metrics. Human review is not required unless the orchestrator's human-blocking conditions are triggered.
- `shapely>=2.0` must be pinned instead of implementing a manual segmentization fallback.
- No practical KMZ file-size or vertex-count ceiling is required.
- Uncertain `Auto` fallback must be shown as a non-blocking status/details warning.

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
| Existing dependency list already includes `numpy`, `scipy`, `shapely`, and `pyproj`. | `requirements_jpg_boundary_kmz.txt` | Verified from code | Planned algorithms must avoid new dependencies except the `shapely>=2.0` pin. |
| Shapely 2.0.7 is installed locally and supports `segmentize`. | `python -c "import shapely; ..."` | Verified in local environment | Segment densification can be implemented without adding dependencies on this machine. |
| Real calibration JPG samples are available under `test_data\jpgs`. | `test_data\jpgs\Lawn Mower JPGs`, `test_data\jpgs\Day 1 - 06-24` | Verified from repository filesystem | Use for calibration/manual validation; keep read-only during implementation. |
| Human-made output-shape examples are available under `test_data\output-shape-examples`. | `test_data\output-shape-examples\Lawn Mower JPGs\Lawn Mower JPGs.kmz`, `test_data\output-shape-examples\Day 1 - 06-24\Day 1 - 06-24.kmz` | Verified from repository filesystem | Use as reference geometry for validation/calibration, not as primary generation input. |
| The lawnmower sample has 533 JPGs. | `test_data\jpgs\Lawn Mower JPGs` count command | Verified from filesystem count | Required real sample for lawnmower strategy calibration. |
| The ROW mapping sample has 1,567 JPGs across seven flight folders. | `test_data\jpgs\Day 1 - 06-24` count command and nested folder listing | Verified from filesystem count | Required real sample for route/mixed-section calibration and sectioning behavior. |
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

`docs/TEMP-camera-boundary-v2-open-decisions.md`

Reason: temporary decision worksheet. The answers in this file have been integrated into this plan; it is not an implementation artifact.

`docs/camera-boundary-v2-implementation-plan.md`

Reason: this planning artifact. Future revisions are allowed only when planning changes are intentional.

`docs/camera-boundary-v2-validation-notes.md`

Reason: Phase 5 validation evidence artifact for commands, real sample calibration, reference KMZ comparison notes, selected strategies, fallback reasons, and pass/fail results.

### Proposed Internal API Contracts

These contracts are implementation targets. They are not current code.

`OutlineMode`

- `auto`
- `concave_hull`
- `route_aware`
- `lawnmower_envelope`

The GUI displays human-friendly labels, and the core uses stable string values. If an unknown value reaches the core, the core must raise `BoundaryError` with a clear message instead of silently falling back.

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

`BoundaryMetadata` additions must remain backward-compatible with existing formatting code. New fields must have simple scalar or string values, not nested Shapely objects or NumPy arrays.

`ReferenceBoundaryContext`

- Calibration input only; not required for normal JPG folder use.
- Source is a human-made KMZ reference polygon or multipolygon.
- Used for validation, scoring diagnostics, and calibration reports when available.
- Must never cause output to expand to a full client pipeline/system boundary that has no matching JPG coverage.
- If reference geometry is larger than the JPG-covered area, scoring must compare only relevant overlap/nearby portions or report that the reference is too broad for direct scoring.
- The first implementation uses reference KMZs for test/calibration workflows. A normal GUI reference-KMZ picker is out of scope for the first implementation.

## 4. Risk Matrix

| Risk | Severity | Likelihood | Mitigation | Detection |
|---|---:|---:|---|---|
| Auto classifier incorrectly treats perimeter/corridor data as lawnmower and shrinks output. | High | Medium | Require high classifier confidence; fallback to concave hull if uncertain. | Synthetic tests and real sample review. |
| Lawnmower outer-envelope misses concave notches or complex corners. | High | Medium | Preserve corner candidates and compare against concave hull coverage/area. | Candidate scoring diagnostics. |
| Mixed-section splitting creates disconnected artifacts. | High | Medium | Validate each section and union result; reject disconnected candidates unless intended. | Geometry validity tests. |
| Capture order is wrong due to missing EXIF timestamps. | Medium | Medium | Track order source; fallback to filename order; avoid route-aware strategy if order quality is poor. | Preflight details output. |
| Densified KMZ files become too large. | Low | Low | No hard ceiling is required; report vertex count for diagnostics only. | Vertex-count tests and manual export review. |
| Existing KMZ polygon input regresses. | High | Low | Keep KMZ path separate; add regression test. | `test_kmz_input_still_works`. |
| GUI cache returns stale results after mode change. | Medium | Medium | Include outline mode and strategy parameters in cache key. | GUI smoke test. |
| New modules introduce circular imports. | Medium | Low | Keep dependencies directional: core imports strategy modules; strategy modules do not import GUI. | `compileall`. |
| Dependency/version mismatch on another machine without Shapely `segmentize`. | Medium | Medium | Pin `shapely>=2.0` and keep a startup/test failure message clear if the installed version is too old. | dependency install check and tests. |
| Reference KMZ is much larger than the JPG-covered work area. | Medium | Medium | Treat reference KMZ as validation/calibration context only; compare only relevant nearby/overlap geometry and never generate a full pipeline/system shape from reference alone. | reference scoring diagnostics and manual calibration review. |

## 5. Assumptions, Decisions, And Implementation Risks

| Item | Classification | Notes |
|---|---|---|
| Current concave hull behavior is acceptable as fallback. | Verified from code and existing README behavior | Existing docs say the outline is intentionally generalized. |
| New modules can live directly under `src/`. | Verified from launcher/import pattern | Existing files import sibling modules from `src`. |
| Synthetic tests are enough for early implementation gates. | Verified decision | Synthetic tests are sufficient through Phase 2; real sample validation is required before final Auto threshold acceptance. |
| JPG filename order can match capture order but is not guaranteed. | Implementation risk | Must not be treated as authoritative when EXIF capture time is available. |
| EXIF `DateTimeOriginal` availability varies by input. | Implementation risk | Missing or invalid timestamps must not reject otherwise valid GPS points. |
| Representative real JPG folders are available under `test_data`. | Verified from filesystem | Use `test_data\jpgs\Lawn Mower JPGs` and `test_data\jpgs\Day 1 - 06-24` for calibration/manual validation. |
| The output remains one parent polygon before section splitting. | Resolved implementation constraint | Existing splitting assumes one connected parent polygon; mixed strategy output must union to a valid parent polygon or fail clearly. |
| Adding an `Outline mode` GUI option is acceptable. | Resolved decision | Default is `Auto`; advanced thresholds remain internal. |
| Reference KMZ support is required as a primary input. | Resolved decision: no | JPGs remain primary; KMZ references are allowed for validation/calibration only. |
| KMZ output size needs a hard limit. | Resolved decision: no | No hard vertex-count or file-size ceiling is required. |

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
- Reference KMZ is much broader than JPG coverage.
- Reference KMZ contains multiple sub-polygons, as in the ROW mapping example.

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
- Reference KMZ selected for calibration while JPG folder remains the primary input.
- Existing saved output path overwrite confirmation.
- Drag/drop path handling remains unchanged.

## 7. Strict File Allow-List

No files outside this table are allowed to be edited, created, deleted, moved, formatted, or regenerated unless this plan is revised first.

| Path | Change Type | Reason | Related Tests | Risk | Rollback Notes |
|---|---|---|---|---|---|
| `docs/camera-boundary-v2-implementation-plan.md` | Create/modify | Planning artifact | Documentation review | Low | Revert file only. |
| `docs/camera-boundary-v2-implementation-orchestrator.md` | Create/modify | Execution runbook for phased implementation | Documentation review | Low | Delete or revise runbook; authoritative plan still wins. |
| `docs/TEMP-camera-boundary-v2-open-decisions.md` | Create/modify | Historical decision worksheet and resolved user answers | Documentation review | Low | Archive or delete after decisions are represented in this plan. |
| `.gitignore` | Create/modify | Keep massive local sample data out of git | `git check-ignore -v test_data/`; `git status --short` | Low | Re-add the `test_data/` ignore rule. |
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
| `tests/geometry_test_utils.py` | Create | Shared synthetic fixtures and assertions | Used by all test files | Low | Delete test helper and inline fixtures during rollback. |
| `requirements_jpg_boundary_kmz.txt` | Modify | Pin `shapely>=2.0` so `segmentize` support is explicit | Full test suite and install check | Medium | Revert pin only if manual densification fallback is added and tested. |
| `docs/camera-boundary-v2-validation-notes.md` | Create | Record Phase 5 real-sample/manual validation evidence | Phase 5 validation checklist | Low | Delete if implementation is rolled back before validation. |

Explicitly excluded unless the plan is revised:

- `outputs/`
- `__pycache__/`
- `src/__pycache__/`
- `run_jpg_boundary_gui.py`
- `src/run_jpg_boundary_gui.py`
- `run_jpg_boundary_gui.bat`
- `agent_prompt_templates/`
- `test_data/` contents, except read-only use during calibration/manual validation. Only the top-level `.gitignore` rule may reference this folder.
- files in `C:\Users\rbake\Desktop\VS Code Shortcuts\Buffer-Zone-Generator`

## 8. Implementation Phases With Gates

### Phase 0: Baseline And Guardrails

Goal: establish current state without modifying source code.

Allowed files touched:

- `.gitignore` only if the required `test_data/` ignore rule is missing; otherwise none.

Tasks:

- Record `git status --short --branch`.
- Confirm `test_data/` is ignored by `.gitignore`.
- Confirm Shapely version and `segmentize` availability.
- Run baseline compile check.
- Document untracked files.

Commands:

```powershell
git status --short --branch
git check-ignore -v test_data/
python -c "import shapely; from shapely.geometry import Polygon; print(shapely.__version__); print(hasattr(Polygon([(0,0),(1,0),(1,1),(0,0)]), 'segmentize'))"
python -m compileall src
```

Expected output:

- Branch is known.
- Existing untracked files are documented.
- `test_data/` is ignored and does not appear as untracked sample data in normal status output.
- `compileall` succeeds.

Failure conditions:

- Source does not compile.
- `test_data/` appears as untracked sample data in `git status --short`.
- `git check-ignore -v test_data/` fails.
- Shapely lacks `segmentize` after dependency verification.

Pass/fail criteria:

- Pass only if baseline is understood and no implementation file has been touched.

Rollback/recovery:

- No rollback required because no source files are changed.

### Phase 1: Geometry Hardening Foundation

Goal: port only the safe geometry foundation from `Buffer-Zone-Generator`.

Allowed files touched:

- `src/geometry_hardening.py`
- `src/jpg_boundary_kmz_core.py`
- `requirements_jpg_boundary_kmz.txt`
- `tests/test_geometry_hardening.py`

Tasks:

- Add `EXPORT_MAX_SEGMENT_M = 10.0` in `src/geometry_hardening.py`.
- Change buffer helper defaults to use `quad_segs=64`.
- Add helper to clean constructive geometry with `buffer(0)` when needed.
- Add helper to segmentize projected polygons before WGS84 transformation/export.
- Pin `shapely>=2.0` in `requirements_jpg_boundary_kmz.txt` and keep a clear runtime/test failure if an older Shapely is installed.
- Replace every core buffer call that affects final boundary, containment padding, KMZ polygon buffering, and section overlap buffering with the shared helper.
- Preserve existing zero-buffer behavior.

Required tests:

- `test_segmentize_caps_projected_segments`
- `test_buffer_cleanup_returns_valid_polygon`
- `test_zero_buffer_does_not_create_extra_shape`

Commands:

```powershell
python -m unittest tests.test_geometry_hardening
python -m compileall src
git status --short
git diff --name-only
```

Expected outputs:

- Valid polygons after cleanup.
- Densified geometry has no long exterior segments above the configured max, within tolerance.
- Existing functions still import.

Failure conditions:

- Densification changes geometry area beyond a small tolerance.
- KMZ input path breaks.
- Implementation relies on `segmentize` without the `shapely>=2.0` dependency pin.

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
- Extend `GpsPoint` with `capture_time: datetime | None`.
- Update `_read_gps_point` to read `EXIF DateTimeOriginal` first, then `Image DateTime`; invalid or missing timestamps must produce `capture_time=None` without rejecting otherwise valid GPS points.
- Camera ordering priority is fixed: EXIF capture time, then filename/path sort, then original input order. The selected order source must be recorded in `CameraPreflightResult.order_source`.

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
git status --short
git diff --name-only
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
git status --short
git diff --name-only
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
- Keep advanced classifier thresholds internal. Backend/config structures must be organized so selected thresholds can be surfaced in a future GUI advanced section without reworking the strategy engine.
- Show in details:
  - selected strategy
  - preflight classification
  - confidence
  - order source
  - fallback reason
  - candidate summary
- Show non-blocking status/details text when `Auto` falls back to concave hull.
- Keep legacy KMZ-as-primary behavior clear: disable outline mode controls for KMZ primary input and report that KMZ input uses source polygon mode.
- Do not add a normal GUI reference-KMZ picker in the first implementation unless the core and tests already support reference scoring cleanly. Reference KMZs are calibration/validation context first.

Required tests:

- Existing core tests.
- Manual GUI smoke test.

Commands:

```powershell
python -m unittest discover -s tests
python -m compileall src
python .\run_jpg_boundary_gui.py
git status --short
git diff --name-only
```

Expected outputs:

- GUI launches.
- Scan/preview works with default `Auto`.
- Changing mode invalidates cache.
- Export creates KMZ.
- Auto fallback is visible in non-blocking status/details text.
- KMZ primary input disables outline mode controls.

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
- `docs/camera-boundary-v2-validation-notes.md`
- implementation files already touched in prior phases, only to fix failing Phase 5 tests or validation findings

Tasks:

- Add or refine synthetic fixtures.
- Run real-sample calibration/manual validation against:
  - `test_data\jpgs\Lawn Mower JPGs` with `test_data\output-shape-examples\Lawn Mower JPGs\Lawn Mower JPGs.kmz`
  - `test_data\jpgs\Day 1 - 06-24` with `test_data\output-shape-examples\Day 1 - 06-24\Day 1 - 06-24.kmz`
- Treat `test_data` as read-only. Write generated validation outputs to a disposable location and do not commit generated KMZs.
- Compare outputs against reference KMZs where meaningful; if the reference KMZ is broader than the JPG-covered area, record that in diagnostics instead of forcing the generated shape to match the full reference.
- Document mode behavior and known limits.
- Confirm sources in README.
- Review final diff against allow-list.
- Review candidate diagnostics for at least one accepted non-concave candidate and one fallback case.
- Create `docs/camera-boundary-v2-validation-notes.md` and record all Phase 5 validation evidence.

Commands:

```powershell
python -m unittest discover -s tests
python -m compileall src
git status --short
git diff --name-only
```

Expected outputs:

- All tests pass.
- Diff is allow-listed only.
- README describes current behavior accurately.
- Real-sample diagnostics exist for the lawnmower and ROW mapping datasets.
- `docs/camera-boundary-v2-validation-notes.md` contains Phase 5 command results, manual sample inputs, reference KMZ paths, disposable output paths, strategy selections, fallback reasons, and pass/fail notes.

Failure conditions:

- Real samples show repeated false positives.
- Generated shapes expand to a full reference/pipeline boundary outside JPG-covered areas.
- README claims behavior not verified by tests or samples.
- `docs/camera-boundary-v2-validation-notes.md` is missing or omits either real sample dataset.

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
| Manual calibration | `lawnmower_real_sample_review` | `test_data\jpgs\Lawn Mower JPGs` against matching reference KMZ | Auto chooses or evaluates lawnmower envelope without row-end artifacts | Output follows row wiggles or ignores true exterior corners | Manual Phase 5 validation |
| Manual calibration | `row_mapping_real_sample_review` | `test_data\jpgs\Day 1 - 06-24` against matching reference KMZ | Auto handles nested ROW flights and sectioning diagnostics without expanding beyond JPG coverage | Output expands to full unrelated reference area or misses actual JPG-covered corridor | Manual Phase 5 validation |

Full validation command:

```powershell
python -m unittest discover -s tests
```

## 10. Pre-Implementation Checklist

- [ ] Confirm branch with `git status --short --branch`.
- [ ] Confirm untracked files are documented and leave non-allow-listed paths untouched.
- [ ] Confirm `.gitignore` ignores `test_data/` with `git check-ignore -v test_data/`.
- [ ] Confirm all allow-listed files still exist or are intentionally new.
- [ ] Confirm Shapely version and `segmentize` support.
- [ ] Confirm dependency change is limited to pinning `shapely>=2.0`.
- [ ] Confirm current source compiles with `python -m compileall src`.
- [ ] Confirm no existing tests are hidden outside repo listing.
- [ ] Confirm no implementation files outside allow-list will be touched.
- [ ] Confirm final fallback behavior is the current concave hull path.
- [ ] Confirm real sample JPG folders and reference KMZ examples remain available under `test_data`.
- [ ] Confirm `test_data` will be treated as read-only during implementation.

## 11. Post-Implementation Validation Checklist

- [ ] `python -m unittest discover -s tests` passes.
- [ ] `python -m compileall src` passes.
- [ ] `python .\run_jpg_boundary_gui.py` launches.
- [ ] Manual scan/preview succeeds for at least one real sample JPG folder.
- [ ] Manual export succeeds for at least one real sample JPG folder.
- [ ] Manual legacy KMZ-as-primary scan/export succeeds using an existing sample KMZ or a temporary test KMZ fixture.
- [ ] Manual calibration is run against `test_data\jpgs\Lawn Mower JPGs`.
- [ ] Manual calibration is run against `test_data\jpgs\Day 1 - 06-24`.
- [ ] `docs/camera-boundary-v2-validation-notes.md` records both manual calibration runs.
- [ ] Reference KMZ comparison is used only as validation/calibration context, not as an input that expands output beyond JPG coverage.
- [ ] `git diff --name-only` contains only allow-listed files.
- [ ] `git status --short` does not list `test_data/` or files below it.
- [ ] No `outputs/` files are modified.
- [ ] No `test_data/` files are modified.
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
- Any generated KMZs during manual tests must be treated as disposable and must not be committed.
- If validation fails after partial implementation, do not continue to downstream phases until the current phase passes or is rolled back.

## 13. Resolved Decisions And Remaining Non-Decision Risks

No user-required open decisions remain as of 2026-06-30.

Resolved decisions:

- JPG folders default to `Auto`.
- Concave hull remains the conservative fallback.
- V2 remains JPG-primary.
- Reference KMZs are allowed only for validation/calibration, and output must stay tied to actual JPG coverage.
- Advanced classifier thresholds remain internal for the first implementation, with backend organization that keeps future GUI exposure practical.
- Acceptance uses reference KMZ comparison when available; otherwise it uses agent-performed visual/manual review plus area, coverage, and boundary-deviation guardrails.
- `shapely>=2.0` will be pinned.
- No hard KMZ file-size or vertex-count ceiling is required.
- Auto fallback is shown through non-blocking status/details text.

Remaining non-decision risks:

- Thresholds still need empirical tuning during implementation.
- The real sample reference KMZs are guidance, not exact machine-verifiable ground truth in every case, because they were human-created from JPG outlines.
- ROW mapping reference geometry contains multiple overlapping sub-polygons; implementation must compare it carefully and must not force generated output to match unrelated areas.
- `test_data/` is a local ignored dataset and must be treated as read-only during implementation.

## 14. Final Readiness Assessment

Ready to begin implementation under the resolved decisions above.

Auto strategy production readiness still depends on Phase 5 real-sample calibration against `test_data`, but this is now an implementation validation task rather than an open planning decision.

## 15. Plan Audit And Hardening Addendum

This addendum audits the plan document using the repository-local guideline at `agent_prompt_templates/detailed-implementation-audit/post_implementation_audit.md`. Because no V2 implementation has been coded yet, this is a pre-implementation audit of the blueprint, not a code audit of completed source changes.

### 15.1 Executive Summary

Audit result: the plan is viable and has been hardened before implementation. The weak spots were missing internal API contracts, missing hard candidate rejection gates, insufficient dependency-version handling for `segmentize`, and previously incomplete user-required decisions. The user decisions were supplied on 2026-06-30 and have been integrated into the plan.

Readiness after audit: ready to begin implementation. Remaining items are implementation validation risks, not open planning decisions.

### 15.2 Original Requirement Compliance Review

| Requirement | Audit Result | Evidence | Patch Required |
|---|---|---|---|
| Use the detailed planning guideline. | Satisfied | Plan includes discovery, evidence, assumptions, allow-list, phase gates, tests, validation, rollback. | No |
| Adapt useful logic from `Buffer-Zone-Generator`. | Satisfied but hardened | Plan references projected buffer, `buffer(0)`, `segmentize(10m)`, and Hausdorff-style verification from the other repo. | Yes, dependency guard added. |
| Improve accuracy around non-linear/complex camera positions. | Partially satisfied by design | Route-aware, lawnmower, and mixed strategies are planned but not implemented. | Yes, hard acceptance gates added. |
| Avoid lawnmower row-end artifacts. | Partially satisfied by design | Lawnmower outer-envelope strategy is planned. | Yes, additional tests and rejection gates added. |
| Include explicit references and allow-lists. | Satisfied | Plan has evidence and strict allow-list. | Yes, test helper and Shapely dependency row added. |
| Include user-required decisions. | Satisfied after user response | See section 15.12. | Yes |

### 15.3 Files Inspected

| File | What Was Verified | Status |
|---|---|---|
| `docs/camera-boundary-v2-implementation-plan.md` | Full plan content, phases, allow-list, tests, and resolved decisions. | Verified directly |
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
| Plan relied on `segmentize` without deciding version pin vs fallback. | Medium | Resolved by user decision | Added `shapely>=2.0` requirement allow-list row and Phase 1 failure condition. |
| Plan had scoring ideas but no hard acceptance gates before scoring. | High | Confirmed planning gap | Added required acceptance gates in Phase 3. |
| Plan duplicated synthetic fixture needs across tests without a helper file. | Low | Likely maintainability issue | Added `tests/geometry_test_utils.py` to allow-list. |
| Plan did not require tests for invalid outline mode. | Medium | Confirmed gap | Added regression test requirement. |
| Plan did not require diagnostics review for both accepted and fallback Auto decisions. | Medium | Confirmed gap | Added Phase 5 task. |
| User decisions were originally open. | Medium | Resolved by user answers on 2026-06-30 | Integrated answers into section 13 and section 15.12. |

### 15.5 Patches Applied To The Plan

- Added proposed internal API contracts for `OutlineMode`, `CameraPreflightResult`, and `OutlineCandidate`.
- Added `tests/geometry_test_utils.py` to the allow-list.
- Added `requirements_jpg_boundary_kmz.txt` allow-list row for the `shapely>=2.0` pin.
- Removed `requirements_jpg_boundary_kmz.txt` from the exclusion list.
- Added Phase 1 requirement for a `segmentize` capability check or dependency version decision.
- Added Phase 3 hard candidate acceptance gates.
- Added additional strategy and regression tests for area ratio, required point coverage, disconnected section handling, and invalid outline mode.
- Added Phase 5 diagnostics review for accepted and fallback Auto decisions.
- Added this audit addendum and integrated user-required decisions.

### 15.6 Edge Cases And Failure Modes Reviewed

Additional audit emphasis beyond the original plan:

- Ambiguous patterns must not produce high-confidence non-concave outputs.
- Bad route order must not be accepted merely because points form a plausible shape.
- Lawnmower envelope must not exclude true perimeter corner points.
- Area ratio checks must prevent both under-coverage and excessive over-coverage.
- Required control-point coverage must be explicit and strategy-aware.
- MultiPolygon or disconnected candidates must not silently flow into section splitting.
- Unknown outline mode values must fail clearly.
- Shapely version mismatch must fail clearly if the pinned dependency is not installed.

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
Get-ChildItem -Directory test_data\jpgs
Get-ChildItem -Directory test_data\output-shape-examples
Get-ChildItem -Directory test_data\jpgs | ForEach-Object { count JPG files }
Get-ChildItem -Recurse -File test_data\output-shape-examples -Filter *.kmz
Get-ChildItem -Directory "test_data\jpgs\Day 1 - 06-24"
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
- Shapely dependency pin is missed or the installed environment still has an older Shapely version.
- Reference KMZ comparison is over-applied to areas without JPG coverage.

The plan now includes explicit tests or phase gates for each risk.

### 15.11 Remaining Non-Decision Risks

No user-required open decisions remain.

Remaining non-decision risks:

- Real-world classifier thresholds still need implementation-time calibration against `test_data`.
- Reference KMZs are human-made guidance and are not guaranteed to be exact machine ground truth.
- The ROW mapping reference KMZ is split into multiple overlapping sub-polygons; comparison logic must account for that.
- `test_data/` is ignored by `.gitignore` and must remain read-only during implementation.

### 15.12 Resolved User Decisions

The user answered the decision worksheet in `docs/TEMP-camera-boundary-v2-open-decisions.md`. Final decisions:

1. `Auto` is the default outline mode for JPG folders.
2. V2 remains JPG-primary. KMZs are allowed only as reference/calibration geometry, and generated shapes must stay focused on actual JPG-covered areas rather than an entire pipeline/system.
3. Advanced classifier thresholds stay internal in the first implementation, but backend structures must make future GUI exposure practical.
4. Acceptance follows the recommended approach: use reference KMZ comparison when available; otherwise use agent-performed visual/manual review plus area, coverage, and boundary-deviation guardrails.
5. Real sample data is available under `test_data`: a lawnmower JPG dataset, a ROW mapping JPG dataset, and matching human-made KMZ examples.
6. Pin `shapely>=2.0`.
7. Do not impose a hard KMZ file-size or vertex-count ceiling.
8. Show uncertain `Auto` fallback through non-blocking status/details text.

### 15.13 Final Readiness Assessment

Ready to begin implementation.

There are no unresolved user decisions. The remaining risks are validation tasks to handle during implementation, especially real-sample calibration against `test_data`.
