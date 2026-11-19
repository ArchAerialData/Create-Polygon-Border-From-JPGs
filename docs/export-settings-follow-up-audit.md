# Export settings follow-up audit

Date: November 18, 2026. Baseline: clean working tree at `3ab1f66`.

Runtime: Python 3.13.3, Tk 8.6, Shapely 2.2.0, Matplotlib 3.11.2,
NumPy 2.5.4, pyproj 3.8.0, simplekml 1.3.6. Dependencies were not changed.

## 1. Executive summary

Audited the six requested features, corrected confirmed edge cases, and expanded
backend, real-worker integration, native keyboard, and window-scaling coverage.
This audit is limited to the export implementation and affected GUI behavior.
It does not certify screen-reader support or resolve Google Earth's reported
stroke thinning without a visual comparison.

## 2. Requirement compliance

| Requirement | Direct verification |
| --- | --- |
| Filename-based shape names; diagnostics outside KMZ | Actual GUI exports and XML: single placemark matches filename; split labels preserved; no descriptions; full summaries and saved paths in rotating external log. |
| Single-shape imported buffer filename | Existing workflow tests cover integer/fractional buffers, custom names, folder changes, and automatic-buffer review before writing. |
| Export opens settings, then final export | Real GUI button invocation confirms menu opening creates no file; final action runs the worker and writes the selected KMZ. |
| Hide split-only footer fields, reserve space | Existing slot-size tests plus actual keyboard traversal confirm hidden fields are skipped and values return intact. |
| Colors, width, fill/outline/both, opacity | Real exports verify all three modes and independent colors/alpha; appearance edits retain cached geometry and preview state. |
| Investigate uneven Google Earth outline | Winding defect corrected and geometry preserved; prepared comparisons remain available. Exact on-screen outcome remains unverified because Earth exposes no targetable window. |

## 3. Files inspected

- `src/jpg_boundary_kmz_gui.py`: output settings, naming, field state, background
  request handling, cache signatures, preview/legend updates, scrolling, focus,
  responsive header/footer, error handling, launch/logging.
- `src/export_style.py`, `src/jpg_boundary_kmz_core.py`,
  `src/generation_log.py`: validation, KML serialization, winding, atomic writes,
  summary retention, log startup and rotation.
- `src/jpg_boundary_gui_theme.py`, `src/jpg_boundary_gui_window.py`, both Python
  GUI launchers, README, previous validation and outline-investigation notes.
- Related export, geometry, multi-facility, GUI, window, and logging tests.

## 4. Confirmed findings and patches

| Finding | Correction / evidence |
| --- | --- |
| Tab could focus a clipped appearance field; repeated Ctrl+E could leave filename above viewport | Settings-descendant focus reveals the control. Real Tab/Shift-Tab and repeated-shortcut tests pass. |
| Closing the drawer left focus inside hidden content | Focus returns to a visible Export/settings control; hiding a focused split-label field also transfers focus. |
| Numeric errors lost field context; color pickers shared indistinguishable names | `ExportStyleError` retains a field identifier; GUI focuses/reveals it. Pickers and dialogs distinguish outline/fill. |
| Huge finite width overflowed preview calculations; enormous numeric inputs leaked OverflowError | Shared validation requires finite width in `(0, 100]` pixels and converts numeric overflow to a field-specific validation error. |
| Naming and Save As required write access to the default outputs directory | Suggestions/dialogs no longer create it. The serializer creates only the selected destination when actually exporting. |
| Pasting an existing destination folder could turn its basename into the filename | Preserve File name and resolve a full path inside that folder before export. |
| Empty/reserved/control-character filenames reached export or reused stale names | Validate final custom filenames before worker creation; Windows reserved names and malformed values have regression coverage. Surrounding whitespace is trimmed. |
| Filename/folder-only changes discarded usable geometry | Invalidate only when the effective boundary/label signature changes; real E2E export proves reuse after appearance/name changes. |
| A facility named `Source polygons` could recolor the source legend entry | Update boundary keys by drawing order, independently of user-visible label text. |
| High-DPI narrow window clipped the application title | Choose a shorter title using measured text width; native sizing tests and screenshot verify it fits. |
| Valid 3D WGS84 polygon failed tuple unpacking | Serialize XY with altitude zero for ground clamp; preserve input WKB, vertices, footprint, and correct winding. |
| Diagnostic path resolution could bypass graceful startup fallback | Include resolution in the fallback guard; test unavailable directory, path failure, idempotency, bounded rotation, and Unicode. |

## 5. Patch scope

