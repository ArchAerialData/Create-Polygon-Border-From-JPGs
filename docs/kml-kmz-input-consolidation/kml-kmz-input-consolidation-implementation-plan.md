# KML/KMZ Polyline Input Consolidation Implementation Plan

Status: draft phased implementation guide pending resolution of `kml-kmz-input-consolidation-open-questions.md`.

Repository root:

```text
C:\Users\rbake\Desktop\VS Code Shortcuts\Create-Polygon-Border-From-JPGs
```

Related decision worksheet:

```text
docs\kml-kmz-input-consolidation\kml-kmz-input-consolidation-open-questions.md
```

Current repository status notes observed during planning:

- Branch: `Testing-New-Methods...origin/Testing-New-Methods`.
- `outputs/` currently has unrelated deleted KMZ files in the worktree. This plan must not restore, delete, or otherwise touch those files unless the user explicitly asks.
- `test_data/` remains read-only calibration data and must stay ignored.
- `C:\Users\rbake\Desktop\VS Code Shortcuts\Buffer-Zone-Generator` is a reference source only. Do not modify it.

## 0. Implementation Authority

This section controls implementation. If later wording is less strict, this section wins.

### 0.1 Fixed Product Decisions

- JPG functionality and classifier expansion are paused for this work. Existing JPG behavior must not regress, but this task focuses on KML/KMZ vector input consolidation.
- Add KML/KMZ polyline input directly to this application so users do not need the separate Buffer-Zone-Generator app for this workflow.
- KML/KMZ `LineString` inputs are treated as authoritative linework for buffering.
- Generated polygon outputs must be exterior-only. Interior rings/holes produced by buffering, source polygons, or intermediate geometry must be removed before preview, sectioning, and export.
- Section names must continue to use the format `<shape-name> (1 of x)`.
- Natural section splitting must prioritize human-usable orthomosaic crop shapes over mathematically efficient but visually odd subdivision.
- Existing single-polygon KMZ behavior must remain supported unless explicitly revised.
- Buffering and shape construction must happen in a projected CRS, not directly in longitude/latitude.
- Do not shell out to, import from, or modify the Buffer-Zone-Generator repo. Reimplement the required small geometry and KML/KMZ parsing concepts locally.

### 0.2 Implementation Constraints

- Use the existing direct `src/` module pattern; do not introduce packaging changes.
- Use Python `unittest`; do not introduce `pytest` or new test dependencies.
- Do not add runtime dependencies. Existing requirements already include `shapely>=2.0`, `pyproj`, `numpy`, `scipy`, `simplekml`, and `exifread`.
- Treat `test_data/` and the user-supplied `A:\...` sample inputs as read-only.
- Do not write generated outputs into `test_data/`, `outputs/`, source folders, the `A:\...` sample folder, or the Buffer-Zone-Generator repo during tests. Use temporary directories.
- Run validation commands without writing Python bytecode into the worktree. Use `python -B`.
- Do not modify `run_jpg_boundary_gui.py`, `src/run_jpg_boundary_gui.py`, or `run_jpg_boundary_gui.bat`.
- Do not modify `agent_prompt_templates/`.
- Do not modify files in `C:\Users\rbake\Desktop\VS Code Shortcuts\Buffer-Zone-Generator`.
- Do not launch, attach to, automate, close, kill, inspect, script, or otherwise interact with any Agisoft Metashape process, window, project, task queue, or processing job.
- Do not read from, write to, copy, move, delete, lock, or otherwise touch Metashape project artifacts, including `.psx`, `.psz`, and `.files` project directories.
- No automated test, manual validation step, phase gate, or final validation command requires opening or controlling Metashape.

### 0.3 Required Module Boundaries

- `src/kml_vector_input.py` should own KML/KMZ loading, namespace handling, KML coordinate parsing, input-type detection, and extraction of `LineString` and polygon geometry.
- `src/polyline_boundary.py` should own projected line buffering, line-derived CRS detection, linework diagnostics, and exterior-only polygon cleanup for polyline inputs.
- `src/natural_sectioning.py` should own human-natural section splitting and overlap construction.
- `src/geometry_hardening.py` should keep shared projected buffer, cleanup, densification, and hole-filling helpers.
- `src/jpg_boundary_kmz_core.py` should own orchestration, metadata, public generation functions, legacy JPG/KMZ compatibility, final export results, and errors.
- `src/jpg_boundary_kmz_gui.py` should own UI labels, file pickers, drag/drop behavior, cached settings, preview, worker calls, and user-visible status/details.
- Tests must remain under `tests/`. Production modules must not import test helpers.

