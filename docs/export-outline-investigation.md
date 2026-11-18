# Google Earth outline rendering investigation

Date: November 18, 2026.

## Scope and status

The user reported apparent width changes in a black exported boundary near a rounded corner, compared with red and blue client boundaries. The screenshot establishes a visible difference, but cannot identify its cause or the geometry/style settings in the displayed files.

A concrete export defect was found: polygon exterior coordinates were serialized clockwise. The serializer now normalizes winding for KML compatibility and the new fill controls. It is **not yet proof of a fix for the reported stroke thinning**. Exact Google Earth reproduction remains necessary.

## Direct file inspection

The following existing files were read without modifying them:

- Input: `C:/Users/rbake/Downloads/Surf Park - CEC/input-boundary/SURF Park Topo.kmz`
  - SHA-256: `3FECA01AA32476966555F3D7EEB859F0DD073713C2F02F3382C7D5EDB13949E5`
- Export: `C:/Users/rbake/Downloads/Surf Park - CEC/output-boundary/SURF Park -50ft Buffer.kmz`
  - SHA-256: `5BEA4F099DF56A59784C9D477850C2E8967BAA4496ED9FA0D01ECC02F4563D61`

| Property | Existing client input | Existing app export |
| --- | --- | --- |
| Geometry | One closed LineString | One Polygon, one exterior LinearRing |
| Vertices including closure | 17 | 32 |
| Line width | 2 pixels | 5 pixels |
| Line color stored in file | Blue (`ffff0000`) | Red (`ff2827d6`) |
| Altitude mode | Omitted, default ground clamp | Explicit `clampToGround` |
| Coordinate altitude | All zero | All zero |
| Winding | Clockwise closed line | Clockwise polygon exterior |
| Consecutive repeated vertices | None | None |
| Geodesic segment length range | 26.384–1096.667 m | 7.047–1081.198 m |
| StyleMap | Present; normal/highlight widths both 2 | Absent |

The user directly confirmed that `SURF Park -50ft Buffer.kmz` is the exported boundary shown in the screenshot. The saved export is red, whereas the displayed boundary is black; its displayed style therefore differs from the saved style. The comparison artifacts use black, 5-pixel outlines to match the reported appearance. The other red client KML has not been identified. A scoped read-only search of Google Earth's saved `myplaces.kml` and profile KML files found no `SURF Park` or `JPG Camera Boundary` feature names. The saved Places file predates today's import/export; it does not establish the current Temporary Places contents.

The four existing polygons in `outputs/Valero Sample Data.kmz` also have clockwise exteriors and valid geometry without consecutive duplicate vertices. This older file uses line width 6 and no explicit altitude mode. It is corroborating winding evidence, not the reported screenshot case.

## Export-code findings

Before this change, `_polygon_to_kml_coords` copied exterior coordinates directly from Shapely, including their winding. Constructive buffers commonly produced clockwise exteriors in the inspected results. `_style_polygon` supplied a single line width for each polygon, disabled fill, enabled outline, and set ground clamp. There were no per-segment styles, separate duplicate outline LineStrings, `gx:physicalWidth`, or `gx:outerWidth` in the inspected current export.

Sources: [export implementation](../src/jpg_boundary_kmz_core.py), [geometry processing](../src/geometry_hardening.py), [existing serialization tests](../tests/test_kmz_export_contract.py).

Google's reference requires counterclockwise polygon coordinates for the intended front face and fill. It defines ordinary line width in pixels. It also states that Polygon ignores `tessellate`: ground clamping already supplies terrain following. A standalone LineString/LinearRing and a Polygon can follow different surface paths. These facts make a same-style, same-geometry comparison necessary. [Google KML reference](https://developers.google.com/kml/documentation/kmlreference#polygon), [LineStyle](https://developers.google.com/kml/documentation/kmlreference#linestyle), [LinearRing](https://developers.google.com/kml/documentation/kmlreference#linearring).

## Supported correction and boundaries

The serializer normalizes the exterior to counterclockwise **only when serializing KML**, preserving all vertex positions, the closed ring, the polygon footprint, and the in-memory generation result. Regression tests cover both starting windings and verify identical geometry after serialization. This is an export compatibility correction, not a change to buffer distances or section algorithms.

`python -B -m unittest tests.test_export_style tests.test_kmz_export_contract -v` passed all 9 tests. The checks cover actual KMZ XML, clamping, style modes and opacity, single/split/collection naming, description removal, retained external summaries, and unchanged counterclockwise output geometry. These file-level results do not establish the Google Earth visual outcome.

Do not add Polygon tessellation flags as a proposed cure. Do not raise the polygon above terrain, add a second outline geometry, densify every simplified edge, or alter buffer/simplification tolerances solely from this screenshot. None of those changes is supported by the current reproduction evidence.

## Prepared comparison artifacts

An ignored local A/B set is available under `test_data/outline-rendering-review/`:

- `surf_outline_clockwise.kmz`: existing clockwise exterior.
- `surf_outline_counterclockwise.kmz`: identical coordinates with reversed winding.
- `surf_outline_linestring.kmz`: the same closed coordinates as a standalone ground-clamped LineString with `tessellate=1`, to isolate geometry rendering.
- `comparison.json`: serialization checks and source path for the winding pair.

All three copies use black, opaque, 5-pixel outlines with ground clamp; the polygon pair has fill disabled. Labels distinguish the variants. Each retains 32 coordinates, is valid, and has exactly the same footprint as the inspected source; the measured Hausdorff distance is zero. Original files were not changed. The copies were prepared before native Google Earth verification; the original user files remain unchanged.

## Native verification attempt

The computer-use runtime initialized, but did not expose a targetable Google Earth window. Its app inventory reported no open Earth windows, while read-only process inspection confirmed the existing `googleearth.exe` process remained running. Two supported launch attempts (installed app identifier, then explicit installed executable) each failed with `accessibility window-opened handler did not become ready`. No clicks, keystrokes, imports, view changes, or Places edits were performed. Native visual verification requires Google Earth to be visibly open and targetable before continuing; no conclusion about the stroke-rendering result can be drawn from this automation failure.

## Google Earth verification procedure

1. Use the user-confirmed SURF export above and the available blue client input. Inspect the black feature as currently displayed and identify the remaining red client file if needed. Preserve their originals; Google Earth can copy a feature as KML if its displayed edits have not been saved.
2. Load one comparison feature at a time. Set the same opaque line color and pixel width, outline-only mode, and ground clamp. Use a saved identical camera position and an unselected feature so highlight styling does not interfere.
3. Compare the unmodified exported polygon against a copy differing only in exterior winding. Examine the rounded bend and both adjacent straight runs at several zoom levels, first top-down and then at the reported tilt.
4. Separately compare the same closed coordinate sequence as a Polygon and as a LineString. This isolates geometry rendering from differences in client/app coordinates and vertex counts.
5. Record Google Earth version, graphics settings, terrain state, view position/tilt, line width, and screenshots. Toggle terrain only as a diagnostic comparison and restore the original setting afterward.
6. Confirm the selected fill/outline mode and opacity after Task 5, including fill-only and combined modes, without changing the geometry.

Acceptance for the reported oddity requires a repeatable before/after improvement in Google Earth at matched settings. File-level tests alone cannot establish visual consistency across camera angles and graphics drivers.
