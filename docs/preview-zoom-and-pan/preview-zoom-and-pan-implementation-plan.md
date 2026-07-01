# Preview Zoom And Pan Implementation Plan

Status: authoritative hardened implementation blueprint. All decisions in `preview-zoom-and-pan-open-questions.md` are resolved and integrated into this plan.

Repository root:

```text
C:\Users\rbake\Desktop\VS Code Shortcuts\Create-Polygon-Border-From-JPGs
```

Resolved decision worksheet:

```text
docs\preview-zoom-and-pan\preview-zoom-and-pan-open-questions.md
```

Execution runbook:

```text
docs\preview-zoom-and-pan\preview-zoom-and-pan-implementation-orchestrator.md
```

If the execution runbook conflicts with this implementation plan, this implementation plan wins.

## 1. Executive Summary

Add zoom and pan inspection controls to the existing GUI preview area using Matplotlib's built-in `NavigationToolbar2Tk` plus direct canvas interactions. This is a GUI-only inspection feature: it must not change boundary generation, KML/KMZ parsing, vector simplification, sectioning, output naming, KMZ export, cached generation settings, or file outputs.

The feature should keep the toolbar in the existing preview frame around the embedded `FigureCanvasTkAgg`, add mouse-wheel zoom around the cursor, add left-click drag pan inside the preview axes, preserve the current plot and external legend behavior, and reset each new Scan / Preview redraw to a full fit of the generated result.

## 2. Current Repository Findings

| Finding | Evidence | Status | Relevance |
|---|---|---|---|
| The GUI already embeds a Matplotlib figure in a Tk preview frame. | `src/jpg_boundary_kmz_gui.py`, `BoundaryKmzApp._build_ui`, `FigureCanvasTkAgg` | Verified directly from code | Toolbar integration should extend the existing preview frame instead of replacing it. |
| The preview frame uses row/column weights and the canvas is currently gridded as the expanding widget. | `src/jpg_boundary_kmz_gui.py`, `BoundaryKmzApp._build_ui`, `preview_frame`, `canvas_widget.grid` | Verified directly from code | Toolbar placement must preserve canvas expansion. |
| Preview drawing is centralized. | `src/jpg_boundary_kmz_gui.py`, `BoundaryKmzApp._draw_preview`, `BoundaryKmzApp._draw_empty_preview` | Verified directly from code | Redraw/reset behavior can remain localized to GUI preview methods. |
| The legend is already outside the plotted geometry. | `src/jpg_boundary_kmz_gui.py`, `BoundaryKmzApp._draw_preview`, `axes.legend(... bbox_to_anchor=(1.02, 0.5) ...)`, `figure.tight_layout(rect=(0.0, 0.0, 0.72, 1.0))` | Verified directly from code | Do not regress the prior legend placement fix. |
| Matplotlib is already a runtime dependency. | `requirements_jpg_boundary_kmz.txt`, `matplotlib` | Verified directly from repo | No dependency or lock-file change is required. |
| GUI tests already instantiate and destroy the app. | `tests/test_gui_input.py`, `_app`, `GuiInputTests` | Verified directly from tests | Toolbar smoke coverage belongs in the existing GUI test file. |
| The GUI already has preview/export cache settings unrelated to Matplotlib view state. | `src/jpg_boundary_kmz_gui.py`, `_cached_result`, `_cached_settings`, `_settings_key` | Verified directly from code | Zoom/pan must not alter cache keys or cached results. |
| README documents the preview as schematic and lists Matplotlib. | `README_JPG_BOUNDARY_KMZ.md`, preview notes and dependency list | Verified directly from repo | README may receive a short user-facing note if implementation changes visible usage. |
| Toolbar-only preview did not register direct canvas event handlers. | `src/jpg_boundary_kmz_gui.py`, no prior `mpl_connect` handlers for scroll/drag | Verified directly before follow-up | Direct scroll zoom and left-drag pan require explicit canvas callbacks. |

## 3. Exact Impacted Files And Symbols

`src/jpg_boundary_kmz_gui.py`

- Import section: add `NavigationToolbar2Tk` beside `FigureCanvasTkAgg`.
- `BoundaryKmzApp._build_ui`: create and grid the toolbar in the preview frame.
- `BoundaryKmzApp._register_preview_interactions`: register scroll, press, move, and release callbacks.
- `BoundaryKmzApp._on_preview_scroll`: zoom around the cursor for wheel events inside preview axes.
- `BoundaryKmzApp._on_preview_button_press`, `_on_preview_mouse_move`, `_on_preview_button_release`: implement left-click drag pan and clear transient state.
- `BoundaryKmzApp._draw_preview`: preserve autoscale/full-fit redraw and external legend layout.
- `BoundaryKmzApp._draw_empty_preview`: remain safe before and after toolbar creation.