### 0.4 Hard Phase Gate Rules

- Phases must be implemented in order.
- Do not begin a downstream phase until every command and pass/fail criterion in the current phase passes.
- If a phase fails, patch within that phase's allow-list or revise this plan before touching additional files.
- After each phase, run `git status --short` and `git diff --name-only`.
- After each phase, confirm only files allowed for that phase changed, aside from pre-existing unrelated `outputs/` deletions.
- After each phase, confirm `test_data/`, `outputs/`, source sample folders, `__pycache__/`, `.pyc` files, launcher files, `agent_prompt_templates/`, and Buffer-Zone-Generator were not modified by the implementation.
- Any implementation that silently drops existing JPG functionality fails the gate.
- Any implementation that silently changes legacy single-polygon KMZ behavior fails the gate.
- Any implementation that exports interior rings/holes for this vector workflow fails the gate.
- Any implementation that creates sharp, irregular, mixed-orientation section splits when a natural same-direction split is possible fails the gate.
- Any implementation or validation step that requires or risks interacting with Metashape fails the gate and must stop before acting.

### 0.5 Final Required Validation Commands

Run these before considering implementation complete:

```powershell
git status --short --branch
git check-ignore -v test_data/
python -B -m unittest discover -s tests
python -B -c "from pathlib import Path; files=list(Path('src').rglob('*.py')); [compile(path.read_text(encoding='utf-8'), str(path), 'exec') for path in files]; print(f'compiled {len(files)} source files')"
python -B -c "import sys; from pathlib import Path; sys.path.insert(0, str(Path('src').resolve())); from jpg_boundary_kmz_gui import _create_root, BoundaryKmzApp; root=_create_root(); root.withdraw(); app=BoundaryKmzApp(root); root.update_idletasks(); root.destroy(); print('GUI smoke ok')"
git diff --name-only
```

Manual validation must use disposable temp outputs and read-only source inputs:

- Source polyline KML: `A:\z_TemporaryDailes_z\Motiva Mapping\_Crops\Day 4 - Test\Northern Section\North 2\photo_polylines_20260630_162709.kml`
- Reference buffer output for exterior-boundary comparison: `A:\z_TemporaryDailes_z\Motiva Mapping\_Crops\Day 4 - Test\Northern Section\North 2\photo_polylines_20260630_162709_170ft_buffer.kml`
- Buffer distance: `170 ft`
- Required validation outcome: generated exterior boundary closely follows the reference exterior boundary, has no interior rings, and supports requested section splitting with natural same-direction crops.

### 0.6 Testing And Evidence Authority

- Automated tests use `unittest`.
- Phase 6 must create `docs/kml-kmz-input-consolidation/kml-kmz-input-consolidation-validation-notes.md`.
- Validation notes must record commands run, disposable output locations, source KML/KMZ inputs used, reference outputs used, generated geometry diagnostics, split diagnostics, and pass/fail notes.
- Manual validation evidence is incomplete if it does not mention the North 2 polyline KML and the existing 170 ft reference buffer KML.

## 1. Executive Summary

This work consolidates the useful KML/KMZ polyline buffer workflow from Buffer-Zone-Generator into this application. Instead of building polygons from JPG GPS points, vector inputs containing `LineString` geometry will be parsed directly, projected to local UTM, dissolved, buffered, cleaned, converted to exterior-only polygons, and exported through the existing KMZ workflow.

The second major improvement is section splitting. The current splitter recursively searches multiple cut angles to hit area targets. For crop KMZs used in orthomosaic workflows, the new splitter should create visually natural sections: parallel or near-parallel cuts, consistent overlap direction, connected pieces, stable naming, and no sharp irregular subdivisions when a simpler strip layout works.

The initial implementation should preserve all existing JPG and legacy KMZ behavior while adding:

