# Export settings validation

Date: November 18, 2026. Windows; repository `.venv` Python.

## Delivered behavior

- Single exported placemark names use the chosen KMZ filename stem. Split labels
  and existing multi-facility names remain meaningful. No KML descriptions are
  embedded; full generation diagnostics remain in Details and the desktop's
  rotating external log.
- Unified, single-shape KML/KMZ buffers default to
  `Original name - (50 ft Buffer).kmz`, using the actual buffer value. Custom
  names and chosen destination folders are preserved. Automatic buffer changes
  require review of the resulting filename before writing the file.
- The footer Export button and Ctrl+E open output settings. Filename, destination,
  split labels, and appearance can be reviewed before the final Export KMZ button.
- Overlap and shape-label controls are hidden for one shape with their footer
  space reserved; two or more shapes reveal the retained values immediately.
- Outline/fill colors, line width, independent opacity, and outline/fill/both
  modes apply to the preview and exported KMZ. Appearance edits preserve geometry,
  cache, view, and the existing automatic color palette when selected.
- KML polygon exterior winding is normalized without changing the footprint.
  This fixes a confirmed compatibility defect; the reported Google Earth stroke
  thinning is **not yet visually verified as resolved**.

Implementation: [GUI](../src/jpg_boundary_kmz_gui.py),
[shared style](../src/export_style.py), [serializer](../src/jpg_boundary_kmz_core.py),
[external log](../src/generation_log.py).

## Automated checks

Commands below use `.venv\Scripts\python.exe -B -m unittest`.

| Test selection | Observed result |
| --- | --- |
| `discover -s tests -q` | 317 tests in 808.476 s; one opt-in test skipped. One test failed in ten subcases because it still required the removed KMZ descriptions. No other failures or errors. |
| `tests.test_per_side_core -q`, after updating that expectation | All 4 tests passed in 40.021 s. The changed check verifies diagnostics in the external summary and no descriptions in KMZ, while retaining all saved-geometry coverage checks. |
| `tests.test_export_style tests.test_kmz_export_contract -v` | All 9 tests passed. |
| `tests.test_export_workflow tests.test_gui_per_side_buffer -q` | All 19 tests passed. |
| `tests.test_export_workflow tests.test_multi_polygon_gui -q`, after final preview changes | All 12 tests passed in 34.876 s, including 37 source facilities exported as 74 polygons. |
| `tests.test_generation_log tests.test_export_style -q` | All 9 tests passed, including the two external-log tests added after full-suite discovery began. |
| `git diff --check` | Passed. |

The full suite was not repeated after correcting the obsolete expectation;
the entire affected test module passed on rerun. A redundant intermediate GUI
run was stopped before completion to avoid running native window tests concurrently;
it is not counted as a passing run. Existing Shapely deprecation and Matplotlib
axis-limit warnings remain outside this change's scope.

## File and UI checks

- The user-confirmed SURF input was generated to a temporary KMZ at 50 ft with a
  black, 5-pixel outline. XML checks confirmed the chosen filename-based name,
  no descriptions, counterclockwise exterior, selected style, and retained source
  diagnostics. Original client and exported files were not modified.
- Inspected the desktop export panel at 1280x800 and 720x500 using offline
  synthetic geometry. The final export action stays visible while settings scroll;
  the footer controls fit. Captures predate only the appearance panel's minor
  background-theme correction.
- Local test logs and screenshots are retained in the ignored
  `test_data/export-settings-review/` directory. The initial full-suite log
  intentionally records the obsolete-description failures before their correction.

## Remaining visual verification

See [outline investigation](export-outline-investigation.md) for inspected file
hashes, Google KML references, prepared identical-footprint comparison files,
and the native verification attempt. Google Earth's process was running, but
the computer-use interface exposed no usable window; two supported launch
attempts failed. No Google Earth imports or Places edits were made.

The remaining check is an identical-camera, identical-style comparison of the
clockwise polygon, corrected polygon, and closed LineString in Google Earth.
File-level tests do not establish the screenshot's stroke-rendering outcome.