Production edits are limited to GUI behavior, shared style validation, the
coordinate serializer, and diagnostic log setup. No dependency changes,
geometry-algorithm redesign, commits, original client-file changes, or Google
Earth Places edits were made. Documentation and focused regression tests accompany
the fixes.

## 6. Edge cases reviewed

Invalid/empty/nonfinite style values; width/opacity limits; Unicode names;
Windows reserved names; read-only default folders; existing destination folders;
custom versus automatic names/labels; automatic buffer adjustment; output
overwrite refusal and atomic write failure; hidden/busy fields; stale background
requests; duplicate legend names; 3D coordinates; single/split/collection exports;
unavailable logging; log rotation; keyboard-only use; enlarged startup text.

## 7. Tests added or expanded

- `tests/test_export_edge_cases.py`: seven naming/path/cache/legend regressions.
- `tests/native_export_accessibility.py`: seven tests using actual Tk keyboard
  events, native center hit-testing, viewport geometry, and callback-error capture.
- `tests/test_export_end_to_end.py`: actual GUI worker, serializer, XML, cache
  reuse, and external log across outline/both/fill and single/split exports.
- `tests/test_export_style.py`: validation field identity, extreme numeric
  inputs, 100-pixel boundary, and actual 3D ground-clamped export.
- `tests/test_generation_log.py`: path-resolution failure, idempotent setup,
  bounded rotation, Unicode retention.
- Two existing GUI assertions now verify the retained geometry cache after
  geometry-neutral output-name edits.

## 8. Validation commands

All commands use `.venv\Scripts\python.exe -B -m unittest`.

| Selection | Result |
| --- | --- |
| `tests.test_export_style tests.test_kmz_export_contract tests.test_generation_log -v` | 15 passed; subsequent field-error update separately passed all 8 style tests. |
| `tests.test_export_workflow tests.test_export_edge_cases -q` | 18 passed in 14.449 s. |
| `tests.native_export_accessibility -v` | All 7 strict native integration tests passed in 37.561 s in the final separate fresh-process run. |
| Startup-scaling test after title fix | Passed all five size/scaling subcases in 17.198 s. |
| `tests.test_export_end_to_end -v` | Passed in 4.926 s with real generated files. |
| Invalid appearance focus + invalid custom filenames | Both passed in 3.781 s. |
| Existing single-shape/custom-label cache tests after expectation update | Both passed in 0.941 s. |
| `discover -s tests -v` | **Passed:** 331 tests in 757.098 s; 330 passed, one opt-in live Esri smoke skipped. No failures or errors. |
| Syntax parsing and `git diff --check` | Passed. |

Logs remain in ignored `test_data/export-settings-review/`. Earlier logs retain
their original results; the complete audit run is `audit-full-suite.txt`.
The first full audit run executed 338 tests in 567.995 s and recorded six
failures: two obsolete cache-discard expectations and four subcase/test failures
where the native test window had no keyboard focus immediately after Ctrl+E.
The native harness now waits for observable Windows activation/focus messages,
establishes Export as the opener, and then checks the shortcut-selected target
without forcing the expected filename focus after the action. Strict hit-testing,
viewport, and title-width assertions are unchanged. That run is retained as
`audit-full-suite-initial.txt`. A second combined run executed 338 tests in
562.670 s: all non-native checks passed, with seven failures confined to native
Windows foreground-focus loss. Waiting longer did not reliably solve that OS
activation precondition. Its log is `audit-full-suite-native-focus.txt`.