- KML and KMZ vector input parsing.
- Polyline-derived boundary generation.
- Exterior-only polygon cleanup.
- Natural same-direction section splitting.
- GUI support for selecting KML/KMZ vector inputs.
- Validation against the known North 2 polyline and reference buffer output.

## 2. Current Repository Findings

| Finding | Evidence | Status | Relevance |
|---|---|---|---|
| GUI currently labels the input as `Input folder or KMZ` and has separate folder/KMZ browse buttons. | `src/jpg_boundary_kmz_gui.py`, UI rows around input controls | Verified from code | UI must become clear for JPG folders, KML, and KMZ vector inputs. |
| `generate_boundary_from_input` currently accepts directories and `.kmz` files only. | `src/jpg_boundary_kmz_core.py`, `generate_boundary_from_input` | Verified from code | `.kml` support and vector input-type detection must be added. |
| Existing KMZ polygon input requires exactly one polygon and rejects holes. | `src/jpg_boundary_kmz_core.py`, `_read_single_polygon_from_kmz` | Verified from code | Legacy behavior must be preserved or explicitly routed separately from new linework input. |
| Current KMZ export writes only polygon exteriors. | `src/jpg_boundary_kmz_core.py`, `_polygon_to_kml_coords` and `save_kmz` | Verified from code | Export behavior already aligns with exterior-only output, but preview and intermediate geometry must also be exterior-only. |
| Current section names already use `<shape_label> (index of count)`. | `src/jpg_boundary_kmz_core.py`, `_build_sections` | Verified from code | Naming requirement is already mostly satisfied. |
| Current section splitting recursively chooses cuts from many candidate angles. | `src/jpg_boundary_kmz_core.py`, `_partition_connected_polygon`, `_find_connected_cut`, `_candidate_split_angles` | Verified from code | This can create mixed-orientation splits; natural splitting should use one coherent axis unless a user-approved exception is needed. |
| Current overlap is applied by buffering each section outward and intersecting the parent polygon. | `src/jpg_boundary_kmz_core.py`, `_build_sections` | Verified from code | Natural crop overlap should likely expand along shared split boundaries only, not bulge all sides. |
| Buffer-Zone-Generator extracts every valid `LineString` from KML/KMZ input. | `Buffer-Zone-Generator\src\buffer_zone_generator\kmz_io.py`, `extract_line_strings` | Verified from code | This is the KML/KMZ parsing behavior to adopt locally. |
| Buffer-Zone-Generator buffers projected dissolved linework with `quad_segs=64`, cleans with `buffer(0)`, segmentizes at 10m, and transforms back to WGS84. | `Buffer-Zone-Generator\src\buffer_zone_generator\geometry.py`, `build_buffer_geometry` | Verified from code | This is the core geometry strategy to port locally. |
| Buffer-Zone-Generator can export inner rings, but this app should not for this workflow. | `Buffer-Zone-Generator\src\buffer_zone_generator\kmz_io.py`, `append_polygon_geometry` | Verified from code | Local implementation must intentionally fill/drop interiors before export. |
| North 2 polyline KML contains 2 `LineString` placemarks with 887 and 705 points. | XML parse of user-provided KML on 2026-07-01 | Verified locally | This is the primary real-world validation fixture. |
| North 2 170 ft Buffer-Zone output is effectively a direct projected Shapely buffer of the two source lines. | Local measurement on 2026-07-01; exterior boundary deviation from regenerated direct buffer was sub-foot | Verified locally | The target behavior is line-buffer geometry, with interiors removed. |
| Existing requirements already include `shapely>=2.0`. | `requirements_jpg_boundary_kmz.txt` | Verified from code | No dependency change should be needed. |

## 3. Exact Impacted Files And Symbols

### Existing Files To Modify

`src/jpg_boundary_kmz_core.py`

- `BoundaryMetadata`
- `BoundaryResult`
- `generate_boundary_from_input`
- `generate_boundary_from_kmz`
- `save_kmz`
- `_build_sections`
- `_partition_connected_polygon`
- `_strict_single_polygon`
- `_ensure_polygon`
- `_build_kml_description`

Reason: central orchestration, metadata, source input routing, section building, and KMZ export.

`src/jpg_boundary_kmz_gui.py`