`tests/test_gui_input.py`

- `GuiInputTests`: add toolbar initialization and redraw-safety assertions.
- `_app`: reuse existing app lifecycle helper.

`README_JPG_BOUNDARY_KMZ.md`

- Optional short note only if implementation needs user-facing documentation for preview controls.

No other production modules, geometry helpers, parsers, exporters, launchers, or external reference repos are in scope.

## 4. Risk Matrix

| Risk | Likelihood | Impact | Mitigation |
|---|---:|---:|---|
| Toolbar breaks Tk layout or shrinks canvas too much. | Medium | Medium | Keep canvas in weighted row and toolbar in non-weighted row; add GUI initialization test. |
| Toolbar creation fails in headless or minimal Tk environments. | Low to Medium | Medium | Gate with GUI smoke command; block for human review only if environment cannot initialize GUI. |
| New toolbar covers or crowds plotted geometry. | Low | Medium | Place toolbar outside the axes, below the canvas, and preserve external legend layout. |
| Redraw preserves stale zoom and hides new geometry. | Medium | Medium | Require `_draw_preview` and `_draw_empty_preview` to clear axes and rely on autoscale/full-fit for each redraw. |
| Scroll events zoom when pointer is outside the preview axes. | Medium | Medium | Ignore events unless `event.inaxes is self.axes` and data coordinates are present. |
| Left-click pan leaves stale drag state after release. | Low | Medium | Clear pan state on release and when press starts outside axes. |
| Implementation accidentally changes export or geometry behavior. | Low | High | Strict allow-list excludes geometry/core files; run full unit suite. |
| Matplotlib toolbar save button writes user-selected files during manual testing. | Low | Low | Treat any save action as optional/manual; do not require saving as a validation gate. |
| Cache keys accidentally include view state. | Low | Medium | Do not touch `_settings_key`; add no persistent view state. |
| Existing tests miss actual toolbar usability. | Medium | Low | Combine unit smoke with manual GUI validation of Home, Pan, and Zoom. |

## 5. Assumptions And Unknowns

| Assumption | Classification | Evidence Or Handling |
|---|---|---|
| `NavigationToolbar2Tk` is available from installed Matplotlib. | Verified from dependency, not imported yet | Matplotlib dependency exists; implementation must validate by GUI smoke. |
| Built-in Matplotlib toolbar is acceptable for v1. | Resolved product decision | Recorded in `preview-zoom-and-pan-open-questions.md`, D1. |
| Reset-to-fit on every new preview is desired. | Resolved product decision | Recorded in `preview-zoom-and-pan-open-questions.md`, D2. |
| Direct mouse-wheel zoom and left-click drag pan are in scope. | Resolved product decision | Recorded in `preview-zoom-and-pan-open-questions.md`, D3. |
| No geometry or export changes are needed. | Verified from feature scope and current architecture | Preview is GUI-only; geometry/export functions are not in the allow-list. |
| GUI manual validation can be performed without Metashape. | Verified from app architecture | Preview uses Tk/Matplotlib only; Metashape is not a dependency. |
| Exact toolbar button set is controlled by Matplotlib. | Verified by API behavior expectation | Do not customize toolbar internals in v1; validate visible controls manually. |

No blockers remain for implementation.

## 6. Edge Cases And Failure Modes

- Empty preview before scan: toolbar must initialize and `_draw_empty_preview()` must not raise.
- Preview after scan: toolbar must work after `_draw_preview()` clears and redraws axes.
- Repeated scans after pan/zoom: the new result must autoscale to full extents.
- Scroll wheel inside axes: zoom around the cursor and preserve current aspect ratio.
- Scroll wheel outside axes: ignore the event so the rest of the window is unaffected.
- Left-click drag inside axes: pan by data-coordinate delta and clear drag state on release.
- Non-left mouse buttons: do not start direct pan.
- Explicit toolbar Pan/Zoom mode: direct left-drag pan defers to the toolbar
  mode so built-in controls remain usable.