The seven strict native tests were separated into
`tests/native_export_accessibility.py` for the historical verification above.
**Subsequent user policy supersedes the original native-run requirement:** all
routine GUI tests must run in the background. Native tests now skip by default;
their foreground assertions are retained only for an explicitly requested session.
The shared test guard also prevents roots, Inspector windows and Focus Preview
from showing or activating during ordinary discovery, and blocks unmocked dialogs.
Two older tests requiring visible layout/hit-testing are now opt-in as well;
the long-credit layout test was converted to hidden operation with its assertions
preserved. Geometry is settled before measuring Inspector text bounds.
The manual preview harness is blocked without the same explicit opt-in.
See `AGENTS.md` and the README regression section. Historical native pass counts
below do not imply that foreground tests were rerun after this policy change.
This separation distinguishes active native focus from the target Tk remembers
for future activation, as documented in the
[Tk focus reference](https://www.tcl-lang.org/man/tcl8.6/TkCmd/focus.htm).

## 9. UI and accessibility verification

Scaling is set **before** constructing the app and theme. Tested Tk pixels per
point and window sizes: 720x500 at 1.333 and 2.0; 960x600 at 1.667 and 2.0;
1100x760 at 2.667. These simulate startup text/DPI scaling, not changing Windows
display settings or a physical multi-monitor DPI transition.

Tests verify focused controls lie inside the visible scroll viewport, the pinned
final button is unobscured and hit-testable, hidden controls are skipped, Escape
returns visible focus, errors wrap, and no Tk callback exceptions occur. The
existing suite separately covers native Windows DPI awareness and work-area fitting.

OS screenshot inspection confirmed the title correction, enlarged text, focused
opacity entry, scrollable settings, and pinned final action at 720x500. Screenshot:
`test_data/export-settings-review/audit-720x500-large-text.png` (ignored local artifact).
The original SURF input and export still match the SHA-256 hashes recorded in
the outline investigation, verified again during this audit.

The Windows computer-use interface found the Tk window but returned no native
accessibility tree; its window capture timed out on retry. The OS screenshot
fallback worked. This proves neither native UIA naming nor screen-reader usability.
Keyboard accessibility is tested; screen-reader compatibility remains unverified.

## 10. Regression risk

Changes avoid boundary-generation algorithms and preserve existing atomic export
behavior. Cache retention is tied to the existing effective settings signature;
automatic split-label changes still invalidate it. The 100-pixel maximum is an
intentional validation bound. GUI paths are exercised with actual workers and
serialized output, not only mocked saves. Independent final read-only reviews
found no additional actionable regressions.

## 11. Remaining verification limits

- The initial Google Earth launch returned `launched app did not expose a targetable window`.
  An alternate interface later exposed the SURF feature tree, but capture timed out
  twice and Raise returned `coordinate input geometry is unavailable`. The
  [outline investigation](export-outline-investigation.md) records prepared
  comparisons and exact remaining steps. No comparison files were imported or
  Places edits performed; stroke-thickness resolution is not claimed.
- No screen reader/native UIA certification; no physical multi-monitor DPI transition
  was performed. Existing native DPI awareness tests and startup-scale matrix are
  distinct evidence.
- Existing Shapely deprecation and Matplotlib/font warnings are outside this patch.

## 12. Readiness

**Ready to commit the implementation and audit fixes, with the verification limits
above explicitly retained.** Before the background-only policy was introduced,
both audit suites passed: 330 broad regression
tests and seven strict native keyboard/scaling tests, plus one intentionally
disabled live-network smoke. No actionable code regression remains from this audit.
Backend behavior, the export workflow, keyboard navigation, and tested startup
sizes/scales are signed off on this runtime. Full screen-reader certification and
Google Earth's specific stroke-rendering outcome are not signed off.

All changes remain uncommitted for user review. Original client files match their
recorded hashes. No generated KMZs, logs, or screenshots are included in the source
diff; local evidence remains in the ignored review directory.

## 13. Background-only GUI testing follow-up

The user requested that future GUI tests never interrupt their desktop or typing.
`AGENTS.md` now makes background execution the standing repository policy.
`tests/__init__.py` installs `tests/gui_test_support.py` before test modules when
using `python -B -m unittest discover -s tests -t . -v`.

The guard keeps Tk roots and child windows withdrawn, including lazy Tk loading,
direct Tcl calls, and Focus Preview state changes. It suppresses native focus and
toplevel raising while preserving ordinary frame stacking. Unmocked dialogs and
popup menus fail immediately through both Python and Tcl entry points. The fresh
DPI subprocess installs the guard and starts without a console window.

Nine guard regressions cover these paths, the default skip behavior of the native
suite, and accidental manual-preview invocation. Guard fixtures initialize DPI
like the app before creating native handles. Hidden Inspector layout checks now
settle Configure events and redraws before measuring text; their assertions remain.
The long-credit layout check runs hidden, while two tests requiring actual window
mapping/native hit-testing and seven native accessibility tests remain opt-in.
No foreground opt-in was enabled for this follow-up.

Hidden checks do not certify native keyboard focus, screen-reader behavior or
desktop hit-testing. Such checks require an explicit request for a foreground
session and must otherwise be reported as not run. The production application's
normal window behavior is unchanged by this test-only policy.

Final verification: **221 tests ran in 216.271 s; 211 passed and 10 skipped**
(nine foreground-only checks and the existing live-network smoke test). The run
covered the guard, all GUI modules, window/DPI behavior, per-side audits, export
edge cases, workflow, and real-worker export integration. Evidence:
`test_data/export-settings-review/background-gui-verified.txt`.
The canonical package-discovery command also passed all nine guard tests in
2.285 s (`background-discovery-tests.txt`). All 34 test modules parsed, and
`git diff --check` passed. No foreground GUI test was run for this follow-up.
