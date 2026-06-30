# Camera Boundary V2 Implementation Orchestrator

Status: execution runbook.

This file controls how to execute the phased implementation. It does not replace the authoritative implementation plan:

- Authoritative plan: `docs/camera-boundary-v2-implementation-plan.md`
- Resolved decisions record: `docs/TEMP-camera-boundary-v2-open-decisions.md`

If this runbook conflicts with `docs/camera-boundary-v2-implementation-plan.md`, the authoritative plan wins.

## 1. Execution Policy

- Do not implement Camera Boundary V2 in one uninterrupted pass.
- Implement in grouped runs with mandatory stop points.
- Do not begin a downstream run until all commands, gates, and file-scope checks for the current run pass.
- Passing agent-verifiable gates do not require human approval by default.
- If the user asks for full implementation, the agent can continue from one run to the next after all gates pass, while still reporting the run summary.
- Human review blocks progress only under the conditions in section 3.
- If a gate fails, patch only files allowed for the current phase group or revise the authoritative plan before touching additional files.
- Keep `test_data/` read-only.
- Keep `.gitignore` configured so `test_data/` is ignored; `git status --short` must not list sample data files or folders.
- Do not write generated validation files into `test_data/`, `outputs/`, source folders, or the other repo.
- Use temporary directories for automated test outputs.
- Generated manual-validation KMZs are disposable and must not be committed.
- After every run, report changed files, commands run, pass/fail status, and next recommended action.
- Every run must include both `git status --short` and `git diff --name-only` in its file-scope check, because `git diff --name-only` does not show untracked files.

## 2. Run Report And Continuation Policy

At the end of every run, provide:

- Run number and phases completed.
- Files changed.
- Tests and commands run.
- Pass/fail result for each command.
- Any failures fixed during the run.
- Any remaining risks or observations.
- Whether the next run is safe to start.

Continuation rules:

- If the current run passes and no human-blocking condition exists, the agent can proceed to the next run without waiting for user approval when the user has requested implementation to continue.
- If the current run passes but the user requested only that run, stop after reporting.
- If the current run fails, do not proceed until the failure is fixed within the current run's allow-list or the authoritative plan is revised.

## 3. Human-Blocking Conditions

Human review or approval is required only when at least one condition below occurs:

- A required command fails and fixing it requires touching files outside the current run's allow-list.
- The implementation needs to revise the authoritative plan, file allow-list, product decisions, or phase grouping.
- Real-sample calibration produces output that passes automated checks but is visually or semantically ambiguous against the human-made reference KMZs.
- Auto strategy calibration requires changing internal thresholds in a way that materially trades off lawnmower accuracy against ROW/corridor accuracy.
- The agent cannot verify GUI launch or GUI behavior from the available environment.
- The implementation would modify `test_data/` contents, remove `.gitignore` protection for `test_data/`, modify `outputs/`, modify launcher files, modify `agent_prompt_templates/`, or modify files in `Buffer-Zone-Generator`.
- A generated result appears to extend beyond JPG-covered areas toward a client pipeline/system reference boundary.
- A manual output must be written to a user-selected persistent location or overwrite an existing user file.

No human review is required for:

- Passing unit tests.
- Passing `python -m compileall src`.
- File-scope checks where `git diff --name-only` is allow-listed.
- Creating or maintaining the `.gitignore` rule that keeps `test_data/` out of git.
- Shapely version verification after the dependency pin.
- Synthetic geometry/classifier/strategy test approval.
- Legacy KMZ regression test approval.
- GUI behavior that the agent can verify directly.
- Real-sample calibration that is objectively documented in `docs/camera-boundary-v2-validation-notes.md` and does not trigger a human-blocking condition.

## 4. Run Grouping

### Run 1: Baseline And Geometry Foundation

Covered phases:

- Phase 0: Baseline And Guardrails
- Phase 1: Geometry Hardening Foundation

Purpose:

- Establish baseline.
- Pin `shapely>=2.0`.
- Add shared projected geometry cleanup/densification helpers.
- Integrate geometry hardening into existing core buffer/export paths.

Allowed files:

- `src/geometry_hardening.py`
- `src/jpg_boundary_kmz_core.py`
- `requirements_jpg_boundary_kmz.txt`
- `.gitignore`
- `tests/test_geometry_hardening.py`

Required commands:

```powershell
git status --short --branch
git check-ignore -v test_data/
python -c "import shapely; from shapely.geometry import Polygon; print(shapely.__version__); print(hasattr(Polygon([(0,0),(1,0),(1,1),(0,0)]), 'segmentize'))"
python -m unittest tests.test_geometry_hardening
python -m compileall src
git diff --name-only
```

Continue gate:

- All commands pass.
- `git diff --name-only` contains only Run 1 allowed files plus already-existing docs changes.
- `git status --short` contains only Run 1 allowed files plus already-existing docs changes and no sample-data entries.
- `git status --short` does not list `test_data/` or files below it.
- `test_data/`, `outputs/`, launcher files, and `agent_prompt_templates/` are unchanged.
- Existing JPG and legacy KMZ generation code still imports.

Stop if:

- Shapely lacks `segmentize` after dependency pin.
- `git check-ignore -v test_data/` fails or `git status --short` lists sample data files.
- Geometry helper tests fail.
- Core import/compile fails.
- Any non-allowed file changes.

Rollback:

- Remove `geometry_hardening` imports/usages.
- Restore direct core buffer calls.
- Revert the `shapely>=2.0` pin only if manual densification fallback is formally planned and tested.

## 5. Run 2: Camera Preflight Classifier

Covered phase:

- Phase 2: Camera Preflight Classifier

Purpose:

- Add camera-order and pattern-classification logic.
- Extend `GpsPoint` with optional capture time.
- Record classifier metrics and ordering source without changing final strategy selection yet beyond safe fallback wiring.

Allowed files:

- `src/camera_preflight.py`
- `src/jpg_boundary_kmz_core.py`
- `tests/test_camera_preflight.py`
- `tests/geometry_test_utils.py`

Required commands:

```powershell
python -m unittest tests.test_camera_preflight
python -m compileall src
git status --short
git diff --name-only
```

Continue gate:

- Classifier tests pass.
- Missing or invalid EXIF timestamps do not reject otherwise valid GPS points.
- Order source is deterministic and recorded as `exif_datetime`, `filename`, or `input_sort`.
- Ambiguous synthetic inputs return low-confidence fallback-ready results.
- `git status --short` and `git diff --name-only` contain only current-run allowed files plus already-authorized planning docs or `.gitignore` changes, with no `test_data/` entries.
- No GUI behavior changes yet.

Stop if:

- Classifier reports high confidence for ambiguous/scattered data.
- Valid GPS points are dropped because timestamps are missing.
- Core compile fails.
- Any non-allowed file changes.

Rollback:

- Stop invoking preflight from core.
- Revert `GpsPoint` timestamp changes if they break current GPS behavior.

## 6. Run 3: Outline Strategy Engine

Covered phase:

- Phase 3: Outline Strategy Engine

Purpose:

- Add outline candidate construction and scoring.
- Implement concave fallback wrapper, route-aware strategy, lawnmower envelope strategy, mixed-section strategy orchestration, and hard rejection gates.
- Keep `Auto` conservative.

Allowed files:

- `src/outline_strategies.py`
- `src/geometry_hardening.py`
- `src/camera_preflight.py`
- `src/jpg_boundary_kmz_core.py`
- `tests/test_outline_strategies.py`
- `tests/test_core_regression.py`
- `tests/geometry_test_utils.py`

Required commands:

```powershell
python -m unittest tests.test_outline_strategies tests.test_core_regression
python -m compileall src
git status --short
git diff --name-only
```

Continue gate:

- All strategy and core regression tests pass.
- Unknown outline mode raises `BoundaryError`.
- Ambiguous Auto cases fall back to concave hull.
- Implausible area ratio, missing required control points, invalid geometry, and disconnected section-incompatible candidates are rejected with specific reasons.
- Legacy KMZ-as-primary behavior still works.
- Candidate diagnostics are serializable and do not contain Shapely or NumPy objects in metadata.
- `git status --short` and `git diff --name-only` contain only current-run allowed files plus already-authorized planning docs or `.gitignore` changes, with no `test_data/` entries.

Stop if:

- `Auto` accepts invalid, disconnected, or non-JPG-covered geometry.
- Existing KMZ input behavior regresses.
- Section splitting receives unsupported geometry silently.
- Any non-allowed file changes.

Rollback:

- Force outline mode to concave fallback in core orchestration.
- Leave strategy modules unused until fixed, or remove them if reverting the run.

## 7. Run 4: GUI Integration

Covered phase:

- Phase 4: GUI And User-Facing Details

Purpose:

- Add outline mode control.
- Pass mode through scan/export workers.
- Include mode in cache key.
- Show selected strategy, confidence, order source, candidate diagnostics, and fallback reasons in details/status text.

Allowed files:

- `src/jpg_boundary_kmz_gui.py`
- `src/jpg_boundary_kmz_core.py`
- `README_JPG_BOUNDARY_KMZ.md`
- `tests/test_core_regression.py`

Required commands:

```powershell
python -m unittest discover -s tests
python -m compileall src
python .\run_jpg_boundary_gui.py
git status --short
git diff --name-only
```

Manual checks:

- GUI launches.
- JPG folder input defaults to `Auto`.
- Changing outline mode invalidates cached preview/export result.
- `Auto` fallback appears as non-blocking status/details text.
- Legacy KMZ-as-primary input disables or clearly bypasses outline mode and still exports.

Continue gate:

- All commands pass.
- Manual GUI launch succeeds.
- No stale-cache behavior after mode changes.
- README documents implemented modes, fallback behavior, and `shapely>=2.0`.
- `git status --short` and `git diff --name-only` contain only current-run allowed files plus already-authorized planning docs or `.gitignore` changes, with no `test_data/` entries.

Stop if:

- GUI cannot launch.
- Export uses stale cached strategy.
- Fallback reason is invisible.
- KMZ-as-primary workflow is broken.
- Any non-allowed file changes.

Rollback:

- Remove mode UI and route core calls through the safe default.
- Restore cache key if mode handling is defective.

## 8. Run 5: Calibration, Documentation, And Closeout

Covered phase:

- Phase 5: Regression, Calibration, And Documentation

Purpose:

- Run full automated validation.
- Run real-sample calibration against both provided datasets.
- Create validation notes.
- Finalize README and closeout evidence.

Allowed files:

- `README_JPG_BOUNDARY_KMZ.md`
- `docs/camera-boundary-v2-validation-notes.md`
- `tests/test_geometry_hardening.py`
- `tests/test_camera_preflight.py`
- `tests/test_outline_strategies.py`
- `tests/test_core_regression.py`
- `tests/geometry_test_utils.py`
- Prior implementation files only to fix failures discovered in this run.

Required commands:

```powershell
python -m unittest discover -s tests
python -m compileall src
git status --short
git diff --name-only
```

Required manual calibration inputs:

```text
test_data\jpgs\Lawn Mower JPGs
test_data\output-shape-examples\Lawn Mower JPGs\Lawn Mower JPGs.kmz
test_data\jpgs\Day 1 - 06-24
test_data\output-shape-examples\Day 1 - 06-24\Day 1 - 06-24.kmz
```

Required evidence file:

```text
docs/camera-boundary-v2-validation-notes.md
```

The validation notes must record:

- Commands run and pass/fail status.
- Disposable output locations.
- Real sample input paths.
- Reference KMZ paths.
- Selected strategy for each sample.
- Fallback reasons, if any.
- Candidate diagnostics reviewed.
- Whether output stayed tied to JPG coverage.
- Any residual implementation risks.

Close gate:

- Full tests pass.
- Compile passes.
- Validation notes cover both real datasets.
- `test_data/` remains unchanged.
- `.gitignore` still ignores `test_data/`.
- `outputs/` remains unchanged unless the user explicitly requested a manual output there.
- No generated KMZs are committed.
- README matches implemented behavior.
- `git diff --name-only` contains only allowed implementation, test, docs, and requirements files.
- `git status --short` contains only allowed modified or untracked files and no `test_data/` entries.

Stop if:

- Real samples show repeated false positives.
- Output expands to full reference/pipeline area without JPG coverage.
- Validation notes are missing either real dataset.
- Tests or compile fail.
- Non-allowed files changed.

Rollback:

- Keep code behind concave fallback if Auto cannot be calibrated safely.
- Revert docs/test refinements that describe behavior not actually implemented.

## 9. Final Closeout Report Template

Use this format after Run 5:

```text
Implementation status:
Runs completed:
Files changed:
Commands run:
Tests added:
Manual validation:
Validation notes:
Known residual risks:
Ready to close: yes/no
```