- Multi-section previews: toolbar must inspect section fills and labels without changing plotted geometry.
- Vector previews with external legend: legend must remain outside the axes.
- JPG previews with many points: toolbar pan/zoom must inspect plotted points without changing point generation.
- Small window sizes: toolbar must not make the canvas disappear; root minimum size remains in effect.
- Headless or broken Tk environment: implementation must stop at GUI-smoke failure and report the environment limitation.
- Manual toolbar Save action: not required for validation and must not write into protected folders.
- Validation bytecode: commands must use `python -B` and in-memory compile to avoid `__pycache__` churn.

## 7. Strict File Allow-List

| Path | Change Type | Reason | Required Tests | Risk | Rollback |
|---|---|---|---|---|---|
| `src/jpg_boundary_kmz_gui.py` | Modify | Add `NavigationToolbar2Tk`, preview toolbar placement, and direct scroll/pan event handlers. | `python -B -m unittest tests.test_gui_input`; GUI smoke command; full suite. | Medium | Remove toolbar import/attribute/grid code and direct event handlers. |
| `tests/test_gui_input.py` | Modify | Add GUI assertions for toolbar presence, event registration, scroll zoom, ignored outside scroll, left-drag pan, active toolbar mode precedence, and redraw safety. | `python -B -m unittest tests.test_gui_input`; full suite. | Low | Remove toolbar/direct interaction tests. |
| `README_JPG_BOUNDARY_KMZ.md` | Optional modify | Add short user-facing note if implementation needs documented toolbar usage. | Full suite; documentation review. | Low | Remove note. |
| `docs/preview-zoom-and-pan/preview-zoom-and-pan-validation-notes.md` | Optional create | Record manual/automated validation evidence if implementation agent decides it is useful. | `git diff --check`; documentation review. | Low | Delete validation notes if inaccurate or unnecessary. |

Files not listed above must not be modified unless this plan is revised first.

Explicitly disallowed:

- `src/jpg_boundary_kmz_core.py`
- `src/kml_vector_input.py`
- `src/polyline_boundary.py`
- `src/natural_sectioning.py`
- `src/geometry_hardening.py`
- `requirements_jpg_boundary_kmz.txt`
- launcher files
- `test_data/`
- `outputs/`
- `agent_prompt_templates/`
- `C:\Users\rbake\Desktop\VS Code Shortcuts\Buffer-Zone-Generator`
- Metashape project artifacts

## 8. Implementation Phases With Gates

### Phase 1: Baseline And Scope Verification

Goal:

- Confirm current worktree, preview code, dependency state, and test entry points before code edits.

Allowed files:

- No production edits.
- Planning docs may be updated only if a discovered fact invalidates this plan.

Tasks:

- Run baseline status and targeted discovery.
- Confirm `FigureCanvasTkAgg`, `_draw_preview`, `_draw_empty_preview`, and Matplotlib dependency exist.
- Confirm current changes are understood before implementation.

Required commands:

```powershell
git status --short --branch
git diff --name-only
rg -n "FigureCanvasTkAgg|NavigationToolbar2Tk|mpl_connect|def _draw_preview|def _draw_empty_preview|_settings_key" src\jpg_boundary_kmz_gui.py
rg -n "matplotlib" requirements_jpg_boundary_kmz.txt
```

Pass criteria:

- Current worktree state is documented.
- Required GUI symbols and dependency are present.
- No disallowed file changes occur.

Failure conditions:

- Preview is no longer Matplotlib/Tk based.
- Matplotlib dependency is missing.
- Worktree contains unrelated changes that conflict with this task.

Rollback/recovery:

- No code changes should exist in this phase. If docs were updated incorrectly, revert the doc-only update.

### Phase 2: Toolbar Integration And GUI Tests

Goal:

- Add the built-in Matplotlib toolbar, direct mouse-wheel zoom, direct left-drag pan, and narrow GUI coverage.

Allowed files:

- `src/jpg_boundary_kmz_gui.py`
- `tests/test_gui_input.py`
- `README_JPG_BOUNDARY_KMZ.md` only if needed

Tasks:

- Import `NavigationToolbar2Tk`.
- Create `self.preview_toolbar` in the existing preview frame.
- Grid toolbar below the canvas in a non-expanding row.
- Register `scroll_event`, `button_press_event`, `motion_notify_event`, and `button_release_event` callbacks.
- Store only transient pan state.
- Ignore scroll/drag events outside the preview axes.
- Preserve canvas expansion and external legend layout.
- Add GUI tests for toolbar presence, event registration, scroll zoom, ignored outside scroll, left-drag pan, active toolbar mode precedence, widget grid state, canvas presence, and `_draw_empty_preview()` safety.