- Input labels and browse controls
- Drag/drop accepted suffixes and text
- `_browse_kmz` or replacement vector browse method
- `_read_inputs`
- `_update_outline_mode_state`
- `_scan_worker`
- `_export_worker`
- `_draw_preview`
- `_settings_key`

Reason: UI must support JPG folders, KML polylines, KMZ polylines, and legacy KMZ polygons without confusing outline modes.

`src/geometry_hardening.py`

- Add exterior-only polygon cleanup helper.
- Add polygon/MultiPolygon hole filling helper.
- Keep buffer cleanup and densification behavior shared.

Reason: hole removal should be centralized and testable.

`README_JPG_BOUNDARY_KMZ.md`

- Update input behavior.
- Document KML/KMZ polyline support.
- Document exterior-only output behavior.
- Document natural section splitting behavior and limits.

Reason: user-facing behavior changes must be documented.

### New Files To Create

`src/kml_vector_input.py`

Reason: parse `.kml` and `.kmz` source files, extract linework and polygon geometry, and classify vector input type without coupling XML parsing to GUI code.

`src/polyline_boundary.py`

Reason: build projected line-buffer boundaries from vector linework and produce exterior-only polygons with diagnostics.

`src/natural_sectioning.py`

Reason: replace or augment recursive sectioning with same-direction, crop-friendly section generation.

`tests/test_kml_vector_input.py`

Reason: prove KML/KMZ parsing, namespace handling, LineString extraction, polygon detection, and mixed-content rejection or precedence.

`tests/test_polyline_boundary.py`

Reason: prove line-buffer generation, CRS detection, exterior-only cleanup, and North 2-style near-closed lines.

`tests/test_natural_sectioning.py`

Reason: prove section strips are connected, consistently oriented, named correctly through core, and have controlled overlap.

`docs/kml-kmz-input-consolidation/kml-kmz-input-consolidation-validation-notes.md`

Reason: record closeout validation evidence.

### Proposed Internal API Contracts

```python
@dataclass(frozen=True)
class VectorInputGeometry:
    source_path: Path
    input_kind: str  # "polyline_kml", "polyline_kmz", "polygon_kml", "polygon_kmz"
    lines_wgs84: tuple[LineString, ...]
    polygons_wgs84: tuple[Polygon, ...]
    source_name: str
```

```python
def load_vector_input(path: Path) -> VectorInputGeometry:
    """Read .kml or .kmz and return parsed vector geometry."""
```

```python
@dataclass(frozen=True)
class PolylineBoundaryResult:
    base_polygon_projected: Polygon
    final_polygon_projected: Polygon
    final_polygon_wgs84: Polygon
    epsg: int
    source_line_count: int
    source_point_count: int
    diagnostics: dict[str, float | int | str]
```

```python
def build_polyline_boundary(
    lines_wgs84: Sequence[LineString],
    buffer_ft: float,
) -> PolylineBoundaryResult:
    """Project, dissolve, buffer, clean, fill interiors, densify, and return polygons."""
```

```python
def fill_polygon_interiors(geometry) -> Polygon | MultiPolygon:
    """Return polygonal geometry with all interior rings removed."""
```

```python
def build_natural_sections(
    parent_polygon: Polygon,
    section_count: int,
    overlap_m: float,
    shape_label: str,
    to_wgs84: Transformer,
    *,
    axis_hint_deg: float | None = None,
) -> tuple[list[BoundarySection], NaturalSplitDiagnostics]:
    """Split parent into connected crop-friendly sections using one coherent axis."""
```

## 4. Risk Matrix

| Risk | Likelihood | Impact | Mitigation |
|---|---:|---:|---|
| KML/KMZ file contains mixed `LineString` and `Polygon` content. | Medium | Medium | Resolve open decision before implementation; test explicit behavior. |
| Direct line buffering produces holes that represent legitimate voids in some projects. | Medium | Low to Medium | Fixed decision is exterior-only output; document that interiors are filled. |
| Direct line buffering returns disconnected `MultiPolygon` for separated linework. | Medium | High | Decide whether to reject, merge, or export multiple parents before implementation. |
| Natural splitter cannot create connected sections for a concave shape. | Medium | High | Fail with actionable message or use an explicitly approved fallback; do not silently emit odd crops. |
| Same-axis equal-area strips produce visually poor sections on strongly curved corridors. | Medium | Medium | Prefer source-line axis hints where available; keep diagnostics and manual validation. |
| GUI wording confuses legacy polygon KMZ with new polyline KML/KMZ input. | Medium | Medium | Update labels, dialogs, details, and error messages. |
| Hole-filling changes area compared with Buffer-Zone reference output. | High | Low | Validate exterior boundary deviation, no interiors, and visual fit instead of exact area match. |
| Existing JPG behavior regresses while paused. | Low | High | Keep core regression tests and no broad JPG refactors. |

