# Camera Boundary V2 Validation Notes

Date: 2026-06-30

## Commands Run

- `git status --short --branch` - passed during baseline.
- `git check-ignore -v test_data/` - passed; `test_data/` is ignored by `.gitignore`.
- `python -B -c "import shapely; from shapely.geometry import Polygon; print(shapely.__version__); print(hasattr(Polygon([(0,0),(1,0),(1,1),(0,0)]), 'segmentize'))"` - passed; Shapely `2.0.7`, `segmentize=True`.
- `python -B -m unittest tests.test_geometry_hardening` - passed; 3 tests.
- `python -B -m unittest tests.test_camera_preflight` - passed; 6 tests.
- `python -B -m unittest tests.test_outline_strategies tests.test_core_regression` - passed; 12 tests.
- `python -B -m unittest discover -s tests` - passed; 22 tests after audit hardening.
- `python -B -c "from pathlib import Path; files=list(Path('src').rglob('*.py')); [compile(path.read_text(encoding='utf-8'), str(path), 'exec') for path in files]; print(f'compiled {len(files)} source files')"` - passed; compiled 6 source files.
- `python -B -c "import sys; from pathlib import Path; sys.path.insert(0, str(Path('src').resolve())); from jpg_boundary_kmz_gui import _create_root, BoundaryKmzApp; root=_create_root(); root.withdraw(); app=BoundaryKmzApp(root); root.update_idletasks(); root.destroy(); print('GUI smoke ok')"` - passed.
- Programmatic GUI state smoke - passed: default outline mode `Auto`, changing outline mode cleared cached settings, KMZ input disabled outline mode.
- Real-sample calibration command using `generate_boundary_from_input` and `save_kmz` - passed.
- Legacy KMZ smoke command using a temporary KMZ fixture, `generate_boundary_from_kmz`, and `save_kmz` - passed.
- Post-implementation audit real-sample smoke command using `generate_boundary_from_input` and `save_kmz` - passed.

## Disposable Output Locations

- Real-sample validation outputs: `C:\Users\rbake\AppData\Local\Temp\camera_boundary_v2_validation_3_1l_1et`
- Legacy KMZ smoke outputs: `C:\Users\rbake\AppData\Local\Temp\camera_boundary_v2_legacy_kmz_frymds45`
- Post-implementation audit validation outputs: `C:\Users\rbake\AppData\Local\Temp\camera_boundary_v2_audit_z984k38a`

These outputs are disposable and were not written to `test_data/`, `outputs/`, source folders, or any Metashape project location.

## Real Sample: Lawn Mower JPGs

- Input JPG folder: `test_data\jpgs\Lawn Mower JPGs`
- Reference KMZ: `test_data\output-shape-examples\Lawn Mower JPGs\Lawn Mower JPGs.kmz`
- Reference KMZ existed: yes
- Generated output: `C:\Users\rbake\AppData\Local\Temp\camera_boundary_v2_validation_3_1l_1et\Lawn Mower JPGs_auto_boundary.kmz`
- Outline mode: `auto`
- Selected strategy: `lawnmower_envelope`
- Strategy confidence: `0.882`
- Preflight pattern: `lawnmower`
- Preflight confidence: `0.882`
- Camera order source: `exif_datetime`
- Fallback reason: none
- Candidate diagnostics: `concave_hull: accepted; route_aware: rejected (preflight pattern is lawnmower, geometry is empty); lawnmower_envelope: accepted`
- Output vertices: `395`
- Sections: `1`
- Output area: `124415.478 m2`
- Pass/fail note: passed. Auto selected the intended lawnmower envelope strategy without a fallback.
- JPG coverage note: output was generated only from JPG GPS coverage. The reference KMZ was used as calibration context only and was not used as generation input.

## Real Sample: Day 1 - 06-24

- Input JPG folder: `test_data\jpgs\Day 1 - 06-24`
- Reference KMZ: `test_data\output-shape-examples\Day 1 - 06-24\Day 1 - 06-24.kmz`
- Reference KMZ existed: yes
- Generated output: `C:\Users\rbake\AppData\Local\Temp\camera_boundary_v2_validation_3_1l_1et\Day 1 - 06-24_auto_boundary.kmz`
- Outline mode: `auto`
- Selected strategy: `concave_hull`
- Strategy confidence: `1.000`
- Preflight pattern: `mixed`
- Preflight confidence: `0.550`
- Camera order source: `exif_datetime`
- Fallback reason: `Auto fell back to concave hull because route_aware: preflight pattern is mixed, preflight confidence is below route threshold, geometry is empty; lawnmower_envelope: preflight pattern is mixed, preflight confidence is below lawnmower threshold, geometry is empty; mixed_sections: geometry contains holes, required camera points are not covered.`
- Candidate diagnostics: `concave_hull: accepted; route_aware: rejected (preflight pattern is mixed, preflight confidence is below route threshold, geometry is empty); lawnmower_envelope: rejected (preflight pattern is mixed, preflight confidence is below lawnmower threshold, geometry is empty); mixed_sections: rejected (geometry contains holes, required camera points are not covered)`
- Output vertices: `2938`
- Sections: `1`
- Output area: `5045561.242 m2`
- Pass/fail note: passed. Auto took the conservative fallback because non-concave mixed candidates failed hard rejection gates.
- JPG coverage note: output was generated only from JPG GPS coverage. The reference KMZ was used as calibration context only and was not used as generation input. The generated output was not expanded to a client pipeline/system reference boundary.

## Legacy KMZ Smoke

- Temporary source KMZ: `C:\Users\rbake\AppData\Local\Temp\camera_boundary_v2_legacy_kmz_frymds45\legacy_source.kmz`
- Generated output: `C:\Users\rbake\AppData\Local\Temp\camera_boundary_v2_legacy_kmz_frymds45\legacy_export.kmz`
- Selected strategy: `source_polygon`
- Sections: `2`
- Output vertices: `45`
- Pass/fail note: passed. Existing KMZ-as-primary workflow remains separate from JPG outline strategy selection.

## Guardrails

- `test_data/` was read-only during validation.
- No generated outputs were written into `test_data/`, `outputs/`, source folders, or `Buffer-Zone-Generator`.
- No Metashape process, active project, project artifact, task queue, or processing job was launched, inspected, modified, interrupted, or otherwise touched.
- The reference KMZs were used only as validation/calibration context.
- Generated KMZs are disposable temp outputs and should not be committed.
- Post-implementation audit hardened section output validation so holed section geometry is rejected instead of being exported with interiors silently omitted.

## Residual Risks

- Real-world classifier thresholds may still need tuning on additional capture styles.
- The ROW sample still falls back to concave hull because the first mixed-section candidate is rejected by safety gates. This is conservative and passes the current plan, but future work can improve mixed-section geometry if needed.
- Reference KMZs are human-created guidance and are not exact machine ground truth.