Required commands:

```powershell
python -B -m unittest tests.test_gui_input
python -B -c "from pathlib import Path; files=list(Path('src').rglob('*.py')); [compile(path.read_text(encoding='utf-8'), str(path), 'exec') for path in files]; print(f'compiled {len(files)} source files')"
python -B -c "import sys; from pathlib import Path; sys.path.insert(0, str(Path('src').resolve())); from jpg_boundary_kmz_gui import _create_root, BoundaryKmzApp; root=_create_root(); root.withdraw(); app=BoundaryKmzApp(root); root.update_idletasks(); root.destroy(); print('GUI smoke ok')"
git status --short
git diff --name-only
```

Pass criteria:

- GUI tests pass.
- GUI smoke initializes and destroys the app cleanly.
- Toolbar and canvas both exist in the preview frame.
- Only allow-listed files changed.
- No geometry/export/cache files changed.

Failure conditions:

- Toolbar cannot initialize.
- Canvas layout breaks.
- Existing GUI tests regress.
- Any disallowed file changes.

Rollback/recovery:

- Remove toolbar import/attribute/grid code and direct event handlers.
- Remove toolbar/direct interaction tests.
- Preserve unrelated GUI behavior.

### Phase 3: Full Regression And Manual Verification

Goal:

- Prove the GUI-only feature did not regress adjacent workflows.

Allowed files:

- Files already changed in Phase 2.
- Optional validation notes under `docs/preview-zoom-and-pan/`.

Required commands:

```powershell
git status --short --branch
python -B -m unittest tests.test_gui_input
python -B -m unittest discover -s tests
python -B -c "from pathlib import Path; files=list(Path('src').rglob('*.py')); [compile(path.read_text(encoding='utf-8'), str(path), 'exec') for path in files]; print(f'compiled {len(files)} source files')"
python -B -c "import sys; from pathlib import Path; sys.path.insert(0, str(Path('src').resolve())); from jpg_boundary_kmz_gui import _create_root, BoundaryKmzApp; root=_create_root(); root.withdraw(); app=BoundaryKmzApp(root); root.update_idletasks(); root.destroy(); print('GUI smoke ok')"
git diff --check
git status --short
git diff --name-only
```

Manual validation:

- Launch the GUI without opening or touching Metashape.
- Generate or load a safe preview.
- Confirm toolbar is visible below the preview canvas.
- Confirm Home/Reset, Pan, and Zoom work.
- Confirm a new Scan / Preview resets to full extents.
- Confirm legend remains outside plotted geometry.

Pass criteria:

- All commands pass.
- Manual validation passes or an environment limitation is documented.
- No disallowed files changed.
- No Metashape process or artifact was touched.

Failure conditions:

- Full suite fails.
- GUI smoke fails in an environment expected to support Tk.
- Manual validation shows toolbar obscures or breaks preview.
- Any protected folder or Metashape artifact is touched.

Rollback/recovery:

- Revert Phase 2 code/test changes.
- Delete optional validation notes if they describe a failed or reverted implementation.

## 9. Testing And Regression Matrix

| Test File | Test Name | Scenario | Expected Result | Command |
|---|---|---|---|---|
| `tests/test_gui_input.py` | `test_preview_toolbar_is_initialized` | App creates preview toolbar. | `preview_toolbar` exists and has a Tk widget. | `python -B -m unittest tests.test_gui_input` |
| `tests/test_gui_input.py` | `test_preview_canvas_and_toolbar_are_gridded` | Canvas and toolbar layout after app init. | Canvas and toolbar are managed by grid and canvas remains present. | `python -B -m unittest tests.test_gui_input` |
| `tests/test_gui_input.py` | `test_empty_preview_redraw_remains_safe` | Calling `_draw_empty_preview()` after toolbar creation. | No exception; canvas can draw idle. | `python -B -m unittest tests.test_gui_input` |
| `tests/test_gui_input.py` | `test_preview_interaction_callbacks_are_registered` | Direct preview callbacks are connected. | Four callback ids are registered. | `python -B -m unittest tests.test_gui_input` |
| `tests/test_gui_input.py` | `test_preview_scroll_inside_axes_changes_limits` | Mouse-wheel zoom over axes. | X/Y ranges shrink for zoom-in. | `python -B -m unittest tests.test_gui_input` |
| `tests/test_gui_input.py` | `test_preview_scroll_outside_axes_is_ignored` | Mouse-wheel event outside axes. | X/Y limits remain unchanged. | `python -B -m unittest tests.test_gui_input` |
| `tests/test_gui_input.py` | `test_preview_left_drag_pans_and_release_clears_state` | Left-drag pan. | X/Y limits change and pan state clears on release. | `python -B -m unittest tests.test_gui_input` |
| `tests/test_gui_input.py` | `test_preview_left_drag_defers_to_active_toolbar_mode` | Explicit toolbar mode precedence. | Direct pan state does not start while toolbar Zoom/Pan mode is active. | `python -B -m unittest tests.test_gui_input` |
| `tests/test_gui_input.py` | Existing GUI tests | KML path input, split direction validation, cache key behavior. | Existing tests continue passing. | `python -B -m unittest tests.test_gui_input` |
| Full suite | Existing all tests | JPG, vector, sectioning, simplification, parser, and GUI regressions. | All tests pass. | `python -B -m unittest discover -s tests` |
| GUI smoke | Existing command | App initializes and destroys without interactive use. | Prints `GUI smoke ok`. | See Phase 3 command list. |
| Manual GUI | Manual check | Toolbar Home/Pan/Zoom on a generated preview. | Controls work and new scan resets view. | Manual validation |