## 5. Assumptions, Decisions, And Implementation Risks

Resolved assumptions:

- The app should consolidate the other repo's polyline buffer workflow rather than depend on the other repo at runtime.
- KML/KMZ vector input is now a primary workflow for this app.
- JPG improvements are paused, not removed.
- Exterior-only output is intentional even when source or generated geometry contains holes.
- Natural sectioning should favor simple, visually consistent crop slabs over recursive mixed-angle cuts.

Open decisions are tracked in:

```text
docs\kml-kmz-input-consolidation\kml-kmz-input-consolidation-open-questions.md
```

Implementation must not begin beyond Phase 0 until decisions that affect file routing, mixed geometry behavior, section fallback behavior, output type, and overlap semantics are answered.

## 6. Edge Cases And Failure Modes

### Input Edge Cases

- `.kml` file with no `Document` element.
- `.kmz` without `doc.kml`.
- KML with valid XML but no `LineString` or polygon geometry.
- KML using nested folders or `MultiGeometry`.
- KML with malformed coordinates or coordinates outside WGS84 bounds.
- KML with UTF-16 or declared non-UTF-8 encoding.
- KML containing both source lines and a previously generated buffer polygon.
- KML containing many separate disconnected lines.
- Input suffix uppercase `.KML` or `.KMZ`.

### Geometry Edge Cases

- Near-closed LineStrings that produce small holes before cleanup.
- Buffers that produce one exterior with interiors.
- Buffers that produce disconnected `MultiPolygon`.
- Self-intersecting source linework.
- Very short line segments or duplicate consecutive coordinates.
- Source linework spanning UTM zones.
- Section overlap larger than a section width.
- Section split producing disconnected slivers.
- Filled interiors changing area materially compared with source output.

### GUI/Workflow Edge Cases

- User drops `.kml` onto the current drop zone.
- User selects vector input while JPG outline mode is still set.
- Cached preview from JPG settings must not be reused for vector settings.
- Output name defaults should be stable for `.kml` and `.kmz` inputs.
- Details dialog should identify source type as `KML polyline`, `KMZ polyline`, `KML polygon`, or `KMZ polygon`.
- Preview should not show JPG GPS points for vector input.

## 7. Strict File Allow-List

Implementation may modify only:

```text
src\geometry_hardening.py
src\jpg_boundary_kmz_core.py
src\jpg_boundary_kmz_gui.py
src\kml_vector_input.py
src\natural_sectioning.py
src\polyline_boundary.py
tests\geometry_test_utils.py
tests\test_core_regression.py
tests\test_geometry_hardening.py
tests\test_kml_vector_input.py
tests\test_natural_sectioning.py
tests\test_polyline_boundary.py
README_JPG_BOUNDARY_KMZ.md
docs\kml-kmz-input-consolidation\kml-kmz-input-consolidation-implementation-plan.md
docs\kml-kmz-input-consolidation\kml-kmz-input-consolidation-open-questions.md
docs\kml-kmz-input-consolidation\kml-kmz-input-consolidation-validation-notes.md
```

Do not modify:

```text
run_jpg_boundary_gui.py
src\run_jpg_boundary_gui.py
run_jpg_boundary_gui.bat
agent_prompt_templates\
test_data\
outputs\
C:\Users\rbake\Desktop\VS Code Shortcuts\Buffer-Zone-Generator\
```

## 8. Implementation Phases With Gates

### Phase 0: Baseline And Decision Lock

Purpose:

- Confirm current tests and imports.
- Resolve required open decisions.
- Record current dirty worktree state and avoid unrelated output deletions.

