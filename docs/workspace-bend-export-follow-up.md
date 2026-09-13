# Import, layout, crop junction, and KMZ export follow-up

Date: September 12, 2026.
Status: complete. All four requested changes are implemented and verified.

## Import recovery

Added a persistent **New input** button and a matching Input-menu command.
They clear the current input, preview/cache, saved-output link, and error state,
and invalidate pending request identities. Reset is disabled during active work.
After a failed import with no displayed result, the browse/drop card appears
again. Failed updates to an existing preview keep the displayed geometry.

The reported file contained multiple polygon placemarks; that remains an
unsupported input type. The correction restores navigation and import controls.
The app accepts one polygon, source polylines, or JPG folders as before.

## Responsive layout

The brand header is one row with reduced padding. Wide windows place footer
status, quick fields, actions, and the saved-folder button on one row. Medium
and small widths use measured control sizes to wrap. Duplicate filename rows
are removed; the saved status and Output settings still show the destination.
The compact import card also fits the 720 x 500 layout.
At exceptionally short map heights, the card hides its heading while keeping
the drop target and both browse buttons visible. This also covers a wrapped
saved-folder row consuming additional space.

Measured at the current 125% Windows text scaling:

| Client size | Header | Footer | Map height |
| --- | ---: | ---: | ---: |
| 2500 x 1000 | 106 px | 45 px | 759 px |
| 1280 x 720 | 106 px | 84 px | 440 px |
| 800 x 600, side controls | 151 px | 125 px | 234 px |
| 720 x 500, import | 151 px | 125 px | 134 px |

## Clean crop junctions

Reproduced the diagonal green/blue junction in the supplied six-shape KMZ and
compared it directly with the hand-edited example. The previous cut-length test
allowed an oblique seam to end beside a concave bend, making a long pointed crop.

Both Auto splitters now require a cut to cross the local boundary at at least
60 degrees. A short local boundary arc supplies a stable tangent independent of
dense rounded-buffer vertices. This complements the existing short-cut test.
Exact-size and relaxed-size candidates use the same quality checks.

Auto first seeks sections within 20% of the original mean area. If that cannot
produce clean cuts, a separately bounded search permits up to 35%. This matches
the requested larger/smaller crop tradeoff: the hand-edited blue polygon was
roughly 32% above the mean exported area. The supplied customer case still fits
within 20% after repositioning the neighboring cuts. Buffer distances and the
parent footprint are unchanged. Explicit split directions retain their behavior.

The corrected six-shape export uses 310 ft buffer and 50 ft overlap, with a
maximum base-area variation of **19.3623%**. The green crop decreases from about
59.8 to **45.5 acres**, and blue increases from about 59.9 to **66.9 acres**
(exported areas include overlap). All six polygons are valid and cover the source
linework. The comparison uses actual saved polygon coordinates, with colors
matched by location rather than the hand-edited file's styles.

## Export style and coordinates

All KMZ polygons use `PolyStyle/fill=0`, `outline=1`, the existing alternating
opaque line colors, `LineStyle/width=5`, and `altitudeMode=clampToGround`.
The polygon geometry remains usable for cropping. Google's KML reference defines
line width in **pixels**, so 5 is the requested Google Earth width setting.

The existing projected-to-WGS84 transformation remains in place. Export now
rejects invalid or empty polygons, holes, nonfinite coordinates, and coordinates
outside longitude/latitude ranges. Descriptions distinguish internal projected
CRS from export CRS **WGS84 / EPSG:4326**. No new export formats are introduced.

Tests serialize single and split KMZs in both northern and southern hemispheres,
check styles and coordinate order, and reproject serialized coordinates to the
internal CRS with less than 0.00001 m discrepancy. These are file/geometry checks;
Google Earth, Metashape, and ArcGIS were not launched for native import testing.

## Verification and remaining limits

- New GUI/export contract checks: six tests passed, covering actual failed
  multi-polygon import, reset after success, busy state, layout wrapping,
  outline styles, and CRS round trips.
- A portable six-section regression checks for material pointed ends with zero
  and 50 ft overlap. Existing width/coverage regressions remain in place; their
  area assertions reflect the newly authorized bounded 35% fallback.
- Eight actual-input cases passed: 310 ft with 1/4/6/8/12 shapes, six shapes with
  zero overlap, 50 ft with six shapes, and 350/150 ft per-side with six shapes.
  Union error was below `1e-8` relative to the parent, source linework remained
  covered, and requested positive buffers were preserved.
- Final suite: `python -B -m unittest discover -s tests -v` ran 282 tests in
  440.472 seconds: **281 passed, one optional live Esri smoke test skipped,
  zero failures**. `git diff --check` passed.
- Desktop captures were reviewed at 2500 x 1000, 1280 x 720, and 720 x 500;
  the wide footer occupies one row, and small-window import controls remain
  visible. Automated layout checks also cover per-side fields and large text.

The audit caught a misleading zero-overlap export assertion: tiny projection
round-off changed whether the union contained internal seam boundaries. Each
serialized crop actually differed by less than `2e-9` m, and the union's area
difference was zero at GEOS precision. The regression now verifies each crop's
boundary and the complete covered area, instead of comparing unstable internal
boundaries from two separate union operations. Export precision was preserved.

The geometry tests are heuristics for sensible crop shapes, not a guarantee of
one universally preferred partition. Very small rounding intersections at
overlap edges can remain. Search is bounded, but the 50 ft / six-shape customer
case took **129.5 seconds**; the normal 310 ft / six-shape case took about ten
seconds. Work remains asynchronous in the GUI. Improving search speed for narrow
branched networks and optional operator-placed cuts are useful future work.

Private KMZs, comparison image, JSON measurements, and validation logs are kept
under ignored `test_data/workspace-bend-review/`. Supplied source/example files
were not overwritten. No known functional blocker remains for the supplied cases.

Review artifacts:

- [Corrected six-shape KMZ](../test_data/workspace-bend-review/C52%20+%20C53-2_310ft_6-shapes_corrected.kmz)
- [Reported / hand-edited / corrected comparison](../test_data/workspace-bend-review/six-shape-comparison.png)
- [Full test log](../test_data/workspace-bend-review/full-suite.log)
- [Actual-input checks](../test_data/workspace-bend-review/customer-validation.json)
- [Serialized export checks](../test_data/workspace-bend-review/export-validation.json)

## References

- [GUI implementation](../src/jpg_boundary_kmz_gui.py)
- [Cut angle and width safeguards](../src/section_quality.py)
- [Sectioning and export](../src/jpg_boundary_kmz_core.py)
- [GUI recovery/layout tests](../tests/test_workspace_followup.py)
- [KMZ style/CRS tests](../tests/test_kmz_export_contract.py)
- [Google KML LineStyle reference](https://developers.google.com/kml/documentation/kmlreference#linestyle)
- [Google KML PolyStyle reference](https://developers.google.com/kml/documentation/kmlreference#polystyle)