## 10. Pre-Implementation Checklist

- [ ] Run `git status --short --branch` and document existing worktree state.
- [ ] Confirm `src/jpg_boundary_kmz_gui.py` contains `FigureCanvasTkAgg`.
- [ ] Confirm `src/jpg_boundary_kmz_gui.py` contains `_draw_preview` and `_draw_empty_preview`.
- [ ] Confirm `requirements_jpg_boundary_kmz.txt` contains `matplotlib`.
- [ ] Confirm `tests/test_gui_input.py` app lifecycle helper is available.
- [ ] Confirm no implementation requires geometry/core/export changes.
- [ ] Confirm no dependency changes are required.
- [ ] Confirm allow-list is complete.
- [ ] Confirm rollback strategy is understood.
- [ ] Confirm no Metashape interaction is required or allowed.

## 11. Post-Implementation Validation Checklist

- [ ] `python -B -m unittest tests.test_gui_input` passes.
- [ ] `python -B -m unittest discover -s tests` passes.
- [ ] In-memory source compile command passes.
- [ ] GUI smoke command passes.
- [ ] `git diff --check` passes.
- [ ] `git status --short` contains only allow-listed changes.
- [ ] `git diff --name-only` contains only allow-listed changes.
- [ ] No `__pycache__/` or `.pyc` churn remains.
- [ ] No temporary, placeholder, TODO, mock, or debug logic was introduced.
- [ ] No public geometry/export/config/API behavior changed.
- [ ] Preview legend remains outside plotted shapes.
- [ ] Direct mouse-wheel zoom and left-click drag pan pass automated GUI tests.
- [ ] Manual toolbar validation passes or a real environment limitation is documented.
- [ ] No Metashape process or artifact was touched.

## 12. Rollback And Recovery Plan

- If toolbar import fails: remove `NavigationToolbar2Tk` import and all toolbar creation code.
- If direct interaction handlers fail: remove `mpl_connect` registrations and handler methods, leaving toolbar-only behavior intact.
- If layout breaks: restore previous preview frame grid with only the canvas widget.
- If GUI tests fail due to environment limitations: document the environment issue, do not broaden scope into custom toolbar code without plan revision.
- If full suite fails outside GUI tests: revert GUI changes first, then re-run to confirm regression source.
- If any disallowed file changes: stop, restore those files unless they are unrelated pre-existing user changes, and revise the plan before continuing.
- If manual validation shows toolbar obscures preview: adjust only preview-frame layout within `src/jpg_boundary_kmz_gui.py`; if that cannot fix it, revert and revise the plan.

## 13. Blockers Or Items Requiring Clarification

No known blockers.

Clarification is required only if:

- Matplotlib toolbar cannot initialize in the target environment.
- The user rejects the built-in toolbar appearance after seeing it.
- The implementation needs interaction behavior beyond direct wheel zoom, direct left-drag pan, persistent viewport, or custom icon buttons.
- Any change outside the strict allow-list becomes necessary.

## 14. Final Readiness Assessment

Ready for implementation.

The plan has direct repository evidence, resolved product decisions, a strict file allow-list, phased gates, concrete tests, rollback instructions, and explicit Metashape safety constraints. The implementer should proceed through the orchestrator runs and stop only on the listed human-blocking conditions.