Allowed files:

- `docs/kml-kmz-input-consolidation/kml-kmz-input-consolidation-open-questions.md`
- `docs/kml-kmz-input-consolidation/kml-kmz-input-consolidation-implementation-plan.md`

Required commands:

```powershell
git status --short --branch
git check-ignore -v test_data/
python -B -m unittest discover -s tests
python -B -c "from pathlib import Path; files=list(Path('src').rglob('*.py')); [compile(path.read_text(encoding='utf-8'), str(path), 'exec') for path in files]; print(f'compiled {len(files)} source files')"
git diff --name-only
```

Continue gate:

- Required decisions are answered.
- Commands pass.
- No files outside the docs folder are changed by this phase.
- Existing unrelated `outputs/` deletions are not touched.

### Phase 1: KML/KMZ Vector Input Parser

Purpose:

- Add local KML/KMZ loader.
- Extract `LineString` geometry.
- Detect polygon geometry.
- Provide explicit errors for unsupported or ambiguous content.

Allowed files:

- `src/kml_vector_input.py`
- `src/jpg_boundary_kmz_core.py`
- `tests/test_kml_vector_input.py`
- `tests/test_core_regression.py`

Required commands:

```powershell
python -B -m unittest tests.test_kml_vector_input tests.test_core_regression
python -B -c "from pathlib import Path; files=list(Path('src').rglob('*.py')); [compile(path.read_text(encoding='utf-8'), str(path), 'exec') for path in files]; print(f'compiled {len(files)} source files')"
git status --short
git diff --name-only
```

Continue gate:

- `.kml` and `.kmz` LineString fixtures parse.
- Legacy single-polygon KMZ tests still pass.
- Malformed, empty, and unsupported KML/KMZ inputs raise clear `BoundaryError` or `ValueError`.
- No source files outside the phase allow-list change.

### Phase 2: Polyline Boundary Generation And Exterior Cleanup

Purpose:

- Build boundary polygons from source linework.
- Use local UTM projection, dissolved linework, round buffer, cleanup, densification.
- Remove all interiors/holes before returning preview/export geometry.

Allowed files:

- `src/geometry_hardening.py`
- `src/polyline_boundary.py`
- `src/jpg_boundary_kmz_core.py`
- `tests/test_geometry_hardening.py`
- `tests/test_polyline_boundary.py`
- `tests/test_core_regression.py`

Required commands:

```powershell
python -B -m unittest tests.test_geometry_hardening tests.test_polyline_boundary tests.test_core_regression
python -B -c "from pathlib import Path; files=list(Path('src').rglob('*.py')); [compile(path.read_text(encoding='utf-8'), str(path), 'exec') for path in files]; print(f'compiled {len(files)} source files')"
git status --short
git diff --name-only
```

Continue gate:

- Direct buffer of synthetic lines returns valid exterior-only polygons.
- A near-closed line fixture that would create an interior ring exports with no interiors.
- North 2-style two-line geometry can produce a valid single exterior polygon when its buffer overlaps into one shape.
- Disconnected geometry behavior matches the resolved open decision.

### Phase 3: Core Input Routing And Metadata

Purpose:

- Route `.kml` and `.kmz` vector inputs through the parser.
- Select polyline boundary generation when LineStrings are the source.
- Preserve legacy JPG and single-polygon KMZ paths.
- Add metadata fields for vector source type, line count, source point count, and exterior-cleanup behavior.

Allowed files:

- `src/jpg_boundary_kmz_core.py`
- `src/kml_vector_input.py`
- `src/polyline_boundary.py`
- `tests/test_core_regression.py`
- `tests/test_kml_vector_input.py`
- `tests/test_polyline_boundary.py`

Required commands:

```powershell
python -B -m unittest tests.test_core_regression tests.test_kml_vector_input tests.test_polyline_boundary
python -B -c "from pathlib import Path; files=list(Path('src').rglob('*.py')); [compile(path.read_text(encoding='utf-8'), str(path), 'exec') for path in files]; print(f'compiled {len(files)} source files')"
git status --short
git diff --name-only
```

Continue gate:

- `generate_boundary_from_input` accepts `.kml` polyline files.
- `generate_boundary_from_input` accepts `.kmz` polyline files.
- Existing JPG folder generation still works.
- Existing single-polygon KMZ generation still works.
- Vector-generated final polygons and sections have no interiors.

### Phase 4: Natural Section Splitting

Purpose:

- Add a same-direction splitter for crop-friendly sections.
- Prefer one coherent split axis derived from source linework or parent polygon orientation.
- Apply overlap along shared split boundaries, not by making odd all-direction bulges, if that open decision is confirmed.

Allowed files:

- `src/natural_sectioning.py`
- `src/jpg_boundary_kmz_core.py`
- `tests/test_natural_sectioning.py`
- `tests/test_core_regression.py`
- `tests/geometry_test_utils.py`

Required commands:

```powershell
python -B -m unittest tests.test_natural_sectioning tests.test_core_regression
python -B -c "from pathlib import Path; files=list(Path('src').rglob('*.py')); [compile(path.read_text(encoding='utf-8'), str(path), 'exec') for path in files]; print(f'compiled {len(files)} source files')"
git status --short
git diff --name-only
```

Continue gate:

- Split sections are connected.
- Split boundaries are parallel or near-parallel within the configured tolerance.
- Sections retain `<shape-name> (1 of x)` names.
- Adjacent sections overlap consistently.
- No section has interiors after cleanup.
- If a natural split cannot be produced, behavior matches the resolved open decision and does not silently emit strange geometry.

### Phase 5: GUI Integration And User-Facing Details

Purpose:

- Update input UI for JPG folder, KML, and KMZ.
- Update drag/drop validation.
- Disable JPG outline mode controls for vector input where they do not apply.
- Update preview labels and details text for vector inputs.
- Ensure cache keys include input type and source path suffix.

Allowed files:

- `src/jpg_boundary_kmz_gui.py`
- `src/jpg_boundary_kmz_core.py`
- `README_JPG_BOUNDARY_KMZ.md`
- `tests/test_core_regression.py`

Required commands:

```powershell
python -B -m unittest tests.test_core_regression
python -B -c "import sys; from pathlib import Path; sys.path.insert(0, str(Path('src').resolve())); from jpg_boundary_kmz_gui import _create_root, BoundaryKmzApp; root=_create_root(); root.withdraw(); app=BoundaryKmzApp(root); root.update_idletasks(); root.destroy(); print('GUI smoke ok')"
python -B -c "from pathlib import Path; files=list(Path('src').rglob('*.py')); [compile(path.read_text(encoding='utf-8'), str(path), 'exec') for path in files]; print(f'compiled {len(files)} source files')"
git status --short
git diff --name-only
```

Continue gate:

- GUI initializes.
- `.kml` and `.kmz` paths are accepted by validation.
- Vector input does not present JPG outline mode as active behavior.
- Details output reports vector source type and line count.
- Preview can render vector source and section output without requiring JPG points.

### Phase 6: Regression, Real-Sample Validation, And Documentation

Purpose:

- Run all tests.
- Validate North 2 KML workflow using disposable output.
- Compare exterior boundary against the existing 170 ft reference buffer KML.
- Validate natural section splitting on the generated exterior-only polygon.
- Write validation notes.

Allowed files:

- `docs/kml-kmz-input-consolidation/kml-kmz-input-consolidation-validation-notes.md`
- `README_JPG_BOUNDARY_KMZ.md`
- Any test file that requires a narrow validation correction discovered in this phase.

Required commands:

```powershell
git status --short --branch
git check-ignore -v test_data/
python -B -m unittest discover -s tests
python -B -c "from pathlib import Path; files=list(Path('src').rglob('*.py')); [compile(path.read_text(encoding='utf-8'), str(path), 'exec') for path in files]; print(f'compiled {len(files)} source files')"
python -B -c "import sys; from pathlib import Path; sys.path.insert(0, str(Path('src').resolve())); from jpg_boundary_kmz_gui import _create_root, BoundaryKmzApp; root=_create_root(); root.withdraw(); app=BoundaryKmzApp(root); root.update_idletasks(); root.destroy(); print('GUI smoke ok')"
git diff --name-only
```

Manual validation:

- Generate a disposable KMZ from the North 2 source polyline KML at 170 ft.
- Confirm output polygon has zero interiors.
- Confirm exterior boundary visually and metrically matches the reference buffer exterior.
- Generate at least one multi-section output and confirm sections have consistent cut direction and visually reasonable crop shapes.

Continue gate:

- All commands pass.
- Validation notes are complete.
- Disposable outputs are not committed.
- `test_data/`, `outputs/`, source folders, and Buffer-Zone-Generator are unchanged.

## 9. Testing And Regression Matrix

| Test Area | Required Coverage |
|---|---|
| KML parser | Plain `.kml`, `.kmz` with `doc.kml`, nested `LineString`, malformed coordinate rejection, empty geometry rejection. |
| Input routing | JPG folder still routes to JPG generation; `.kml` linework routes to polyline generation; `.kmz` linework routes to polyline generation; legacy polygon KMZ still routes to polygon generation. |
| Polyline buffer | Projected buffer distance, dissolved lines, exterior-only output, no interior rings, densified export geometry. |
| Exterior cleanup | Polygon holes filled; MultiPolygon behavior follows resolved decision; invalid geometry repaired or rejected clearly. |
| Natural sectioning | Same-axis cuts, connected sections, stable labels, consistent overlap, no interiors, clear failure on impossible shapes. |
| GUI smoke | App initializes; vector suffix accepted; outline controls behave correctly; preview path does not require JPG points. |
| Regression | Existing core JPG tests and legacy KMZ tests continue to pass. |

## 10. Pre-Implementation Checklist

- Open questions are answered or explicitly deferred with safe defaults.
- Baseline tests pass.
- Dirty worktree state is understood; unrelated `outputs/` deletions are not touched.
- `test_data/` is ignored.
- North 2 source and reference files exist and are treated as read-only.
- Buffer-Zone-Generator source files are treated as references only.

## 11. Post-Implementation Validation Checklist

- `.kml` polyline input works.
- `.kmz` polyline input works.
- Legacy single-polygon KMZ input works.
- JPG folder input still works.
- Generated polyline-derived output has no interiors.
- Natural splitting produces crop-friendly same-direction sections.
- Output section names use `<shape-name> (1 of x)`.
- GUI preview and details are accurate for vector inputs.
- All final validation commands pass.
- Validation notes are complete.

## 12. Rollback And Recovery Plan

If vector parsing fails:

- Remove vector routing from `generate_boundary_from_input`.
- Leave legacy JPG and KMZ paths unchanged.
- Keep parser module unused until fixed, or remove it if the phase is reverted.

If polyline buffering fails:

- Disable polyline generation path and return a clear unsupported-input error for LineString KML/KMZ.
- Preserve parser tests if useful, but do not expose broken generation in the GUI.

If natural sectioning fails:

- Keep single-shape vector generation available.
- Disable multi-section vector export with a clear error rather than falling back to weird crop shapes.
- Re-enable only after section tests and manual validation pass.

If GUI integration fails:

- Keep backend vector functions covered by tests.
- Do not ship partial GUI controls that imply vector input is supported when it is not.

## 13. Human-Blocking Conditions

Human review or approval is required when:

- Any open decision in the companion decisions file blocks implementation.
- A required command fails and fixing it requires touching files outside the current phase allow-list.
- Real-sample output has a good metric match but looks visually wrong for orthomosaic crop usage.
- Natural splitter behavior requires choosing between equal-area accuracy and human-visual crop quality.
- Disconnected source linework or mixed LineString/Polygon source content appears in real user files and the resolved behavior does not cover it.
- Implementation would write to or modify `test_data/`, `outputs/`, source folders, Buffer-Zone-Generator, launcher files, or `agent_prompt_templates/`.
- Validation would need to overwrite a user-selected persistent output file.
- Any step would interact with Metashape or Metashape project artifacts.

No human review is required for:

- Passing unit tests.
- Passing compile and GUI smoke commands.
- Implementing the fixed exterior-only rule.
- Creating disposable outputs in a temp directory.
- Updating validation notes with objective command and geometry evidence.

## 14. Final Readiness Assessment

This plan is ready for user decision review. It is not implementation-ready until the open questions file is answered, especially decisions about mixed vector content, disconnected linework, natural split fallback behavior, output type, and overlap semantics.
