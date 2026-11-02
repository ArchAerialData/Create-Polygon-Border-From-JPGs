# Esri World Imagery Basemap and Dynamic Mileage Scale Bar Implementation Plan

Plan date: 2026-07-24

Repository: `Create-Polygon-Border-From-JPGs`

Audited branch and commit: `Testing-New-Methods` at
`2a74a4c94b078f9fc4335348ea26601928ea79cf`

Audited implementation baseline: the current uncommitted GUI revamp working tree,
identified by the hashes in Section 2.10

Plan scope: GUI-only online basemap rendering, mileage scale-bar rendering, preview
legibility, and related GUI lifecycle/quality-of-life behavior

Required planning guide:
`agent_prompt_templates/extremely-detailed-planning/detailed-planning-requirements.md`

Revision audited on 2026-07-24: `World Imagery` can be disabled at any time to
restore the exact existing themed preview background while retaining the dynamic
mileage scale. This revision changes no production code or implementation
allow-list.

## 1. Executive summary

### 1.1 Outcome

Yes, the supplied Esri service can be used as the preview basemap, and an accurate
scale bar can be added without changing boundary generation, sectioning, KML/KMZ
input interpretation, KMZ output, or any other processing result.

The implementation will:

- Keep the current Tkinter/ttk and Matplotlib TkAgg desktop GUI.
- Keep every boundary, camera point, source outline, final outline, and section
  in the preview's current projected coordinate reference system.
- Keep `axes.set_aspect("equal", adjustable="datalim")`, so the same projected
  distance occupies the same screen distance horizontally and vertically.
- Fetch the supplied WGS84 Geographic Version 2 JPEG tiles on a GUI-only
  background worker.
- Stitch the required tiles in memory and reproject the tile mosaic, per output
  pixel, into the result's existing projected preview coordinate system.
- Display that reprojected image below the current vector artists.
- Retain the original basic dark preview as a first-class `Original Background`
  mode, not only a failure fallback. Unchecking `World Imagery` immediately removes
  basemap imagery/attribution and restores the original `#0f0f0f` figure/axes
  background while the dynamic mileage scale, vectors, navigation, Update, and
  Export remain active.
- Add a compact `World Imagery` toggle to the existing preview toolbar area. It is
  enabled by default, shared across the main preview and Preview Inspector, and
  changes no processing or export option.
- Add a geodesically calibrated scale bar to both preview surfaces. The bar updates
  after initial fit, wheel zoom, direct drag pan, Matplotlib toolbar navigation,
  focus-mode resize, Inspector resize, and result redraw.
- Express the scale in statute miles, use a readable `1 / 2 / 5 x 10^n` distance,
  and display no more than two decimal places while removing trailing zeros.
- Display mandatory Esri and data-provider attribution whenever Esri imagery is
  visible, including in images saved with the Matplotlib toolbar.
- Use no persistent tile cache and never add imagery to the exported KMZ.
- Add no new runtime dependency. Existing `matplotlib`, `numpy`, `pyproj`, and
  `scipy` dependencies provide JPEG decoding, coordinate transformation, numeric
  arrays, and bilinear sampling.

The supplied endpoint is publicly accessible without a token as verified on
2026-07-24, but it must not be described as unrestricted, open, or simply "free."
It is proprietary Esri content subject to Esri terms and attribution requirements.
This plan therefore describes it as a public, currently unauthenticated online
basemap service and limits the implementation to live display with bounded,
session-only memory.

### 1.2 Chosen architecture

The preview axes remain in `BoundaryResult.metadata.epsg`, which is the same display
CRS used today. Only the basemap raster is transformed.

```text
Supplied ArcGIS tile service (EPSG:4326 JPEG tiles)
                            |
                            v
              fixed-schema metadata validation
                            |
                            v
        tile selection -> HTTPS fetch -> memory-only LRU
                            |
                            v
                 native WGS84 tile mosaic
                            |
                            v
        inverse-map projected output pixels to WGS84
           with pyproj; bilinear sample with SciPy
                            |
                            v
           projected RGBA frame for the current view
                            |
                            v
   Matplotlib image (back) + current vectors + scale/attribution

BoundaryResult ----------> current projected vector drawing
      |
      +------------------> display EPSG for raster warp and scale bar

generate_boundary_from_input / save_kmz / export payloads: untouched
```

This is intentionally not the shortest implementation. Drawing native WGS84 tiles
and converting all vectors to longitude/latitude would avoid raster reprojection,
but it would also replace the current projected preview coordinate contract.
Longitude and latitude degrees do not represent equal ground distances; a
center-latitude aspect correction is only locally approximate. That alternative
would change bounds, aspect, display shape, antimeridian behavior, and existing
equal-scale tests even when imagery is disabled.

Keeping the projected axes:

- preserves the exact geometry currently drawn;
- preserves existing fit and navigation semantics;
- preserves the same view when imagery is toggled or fails;
- preserves equal projected map scale;
- makes the basemap an additive presentation layer;
- contains provider-specific complexity in a new GUI support module.

The raster warp must be a real inverse, per-pixel reprojection with bilinear
sampling. Transforming only tile corners and stretching each tile as a projected
rectangle is explicitly prohibited because it can misregister imagery.

### 1.3 User-visible end state

The application remains the same single-page, preview-first GUI. It gains no
sidebar, page, tab set, wizard, or page-level scrollbar.

```text
+--------------------------------------------------------------------------+
| JPG Boundary to KMZ  Input: ... [Change] [Key] [Settings] [Focus] [...] |
+--------------------------------------------------------------------------+
| [Matplotlib navigation tools]       [x World Imagery] [imagery status]   |
+--------------------------------------------------------------------------+
|                                                                          |
|                 ESRI WORLD IMAGERY, WHEN AVAILABLE                       |
|                                                                          |
|               existing camera/source/boundary/section vectors            |
|                                                                          |
|  [ 2.5 mi ]                                                              |
|  Powered by Esri | Source: Esri, Vantor, Earthstar Geographics, ...      |
+--------------------------------------------------------------------------+
| Preview current  Buffer [0] Shapes [4] Overlap [50]  [...] [Update] [...]|
+--------------------------------------------------------------------------+
```

Workflow:

1. Input selection remains drag/drop or either browse action.
2. `Update Preview` still generates the same `BoundaryResult`.
3. The vector preview appears immediately on the existing dark surface.
4. If `World Imagery` is enabled, the GUI requests only the tiles needed for the
   visible view on a separate worker.
5. When a matching response arrives, imagery appears behind the vectors without
   changing the axes limits or toolbar history.
6. The scale bar appears as soon as a valid result CRS and view exist; it does not
   depend on network access.
7. Pan and zoom update the scale bar immediately and schedule a debounced imagery
   refresh. The old correctly georeferenced imagery remains in its covered region
   while a same-result replacement loads.
8. Unchecking `World Imagery` enters `Original Background` mode on both preview
   surfaces: no imagery or Esri attribution remains, no new basemap request or
   HTTP attempt is authorized after the disabled state commits, the original dark
   background is visible, and the scale continues updating. At most one attempt
   already reserved or in flight per active worker slot (two total) may later
   enter/return only to be discarded.
9. Rechecking `World Imagery` leaves the boundary result untouched and requests
   imagery for each active view through the normal debounce.
10. An imagery failure leaves vectors, scale, controls, preview generation, and
   KMZ export operational. It produces a compact nonmodal status, not a dialog.
11. The Preview Inspector uses the same shared tile cache but has its own view,
   request token, image artist, scale bar, and status.
12. `Export KMZ` remains a vector-only export through the existing code path.

### 1.4 Non-negotiable protected contract

The following must remain semantically unchanged:

1. `generate_boundary_from_input(...)` is called with the same arguments and
   generation profiles as the implementation baseline.
2. `save_kmz(...)` remains the only KMZ write path.
3. `BoundaryResult`, `BoundaryMetadata`, and `BoundarySection` remain unchanged.
4. Preview generation uses `GENERATION_PROFILE_PREVIEW`.
5. Export generation uses `GENERATION_PROFILE_EXPORT`.
6. Export reuses a cached result only under the current complete settings-key
   contract.
7. Folder, KML, and KMZ inputs retain current parsing, validation, drag/drop,
   browse, and typed-path behavior.
8. Buffer, outline mode, vector simplification, section count, overlap, label,
   split direction, output name, and output path retain current semantics.
9. The existing processing queue and its `scan_done`, `export_done`, and `error`
   payloads remain unchanged.
10. Basemap work never sets the application's processing busy state.
11. Basemap work never invalidates or changes the boundary result cache.
12. A basemap error never enters the boundary-generation error path and never
    opens a modal dialog.
13. Raw or composite imagery is never embedded in a KMZ.
14. No core, input, geometry, sectioning, or output module may be modified.
15. The four existing direct preview interaction callbacks per canvas remain
    registered and keep their current behavior.
16. The main and Inspector previews retain independent view limits.
17. Focus Preview continues to reuse the main canvas rather than creating a third
    rendering surface.

### 1.5 Fixed implementation decisions

These decisions are resolved requirements, not open questions.

| ID | Decision | Reason |
| --- | --- | --- |
| FD-01 | Keep projected preview axes and reproject only the raster. | Preserves existing preview behavior and the user's no-functional-regression boundary. |
| FD-02 | Use the supplied URL exactly as a fixed HTTPS service root. | Prevents arbitrary URL fetching and uses the requested WGS84 service. |
| FD-03 | Validate service metadata before requesting tiles. | Prevents silent geographic misplacement if the service schema changes. |
| FD-04 | Support only the verified EPSG:4326, 256 x 256 JPEG, top-left-origin, LOD-based schema in this scope. | Makes tile math explicit and fail-safe. |
| FD-05 | Use `/tile/{level}/{row}/{column}` only. Do not use `/export`, `exportTiles`, or `tilemap`. | The service is `TilesOnly`, `/export` returned 404, and offline tile export is disallowed. |
| FD-06 | Keep imagery enabled by default with one shared session toggle visible on main and Inspector toolbars. | Satisfies the requested replacement while retaining immediate user control and an offline mode. |
| FD-07 | Retain a dark fallback beneath vectors at all times. | Network imagery must be optional and nonblocking. |
| FD-08 | Use at most two lazy daemon workers: one dedicated to the main surface and one to the current Inspector surface, each with latest-only pending work and a shared cache/metadata state. | Prevents either surface from starving the other while keeping concurrency and request buildup bounded. |
| FD-09 | Share decoded tiles in a bounded in-memory LRU; clear it on actual input change, imagery disable, and shutdown; do not write any tile or metadata cache to disk. | Supports responsive navigation while bounding the lifetime of provider data and respecting the online-only service contract. |
| FD-10 | Cap each view at 24 tiles, 1,500,000 warped output pixels, and 1,600 pixels on either output dimension. | Bounds network, CPU, and memory use. |
| FD-11 | Cap decoded tile cache state at 128 tiles and 32 MiB, evicting least-recently used entries when either limit is reached. | Provides a deterministic memory ceiling for two canvases. |
| FD-12 | Debounce view refreshes by 300 ms. | Prevents a tile job for every drag frame or wheel event. |
| FD-13 | Use a 4-second request timeout and at most one retry for transient failures. | Keeps a failed provider from monopolizing the worker. |
| FD-14 | Use `matplotlib.image.imread` for JPEG decoding and `scipy.ndimage.map_coordinates(order=1)` for inverse bilinear sampling. | Reuses installed public APIs and adds no dependency. |
| FD-15 | Render the basemap with negative z-order, vectors above it, and scale/attribution at the highest overlay z-order. | Makes layer ordering deterministic. |
| FD-16 | Add a restrained outline/halo to preview lines and points. | Maintains legibility over bright and dark aerial imagery without changing geometry. |
| FD-17 | Compute scale distance geodesically from actual axes endpoints through the display CRS; never divide projected x span by 1,609.344. | Handles projection scale variation and does not assume projected units are exact ground metres. |
| FD-18 | Select the largest `1 / 2 / 5 x 10^n` mileage not exceeding 25% of axes width. | Produces familiar, stable labels of useful visual size. |
| FD-19 | Use a minimum exact label of `0.01 mi`; hide the bar when that value cannot fit truthfully. | Avoids a misleading `0.00 mi` label. |
| FD-20 | Format labels with at most two decimal places and strip trailing zeros. | Meets the user request and yields `10 mi`, `2.5 mi`, and `0.25 mi`. |
| FD-21 | Keep the scale bar visible on the dark fallback and while imagery loads or fails. | Scale depends on view/CRS, not the provider. |
| FD-22 | Display `Powered by Esri` and live service `copyrightText` whenever any valid imagery is visible. | Meets Esri and source-provider attribution requirements. |
| FD-23 | Put attribution inside the Matplotlib figure and keep it in the unobstructed left portion of the main axes when a right-side GUI overlay is open. | Keeps attribution visible on screen and in toolbar-saved preview images. |
| FD-24 | Do not persist the basemap toggle in a new config file. | Avoids expanding configuration scope for one session-only view choice. |
| FD-25 | Default automated tests perform no live network access. | Keeps the suite deterministic and offline-capable. |
| FD-26 | Provide a separately skipped, environment-gated live service smoke test. | Allows explicit provider verification without making CI depend on Esri. |
| FD-27 | Use a separate basemap response queue and surface state; do not add basemap payloads to the processing queue. | Protects current worker and queue contracts. |
| FD-28 | Preserve the current image while a same-result replacement view loads, but discard it immediately on input/result CRS change or imagery disable. | Avoids flashes while preventing stale cross-input imagery. |
| FD-29 | Treat transient metadata acquisition/parse failures with a 30-second cooldown, but latch authentication/body-policy/well-formed schema incompatibility until app restart; off/on clears only the transient cooldown. | Prevents repeated incompatible placement attempts while allowing deliberate retry after a transient outage. |
| FD-30 | Advance an atomic transient-cache epoch on input change, imagery disable, and shutdown; canceled jobs may not insert after that epoch changes. | Makes the memory-cache clearing promise race-safe. |
| FD-31 | Define unchecked `World Imagery` as `Original Background` mode: restore the existing `PALETTE.BACKGROUND_DEEP` (`#0f0f0f`) figure/axes styling, remove basemap and attribution, authorize no new imagery submission or HTTP-attempt reservation after the disabled state commits, but retain and refresh the geodesic scale and every vector/navigation/action control. At most one attempt already reserved or in flight per active worker slot (two total) may later enter/return; cancellation/epoch checks then prohibit retry, next-tile fetch, metadata/cache commit, response publication, or artist application. | Makes the requested reversible basic-background view explicit while stating the technically honest two-worker in-flight boundary. |

### 1.6 Definition of done

Implementation is complete only when all of the following are true:

- A valid online request shows geographically aligned imagery beneath the current
  projected preview in main, focus, and Inspector modes.
- Unchecking `World Imagery` on either toolbar immediately places both surfaces in
  the original `#0f0f0f` background mode; pan/zoom/resize still refresh the scale,
  no attribution remains, and no new request/attempt reservation is authorized
  until re-enabled.
- Toggling imagery never changes vector positions, limits, aspect, result state,
  cache keys, or output.
- The scale bar back-measures to its displayed geodesic distance within the numeric
  tolerance in Section 9.
- Scale labels never exceed two decimal places.
- Wheel, direct pan, toolbar Home/Back/Forward/Pan/Zoom, result redraw, resize,
  focus, and Inspector interactions update the correct surface.
- Attribution is present whenever imagery is visible and is included in a
  toolbar-saved preview image.
- No default test opens a network connection.
- Offline, HTTP, schema, decode, projection, and shutdown failures remain nonfatal.
- All baseline and new automated tests pass.
- The final diff contains only files in Section 7.
- Protected core and GUI methods pass the final scope/AST checks.

## 2. Current repository and service findings

### 2.1 Application structure

| Finding | Direct evidence | Status |
| --- | --- | --- |
| The GUI is one Tkinter controller with Matplotlib canvases. | `src/jpg_boundary_kmz_gui.py:89`, `BoundaryKmzApp`; preview creation at `:297-336` | Verified |
| The primary canvas and navigation toolbar already occupy a dedicated preview toolbar and preview stack. | `_build_preview_workspace`, `:297-336` | Verified |
| Settings and Key are temporary overlays, not permanent sidebars. | `_build_settings_drawer`, `:395-472`; `_toggle_settings_drawer`, `:927-962`; `_toggle_preview_key`, `:964-971` | Verified |
| The bottom action bar remains outside the preview. | `_build_action_bar`, `:748-899` | Verified |
| Focus mode reuses the primary window/canvas. | `_toggle_focus_mode`, `:1241-1321` | Verified |
| Inspector is a second `Toplevel`, Figure, axes, canvas, toolbar, and independent interaction registration. | `_open_fullscreen_preview`, `:2739-2937` | Verified |
| No web view, ArcGIS SDK, HTTP client library, map library, app configuration system, database, schema, migration, API server, or packaging build exists. | Repository inventory and targeted `rg` searches | Verified absence |
| Both launchers only start the existing Python GUI. | `run_jpg_boundary_gui.py`; `run_jpg_boundary_gui.bat` | Verified |

No launcher, backend service, schema, migration, database, API route, or external
message payload needs to change. The integration surfaces are limited to the Tk
event loop, Matplotlib canvases, the new two-slot GUI-only basemap client, and the
existing result objects already passed to the draw path.

### 2.2 Current preview rendering contract

`BoundaryKmzApp._draw_preview_on_axes` at
`src/jpg_boundary_kmz_gui.py:2476-2562` currently:

1. Clears and restyles the axes.
2. Draws `result.projected_points` for JPG inputs.
3. Draws `result.base_polygon_projected` for vector inputs.
4. Draws `result.final_polygon_projected`.
5. Draws every `section.polygon_projected`.
6. Fits projected result bounds through `_fit_preview_axes_to_result`.
7. Sets equal aspect with `adjustable="datalim"`.
8. Hides axes and coordinate text.
9. Uses the full figure area.
10. Schedules a canvas draw.

The fit path at `:2632-2678` combines projected base/final/section bounds and
projected point minima/maxima. This is a presentation contract worth preserving.

The original basic background is directly verified:

- `src/jpg_boundary_gui_theme.py:31-32` defines
  `PALETTE.BACKGROUND_DEEP == "#0f0f0f"`;
- `style_matplotlib_figure` and `style_matplotlib_axes` apply that token to the
  Figure and axes at `src/jpg_boundary_gui_theme.py:114-139`;
- `GuiInputTests.test_dark_theme_survives_empty_and_result_redraw` at
  `tests/test_gui_input.py:886-899` asserts both facecolors remain that token after
  result/empty/result redraw.

`Original Background` mode therefore means restoring/reusing this exact existing
theme path with no `AxesImage` or imagery attribution. It does not introduce a new
background color, renderer, theme token, or edit to
`src/jpg_boundary_gui_theme.py`.

The current README explicitly describes the preview as schematic and without an
imagery basemap at `README_JPG_BOUNDARY_KMZ.md:165-166`; that documentation must be
updated after implementation.

### 2.3 Available CRS data

The core already returns everything the GUI needs:

- `BoundaryMetadata.epsg` and `crs_name`:
  `src/jpg_boundary_kmz_core.py:82-89`.
- `BoundarySection.polygon_projected` and `polygon_wgs84`:
  `:147-153`.
- `BoundaryResult.projected_points`, projected polygons, and final WGS84 polygon:
  `:157-164`.

Folder and polygon inputs choose a WGS84 UTM CRS and create forward/reverse
transformers at `src/jpg_boundary_kmz_core.py:230-238` and `:489-500`. The
polyline path also preserves its projected CRS in metadata at `:647-714`.

The basemap and scale-bar code will consume `metadata.epsg` but will not modify,
replace, or append to these dataclasses.

### 2.4 Existing view interactions

`_register_preview_canvas_interactions` at
`src/jpg_boundary_kmz_gui.py:1473-1506` registers exactly four Matplotlib events
for each canvas:

- scroll;
- button press;
- mouse motion;
- button release.

Wheel zoom updates limits and calls `draw_idle` at `:1511-1548`. Direct pan updates
limits and calls `draw_idle` at `:1601-1637`. The same callback helper is used by
the Inspector at `:2923-2927`.

Tests currently assert four direct interaction callback IDs for the main canvas
and Inspector at `tests/test_gui_input.py:923-926` and `:1046-1062`. New basemap
and scale observers must therefore have their own `_PreviewMapSurface` callback
registries. They must not be appended to `_preview_event_cids` or
`_fullscreen_event_cids`.

Canvas `draw_event` and `resize_event` are the common provider-independent seams
for:

- direct wheel and pan redraws;
- Matplotlib toolbar Home, Back, Forward, Pan, Zoom, and subplot-driven redraws;
- focus-mode resize;
- Inspector resize;
- new result drawing.

The planned GUI surface observer must use at most one guarded follow-up
`draw_idle` after a draw event creates or moves scale artists. Its view signature
and redraw guard will prevent a draw loop; this is not current baseline behavior.

### 2.5 Existing result and worker lifecycle

The processing worker boundary is:

- processing queue: `src/jpg_boundary_kmz_gui.py:115`;
- preview worker creation: `:2076-2102`;
- export worker creation: `:2146-2162`;
- worker functions: `:2164-2221`;
- main-thread queue drain: `:2223-2297`;
- busy-state management: `:3218-3270`.

Those workers are daemon threads. `_drain_queue` is scheduled every 100 ms at
`:203` and reschedules itself at `:2297`.

The new imagery path must not reuse `_queue`, `_drain_queue`, `_set_busy`, or any
processing thread. It needs:

- a separate latest-only request path;
- a separate bounded response queue;
- separate nonmodal surface statuses;
- a shutdown flag;
- no call to core generation or export functions.

### 2.6 Empty, input-change, and Inspector lifecycle

- `_on_input_changed` invalidates the current boundary cache and clears the
  preview when the selected input text changes at `:1927-1935`.
- `_draw_empty_preview_on_axes` clears axes and redraws the dark empty state at
  `:2716-2737`.
- `_draw_preview` updates the main surface and then the Inspector at `:2466-2474`.
- `_draw_fullscreen_preview` uses the same shared draw function at `:3060-3087`.
- `_close_fullscreen_preview` disconnects current interaction callbacks and clears
  references at `:3129-3165`.

Basemap surface tokens must be invalidated in each of these transitions so a late
response cannot repaint an empty surface, a new input, a new result CRS, or a
destroyed Inspector.

### 2.7 Existing dependencies

`requirements_jpg_boundary_kmz.txt` contains:

```text
exifread
matplotlib
numpy
pyproj
scipy
shapely>=2.0
simplekml
tkinterdnd2
```

The audited runtime is:

```text
Python      3.13.3
Matplotlib  3.10.3
NumPy       2.2.6
pyproj      3.7.1
Shapely     2.0.7
```

The planned implementation uses:

- standard-library `urllib.request`, `json`, `queue`, `threading`, `time`,
  `dataclasses`, and `collections.OrderedDict`;
- `matplotlib.image.imread` and Matplotlib artist APIs;
- NumPy vectorized grids and arrays;
- `pyproj.CRS`, `Transformer`, and `Geod`;
- `scipy.ndimage.map_coordinates`.

No requirement or launcher change is authorized.

### 2.8 Verified Esri service contract

Supplied service:

`https://wi.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer`

Live metadata:

`https://wi.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer?f=pjson`

Official ArcGIS item:

`https://www.arcgis.com/home/item.html?id=898f58f2ee824b3c97bae0698563a4b3`

The service and item were queried directly on 2026-07-24.

| Property | Verified value |
| --- | --- |
| Item owner/access | `esri`; `public`; `public_authoritative` |
| Item title | `World Imagery (WGS84)` |
| Service version | `10.91` |
| Cache | `singleFusedMapCache: true` |
| Capabilities | `Map, Tilemap, TilesOnly` |
| Service CRS | EPSG:4326 |
| Tile CRS | EPSG:4326 |
| Units | decimal degrees |
| Tile dimensions | 256 x 256 |
| Tile format | JPEG |
| DPI | 96 |
| Origin | `(-180, 90)` |
| Levels | 0 through 22 |
| Level-0 resolution | `0.703125` degrees/pixel |
| Resolution rule | `0.703125 / 2^level` degrees/pixel |
| Level-0 tile span | 180 degrees |
| Tile span rule | `180 / 2^level` degrees |
| Matrix dimensions | `2^(level+1)` columns by `2^level` rows |
| Tile URL order | `/tile/{level}/{row}/{column}` |
| Offline export | `exportTilesAllowed: false` |
| Copyright text | `Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community` |

Direct probes on 2026-07-24:

```text
/tile/15/8283/16493 -> HTTP 200, image/jpeg, 11,035 bytes
/tile/23/0/0        -> HTTP 400
/export?f=json      -> HTTP 404
```

The official [ArcGIS Map Tile resource documentation](https://developers.arcgis.com/rest/services-reference/enterprise/map-tile/)
defines the `level/row/column` route. Esri also identifies this exact URL as the
WGS84 replacement endpoint in its
[raster basemap retirement guidance](https://support.esri.com/en-us/knowledge-base/deprecation-imagery-world-2d-and-streetmap-world-2d-bas-000027382).

The implementation must not assume an ArcGIS Web Mercator/XYZ scheme. This service
is WGS84 Geographic Version 2, and its route uses row before column.

### 2.9 Licensing, attribution, and privacy boundary

The item metadata says the layer is licensed under the Esri Master License
Agreement and is not intended for exporting tiles offline. The service reports
`exportTilesAllowed: false`.

Applicable primary references include the
[Esri Master Agreement](https://assets.esri.com/content/dam/esrisites/en-us/media/legal/ma-full/ma-full.pdf)
and Esri's
[Data Attributions and Terms of Use](https://www.esri.com/en-us/legal/terms/data-attributions).
The official
[ArcGIS.com terms of use](https://www.arcgis.com/home/termsofuse.html)
Section 3.2(b) permits attributed hard-copy or static electronic representations
of data, including image formats. That directly supports retaining the existing
toolbar Save capability only when the saved composite contains Esri and provider
attribution. It does not authorize raw-tile export or a persistent tile cache.

Esri's
[attribution requirements](https://developers.arcgis.com/documentation/esri-and-data-attribution/)
require:

- `Powered by Esri` for applications using an Esri service;
- data-provider attribution for ArcGIS basemap/data content;
- an unobstructed and discoverable display;
- attribution in each UI component that uses the service.

Accordingly:

- no raw tile is written to disk;
- no persistent cache, offline pack, prefetch region, or background download
  feature is added;
- no raw tile is exposed through an app export;
- no tile is placed in KMZ output;
- composite images saved from the existing Matplotlib toolbar retain attribution;
- main/focus and Inspector surfaces each display attribution while imagery is
  visible;
- provider text comes from validated live `copyrightText`, not a silently stale
  hard-coded provider list;
- if validated attribution is absent, imagery is not displayed;
- README documentation does not call the service open or unrestricted;
- README documents that requesting tiles sends the viewed tile locations and
  normal network information such as the client IP address to Esri.

This is an engineering plan, not a legal opinion. External redistribution or use
outside the online, attributed display behavior defined here remains subject to
the service owner's current terms.

### 2.10 Repository and test baseline

The current worktree contains the completed but uncommitted GUI revamp:

```text
 M README_JPG_BOUNDARY_KMZ.md
 M src/__pycache__/jpg_boundary_kmz_gui.cpython-313.pyc
 M src/jpg_boundary_kmz_gui.py
 M tests/test_gui_input.py
?? src/jpg_boundary_gui_theme.py
?? src/jpg_boundary_gui_window.py
?? tests/test_gui_window.py
```

This is not a clean-HEAD implementation target. Phase 0 must treat the current
working files as the baseline, preserve all existing user/revamp changes, and use
temporary out-of-repository snapshots plus hashes. It must not reset or check out
these files from `HEAD`.

Audited SHA-256 values:

| File | SHA-256 |
| --- | --- |
| `src/jpg_boundary_kmz_gui.py` | `92948E6E145B85B66BBD3367FFE128058D01B40D2B176D628D4C33693F50BAAF` |
| `src/jpg_boundary_kmz_core.py` | `044D9747810FEA9C1F7F0EFD5CBC720B54A5AFEE649C0C5C1A118A3DFDF63B21` |
| `src/jpg_boundary_gui_theme.py` | `E7FFA6689723EDE7B3533B1D06EDD38A86D722D9D54FAF3C0C93FFEBC0E98845` |
| `src/jpg_boundary_gui_window.py` | `E5E09448F02E17A0CB95602861AA2C09E88AD71DB0A851C44D6744C73080BA76` |
| `requirements_jpg_boundary_kmz.txt` | `533FBEF14F52E8FE781C0DD333158C8B93A34513AD2468FB872BA7388356E44A` |
| `README_JPG_BOUNDARY_KMZ.md` | `EB768BF3489DE778507C7D2AFB6A1F8F88F726074F146670EC5F06110ACC4A09` |
| `tests/test_gui_input.py` | `D94938DC72CCDFDB3BDBCC4B7F9DAD954E06F807733681000FCCCF8CC68C0EEA` |
| `tests/test_gui_window.py` | `D792688039C9A205C18E286CA7E236B50CE30EDFFFB3ECDFCD7B985D60D43A04` |

Executed baseline command:

```powershell
python -B -m unittest discover -s tests -v
```

Result on 2026-07-24:

```text
Ran 161 tests in 71.919s
OK
```

`-B` is mandatory for implementation testing so the already modified tracked
`src/__pycache__/jpg_boundary_kmz_gui.cpython-313.pyc` is not changed again.

### 2.11 Rejected alternatives

#### Convert the whole preview to EPSG:4326

Rejected because it changes the view contract even with imagery off:

- all preview artists and bounds would change coordinate systems;
- equal longitude/latitude degrees are not equal ground distances;
- `1 / cos(latitude)` aspect is local and latitude-dependent;
- broad views and antimeridian crossings become new vector-display concerns;
- existing projected equal-scale tests would need semantic replacement;
- toggling imagery could not be a strictly additive layer unless the preview
  remained geographic even offline.

#### Stretch transformed tile corners

Rejected because a projected WGS84 tile is generally not represented by one
axis-aligned rectangle in the local projected CRS. Corner-only placement can create
alignment and seam errors.

#### Add Rasterio/GDAL, Contextily, Cartopy, or an ArcGIS SDK

Rejected in this scope:

- Contextily's normal path assumes Web Mercator, while this service is EPSG:4326.
- Rasterio/GDAL and Cartopy add native geospatial packaging weight for one
  controlled reprojection operation.
- An ArcGIS SDK would introduce a second GUI/map runtime and provider coupling.
- Existing NumPy, pyproj, SciPy, and Matplotlib can implement and test the bounded
  inverse warp without a new package.

#### Use `/export` or offline tile export

Rejected because `/export` returned 404, the service is `TilesOnly`, and the item
explicitly disallows offline tile export.

#### Run network or reprojection on the Tk thread

Rejected because timeout, JPEG decode, mosaic assembly, and grid reprojection can
all exceed interactive frame time.

### 2.12 Conflict, regression, and decommission analysis

The earlier GUI blueprint at
`docs/gui-visual-qol-revamp-implementation-plan.md:966-1007` protects processing
methods and limits `_draw_preview_on_axes` changes to presentation while preserving
geometry selection, bounds, aspect, labels, and decimation. This plan remains
compatible with that contract:

- projected geometry sources remain identical;
- projected fit/bounds/decimation remain identical;
- equal aspect remains identical;
- new image, halo, scale, and attribution artists are presentation-only;
- new scheduling occurs after the existing result draw and does not enter result
  generation or export.

The earlier plan's exact four direct navigation callback contract remains. New
draw/resize observers are surface-owned and separately counted.

No current feature is decommissioned:

- the dark preview remains the exact user-selectable Original Background and also
  serves as the loading/offline fallback;
- existing vector preview artists remain;
- Matplotlib toolbar remains;
- direct wheel/drag behavior remains;
- Key, Settings, Focus, and Inspector remain;
- toolbar Save remains, now with required attribution when imagery is present;
- no old queue, cache, worker, input, or export path is replaced.

The only obsolete documentation to remove is the README statement that the preview
has no imagery basemap. No compatibility alias, migration shim, data migration, or
feature-removal period is required.

## 3. Exact impacted files, symbols, and design

### 3.1 Planned file architecture

```text
src/jpg_boundary_gui_basemap.py       new: service, tile, cache, worker, warp
src/jpg_boundary_gui_scale_bar.py     new: geodesic scale calculation/artists
src/jpg_boundary_kmz_gui.py           modify: surface/controller integration

tests/test_gui_basemap.py             new: pure/network-mocked basemap tests
tests/test_gui_scale_bar.py           new: pure/Agg scale tests
tests/test_gui_input.py               modify: Tk integration/regression tests

README_JPG_BOUNDARY_KMZ.md            modify: behavior, terms, offline fallback
```

The two support modules may import installed numeric/plotting packages and standard
library modules. They must not import `jpg_boundary_kmz_core` or call processing or
output functions. The GUI passes immutable view values and EPSG codes into them.

### 3.2 `src/jpg_boundary_gui_basemap.py` - new

#### 3.2.1 Public constants and immutable data models

Define these typed immutable models:

```python
@dataclass(frozen=True)
class ArcGisTileService:
    root_url: str
    metadata_url: str
    expected_wkid: int
    tile_size: int
    image_format: str
    origin_x: float
    origin_y: float
    lod_resolutions: tuple[float, ...]
    copyright_text: str

@dataclass(frozen=True)
class ProjectedView:
    surface_id: str
    generation: int
    result_generation: int
    epsg: int
    xlim: tuple[float, float]
    ylim: tuple[float, float]
    pixel_width: int
    pixel_height: int

@dataclass(frozen=True)
class TileAddress:
    level: int
    row: int
    request_column: int
    display_column: int

@dataclass(frozen=True)
class ServiceMetadataError:
    code: str
    message: str

@dataclass(frozen=True)
class BasemapFrame:
    surface_id: str
    generation: int
    result_generation: int
    epsg: int
    xlim: tuple[float, float]
    ylim: tuple[float, float]
    pixel_width: int
    pixel_height: int
    rgba: numpy.ndarray
    copyright_text: str
    requested_tile_count: int
    valid_tile_count: int
    missing_tile_count: int
    is_partial: bool

@dataclass(frozen=True)
class BasemapFailure:
    surface_id: str
    generation: int
    result_generation: int
    category: str
    user_message: str
    retryable: bool
```

These class and field names are the implementation contract. Refactoring them
requires a plan amendment. The following fields may not be omitted:

- independent surface identity;
- monotonically increasing per-surface generation;
- app-owned monotonic result generation and display EPSG;
- exact requested limits and pixel size;
- attribution;
- requested/valid/missing tile counts and explicit partial state;
- categorized non-exception failure result.

Every emitted frame enforces:

```text
requested_tile_count == valid_tile_count + missing_tile_count
valid_tile_count > 0
is_partial == (missing_tile_count > 0)
```

Projection/out-of-bounds alpha does not set `is_partial`; only an addressed tile
that was 404 or an isolated exhausted nonfatal failure increments
`missing_tile_count`. Three consecutive failures and all-missing views emit a
failure, not a frame.

Do not pass Tk widgets, Matplotlib axes, mutable `BoundaryResult`, or secrets to the
worker.

Fixed operational constants:

```text
SERVICE_ROOT                 exact supplied HTTPS URL
EXPECTED_WKID                4326
EXPECTED_TILE_SIZE           256
EXPECTED_FORMAT              JPEG
ORIGIN_ABS_TOLERANCE         1e-12 degrees
LOD_REL_TOLERANCE            1e-12
LOD_ABS_TOLERANCE            1e-18 degrees/pixel
MAX_TILES_PER_VIEW           24
MAX_OUTPUT_PIXELS            1_500_000
MAX_OUTPUT_DIMENSION         1_600
MAX_METADATA_BYTES           1 MiB
MAX_TILE_BYTES               2 MiB
MAX_CACHE_TILES              128
MAX_CACHE_DECODED_BYTES      32 MiB
MAX_RESPONSE_ITEMS           4
WARP_CHUNK_ROWS              128
REQUEST_TIMEOUT_SECONDS      4
MAX_TRANSIENT_RETRIES        1
VIEW_DEBOUNCE_MS             300
METADATA_RETRY_COOLDOWN      30 seconds
```

The exact public support-module symbols are:

```text
ArcGisTileService
ProjectedView
TileAddress
ServiceMetadataError
BasemapFrame
BasemapFailure
MemoryTileCache
ArcGisBasemapClient
parse_service_metadata
tile_resolution
tile_span
tile_matrix_shape
select_tile_addresses
sample_projected_perimeter
select_lod
decode_jpeg_tile
assemble_tile_mosaic
warp_mosaic_to_projected_view
```

Private helpers may be added inside the module, but these named interfaces and
their responsibilities are fixed.

#### 3.2.2 Metadata parsing and validation

`parse_service_metadata` accepts decoded JSON and returns either
`ArcGisTileService` or the context-free
`ServiceMetadataError(code, message)`; it does not raise for provider-controlled
content. The HTTP/worker layer converts that error to a contextual
`BasemapFailure` using the request's surface, surface generation, and result
generation. Sentinel surface IDs or generation numbers are prohibited. Error
codes come from a closed internal set and user messages are static application
text; raw metadata/body/provider exception text is never displayed or logged.

Required validation:

- mapping/object root;
- `singleFusedMapCache is True`;
- `capabilities` is a string split only on commas, each token is trimmed, and at
  least one token equals `TilesOnly` case-insensitively; missing/wrong-type/empty
  capabilities or similar-but-nonexact tokens such as `Tiles` are rejected;
- service and `tileInfo` WKID are exactly 4326;
- tile rows and columns are exactly 256;
- format case-insensitively equals JPEG/JPG;
- origin is finite and each component satisfies
  `math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-12)` for expected
  `(-180, 90)`;
- LODs form unique integer levels 0 through 22;
- every resolution is finite, positive, and monotonically decreasing;
- each resolution agrees with `0.703125 / 2^level` under
  `math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-18)`;
- `copyrightText` is a string; permit only tab/CR/LF among Unicode `Cc` controls,
  reject every other `Cc` plus every `Cf`/surrogate code point, normalize all
  remaining Unicode whitespace runs with `" ".join(value.split())`, and require
  1-500 Unicode code points after normalization;
- `exportTilesAllowed` is false or absent; the implementation never invokes export
  in either case.

Metadata failure lifetime is exact:

- timeout; `URLError` whose reason is `TimeoutError`, `ConnectionError`,
  `socket.timeout`, or `socket.gaierror`; HTTP 408/429/500-599; or
  malformed/truncated JSON:
  cache a transient unavailable result for exactly
  `METADATA_RETRY_COOLDOWN` (30 seconds);
- HTTP 400-499 other than 408/429 (including 404), any unhandled final non-200
  status, nonretryable `URLError`, a body over 1 MiB, an explicitly non-JSON
  content type whose body is not safely valid JSON, or a well-formed JSON object
  that fails any placement/attribution schema rule: latch metadata as incompatible
  for the remainder of the application session;
- requests during cooldown/latch perform no metadata or tile I/O;
- at `monotonic_now >= cooldown_started + 30.0`, the next eligible worker changes
  `COOLDOWN` to `EMPTY` under the condition and enters normal single-flight
  acquisition;
- toggling imagery off then on clears only the transient 30-second cooldown and
  permits one immediate metadata retry;
- toggling does not clear the incompatible-session latch; restarting the
  application is the only retry boundary for an incompatible service shape.

Do not "best guess" a changed schema. Both failure classes remain nonfatal to
vectors, scale, preview generation, and KMZ export.

Fetch metadata with:

- exact fixed URL;
- exact `User-Agent: JPG-Boundary-to-KMZ-GUI/1.0`;
- 4-second timeout;
- maximum 1 MiB body;
- accepted JSON content type or a body that safely parses as JSON;
- a custom `urllib` redirect handler that rejects a redirect before following it
  when the target is not HTTPS on the exact allowed host;
- final URL scheme/host validation as a second check;
- no token, cookie, credential, or user-supplied query.

#### 3.2.3 Tile matrix math

Pure functions must implement:

```text
resolution(level) = 0.703125 / 2^level
tile_span(level)  = 256 * resolution(level) = 180 / 2^level
column_count      = 2^(level + 1)
row_count         = 2^level

column = floor((longitude + 180) / tile_span)
row    = floor((90 - latitude) / tile_span)
```

Tile selection rules:

- treat extents as half-open on east/south boundaries to avoid requesting an
  adjacent tile solely because a limit equals a tile edge;
- clamp rows to the matrix;
- allow unwrapped display columns across the antimeridian;
- request `display_column % column_count`;
- retain the unwrapped display column to position the mosaic continuously;
- clip geographic latitude to valid service latitude;
- return no request for a nonfinite or empty extent;
- lower LOD until the complete request fits `MAX_TILES_PER_VIEW`;
- if even level 0 cannot represent a meaningful view, report a bounded failure.

Do not use standard XYZ/Web Mercator formulas.

#### 3.2.4 Projected view perimeter and geographic extent

To avoid missing curved projected edges:

1. Begin with 33 evenly spaced points on each of the four projected viewport
   edges, de-duplicating corners, plus a 9 x 9 interior control grid.
2. Transform those points from `ProjectedView.epsg` to EPSG:4326 with
   `always_xy=True`.
3. Reject nonfinite transform output.
4. Normalize/unwrap longitudes around the transformed view center so a dateline
   crossing produces a narrow continuous interval rather than a nearly 360-degree
   request.
5. Choose a preliminary LOD from the initial bounds.
6. Adaptively subdivide every projected edge segment. Transform its projected
   midpoint and compare it with the longitude-unwrapped midpoint of the transformed
   segment endpoints. Subdivide while either longitude or latitude deviation is
   greater than 0.25 of the preliminary source-pixel resolution.
7. Cap subdivision at depth 8 and 4,097 points per edge. If convergence is not
   reached under that cap, return a nonfatal `extent_not_converged` failure instead
   of risking incomplete imagery.
8. Recompute extrema and LOD. Repeat adaptive convergence when the selected LOD
   changes, for at most three LOD passes; fail safely if it does not stabilize.
9. Expand the converged geographic request envelope by one selected source pixel
   on all four sides before half-open tile selection.
10. Recompute the tile count after padding. If it exceeds 24, step to a coarser
    LOD, recompute its one-pixel padding, and repeat until within the cap.
11. Retain the longitude unwrap reference for output-grid mapping.

The current core normally uses a local UTM CRS, but the helper must fail safely for
any valid or invalid EPSG supplied by a synthetic test.

#### 3.2.5 LOD selection

LOD must be selected from ground resolution rather than assuming degrees have a
constant metre length.

Algorithm:

1. Calculate projected units per output pixel from the requested projected limits
   and bounded output raster dimensions.
2. Convert projected center and representative one-pixel horizontal/vertical
   offsets to WGS84.
3. Measure both offsets with the display CRS geodesic.
4. For each service LOD, measure the WGS84 ground distance of one service pixel at
   the center latitude in horizontal and vertical directions.
5. Choose the coarsest LOD whose worst ground sampling distance is no more than
   1.25 times the requested output ground resolution.
6. Clamp to advertised LODs.
7. If the tile count exceeds 24, step to coarser levels until it does not.

If local resolution cannot be calculated, fall back to a degree-per-output-pixel
estimate only for selection, not placement. If that also fails, return a nonfatal
failure.

#### 3.2.6 HTTP tile fetch and validation

Build only:

```text
{fixed_root}/tile/{level}/{row}/{request_column}
```

For every response:

- require HTTP 200;
- require final host to match the fixed allowed host;
- require `image/jpeg` or `image/jpg`;
- enforce 2 MiB maximum while streaming;
- parse the bounded JPEG marker stream with a small, pure header reader before
  decode; accept only a valid SOF marker declaring exactly 256 x 256 pixels and
  reject missing, truncated, overflowed, or contradictory dimension markers;
- decode with `matplotlib.image.imread(BytesIO(data), format="jpeg")`;
- defensively require the decoded array is still exactly 256 x 256 pixels;
- accept only 2-D grayscale or 3-D arrays with 1, 3, or 4 channels; repeat
  grayscale/one-channel data to RGB and drop the fourth channel from RGBA;
- accept `uint8` unchanged; for floating arrays, reject any nonfinite value, clip
  to `[0.0, 1.0]`, convert with
  `numpy.rint(clipped * 255.0).astype(numpy.uint8)`, and reject every other dtype;
- require the normalized result is contiguous 256 x 256 x 3 `uint8`, then mark it
  read-only;
- never log bodies or query values;
- cache only successfully decoded RGB arrays.

The pre-decode JPEG header reader is deterministic:

1. Require SOI bytes `FF D8`.
2. Scan the already body-capped byte string without allocating from declared
   dimensions.
3. Treat SOI, EOI, TEM, and RST0-RST7 as standalone markers; for every other
   marker require an in-bounds big-endian segment length >=2.
4. Recognize SOF markers `C0-C3`, `C5-C7`, `C9-CB`, and `CD-CF`; require an
   in-bounds SOF payload, positive dimensions exactly 256 x 256, and 1-4
   components.
5. Reject contradictory multiple SOF declarations, arithmetic/segment overflow,
   truncation, EOI/SOS before any SOF, or a scan ending without SOF.
6. Header acceptance only permits decoder invocation; decoded-shape/dtype checks
   remain mandatory.

Failure policy:

| Condition | Action |
| --- | --- |
| 404 | Mark tile missing; no retry |
| 408, 429, 500-599, timeout, or retryable `URLError` reason defined above | One cancel-aware retry |
| Any other 400-499 or final non-200 status | Fail current refresh; no automatic retry |
| Any other/nonretryable `URLError` | Fail current refresh; no automatic retry |
| Redirect off allowed host | Reject |
| Wrong content type/body too large/unsafe JPEG header/decode error/decoded shape mismatch | Reject tile; no retry |
| Three consecutive exhausted non-404 tile failures in one view | Stop remaining uncached fetches, discard the current frame, and return one `BasemapFailure`; already validated tiles may remain in the LRU |
| Some valid tiles plus missing tiles | Return partial RGBA frame with transparent missing areas |
| No valid tiles | Preserve dark fallback and return compact failure status |

The consecutive-failure counter increments only after a non-404 tile has exhausted
its allowed attempt(s), resets on a valid cache/fetch result or a handled 404, and
marks the failed tile transparent while the count is below three. Thus one or two
isolated failures may yield `Imagery partial` when another valid tile exists, while
the third consecutive failure yields no frame for that view.

Retry delay must use a shutdown/request-generation-aware event wait, not an
uninterruptible long sleep.

#### 3.2.7 Memory-only LRU

Implement an injectable, lock-protected LRU keyed by:

```text
(service_root, level, row, request_column)
```

Required behavior:

- decoded arrays only;
- maximum 128 entries;
- maximum 32 MiB based on `array.nbytes`;
- LRU promotion on hit;
- eviction until both limits are satisfied;
- a same-key acceptable replacement is serialized, subtracts the old `nbytes`
  before adding the new value, leaves entry count unchanged, and moves the key to
  most-recently-used position; concurrent replacements linearize by lock
  acquisition and the last one wins;
- an oversized replacement is rejected before mutation and preserves the existing
  cached value/order/accounting;
- no cache of errors;
- no filesystem access;
- `clear()` on app shutdown;
- `clear()` on actual input change and imagery disable;
- no clear for a same-input preview regeneration, so main/Inspector and nearby
  refreshed views can still share tiles within the active enabled session;
- defensive read-only arrays or copies so one mosaic cannot mutate cached tiles.

`clear_cache()` must be race-safe:

- `MemoryTileCache` accepts an optional lock; the client constructs it with the
  client's single `threading.RLock`, while standalone tests may let it create its
  own lock;
- latest-generation state, cache epoch, LRU lookup/insertion, and clear all use
  that same lock, so no nested client/cache lock order exists;
- increment a client-owned cache epoch and clear the LRU atomically under that
  coordination lock;
- each job captures the epoch at submission;
- after fetch/decode and immediately before cache insertion, atomically verify
  both the request generation and captured cache epoch;
- if imagery disable, input change, or shutdown advanced either value, discard the
  decoded tile without inserting it.

#### 3.2.8 Mosaic assembly and inverse raster warp

Mosaic assembly:

- allocate only the selected bounded tile grid;
- order rows north-to-south and display columns west-to-east;
- insert decoded tile RGB in the exact published orientation;
- create a parallel validity mask;
- fill missing tiles with zeros plus zero validity, not an opaque black tile;
- retain requested/valid/missing address counts independently of output alpha;
- calculate native unwrapped mosaic west/north and resolution.

Output sizing:

- begin with current axes pixel width/height;
- preserve aspect ratio;
- cap either dimension at 1,600;
- downscale further until `width * height <= 1,500,000`;
- reject dimensions below two pixels.

Inverse warp:

1. Construct projected x coordinates from left to right and projected y
   coordinates from top to bottom at the exact pixel centers implied by the
   output array and its outer-edge projected extent.
2. Process at most 128 output rows per chunk. Do not allocate full-frame projected
   x/y and longitude/latitude mesh grids simultaneously.
3. Accept an injected `is_cancelled() -> bool` callback and check it before every
   row chunk and between the RGB/alpha sampling passes. On cancellation, discard
   temporary/output arrays and return the internal canceled result without
   enqueueing or caching a frame.
4. Transform each chunk from result EPSG to EPSG:4326 with vectorized pyproj calls.
5. Unwrap each transformed longitude to the mosaic reference.
6. Convert longitude/latitude to floating mosaic pixel-center indices:

   ```text
   source_column = (longitude - mosaic_west) / resolution - 0.5
   source_row    = (mosaic_north - latitude) / resolution - 0.5
   ```

7. Sample each RGB channel with
   `scipy.ndimage.map_coordinates(..., order=1, mode="constant", cval=0)`.
8. Sample the validity mask and convert it to alpha.
9. Zero alpha for nonfinite/out-of-range coordinate transforms.
10. Write the chunk into the preallocated bounded RGBA output.
11. Mark the completed RGBA array read-only.
12. Return the RGBA array and the exact projected outer-edge extent.

Accuracy controls:

- no corner-only approximation;
- no forward splatting that can leave holes;
- no silent axis-order swap;
- no use of nominal Esri DPI/scale for coordinate placement;
- retain the request's exact projected limits in the response signature.

#### 3.2.9 Worker and request coalescing

Implement a client with at most two lazy daemon workers:

- one stable worker slot is dedicated to surface ID `main`;
- one stable worker slot is dedicated to the currently registered
  `inspector:<generation>` surface;
- each starts only on the first enabled request for its slot;
- both share one lock-protected metadata state and memory cache;
- each maintains at most one pending request for its surface;
- a newer request atomically replaces the older pending request for that surface;
- no third surface is accepted;
- authorizes every metadata/tile HTTP attempt through one atomic per-slot
  reservation under the same client `RLock` used for generation, registration,
  metadata, and cache-epoch state;
- checks a thread-safe latest-generation map before metadata; after metadata
  HTTP/parse and immediately before atomically committing shared success,
  cooldown, or session-latch state; between tile requests; before every warp
  chunk/channel through `is_cancelled`; and before enqueueing a response;
- uses a response queue with `maxsize=4` and one response lock shared by both
  producers and `poll()`; while holding that lock, a producer removes exactly the
  oldest item with `get_nowait()` only if full and then `put_nowait()`s the new
  item, preserving a linearizable FIFO of the four newest publications even when
  both workers finish simultaneously;
- never calls Tk or Matplotlib APIs that mutate artists/widgets;
- uses Matplotlib's pure image decoder in the worker but never a Tk canvas;
- exits on a stop event;
- clears pending work and cache during shutdown;
- does not prevent process exit if a network request is still timing out.

HTTP-attempt authorization is an explicit cancellation boundary:

1. A private `_reserve_http_attempt(...)` runs under the client `RLock` immediately
   before every initial attempt and every retry. It verifies stop state, exact
   surface registration/slot epoch, latest request generation, and captured cache
   epoch. If any check fails, it returns no reservation and no opener call occurs.
2. A successful reservation records one monotonic token for that exact slot,
   surface, generation, registration epoch, and cache epoch. A slot cannot hold
   more than one reservation because it has one serial worker and the reservation
   map rejects a second active token.
3. The lock is then released and a private `_perform_reserved_open(...)` performs
   the injected synchronous opener call. Its separation from reservation lets
   deterministic tests place a barrier after authorization but before opener
   entry without adding a test-only production branch.
4. A `finally` block reacquires the lock and removes only that exact reservation.
   The returned payload is usable only after the normal generation,
   registration, stop, metadata-token, and cache-epoch checks pass again.
5. `cancel_surface`, `deregister_surface`, cache-epoch advance, and shutdown never
   wait for or forcibly revoke a reservation already released to synchronous I/O.
   They do make every later reservation check fail for the invalidated work.
6. Metadata single-flight permits at most one metadata reservation globally.
   Once metadata is `READY`, main and Inspector can each have one tile attempt
   reserved/in flight, so the honest upper bound during shared disable is two
   pre-authorized calls, one per active worker slot.

Therefore the implementation and tests assert reservation counts, not that the
raw opener-call count remains numerically fixed after a GUI disable returns. A
pre-authorized call may enter the opener after that return, but it cannot authorize
a retry/next tile, commit metadata/cache state, publish a response, or reach an
artist.

The one allowed transient retry uses the affected slot's condition and
latest-generation lock:

- wait with an exact 250 ms timeout while the predicate remains
  `not stopping and latest_generation == request_generation`;
- a newer submit, `cancel_surface`, or shutdown updates the predicate and calls
  `notify_all()`;
- if awakened by cancellation/shutdown, perform no retry;
- if the full timeout expires while the generation remains current, perform the
  single retry.

This makes both generation cancellation and shutdown interrupt the retry delay
without a lost-wakeup-prone event clear. Main and Inspector cannot starve each
other because no surface waits behind the other surface's tile fetch or warp.

Initial/service metadata acquisition is single-flight across worker slots:

1. Maintain `EMPTY`, `FETCHING`, `READY`, `COOLDOWN`, `INCOMPATIBLE`, and
   `SHUTDOWN` states plus a metadata epoch/fetch token under a worker condition
   using the client `RLock`.
2. The first eligible worker changes `EMPTY` to `FETCHING`, captures the token,
   releases the lock, and performs metadata HTTP/JSON/parser work.
3. No client/cache/response lock is held during network, JSON parsing, retry wait,
   or decode.
4. Another eligible worker seeing `FETCHING` waits on the condition in at most
   50 ms intervals and rechecks stop/latest-generation state after every wake;
   stale/stopped waiters return without fetching.
5. The fetch owner reacquires the condition and commits `READY`, `COOLDOWN`, or
   `INCOMPATIBLE` only when its token/epoch is current, the client is not stopping,
   and its initiating surface generation is still latest. It then notifies all.
6. Surface generation replacement/cancellation or shutdown that invalidates an
   active token prevents its result from committing. When the bounded in-flight
   call returns, it changes the still-owned `FETCHING` state to `EMPTY`, notifies
   waiters, and one current waiter may become the next owner.
7. `READY` is immutable for the session; only one accepted metadata object is
   shared, and a later transient outcome cannot overwrite it.

This permits at most one metadata HTTP request at a time without holding a
GUI-facing lock across I/O.

`ArcGisBasemapClient` exposes this exact GUI-facing API:

```python
submit(view: ProjectedView) -> None
cancel_surface(surface_id: str, minimum_generation: int) -> None
deregister_surface(surface_id: str) -> None
poll() -> BasemapFrame | BasemapFailure | None
clear_cache() -> None
reset_transient_metadata_failure() -> None
shutdown() -> None
```

All seven methods are nonblocking from the caller's perspective. `poll()` acquires
the response lock only around one `get_nowait()` and never waits for worker I/O.
`reset_transient_metadata_failure()` clears only an active 30-second transient
metadata cooldown by atomically advancing the metadata epoch, changing `COOLDOWN`
to `EMPTY`, and notifying worker waiters; it is a no-op for `EMPTY`, `FETCHING`,
`READY`, `INCOMPATIBLE`, or `SHUTDOWN` and performs no I/O. `shutdown` signals and
detaches; it does not join a network timeout on the Tk thread.

Surface registry semantics are exact:

- `submit` registers/reuses `main` or replaces the Inspector slot with the supplied
  unique `inspector:<generation>` ID; latest-map cardinality is never above two;
- `cancel_surface` retains a registered surface but atomically advances its latest
  generation to at least `minimum_generation`, clears its pending request, and
  notifies its slot condition; active older work treats the greater generation as
  canceled and `_reserve_http_attempt` rejects every later attempt for it;
- `deregister_surface` is used on Inspector close, atomically removes that ID from
  the latest map/current Inspector slot, clears pending work, advances the slot
  registration epoch, and notifies waiters; missing membership or epoch mismatch
  cancels active work and later attempt authorization;
- repeated deregistration is a no-op, a new Inspector ID never inherits the prior
  ID's latest value, and shutdown clears both registry entries;
- no tombstone for a closed Inspector ID remains.

The response queue contains only immutable frame/failure objects. The Tk thread
polls it and performs all artist/widget changes.

Expose dependency injection seams for:

- URL opener;
- monotonic clock;
- retry wait;
- metadata fixture;
- cache;
- response queue.

No default unit test may instantiate the real URL opener.

### 3.3 `src/jpg_boundary_gui_scale_bar.py` - new

#### 3.3.1 Pure scale model

Define these exact constants:

```text
SCALE_START_X_FRACTION          0.03
SCALE_Y_FRACTION                0.08
SCALE_MAX_WIDTH_FRACTION        0.25
SCALE_MIN_MILES                 0.01
SCALE_RELATIVE_ERROR_TOLERANCE  0.0025
SCALE_BISECTION_MAX_ITERATIONS  48
METRES_PER_STATUTE_MILE         1609.344
```

Define this result model:

```python
@dataclass(frozen=True)
class ScaleBarSpec:
    start_fraction: float
    end_fraction: float
    y_fraction: float
    miles: float
    label: str
    relative_error: float
```

The exact public support-module symbols are:

```text
SCALE_START_X_FRACTION
SCALE_Y_FRACTION
SCALE_MAX_WIDTH_FRACTION
SCALE_MIN_MILES
SCALE_RELATIVE_ERROR_TOLERANCE
SCALE_BISECTION_MAX_ITERATIONS
METRES_PER_STATUTE_MILE
ScaleBarSpec
format_miles
select_nice_miles
calculate_scale_bar
ScaleBarController
```

Private helpers may be added, but these named interfaces and responsibilities are
fixed.

The calculator accepts:

- axes or an injected axes-fraction-to-data transform;
- explicit display CRS/EPSG;
- current limits and axes pixel bounds;
- target maximum width `SCALE_MAX_WIDTH_FRACTION == 0.25`;
- fixed lower-left start at axes fractions
  `(SCALE_START_X_FRACTION, SCALE_Y_FRACTION) == (0.03, 0.08)`;
- minimum `SCALE_MIN_MILES == 0.01`.

`calculate_scale_bar(...) -> ScaleBarSpec | None`; `None` is the sole hidden/invalid
result. No second sentinel, exception payload, or partially populated spec is
allowed. The controller treats `None` as remove/hide all scale artists.

#### 3.3.2 Geodesic calculation

Required algorithm:

1. Resolve `pyproj.CRS.from_user_input(display_crs)`.
2. Create/cache a transformer from the display CRS to its geodetic CRS with
   `always_xy=True`.
3. Use `CRS.get_geod()` for ellipsoidal inverse distance.
4. Convert the start and 25%-width axes-fraction positions through
   `axes.transAxes`, display coordinates, and `axes.transData.inverted()`.
5. Transform those projected endpoints to longitude/latitude.
6. Use `Geod.inv` to obtain ground distance.
7. Convert metres to statute miles using exactly `1609.344`.
8. Select the largest nice value from `{1, 2, 5} x 10^n` no larger than the
   available 25%-width distance and no smaller than `0.01 mi`.
9. Solve the end fraction with bounded bisection over `[0.03, 0.28]`.
10. Stop when relative distance error is at most `0.0025` (0.25%) or after exactly
    48 iterations.
11. Re-measure the final endpoints and reject the bar if it misses tolerance.

Do not derive the label from:

- raw projected x span;
- the basemap LOD scale;
- map DPI;
- a fixed metres-per-pixel assumption;
- screen resolution alone.

This makes the bar locally accurate at its lower-left anchor. A single bar is not
a claim that scale is globally constant over an extremely broad projected view.

#### 3.3.3 Nice values and formatting

Pure helpers must:

- support at least `0.01`, `0.02`, `0.05`, `0.1`, `0.2`, `0.5`, `1`, `2`, `5`,
  `10`, `20`, `50`, and higher values;
- never round a selected value up beyond the available target width;
- use `f"{miles:.2f}".rstrip("0").rstrip(".") + " mi"`;
- never emit scientific notation in normal GUI ranges;
- never emit `-0`, `nan`, `inf`, or `0.00 mi`;
- hide if `0.01 mi` cannot fit and be verified.

Examples:

```text
10 mi
2.5 mi
0.25 mi
0.05 mi
0.01 mi
```

#### 3.3.4 Artist controller

One controller per axes/canvas:

- owns its scale line, endpoint ticks, label, and translucent background;
- draws in axes-fraction coordinates so visual placement remains stable;
- uses high z-order;
- uses light text/line plus dark outline or rounded translucent dark box;
- stores explicit display CRS and result generation;
- caches a view signature containing CRS, limits, axes pixel bounds, and figure
  DPI;
- skips work when the signature is unchanged;
- hides all artists on empty/invalid state;
- recreates artists idempotently after `axes.clear()`;
- is passive and registers no Matplotlib/Tk callbacks;
- exposes `bind_result(display_crs, result_generation)`, `refresh()`, and `clear()`;
- returns whether artist state changed so the GUI surface observer decides whether
  one guarded follow-up draw is needed;
- never raises out of a draw callback.

Only `_PreviewMapSurface` owns the two canvas observer callback IDs
(`draw_event` and `resize_event`). Its GUI handlers invoke
`ScaleBarController.refresh()` and schedule basemap work. This single ownership
prevents duplicate callbacks and draw loops.

Attribution placement and scale placement must be coordinated by the GUI so they
remain readable and do not overlap at the supported minimum sizes.

### 3.4 `src/jpg_boundary_kmz_gui.py` - modified

#### 3.4.1 Imports and constructor state

Add imports only from the two new GUI support modules and Matplotlib path effects,
which are required for the FD-16 vector halos.

Extend `BoundaryKmzApp.__init__` with a backward-compatible keyword-only injection
seam for the basemap client/factory. Existing `BoundaryKmzApp(root)` remains valid.

Add GUI-only state:

- shared `BooleanVar(value=True)` for imagery;
- lazy basemap client/factory;
- separate basemap response poll `after` ID;
- closing flag;
- main surface controller/state;
- Inspector surface controller/state;
- per-surface status variables;
- per-surface generation values;
- current app-owned monotonic result-generation token/EPSG for each surface;
- scale-bar controller references;
- basemap image and attribution artist references owned through surface state.

Define one private GUI dataclass named `_PreviewMapSurface` containing:

```text
surface_id
axes
figure
canvas
status_var
surface_generation
result_generation
epsg
basemap_image
attribution_artist
scale_controller
observer_event_cids
debounce_after_id
last_submitted_signature
last_applied_signature
```

The dataclass remains on the Tk thread and is never passed to the worker.

Register a root close protocol that:

1. marks the app closing;
2. invalidates all surface generations;
3. closes/disconnects the Inspector;
4. signals and detaches both basemap-client slots without waiting on a network
   timeout;
5. clears the memory cache;
6. destroys the root;
7. does not alter normal boundary worker behavior.

The constructor must not make a network request. The client remains lazy until a
valid result is displayed with imagery enabled.

Do not use Python object `id(result)` as the result-generation token. Increment an
application-owned integer whenever a newly accepted `BoundaryResult` replaces the
displayed result, and pass that token to both active surfaces. Reusing the same
displayed result for focus/Inspector redraw retains the token.

#### 3.4.2 Main toolbar integration

In `_build_preview_workspace`:

- retain the existing Matplotlib toolbar in column 0;
- add a compact right-aligned view-control frame;
- add `World Imagery` checkbutton bound to the shared BooleanVar;
- add a short status label that may show only:
  - `""` for ready;
  - `Imagery loading...`;
  - `Imagery partial`;
  - `Imagery unavailable`;
  - `Imagery off`;
- keep the row height compact;
- preserve existing toolbar buttons and canvas size behavior;
- ensure the control remains inside client bounds at the adaptive minimum.

Toggling off:

- observes the shared BooleanVar already set to false;
- calls `after_cancel(surface.debounce_after_id)` for each non-`None` main or
  Inspector debounce ID, then sets each stored ID to `None`;
- increments each active surface generation and, only when the lazy client already
  exists, calls `cancel_surface(...)` for each registered surface before clearing
  its transient cache/advancing the cache epoch;
- defines the disabled-state commit as the point after the false preference,
  debounce cancellation, both surface-generation advances, and any applicable
  existing-client cancellations/cache-epoch advance have all completed on the Tk
  thread;
- removes basemap and attribution artists from both surfaces;
- sets each currently result-bound surface status to exactly `Imagery off`; an
  empty/unbound surface remains `""`;
- clears each surface's last-submitted/last-applied imagery signatures so a later
  toggle-on resubmits the unchanged visible view;
- clears the transient decoded-tile cache;
- leaves vector artists, limits, scale bars, key, result state, and processing
  state unchanged;
- restores the existing theme path with the already-imported
  `style_matplotlib_axes(surface.figure, surface.axes)`, which styles both
  objects; both facecolors must equal
  `matplotlib.colors.to_rgba(PALETTE.BACKGROUND_DEEP)`;
- keeps exactly one scale group bound to each valid surface, calls its normal
  refresh path after the imagery artists are removed, and continues scale refresh
  on every supported pan, zoom, navigation, and resize route;
- requests at most one `draw_idle()` per affected surface after the background and
  scale artist state is updated;
- performs no basemap submission or lazy worker start while disabled, including
  when imagery is disabled before the first valid preview;
- creates no new HTTP-attempt reservation after the disabled-state commit. At
  most one attempt already reserved/in flight per active worker slot (two total)
  may enter/return; generation/registration/cache-epoch checks then prevent retry,
  next-tile/metadata fetch, metadata/cache commit, response publication, or artist
  application;
- does not duplicate the `#0f0f0f` literal or add a second background token in the
  basemap/scale modules;
- does not clear the boundary-result cache/settings key.

Toggling on:

- calls `reset_transient_metadata_failure()` once only when the lazy client
  already exists; it never instantiates a client merely to reset an empty state;
- schedules each active valid surface after the normal debounce;
- does not regenerate the boundary;
- shows a nonmodal loading state on each result-bound surface;
- leaves an empty/unbound surface at status `""` and does not start the client for
  that surface.

#### 3.4.3 Surface abstraction

Add these private GUI helpers:

```text
_create_preview_map_surface(...)
_bind_preview_map_surface(...)
_reset_preview_map_surface(...)
_schedule_basemap_refresh(...)
_current_projected_view(...)
_drain_basemap_queue(...)
_apply_basemap_frame(...)
_apply_basemap_failure(...)
_remove_basemap_artist(...)
_refresh_attribution_artist(...)
_shutdown_basemap(...)
```

Each surface state must bind:

- stable surface ID (`main` or a unique Inspector generation);
- axes/canvas;
- current result generation and EPSG;
- basemap image;
- attribution;
- scale controller;
- draw/resize callback IDs;
- debounce `after` ID;
- last submitted and last applied view signatures;
- status variable.

No surface state may own or mutate a `BoundaryResult`.

#### 3.4.4 Draw path integration

Modify `_draw_preview_on_axes` only for presentation-layer integration:

1. Reset the surface's existing basemap/attribution/scale artist references before
   or immediately after `axes.clear()`.
2. Keep all current projected geometry sources, decimation, labels, colors,
   bounds, and equal aspect semantics.
3. Give vector fills and lines explicit z-orders above the basemap.
4. Add modest path-effect halos/edges that do not change coordinates.
5. Keep `_fit_preview_axes_to_result` and `_preview_result_bounds` semantically
   unchanged.
6. Bind the result generation and `metadata.epsg` to the relevant surface.
7. Activate/rebuild the scale controller.
8. Schedule basemap refresh only after fit/aspect/layout produce a valid view.
9. Keep Key entries unchanged; imagery and scale do not become boundary sections.
10. Draw the dark surface immediately; never wait for imagery.

Change the private draw signature to accept the explicit surface:

```python
_draw_preview_on_axes(
    result,
    axes,
    figure,
    canvas,
    key_content,
    surface: _PreviewMapSurface,
)
```

Likewise, `_draw_empty_preview_on_axes` receives the affected
`_PreviewMapSurface` so it can invalidate that surface without discovering it from
widget identity.

Applying a completed frame:

- verify surface still exists;
- verify imagery remains enabled;
- verify surface generation, result generation, EPSG, limits, and pixel signature;
- save exact current x/y limits, `dataLim.frozen()`, x/y autoscale flags,
  `use_sticky_edges`, aspect, adjustable mode, and anchor;
- create/update one `AxesImage` with a negative z-order;
- clear the basemap image's own x/y sticky-edge lists;
- restore exact `dataLim`, x/y autoscale flags, `use_sticky_edges`, limits, aspect,
  adjustable mode, and anchor without expanding/autoscaling;
- create/update attribution;
- set `Imagery partial` if and only if `frame.is_partial`; otherwise set status
  exactly to `""`;
- preserve vector artists and scale artists;
- call `draw_idle`;
- never call `_draw_preview_on_axes` recursively.

For signed view limits `xlim=(x0, x1)` and `ylim=(y0, y1)`, the worker samples:

```text
x_center(i) = x0 + (i + 0.5) * (x1 - x0) / width
y_center(j) = y1 - (j + 0.5) * (y1 - y0) / height
```

The Tk thread displays the resulting north/screen-top-to-south/screen-bottom rows
with the exact equivalent of:

```python
axes.imshow(
    frame.rgba,
    extent=(x0, x1, y0, y1),
    origin="upper",
    interpolation="bilinear",
    zorder=-100,
)
```

It then restores saved `dataLim`, autoscale/sticky state,
aspect/adjustable/anchor, and the exact signed limits.
It does not sort the display extent; this preserves intentionally inverted x or y
axes. Tests must cover all four normal/inverted x/y combinations and assert the
signed-screen contract: mosaic column zero remains at the screen edge represented
by `x0`, output row zero remains at the screen edge represented by `y1`, and the
opposite sentinels remain at the opposite screen edges. Geographic north/west is
expected to move to the opposite screen edge when the corresponding axis is
intentionally inverted; tests must not falsely require geographic north-up or
west-left in those cases.

If any signature differs, discard the frame silently.

#### 3.4.5 Navigation observation

The existing four direct handlers remain unchanged.

`_PreviewMapSurface`-owned `draw_event`/`resize_event` observers:

- derive the current surface view;
- update the same bound geodesic scale controller for every changed valid
  signature before evaluating imagery state;
- when imagery is disabled, return only from the basemap
  debounce/client/submission branch after that scale refresh; never return from or
  disconnect the provider-independent observer as a whole;
- schedule/replace a basemap request after 300 ms, canceling any prior non-`None`
  stored debounce ID before storing the replacement ID;
- when the debounce fires, first set that surface's stored debounce ID to `None`
  and recheck the shared imagery BooleanVar plus valid bound-result state; if
  disabled/invalid, return before lazy-client creation, generation increment,
  signature mutation, or submission;
- only after that recheck, compare the full view signature (surface ID, result
  generation, EPSG, exact signed limits, bounded pixel width/height); if it
  differs from `last_submitted_signature`, increment that surface's monotonic
  generation exactly once, store the signature, lazily acquire/create the shared
  client, and submit the `ProjectedView` carrying the new generation;
- if the signature equals `last_submitted_signature`, do not increment and do not
  submit;
- a distinct same-surface submission atomically replaces/cancels older pending or
  active work through the client's latest-generation map;
- for empty/no-result surfaces, clear/hide the scale as defined in Section 3.3 and
  schedule no basemap work;
- do not enqueue duplicate signatures;
- do not change axes limits;
- do not block the event callback with transform, HTTP, decode, or warp work.

This covers Matplotlib toolbar interactions without monkey-patching toolbar methods.

#### 3.4.6 Empty and input-change behavior

`_draw_empty_preview_on_axes`, `_clear_preview_for_input_change`, and result changes
must:

- increment the affected surface generation;
- cancel its pending debounce;
- detach/remove basemap and attribution;
- hide scale;
- clear result generation/EPSG;
- retain the current empty-state text and dark theme;
- prevent late responses from applying.

An actual input text change clears the shared tile cache after invalidating both
surfaces. A same-input preview regeneration does not clear it. Neither path may
modify filesystem state or boundary processing state.

#### 3.4.7 Inspector integration

In `_open_fullscreen_preview`:

- place the Inspector Matplotlib toolbar at the left of one compact toolbar row
  and a right-aligned view-control frame in that same row;
- add an Inspector `World Imagery` checkbutton bound to the same BooleanVar;
- add an independent short imagery-status label;
- create an independent map surface and scale controller;
- retain all existing preview mutation controls and Apply Preview behavior;
- retain the independent direct-navigation callback list of length four;
- draw the cached/last displayed result immediately before imagery completes.

The shared BooleanVar means toggling in either surface changes both surfaces.

In `_draw_fullscreen_preview`:

- bind the Inspector surface to the selected cached/last displayed result;
- use the shared draw path;
- retain independent limits after subsequent navigation.

In `_close_fullscreen_preview`:

- cancel the Inspector debounce and pending request;
- increment its surface generation and call
  `deregister_surface(inspector_surface_id)`;
- disconnect the two surface-owned observer callback IDs and clear the passive
  scale controller;
- remove all controller references before destroying the window;
- retain the existing direct callback disconnect behavior;
- ensure a late Inspector response cannot touch a reopened Inspector with a new
  surface generation.

#### 3.4.8 Focus mode

Focus mode requires no third map surface:

- reuse the main surface ID/controller/cache/image;
- let resize/draw observation request a resolution appropriate to the larger
  canvas;
- retain the current view center and scale semantics;
- update scale after final axes bounds are known;
- do not duplicate callbacks when focus is entered repeatedly;
- restore without a duplicate request if the existing frame already satisfies the
  restored view signature.

#### 3.4.9 Attribution

Whenever `valid_tile_count > 0`:

- display `Powered by Esri`;
- display the exact validated service `copyrightText`;
- use at least 9-point Matplotlib text (approximately 12 px at 96 DPI);
- use a translucent light or dark box that remains legible over imagery;
- render provider text with Matplotlib math parsing disabled and normalized
  whitespace so provider-controlled text is displayed literally;
- place it at high z-order;
- keep it unobstructed by the right-side Settings/Key overlays by using the
  available left preview region and renderer-measured greedy word wrapping;
- when one token exceeds the available measured line width, split it at the
  largest character boundary that fits rather than clipping, eliding, shrinking
  below 9 pt, or overflowing;
- render and retain the complete validated text, including the 500-character
  accepted maximum;
- keep it separate from the scale bar;
- include it in Inspector and toolbar-saved figures.

Whenever no valid imagery is displayed:

- remove/hide attribution;
- do not imply Esri imagery is active.

Attribution content is not user-editable.

#### 3.4.10 Nonmodal status

Imagery status is separate from:

- `status_var`;
- `preview_state_var`;
- `_fullscreen_status_var`;
- `_busy`;
- progress animation;
- processing errors.

Do not show a modal dialog for:

- no internet;
- provider timeout;
- rejected metadata;
- missing tile;
- corrupt image;
- projection/warp failure;
- rate limit;
- canceled/stale request.

Visible status mapping is exact:

| State | Text |
| --- | --- |
| No bound result/empty preview | `""` |
| Imagery disabled | `Imagery off` |
| Current eligible request pending/active | `Imagery loading...` |
| Complete current frame | `""` |
| Partial current frame | `Imagery partial` |
| Current nonstale failure/no valid tile | `Imagery unavailable` |
| Stale/canceled response | Do not change current text |

The table is evaluated top-down for empty state first: with no bound result the
status is `""` even if the shared preference is off. `Imagery off` applies only to
a bound result.

Store only a closed internal failure category plus a static application diagnostic
message truncated to at most 160 Unicode code points in memory for tests/support.
User-facing text remains the table value and contains no response body, exception
text, URL query, or provider-controlled content.

### 3.5 Contract-protected symbols in `src/jpg_boundary_kmz_gui.py`

The file is allow-listed because it owns the GUI. The following is the exact
immutable normalized-AST hash set; every listed method must be present exactly once
and its function AST must match the Phase 0 working-tree baseline:

```text
_read_inputs
_scan_clicked
_start_preview_generation
_export_clicked
_scan_worker
_export_worker
_drain_queue
_selected_outline_mode
_selected_split_direction
_parse_dropped_paths
_path_from_text
_strip_wrapping_quotes
_resolve_output_path
_settings_key
_settings_outline_key
_default_output_path
_safe_filename_stem
_filename_from_output_name
_default_shape_label
_disable_toolbar_coordinate_message
_register_preview_interactions
_register_preview_canvas_interactions
_on_preview_scroll
_handle_preview_scroll
_on_preview_button_press
_handle_preview_button_press
_on_preview_mouse_move
_handle_preview_mouse_move
_on_preview_button_release
_is_preview_axes_event
_preview_toolbar_has_active_mode
_event_pixels
_is_left_mouse_event
_scroll_direction
_fit_preview_axes_to_result
_preview_result_bounds
_preview_polygon_xy
_toggle_focus_mode
main
```

`_drain_queue` is explicitly protected in this plan because basemap responses use
a new queue and poller. No basemap branch is needed there.

The following draw/lifecycle methods may change only as specified in Section 3.4:

```text
__init__
_build_preview_workspace
_draw_preview
_draw_preview_on_axes
_draw_empty_preview
_draw_empty_preview_on_axes
_on_input_changed
_clear_preview_for_input_change
_open_fullscreen_preview
_draw_fullscreen_preview
_close_fullscreen_preview
```

The root close protocol is wired in `__init__`; `main` is not edited. The existing
fit, bounds, decimation, focus, direct wheel/pan, and toolbar-mode helper methods
are immutable rather than merely behaviorally described.

Phase 0 must generate normalized AST hashes for exactly the immutable code block
above from the current working-tree baseline and store the manifest outside the
repository in the task-specific temporary backup directory. Allowed-change methods
are intentionally excluded from that manifest. Post-implementation validation
must recompute and compare the exact immutable set. No comparison to `HEAD` is
sufficient because the current GUI revamp is intentionally uncommitted.

### 3.6 `tests/test_gui_basemap.py` - new

This file owns non-Tk, deterministic tests for:

- metadata parser;
- tile matrix/range calculations;
- LOD choice and tile cap;
- antimeridian column wrapping;
- perimeter transformation;
- equator/high-latitude ground-resolution LOD selection;
- URL construction and host validation;
- HTTP classification/retry limits;
- metadata cooldown/session-latch lifetime;
- cross-surface metadata single-flight and stale-commit rejection;
- JPEG body/type/size, pre-decode header dimensions, and decoded-shape validation;
- LRU eviction;
- cache-epoch clear versus in-flight fetch race;
- latest-only request replacement;
- stale response suppression;
- exact serialized oldest-first response-queue overflow with two producers;
- mosaic orientation;
- inverse raster warp;
- partial/no-data alpha;
- worker shutdown;
- no disk I/O;
- optional live service smoke.

Use synthetic image arrays, byte fixtures, mocked URL responses, and injected
clocks/waits. Do not use Tk.

The optional live test must be skipped unless:

```text
JPG_BOUNDARY_LIVE_ESRI_TEST=1
```

Even when enabled, it may fetch only metadata and one known valid tile and must
write no cache.

### 3.7 `tests/test_gui_scale_bar.py` - new

Use Matplotlib `FigureCanvasAgg` and pyproj; do not require Tk or network.

Cover:

- nice value selection;
- at-most-two-decimal formatting;
- exact minimum behavior;
- EPSG:32615;
- EPSG:32755 as the exact southern UTM fixture;
- EPSG:3857 centered exactly at 0.0 and 60.0 degrees latitude to catch
  projected-map-metre distortion assumptions;
- EPSG:2263 (NAD83 / New York Long Island (ftUS)) as the exact non-metre fixture;
- inverted limits;
- zero-width/height limits;
- NaN/inf limits;
- invalid EPSG;
- transform failure;
- extremely small axes;
- hide below 0.01 mi;
- endpoint bisection convergence;
- numeric verification tolerance;
- idempotent artist update;
- axes clear/rebind;
- resize/view signature;
- draw recursion guard;
- passive controller clear/rebind.

### 3.8 `tests/test_gui_input.py` - modified

Update the shared `_app` test context to inject a no-network basemap client and to
shut down the app/controller cleanly before destroying the root.

Add GUI integration tests for:

- main toolbar toggle/status existence and mapping;
- direct interaction callback count remains exactly four;
- separate controller callback registry exists and does not duplicate;
- result draw creates exactly one scale bar;
- repeated draw does not duplicate scale/attribution/image artists;
- image has a lower z-order than all boundary lines;
- vector limits and aspect are identical before and after applying a frame;
- imagery toggle leaves the boundary-result cache, result generation, processing
  queue/busy state, output fields, and vector/scale artists unchanged;
- imagery toggle off removes image/attribution, invalidates optional requests, and
  clears only the transient decoded-tile cache;
- a tile fetch completing after imagery disable or input-change clear cannot
  repopulate the transient tile cache;
- imagery off restores both Figure/axes colors through the existing theme helpers,
  removes imagery/attribution, and retains exactly one scale group;
- off-state pan/zoom/navigation/resize refreshes the scale while producing zero
  new basemap submissions/HTTP-attempt reservations or lazy worker starts after
  disable commits;
- pending Tk debounces are canceled, their callbacks recheck imagery enabled, and
  at most two pre-authorized calls (one per active slot) may return only to be
  discarded;
- input change rejects old response;
- new result with same limits but different identity rejects old response;
- main wheel zoom and direct pan schedule only a debounced latest request;
- programmatic limit change plus draw represents toolbar navigation;
- focus resize reuses the main controller;
- Inspector has independent controller/view/status;
- Inspector direct callback count remains four;
- Inspector close disconnects controller callbacks;
- Inspector reopen cannot accept an old-generation result;
- shared tile client/cache is not duplicated;
- offline failure leaves Update Preview and Export KMZ states unchanged;
- basemap result never calls `_set_busy`;
- Settings/Key overlay states preserve view and keep attribution unobstructed while
  either overlay is open;
- minimum-size toolbar controls remain in bounds;
- empty redraw is safe;
- current dark theme remains the loading/offline fallback and the exact
  user-selected Original Background;
- saved figure artist set includes attribution when imagery is visible.

Existing drag/drop, browse, settings, stale-preview, preview/export, focus, Inspector,
layout, and window tests remain.

### 3.9 `README_JPG_BOUNDARY_KMZ.md` - modified

Update only relevant documentation:

- replace the "without an imagery basemap" statement;
- describe default-on checked World Imagery and the shared main/Inspector toolbar
  toggle;
- name unchecked mode `Original Background` and explain that it restores the exact
  original dark preview, removes imagery/attribution, and authorizes no new imagery
  request/HTTP attempt after disable commits, but retains vectors, the dynamic
  scale, navigation, Update Preview, and Export KMZ;
- note that at most one already-reserved/in-flight bounded call per active worker
  slot (two total) may later enter/return and is discarded without retry,
  subsequent fetch, metadata/cache commit, publication, or display;
- explain dark loading/offline fallback separately from the intentional
  user-selected Original Background mode;
- explain that the scale bar is locally geodesic, in miles, and updates with view;
- state labels use up to two decimals;
- state imagery is display-only and never included in KMZ;
- state internet is optional for core functionality;
- state no Esri token is currently required for the supplied public endpoint;
- avoid calling it open/unrestricted/free;
- include Esri/provider attribution;
- link the official service item, REST tile documentation, attribution guidance,
  and terms;
- state no persistent/offline tile cache is created;
- explain that online requests reveal viewed tile locations and normal network
  information to Esri;
- document `JPG_BOUNDARY_LIVE_ESRI_TEST=1` as a maintainer-only opt-in test;
- retain all current drag/drop, browse, control, Inspector, and export docs.

### 3.10 Files that do not change

No changes are required in:

- `requirements_jpg_boundary_kmz.txt`;
- either launcher;
- theme tokens;
- window geometry helper;
- core result/data models;
- core generation/export;
- KML/KMZ parsers;
- geometry and sectioning modules;
- output folder content.

## 4. Risk matrix

| Risk | Likelihood | Impact | Mitigation | Verification |
| --- | --- | --- | --- | --- |
| WGS84 tiles placed with Web Mercator/XYZ math | Medium without controls | Critical geographic misalignment | Validate metadata and use published WGS84 row/column formulas | Known tile extent and synthetic mosaic tests |
| Corner-only raster transform misaligns imagery | Medium | High | Require inverse per-pixel reprojection | Control-grid/RMS warp tests |
| Basemap changes existing vector geometry/view | Medium | High | Keep projected artists/bounds/aspect unchanged; raster only | Before/after limit, artist coordinate, and aspect tests |
| Service unavailable or later authenticated | Medium | Low to core, medium to UX | Nonmodal dark fallback; no provider dependency for processing/export | Offline/401/403/timeout tests |
| Provider schema changes | Low/medium | High if silently accepted | Strict runtime metadata validation; fail closed for imagery | Altered fixture rejection tests |
| Terms/attribution violation | Medium without controls | High | Visible live attribution; online-only memory; no tile export/disk cache | Artist/save tests, filesystem spy, README review |
| Settings/Key overlay covers attribution | Medium | Medium | Responsive placement in unobstructed left preview region | Minimum-size overlay manual/GUI tests |
| Tile jobs accumulate during pan | High without controls | Medium/high | 300 ms debounce, latest-only per surface, generation checks | Coalescing and rapid-pan tests |
| Late result paints wrong input/view | High without token | High | Surface generation, result generation, EPSG, limits, size signatures | Input/result/close/reopen stale tests |
| Network/warp blocks Tk | Medium | High | All fetch/decode/mosaic/warp on daemon worker | Thread-identity and responsiveness tests |
| Worker prevents application close | Medium | Medium | Daemon worker, stop event, short timeout, no blocking join | Shutdown-during-timeout test |
| Main and Inspector starve each other | Medium | Medium | Dedicated bounded daemon worker slot per active surface | Dual-surface blocked-request test |
| Excess tile/mosaic memory | Medium | High | 24-tile, 1.5M-pixel, 32 MiB cache caps | Boundary/cap/eviction tests |
| JPEG bomb or wrong payload | Low/medium | High | Streamed body cap plus bounded JPEG SOF dimension validation before decode; decoded-shape recheck before cache | Huge-declared-dimension, oversize, corrupt, and decoded-shape tests |
| Redirect reaches unapproved host | Low | Medium/security | Validate fixed scheme/host and final response host | Redirect-host test |
| Projection transform returns invalid values | Low | Medium | Nonfinite masks and nonfatal failure | Invalid/extreme CRS tests |
| Antimeridian becomes world-wide request | Low for current data | High | Perimeter longitude unwrapping and column wrap | Dateline tests |
| High-latitude/large view has poor LOD | Low/medium | Medium | Ground-based center resolution plus tile cap | Equator/high-latitude LOD tests |
| Partial tiles paint opaque black squares | Medium | Medium | Separate validity mask and transparent alpha | Partial mosaic tests |
| Bilinear resampling creates seam/flip | Medium | Medium | Pixel-center math and synthetic quadrant fixtures | Orientation/seam tests |
| Basemap artist autoscales axes | Medium | High | Save/restore limits and explicit z-order | Navigation history/limits tests |
| Imagery toggle replaces the original theme or removes/stales the scale | Medium without an explicit contract | High to requested UX | Reuse the existing figure/axes theme helpers; keep scale ownership provider-independent and refresh it after disabling imagery | Exact facecolor, artist-count, zero-request, and off-state navigation assertions |
| Disable commits between worker cancellation check and synchronous opener entry | Medium without authorization boundary | Medium: a supposedly disabled view could start more work | Atomic per-slot attempt reservation under the client lock; revoke later reservations through generation/registration/cache epochs; permit at most one pre-authorized call per active slot to return only to be discarded | Deterministic post-reservation/pre-opener barrier with two active slots, reservation-count and no-commit/publication assertions |
| Draw callback loops | Medium | High | View signatures and guarded single follow-up draw | Bounded draw-count tests |
| Repeated axes clear duplicates artists/callbacks | Medium | Medium | Idempotent reset/rebind lifecycle | Repeated redraw/reopen tests |
| Scale label uses raw UTM metres inaccurately | Medium without controls | High to requested accuracy | Inverse CRS transform plus geodesic endpoint distance | UTM/Web Mercator/high-lat tests |
| Scale rounds to misleading `0.00 mi` | Medium | Medium | Minimum 0.01 mi and hide rule | Formatting/small-view tests |
| Scale and attribution overlap | Medium | Medium | Reserved responsive vertical positions | Minimum-size main/Inspector tests |
| Line colors disappear over imagery | High | Medium | Modest halos and existing distinct colors | Bright/dark synthetic image visual test |
| Basemap failure changes busy/export state | Low with isolation | High | Separate queue/status; prohibit `_set_busy` | Mock assertions and export-during-load test |
| Dirty worktree causes overwrite/regression | High | High | Phase-0 hashes, temp backups, allow-list, AST manifest | Pre/post scope audit |
| Tracked `.pyc` changes again | High without `-B` | Low/noise | Run all Python commands with `-B`; treat pyc as pre-existing | Final status/hash comparison |

## 5. Assumptions and unknowns

### 5.1 Assumption register and mandatory classification

| ID | Assumption | Classification | Evidence/risk control |
| --- | --- | --- | --- |
| A-01 | The feature is for online in-app visualization, not offline imagery distribution. | Likely but not fully proven | The request concerns preview background; the item forbids offline tile export; this plan hard-scopes the implementation to live display. No different runtime behavior depends on intent. |
| A-02 | The exact supplied endpoint is authoritative for this feature. | Likely but not fully proven | External rather than repository evidence: it matches Esri's authoritative World Imagery WGS84 item and replacement guidance and was queried directly. Runtime schema validation isolates later changes. |
| A-03 | Current no-token access can change later. | Unverified risk | Future provider policy is unknowable. Authentication failure is isolated to the optional imagery layer and falls back without inventing a token UX. |
| A-04 | Existing projected preview behavior has priority over avoiding raster-warp complexity. | Verified from code | Current code and tests use projected result geometry, projected bounds, and equal aspect; the user explicitly protects existing functionality. |
| A-05 | A bounded process-memory render cache is transient display state rather than an offline tile product. | Likely but not fully proven | External terms prohibit offline storage; mapping clients necessarily hold active render data. This implementation caps memory, never serializes it, and clears it on input change, disable, and shutdown. |
| A-06 | Static preview image saving may continue only with embedded attribution. | Likely but not fully proven | External primary evidence: ArcGIS.com terms Section 3.2(b) permits attributed static electronic data representations. The implementation embeds live Esri/provider attribution and never exposes raw tiles. |
| A-07 | Scale accuracy means geodesic accuracy at the bar's lower-left anchor. | Likely but not fully proven | This is the fixed engineering interpretation of a dynamic map scale; it is measurable, documented, and does not claim constant scale over the whole map. |
| A-08 | "Up to two decimal places" means a maximum, not forced trailing zeros. | Likely but not fully proven | It follows the user's exact wording and yields the conventional readable examples in Section 3.3. |
| A-09 | The current themed surface is the exact `Original Background` shown whenever imagery is disabled, while the scale remains provider-independent. | Verified from code and fixed by user request | `PALETTE.BACKGROUND_DEEP == "#0f0f0f"` and both Matplotlib styling helpers use it; the existing dark-theme redraw test protects that baseline. The toggle test additionally locks scale retention/refresh and zero new imagery submission/attempt authorization after the disabled state commits. |
| A-10 | No preference/config persistence is required. | Likely but not fully proven | The request asks for the view capability, not a preference subsystem; the fixed session-only toggle avoids any configuration/API/schema expansion. |

No assumption is classified as `Blocker requiring clarification`. The one
`Unverified risk` concerns future external service policy and is fully isolated by
the nonfatal fallback; it does not require user confirmation or a materially
different implementation.

### 5.2 Unknown external state isolated at runtime

These do not require user decisions because the implementation has deterministic
safe behavior:

- Esri uptime and latency.
- Future Esri endpoint authentication or URL changes.
- Future provider attribution changes.
- Missing individual cached tiles.
- Proxy, DNS, TLS, firewall, or rate-limit behavior.
- Exact imagery currency/coverage for a particular input.

Every case affects only the optional imagery layer. It cannot block preview
generation, scale drawing, or export.

### 5.3 No unresolved user decision

No unresolved choice changes the implementation contract:

- provider URL is supplied;
- display architecture is fixed;
- toggle behavior is fixed;
- default state is fixed;
- units/precision are supplied;
- attribution/cache behavior is constrained by verified service metadata;
- failure behavior is fixed;
- no backend or output change is permitted.

No open-decisions sidecar is required.

## 6. Edge cases and failure modes

### 6.1 Result/view state

- No input selected: no imagery request; no scale.
- Input selected but no preview generated: no imagery request; no scale.
- Preview result becomes stale after a settings edit: retain current result,
  imagery, and scale just as the vector preview remains visible; stale badge still
  controls interpretation.
- Input text changes: immediately remove imagery/scale and invalidate generations.
- Result regeneration returns same bounds: result generation still invalidates the
  old response.
- Result CRS changes: remove old image before scheduling the new CRS.
- Empty/degenerate bounds: no request and hidden scale.
- Inverted limits after user action: normalize for request/math without changing
  stored axes direction; apply result only if exact signed limits still match.
- Nonfinite limits: hide optional overlays and preserve vectors/UI.

### 6.2 Navigation

- Rapid wheel events: update scale for final draw and submit only final debounced
  imagery view.
- Long direct drag: no job per motion; old imagery may remain under overlap.
- Toolbar rectangle zoom: draw observer schedules final view.
- Toolbar Home/Back/Forward: exact limits remain authoritative.
- Pan beyond cached imagery: uncovered regions remain dark until valid tiles load.
- Resize to zero/hidden axes: do not request.
- Focus enter/exit: reuse main generation family; resize signature controls request.
- Settings/Key overlay: overlay does not alter axes limits; no unnecessary tile
  request solely from lifting/hiding it unless actual canvas pixels change.
- Original Background mode: all scale refresh routes above remain active, but the
  imagery scheduler returns before lazy-client creation or request submission.

### 6.3 Geographic limits

- Antimeridian: unwrap longitudes around view center and wrap request columns.
- Longitude beyond `[-180, 180]` after panning: request wrapped columns and retain
  unwrapped mosaic placement.
- Latitude beyond service matrix: clip tile requests; invalid output pixels remain
  transparent/dark.
- Very broad view: lower LOD until <=24 tiles.
- Extremely narrow/high zoom: cap at LOD 22; Matplotlib may upscale the best
  available imagery.
- Multiple UTM zones in one broad input: honor the result EPSG supplied by core;
  do not invent a new preview CRS.
- Southern hemisphere: `always_xy=True` and EPSG metadata drive transforms.

### 6.4 Service and HTTP

- Metadata timeout: status unavailable; cooldown; vectors/scale continue.
- Metadata JSON malformed/truncated: reject for exactly 30 seconds.
- Metadata body too large, an explicitly non-JSON content type with no safely
  valid JSON body, any 4xx other than 408/429 (including 404), another unhandled
  final status/nonretryable URL error, or valid JSON reporting
  EPSG:3857/unexpected tile size/format/attribution: latch incompatible for the
  application session.
- Explicit imagery off/on clears a transient cooldown for one immediate retry but
  never clears the incompatible-session latch.
- 301/302 off allowed host: reject.
- tile 400-499 other than 404/408/429 and any other unhandled final status: fail
  current refresh with no retry.
- 404 tile: transparent missing tile.
- 408/429/5xx/timeout/retryable URL reason: one retry only.
- HTML error with HTTP 200: content-type/decode validation rejects it.
- JPEG header declares wrong/huge dimensions: reject before decoder invocation.
- JPEG header says 256 x 256 but decoded shape differs: reject defensively.
- Grayscale JPEG: normalize to RGB.
- Partial response/body limit: reject.
- Service returns attribution empty: do not display imagery.
- Tilemap child remains unused even though advertised.

### 6.5 Worker/cancellation

- New main view while old main request fetches: generation check aborts old work
  after the current bounded request.
- Inspector request while main request exists: retain one latest request in each
  dedicated worker slot; neither waits behind the other.
- Toggle off during fetch: invalidate generations, advance the cache epoch, remove
  imagery/attribution from both active surfaces, restore their exact existing
  background styling, refresh their scales, and discard the response without
  cache insertion. Python's synchronous `urlopen` call is not forcibly terminated.
  No reservation may be authorized after disable commits, but at most one
  pre-authorized call per active worker slot (two total) may enter/return. Each
  then fails the cancellation/epoch checks before retry, next-tile/metadata fetch,
  metadata/cache commit, warp, enqueue, or application; raw opener count is not a
  post-commit invariant.
- Input changes during warp: final generation check discards output.
- Inspector closes during fetch: unregister surface; response is discarded.
- Inspector closes and reopens: use a new unique surface generation/identity.
- App closes during timeout: daemon worker does not block process; no Tk callback.
- Response queue full: unconditionally drop the oldest queued item, enqueue the new
  item, and retain the newest four in FIFO order; never inspect payload validity or
  block the worker.

### 6.6 Raster

- One/more missing tiles: alpha exposes dark background.
- All missing: remove/retain no image and show unavailable.
- Mosaic spans antimeridian: display columns remain monotonically ordered.
- Output coordinates fall just outside source due floating error: constant alpha
  zero, no index exception.
- Bilinear mask fringe: alpha may feather one source pixel; it must never create
  opaque imagery from invalid data.
- Worker memory error: catch at feature boundary, clear temporary arrays, preserve
  dark fallback.
- Result larger than output cap: downsample render only; vector geometry remains
  full resolution.

### 6.7 Scale bar

- Invalid EPSG or transformer failure: hide scale only.
- Nonfinite geodesic output: hide.
- Distance nonmonotonic over an extreme world view: fail verification and hide.
- Target under 0.01 mi: hide; never show `0.00`.
- Target exactly on a nice threshold: select that threshold deterministically.
- Very large distance: format non-scientifically while remaining <=2 decimals.
- Resize changes axes pixels but not data limits: recalculate visual fraction.
- Axes clear: recreate once.
- Draw recursion: guarded one-follow-up maximum.
- Network failure: no effect.

### 6.8 UI and output

- Imagery toggle while processing busy: toggle remains a view control and may
  operate without affecting processing widgets.
- Toggling from main or Inspector changes the one shared BooleanVar, so both
  controls and both active surfaces enter/leave Original Background mode together.
- Export while imagery loads: follows current export state and path.
- Toolbar Save while imagery visible: image includes attribution and scale.
- Toolbar Save while imagery unavailable/off: contains the exact original
  background, vectors, and scale, with no imagery or Esri attribution.
- Settings and Key remain mutually exclusive.
- Drag/drop and browse remain functional.
- Permanent Update/Export actions remain visible.
- No new modal window is required for normal imagery behavior.

## 7. Strict file allow-list

Implementation may create or modify only the files in this table:

| Path | Change type | Why necessary | Related tests | Risk | File-specific rollback |
| --- | --- | --- | --- | --- | --- |
| `src/jpg_boundary_gui_basemap.py` | Create | Isolates fixed-service metadata validation, WGS84 tile math, HTTP hardening, bounded memory cache, worker slots, mosaic assembly, and projected inverse raster warp from the GUI/controller and protected core. | Every `tests.test_gui_basemap` test; GUI frame/stale/offline tests in `tests.test_gui_input` | High: network, CRS, concurrency, memory | Delete this exact new file after verifying its resolved path is inside the repository; restore callers from the prior phase snapshot. |
| `src/jpg_boundary_gui_scale_bar.py` | Create | Isolates geodesic mileage selection, formatting, endpoint verification, and passive Matplotlib scale artists. | Every `tests.test_gui_scale_bar` test; GUI scale lifecycle tests in `tests.test_gui_input` | Medium: accuracy and draw lifecycle | Delete this exact new file after path verification; restore callers from the prior phase snapshot. |
| `src/jpg_boundary_kmz_gui.py` | Modify | Owns Tk variables, toolbar controls, two preview surfaces, main-thread artist application, debounce/queue polling, result-generation tokens, and shutdown integration. | Existing/new `tests.test_gui_input`; `tests.test_gui_window`; protected AST audit; full suite | High: central GUI and existing workflow | Restore only this file from the external Phase 0 or latest passing phase snapshot; never restore from `HEAD`. |
| `tests/test_gui_basemap.py` | Create | Provides deterministic, no-network unit/worker/warp tests plus the skipped opt-in service smoke. | Self; full discovery | Low | Delete this exact new test file with its module if its phase is rolled back. |
| `tests/test_gui_scale_bar.py` | Create | Provides Agg/pyproj scale math and passive artist lifecycle tests. | Self; full discovery | Low | Delete this exact new test file with its module if its phase is rolled back. |
| `tests/test_gui_input.py` | Modify | Injects a no-network client, performs clean controller shutdown, and verifies real Tk integration while preserving all current GUI regression tests. | `python -B -m unittest tests.test_gui_input -v`; full discovery | Medium: shared GUI test harness | Restore only this file from the relevant external phase snapshot. |
| `README_JPG_BOUNDARY_KMZ.md` | Modify | Replaces the obsolete no-basemap statement and documents controls, scale semantics, online/offline behavior, attribution, privacy, cache, test switch, and KMZ exclusion. | Documentation checklist, link/manual review, `git diff --check` | Low | Restore only this file from the Phase 5 snapshot if documentation validation fails. |

### 7.1 Explicitly excluded

Do not modify:

```text
requirements_jpg_boundary_kmz.txt
run_jpg_boundary_gui.py
run_jpg_boundary_gui.bat
src/jpg_boundary_kmz_core.py
src/camera_preflight.py
src/geometry_hardening.py
src/kml_vector_input.py
src/natural_sectioning.py
src/outline_strategies.py
src/polyline_boundary.py
src/section_ordering.py
src/run_jpg_boundary_gui.py
src/jpg_boundary_gui_theme.py
src/jpg_boundary_gui_window.py
tests/test_core_regression.py
tests/test_gui_window.py
tests/test_camera_preflight.py
tests/test_geometry_hardening.py
tests/test_kml_vector_input.py
tests/test_natural_sectioning.py
tests/test_outline_strategies.py
tests/test_polyline_boundary.py
tests/test_section_ordering.py
outputs/**
.vscode/**
**/__pycache__/**
**/*.pyc
```

No generated screenshot, downloaded tile, metadata JSON, cache, benchmark output,
or temporary backup may be written inside the repository.

If implementation appears to require another file:

1. stop;
2. identify the exact missing responsibility;
3. prove why an allow-listed file cannot safely own it;
4. amend and re-audit this plan before changing that file.

## 8. Implementation phases and gates

### Phase 0 - Baseline, backup, and scope lock

#### Goal

Freeze an evidence-backed working-tree baseline before any implementation edit so
the existing GUI revamp, backend behavior, and user-owned dirty changes can be
distinguished from this feature.

#### Phase-local file allow-list

- Repository writes: none.
- Read-only inspection: every tracked/untracked repository path needed for
  inventory, hashing, tests, and import verification.
- External writes: one task-specific directory under the resolved OS temporary
  directory, verified to be outside the repository.

#### Preconditions

- Work in the current workspace.
- Do not clean, reset, restore, checkout, or overwrite the existing dirty files.
- Confirm the branch/commit and current status.

#### Steps

1. Record:
   - `git rev-parse --abbrev-ref HEAD`;
   - `git rev-parse HEAD`;
   - `git status --short`;
   - `git diff --stat`;
   - `git diff --numstat`.
2. Create a task-specific directory under the OS temporary directory with
   `phase-0` through `phase-5` child snapshot locations.
3. Resolve and verify the temp path is outside the repository.
4. Copy every existing allow-listed file and the tracked `.pyc` to that temp
   baseline directory. Record hashes.
5. Record repository-wide tracked/untracked inventory.
6. Generate normalized AST hashes for all protected methods in Section 3.5 from
   the working copy and store that manifest in the temp directory.
7. Record hashes for every excluded core/runtime file.
8. Run the required baseline test command below.
9. Require 161 passing baseline tests. If test discovery count changes before any
   implementation edit, investigate rather than rewriting the expected count.
10. Confirm imports of NumPy, pyproj, SciPy, and Matplotlib image APIs.
11. Do not run a live service request as a prerequisite; live evidence is already
    captured and the implementation must remain offline-testable.

#### Static/lint/type/build checks

- No repository linter, static type checker, packaging build, or GUI bundle step is
  configured; those checks are verified not applicable for this phase.
- Run a no-bytecode syntax compile of the existing GUI:

  ```powershell
  python -B -c "from pathlib import Path; p='src/jpg_boundary_kmz_gui.py'; compile(Path(p).read_text(encoding='utf-8'), p, 'exec')"
  ```

#### Required tests

```powershell
python -B -m unittest discover -s tests -v
```

Expected result: exactly 161 passing baseline tests and no skip, error, or failure.

#### Expected outputs

- external temporary backup;
- file-hash manifest;
- protected-method AST manifest;
- baseline test log;
- exact dirty-state record.

#### Gate

Proceed only if:

- all 161 tests pass;
- baseline hashes match Section 2.10 or any difference is explicitly attributed to
  user edits made after this plan;
- no existing change is overwritten;
- the temp backup can be read;
- protected methods are found exactly once.

#### Explicit failure criteria

Phase 0 fails if any baseline test fails, the current branch/commit/dirty state
cannot be recorded, a protected symbol is absent or duplicated, the external
backup cannot be verified/read, a syntax/import check fails, or any repository
file changes during the phase.

#### Rollback

No production edit has occurred. Stop with the current workspace unchanged.

### Phase 1 - Pure service schema, tile math, cache, and raster warp

#### Goal

Prove every coordinate, tiling, cache, and raster-placement rule with deterministic
pure code before introducing a network request or touching the GUI.

#### Phase-local file allow-list

- Create/modify `src/jpg_boundary_gui_basemap.py`.
- Create/modify `tests/test_gui_basemap.py`.
- Read-only: all other repository files.
- External write: verified OS-temp `phase-1` snapshot directory only.

#### Preconditions

- Phase 0 gate passed.
- No file outside the allow-list has changed.

#### Steps

1. Add `src/jpg_boundary_gui_basemap.py` data models and constants.
2. Implement pure metadata parsing/validation.
3. Implement WGS84 tile matrix and half-open tile-range math.
4. Implement longitude unwrapping and antimeridian column wrapping.
5. Implement projected perimeter sampling and WGS84 extent calculation.
6. Implement bounded output dimensions and ground-aware LOD choice.
7. Implement lock-protected memory-only LRU.
8. Implement mosaic layout and validity mask.
9. Implement inverse projected-grid to WGS84 mapping.
10. Implement bilinear RGB and alpha sampling.
11. Add `tests/test_gui_basemap.py` pure tests for all above behavior.
12. Do not add HTTP or Tk integration until pure placement is proven.
13. After every other test/static/gate assertion passes, copy the two phase-local files
    to external `phase-1`, record hashes, and read-verify the copies before Phase 2.

#### Static/lint/type/build checks

- No configured linter, type checker, packaging build, or bundle step applies.
- Run:

  ```powershell
  python -B -c "from pathlib import Path; p='src/jpg_boundary_gui_basemap.py'; compile(Path(p).read_text(encoding='utf-8'), p, 'exec')"
  python -B -c "from pathlib import Path; ps=['src/jpg_boundary_gui_basemap.py','tests/test_gui_basemap.py']; bad=[f'{p}:{i}' for p in ps for i,s in enumerate(Path(p).read_text(encoding='utf-8').splitlines(),1) if s.rstrip(' '+chr(9)) != s]; assert not bad, bad"
  git diff --check -- src/jpg_boundary_gui_basemap.py tests/test_gui_basemap.py
  ```

#### Required tests

```powershell
python -B -m unittest tests.test_gui_basemap -v
python -B -m unittest tests.test_core_regression tests.test_gui_input -v
```

#### Expected outputs

- a deterministic, GUI-independent basemap support module;
- pure tests proving metadata validation, tile addressing, adaptive extent
  sampling, caps, LRU behavior, orientation, and inverse raster warp;
- a readable external Phase 1 snapshot and hash manifest;
- no socket use, Tk object, downloaded file, or repository cache artifact.

#### Gate

Proceed only if:

- level-0 and high-level known tile extents pass;
- row/column order and orientation pass;
- dateline tests request a narrow wrapped range;
- 24-tile/output-pixel caps pass;
- synthetic UTM warp control points meet Section 9 tolerance;
- missing data is transparent;
- cache limits/eviction pass;
- existing core/GUI tests remain green;
- no network request is present in these tests;
- the Phase 1 snapshot hashes match the passing workspace files.

#### Explicit failure criteria

Phase 1 fails if any required test/static check fails, a fixture can request more
than the declared tile/output cap, adaptive sampling cannot bound curvature within
the source-pixel tolerance, orientation/alignment acceptance is missed, any network
API is invoked, a file outside the phase allow-list changes, or the successful-gate
snapshot cannot be created and read-verified.

#### Rollback

Delete only the newly added basemap module/test and restore any modified
allow-listed file from the Phase 0 temp copy. Re-run the baseline suite.

### Phase 2 - HTTP client and latest-only worker

#### Goal

Add a bounded, fixed-host, failure-tolerant imagery transport and per-surface
latest-only execution model without allowing network latency to enter Tk or the
existing processing worker.

#### Phase-local file allow-list

- Modify `src/jpg_boundary_gui_basemap.py`.
- Modify `tests/test_gui_basemap.py`.
- Read-only: all other repository files.
- External write: verified OS-temp `phase-2` snapshot directory only.

#### Preconditions

- Phase 1 gate passed.
- Pure raster placement is accepted.

#### Steps

1. Add fixed-host metadata and tile fetch code.
2. Add response size/content/dimension/final-host validation.
3. Add categorized failure and retry policy.
4. Add the two-slot lazy daemon worker client.
5. Add per-surface latest request replacement and dedicated-slot isolation.
6. Add atomic per-slot HTTP-attempt reservations and the private reserved-open
   boundary; verify generation/registration/cache epoch before authorization and
   after return.
7. Add bounded response queue and shutdown.
8. Add dependency injection for all external/time behavior.
9. Extend `tests/test_gui_basemap.py` with mocked transport/concurrency tests,
   including a deterministic two-slot post-reservation/pre-opener disable race.
10. Add the opt-in skipped live smoke test.
11. Confirm default discovery opens no network socket by patching the opener/socket
    in tests.
12. After every other test/static/gate assertion passes, copy the two phase-local files
    to external `phase-2`, record hashes, and read-verify them before Phase 3.

#### Static/lint/type/build checks

- No configured linter, type checker, packaging build, or bundle step applies.
- Run:

  ```powershell
  python -B -c "from pathlib import Path; p='src/jpg_boundary_gui_basemap.py'; compile(Path(p).read_text(encoding='utf-8'), p, 'exec')"
  python -B -c "from pathlib import Path; ps=['src/jpg_boundary_gui_basemap.py','tests/test_gui_basemap.py']; bad=[f'{p}:{i}' for p in ps for i,s in enumerate(Path(p).read_text(encoding='utf-8').splitlines(),1) if s.rstrip(' '+chr(9)) != s]; assert not bad, bad"
  git diff --check -- src/jpg_boundary_gui_basemap.py tests/test_gui_basemap.py
  ```

#### Required tests

```powershell
python -B -m unittest tests.test_gui_basemap -v
python -B -m unittest discover -s tests -v
```

#### Gate

Proceed only if:

- every HTTP class follows the table in Section 3.2.6;
- body, pre-decode dimension, decoded-shape, and normalization limits are enforced;
- no redirect can leave the allowed host;
- no test writes a tile to disk;
- simultaneous main/Inspector startup performs one metadata request;
- pending jobs stay bounded to active surfaces;
- each worker slot holds at most one attempt reservation; after both slots are
  canceled and the cache epoch advances, no later reservation is authorized;
- a deterministic barrier proves up to two pre-authorized calls may enter/return
  after cancellation without retry, next fetch, metadata/cache commit, response
  publication, or applicable frame;
- concurrent response publication is linearizable and bounded;
- stale jobs do not enqueue applicable frames;
- shutdown during a simulated blocked request returns immediately on the caller;
- full baseline suite remains green;
- the environment-gated live test remains skipped by default;
- the Phase 2 snapshot hashes match the passing workspace files.

#### Optional evidence, not a normal gate

With explicit maintainer intent only:

```powershell
$env:JPG_BOUNDARY_LIVE_ESRI_TEST='1'
python -B -m unittest tests.test_gui_basemap.LiveEsriSmokeTests -v
Remove-Item Env:JPG_BOUNDARY_LIVE_ESRI_TEST
```

Failure of an opt-in live test due solely to external availability does not permit
loosening offline behavior or metadata validation.

#### Expected outputs

- validated fixed-host metadata/tile HTTP behavior;
- two lazy, daemonized, surface-isolated worker slots sharing one bounded
  memory-only cache;
- deterministic mocked tests for retry, metadata single-flight, cancellation,
  attempt authorization, two-slot pre-authorized return, replacement, concurrent
  queue bounds, shutdown, content validation, and redirect rejection;
- a readable external Phase 2 snapshot and hash manifest;
- an opt-in live smoke test that remains skipped during normal discovery.

#### Explicit failure criteria

Phase 2 fails if any required/static check fails, default tests can reach the
network, an off-host/non-HTTPS redirect can be followed, response or queue bounds
can be exceeded, a slot holds multiple reservations, a new attempt is authorized
after its generation/registration/cache epoch is invalidated, a pre-authorized
return retries/fetches/commits/publishes, a stale/cancelled request can publish an
applicable frame, caller shutdown blocks, a downloaded artifact reaches disk, or
a file outside the phase allow-list changes, or the successful-gate snapshot
cannot be read-verified.

#### Rollback

Restore the Phase 1 versions of `src/jpg_boundary_gui_basemap.py` and
`tests/test_gui_basemap.py` from the external snapshot, then re-run the Phase 1
static checks and gate. Do not alter any other file.

### Phase 3 - Geodesic scale-bar module

#### Goal

Implement a network-independent, CRS-aware scale bar whose displayed mileage is
derived from the actual rendered axes geometry and remains accurate under every
supported navigation path.

#### Phase-local file allow-list

- Create/modify `src/jpg_boundary_gui_scale_bar.py`.
- Create/modify `tests/test_gui_scale_bar.py`.
- Read-only: all other repository files, including the completed basemap module.
- External write: verified OS-temp `phase-3` snapshot directory only.

#### Preconditions

- Phase 2 gate passed.
- Basemap code remains independent from scale calculation.

#### Steps

1. Add `src/jpg_boundary_gui_scale_bar.py`.
2. Implement nice mileage selection and formatting.
3. Implement axes-fraction/data transform sampling.
4. Implement display-CRS-to-geodetic transform and geodesic distance.
5. Implement bounded bisection and final verification.
6. Implement the passive, idempotent artist lifecycle; GUI callback wiring remains
   deferred to Phase 4.
7. Add `tests/test_gui_scale_bar.py`.
8. Verify the controller works without a basemap or network.
9. After every other test/static/gate assertion passes, snapshot every then-existing
   allow-listed file to external `phase-3`, record hashes, and read-verify it before
   Phase 4. This captures the pre-Phase-4 GUI/test baseline.

#### Static/lint/type/build checks

- No configured linter, type checker, packaging build, or bundle step applies.
- Run:

  ```powershell
  python -B -c "from pathlib import Path; p='src/jpg_boundary_gui_scale_bar.py'; compile(Path(p).read_text(encoding='utf-8'), p, 'exec')"
  python -B -c "from pathlib import Path; ps=['src/jpg_boundary_gui_scale_bar.py','tests/test_gui_scale_bar.py']; bad=[f'{p}:{i}' for p in ps for i,s in enumerate(Path(p).read_text(encoding='utf-8').splitlines(),1) if s.rstrip(' '+chr(9)) != s]; assert not bad, bad"
  git diff --check -- src/jpg_boundary_gui_scale_bar.py tests/test_gui_scale_bar.py
  ```

#### Required tests

```powershell
python -B -m unittest tests.test_gui_scale_bar -v
python -B -m unittest tests.test_gui_basemap tests.test_gui_input -v
```

#### Expected outputs

- a passive, idempotent scale artist/controller module with no callback ownership;
- deterministic formatting and geodesic-accuracy tests across representative
  projected coordinate systems and failure cases;
- a readable external Phase 3 snapshot and hash manifest;
- no network, Tk, basemap-service, or backend-core dependency.

#### Gate

Proceed only if:

- every label has <=2 decimals;
- minimum/hide behavior is exact;
- northern UTM, southern UTM, Web Mercator at high latitude, and non-metre CRS
  tests meet tolerance;
- invalid/degenerate inputs hide without raising;
- repeated draws create one artist group;
- clear/rebind tests pass;
- no network dependency exists;
- existing GUI tests remain green;
- the Phase 3 snapshot hashes match the passing workspace files.

#### Explicit failure criteria

Phase 3 fails if any required/static check fails, a visible label exceeds two
decimals, independently measured endpoint error exceeds 0.25%, invalid CRS/view
state raises or displays a misleading value, repeated refresh duplicates artists,
the module owns Matplotlib callbacks, or a file outside the phase allow-list
changes, or the successful-gate snapshot cannot be read-verified.

#### Rollback

Remove the new scale module/test only and verify Phase 2 tests plus the full
baseline suite.

### Phase 4 - Main preview integration

#### Goal

Integrate the independently proven basemap and scale components into the main
preview while preserving the current projected vector drawing, navigation,
processing, export, window, and backend contracts.

#### Phase-local file allow-list

- Modify `src/jpg_boundary_kmz_gui.py`.
- Modify `tests/test_gui_input.py`.
- Read-only: all other repository files, including both support modules/tests.
- External write: verified OS-temp `phase-4` snapshot directory only.

#### Preconditions

- Phases 1-3 passed independently.
- Phase 0 GUI backup and AST manifest are available.

#### Steps

1. Add backward-compatible constructor injection and lazy client state.
2. Add main toolbar toggle and imagery status, including explicit Tk debounce
   cancellation plus enabled-state recheck before lazy-client creation/submit.
3. Add main surface/controller lifecycle.
4. Integrate scale binding into result and empty draws.
5. Integrate basemap request scheduling after projected fit.
6. Apply basemap frames below current vectors without changing limits/aspect.
7. Add attribution and vector legibility path effects.
8. Add separate basemap response polling.
9. Add root shutdown behavior.
10. Modify the test `_app` context to inject a no-network client.
11. Add main-surface integration tests.
12. After every other test/static/gate assertion passes, snapshot every
    then-existing allow-listed file to external `phase-4`, record hashes, and
    read-verify it before Inspector integration.

#### Static/lint/type/build checks

- No configured linter, type checker, packaging build, or bundle step applies.
- Run:

  ```powershell
  python -B -c "from pathlib import Path; paths=['src/jpg_boundary_kmz_gui.py','src/jpg_boundary_gui_basemap.py','src/jpg_boundary_gui_scale_bar.py']; [compile(Path(p).read_text(encoding='utf-8'), p, 'exec') for p in paths]"
  python -B -c "from pathlib import Path; ps=['src/jpg_boundary_kmz_gui.py','tests/test_gui_input.py']; bad=[f'{p}:{i}' for p in ps for i,s in enumerate(Path(p).read_text(encoding='utf-8').splitlines(),1) if s.rstrip(' '+chr(9)) != s]; assert not bad, bad"
  git diff --check -- src/jpg_boundary_kmz_gui.py tests/test_gui_input.py
  ```

#### Required tests

```powershell
python -B -m unittest tests.test_gui_input tests.test_gui_basemap tests.test_gui_scale_bar -v
python -B -m unittest tests.test_gui_window tests.test_core_regression -v
```

#### Expected outputs

- one main-preview World Imagery toggle/status using the existing toolbar area;
- nonblocking imagery below vectors, an always-independent dynamic scale, and
  mandatory in-figure attribution;
- an explicit `Original Background` state that reuses the existing Figure/axes
  theme styling, retains exactly one live scale group, and authorizes no new
  imagery request/HTTP-attempt reservation after disable commits; the main slot's
  one possible pre-authorized call is discarded under FD-31;
- deterministic GUI integration tests using injected no-network doubles;
- a readable external Phase 4 snapshot and hash manifest;
- unchanged projected vector arrays, signed limits, aspect, callbacks, processing
  state, output paths, and protected backend symbols.

#### Gate

Proceed only if:

- main vectors use the same data arrays and bounds as baseline;
- equal aspect remains;
- before/after imagery limits, `dataLim`, autoscale flags, and sticky-edge mode are
  exactly equal;
- four direct callback IDs remain;
- controller callbacks do not duplicate;
- scale updates on fit/zoom/pan/resize;
- imagery requests are debounced and latest-only;
- toggle does not affect boundary-result cache/busy/result/output state and toggle
  off does clear the optional decoded-tile cache;
- toggle off restores both Figure and axes to
  `matplotlib.colors.to_rgba(PALETTE.BACKGROUND_DEEP)`, removes every
  image/attribution artist, retains exactly one scale group, refreshes that scale
  through pan/zoom/resize, cancels/clears its debounce ID, and authorizes zero new
  submissions or HTTP-attempt reservations after the disabled state commits;
- a main-slot call reserved before disable may enter/return, but cannot
  retry/fetch/commit/publish/apply;
- attribution appears only with valid imagery;
- offline fallback remains dark and functional;
- core and window regressions pass;
- the Phase 4 snapshot hashes match the passing workspace files.

#### Explicit failure criteria

Phase 4 fails if any required/static check fails, the UI thread performs network
or warp work, any current vector/bounds/aspect/navigation/output behavior changes,
an image application mutates signed limits, callbacks exceed the recorded count,
imagery state contaminates `_queue`/`_busy`/boundary-result cache/output state, offline
use blocks or shows a modal, an off-state debounce creates/submits a client/job, a
post-commit attempt reservation is created, a pre-authorized return mutates shared
or visible state, a protected AST hash changes, or any file outside the phase
allow-list changes, or the successful-gate snapshot cannot be read-verified.

#### Rollback

Restore `src/jpg_boundary_kmz_gui.py` and `tests/test_gui_input.py` from the Phase 3
snapshot. Keep the independently passing Phase 1-3 support modules and tests.
Re-run the Phase 3 gate.

### Phase 5 - Inspector, focus, lifecycle, and saved-image parity

#### Goal

Extend the same basemap/scale behavior to Inspector and Focus Preview while
proving independent view state, bounded lifecycle ownership, shared caching, and
attributed toolbar image saves.

#### Phase-local file allow-list

- Modify `src/jpg_boundary_kmz_gui.py`.
- Modify `tests/test_gui_input.py`.
- Read-only: all other repository files.
- External write: verified OS-temp `phase-5` snapshot directory only.

#### Preconditions

- Main preview integration passed.

#### Steps

1. Add Inspector toolbar toggle/status using the shared BooleanVar.
2. Add independent Inspector surface/controller state.
3. Bind cached/last result EPSG and identity.
4. Add Inspector close cancellation/disconnect.
5. Verify reopen generation safety.
6. Verify main/Inspector cache sharing and view independence.
7. Verify focus reuses main controller.
8. Verify in-figure attribution and scale are included by toolbar Save.
9. Verify Settings/Key overlays leave attribution visible and unobstructed.
10. Verify toggling from either toolbar synchronously restores the original theme
    on both active surfaces, retains and refreshes one scale group per surface,
    cancels both pending debounce IDs, and authorizes no new imagery submission or
    HTTP-attempt reservation after disable commits until re-enabled.
11. Add corresponding GUI tests.
12. After every other test/static/gate assertion passes, snapshot every
    then-existing allow-listed file to external `phase-5`, record hashes, and
    read-verify it before Phase 6. This supplies the README rollback point.

#### Static/lint/type/build checks

- No configured linter, type checker, packaging build, or bundle step applies.
- Run:

  ```powershell
  python -B -c "from pathlib import Path; paths=['src/jpg_boundary_kmz_gui.py','src/jpg_boundary_gui_basemap.py','src/jpg_boundary_gui_scale_bar.py']; [compile(Path(p).read_text(encoding='utf-8'), p, 'exec') for p in paths]"
  python -B -c "from pathlib import Path; ps=['src/jpg_boundary_kmz_gui.py','tests/test_gui_input.py']; bad=[f'{p}:{i}' for p in ps for i,s in enumerate(Path(p).read_text(encoding='utf-8').splitlines(),1) if s.rstrip(' '+chr(9)) != s]; assert not bad, bad"
  git diff --check -- src/jpg_boundary_kmz_gui.py tests/test_gui_input.py
  ```

#### Required tests

```powershell
python -B -m unittest tests.test_gui_input -v
python -B -m unittest tests.test_gui_basemap tests.test_gui_scale_bar -v
python -B -m unittest discover -s tests -v
```

#### Expected outputs

- shared imagery preference/client/cache with independent main and Inspector
  request generations, axes, callbacks, artists, and navigation;
- Focus Preview reusing (not duplicating) the main surface controller;
- saved preview images containing imagery, scale, and attribution when imagery is
  valid;
- one synchronized `Original Background` mode on main and Inspector, with the
  original themed Figure/axes colors, independent live scale bars, no
  imagery/attribution, and no new imagery request/attempt authorization after
  disable commits; at most two pre-authorized calls (one per active slot) are
  discarded under FD-31;
- lifecycle tests covering close, reopen, in-flight cancellation, and stale
  responses;
- a readable external Phase 5 snapshot and hash manifest.

#### Gate

Proceed only if:

- main and Inspector pan/zoom independently;
- shared cache/client is singular;
- surface generations are independent;
- closing/reopening Inspector leaks no callback/artist/request;
- focus adds no controller;
- toggle state is synchronized between both toolbars; disabling from either one
  restores both active Figure/axes backgrounds to
  `matplotlib.colors.to_rgba(PALETTE.BACKGROUND_DEEP)`, leaves one live scale group
  on each, clears both pending debounce IDs, and produces zero new
  submissions/HTTP-attempt reservations while subsequent views change;
- up to one pre-authorized call per active slot may enter/return after disable,
  but neither can retry/fetch/commit/publish/apply;
- re-enabling requests each bound surface through normal debounce without
  regenerating or moving its boundary vectors, and resets transient metadata only
  if the shared lazy client already exists;
- scale/attribution are present in both figures when applicable;
- all baseline and new tests pass;
- callback counts remain bounded after repeated open/close/focus cycles;
- the Phase 5 snapshot hashes match the passing workspace files.

#### Explicit failure criteria

Phase 5 fails if any required/static check fails, main and Inspector views influence
one another, more than one shared client/cache exists, toggle state or mode differs
between surfaces, Original Background mode changes a vector/view/result/action
state, its scale disappears/stales, a pending debounce survives, a post-commit
attempt reservation/submission is created, a pre-authorized return mutates shared
or visible state, re-enable creates a client solely to reset metadata, a
closed/reopened surface accepts an old response, Focus Preview adds a
controller/callback, save omits required attribution, scale/imagery artists leak
or duplicate, a protected AST hash changes, a file outside the phase allow-list
changes, or the successful-gate snapshot cannot be read-verified.

#### Rollback

Restore Phase 4 GUI/test snapshot. Verify main-only integration still passes.

### Phase 6 - Documentation, full validation, and release audit

#### Goal

Document the final user-visible behavior and prove, from a clean comparison
against the recorded working-tree baseline, that the GUI-only feature is complete,
attributed, bounded, maintainable, and regression-safe.

#### Phase-local file allow-list

- Modify `README_JPG_BOUNDARY_KMZ.md`.
- Read-only validation: the six completed implementation/test files from Phases
  1-5 and every excluded/protected repository path.
- External write: one new uniquely named `phase-6-validation-<GUID>` child inside
  the verified task OS-temp root, containing only `preview-save.png` and
  `export-check.kmz`.
- If validation exposes a code/test defect, stop Phase 6 and return to the phase
  that owns that file; do not repair it under the documentation allow-list.

#### Preconditions

- All implementation phases passed.

#### Steps

1. Update README as defined in Section 3.9, including the checked World Imagery
   mode, unchecked Original Background mode, and scale independence in both.
2. Run compile/import checks with bytecode disabled.
3. Run the targeted suites.
4. Run full discovery at least twice to expose lifecycle/order dependence.
5. Run protected-method AST comparison against Phase 0 working-tree manifest.
6. Compare excluded-file hashes.
7. Compare final status against Phase 0 inventory.
8. Inspect `git diff --check`.
9. Inspect complete diffs for every allow-listed modified file.
10. Confirm no downloaded/cache/temp file exists in the repo.
11. Record the GUI's current output-name/location field values.
12. Create a new nonexisting `phase-6-validation-<GUID>` under the already
    verified external task temp root; resolve it and prove it remains under that
    root and outside the repository before writing.
13. Point toolbar Save only to its exact `preview-save.png`, point KMZ export only
    to its exact `export-check.kmz`, and perform Section 9.4.
14. Confirm both files are newly created regular files, inspect their required
    content, and record size/SHA-256 in the handoff.
15. Restore the recorded GUI output fields, then remove only those two exact
    validation files and their now-empty exact child directory after resolved-path
    verification; confirm neither file remains and no user file was overwritten.
16. Capture validation notes in the implementation handoff, not a new unplanned
    repository file.

#### Static/lint/type/build checks

- The repository has no configured linter, static type checker, packaging build,
  or GUI bundle step; these remain verified not applicable.
- The no-bytecode syntax compile and `git diff --check` commands below are the
  applicable static checks.

#### Required tests and validation commands

```powershell
python -B -c "from pathlib import Path; paths=['src/jpg_boundary_gui_basemap.py','src/jpg_boundary_gui_scale_bar.py','src/jpg_boundary_kmz_gui.py']; [compile(Path(p).read_text(encoding='utf-8'), p, 'exec') for p in paths]"
python -B -c "from pathlib import Path; ps=['src/jpg_boundary_gui_basemap.py','src/jpg_boundary_gui_scale_bar.py','src/jpg_boundary_kmz_gui.py','tests/test_gui_basemap.py','tests/test_gui_scale_bar.py','tests/test_gui_input.py','README_JPG_BOUNDARY_KMZ.md']; bad=[f'{p}:{i}' for p in ps for i,s in enumerate(Path(p).read_text(encoding='utf-8').splitlines(),1) if s.rstrip(' '+chr(9)) != s]; assert not bad, bad"
python -B -m unittest tests.test_gui_basemap tests.test_gui_scale_bar tests.test_gui_input tests.test_gui_window -v
python -B -m unittest discover -s tests -v
python -B -m unittest discover -s tests -v
git diff --check
git status --short
```

#### Expected outputs

- README coverage for service dependency, attribution, checked World Imagery
  mode, unchecked Original Background mode, dynamic scale retained in either
  mode, offline fallback, cache limits, toolbar save, and vector-only KMZ;
- two consecutive green full-suite runs plus targeted/static/manual evidence;
- matching protected AST/excluded-file hashes;
- a final diff containing only the seven files in Section 7 and no downloaded,
  generated, cache, backup, or bytecode artifacts;
- inspected/hashes-recorded then safely removed external preview/KMZ validation
  artifacts, with the GUI output fields restored.

#### Gate

Complete only if:

- each full discovery run finds exactly 211 methods with 210 passed and only the
  environment-gated live smoke skipped;
- manual online/offline behavior passes;
- alignment/scale tolerances pass;
- attribution is verified;
- no protected method/core file changed;
- diff is allow-list clean;
- both exact external validation files are removed and prior output fields restored;
- no `.pyc` changed from the Phase 0 recorded dirty baseline;
- no open issue remains.

#### Explicit failure criteria

Phase 6 fails if any command or manual case fails, any unexpected skip/error occurs,
alignment/scale tolerances are missed, attribution is absent/obscured from an
imagery-bearing figure or save, a protected/excluded hash changes, a path outside
the strict allow-list differs from Phase 0, a generated artifact exists in the
repository, the full suite is order-dependent, or any unresolved issue remains.
Failure also includes overwriting a preexisting/user file, an external artifact
escaping the verified task temp child, cleanup targeting an unresolved/broad path,
or failure to restore the prior output fields.

#### Rollback

Restore only `README_JPG_BOUNDARY_KMZ.md` to its Phase 5 external snapshot if the
documentation change itself is defective. If code/test validation fails, preserve
evidence and return to the owning earlier phase; after repair, repeat all of Phase
6 from its preconditions. On any manual-validation failure, restore the recorded
GUI output fields and remove only exact newly created temp validation files after
path verification. Never roll back user-owned pre-Phase-0 changes.

## 9. Testing and regression matrix

### 9.0 Exact automated test inventory

Every row below is an implementation requirement, not a suggested test name.
`Expected result` is the assertion contract. Any uncaught exception, unexpected
network/file access, failed assertion, timeout, or result contrary to that column
is a test failure. The exact file path in each table's subheading applies to every
row in that table.

#### Basemap tests: `tests/test_gui_basemap.py`

| Exact test target | Purpose | Expected result | Failure condition | Exact command |
| --- | --- | --- | --- | --- |
| `ServiceMetadataTests.test_parse_verified_world_imagery_fixture` | Accept the captured live service shape and explicitly permitted lexical variants without live I/O. | Exact live WKIDs/grid/origin/LODs/credit plus unknown harmless fields parse; comma-token whitespace/case variants of `TilesOnly`, `JPEG`/`JPG` case variants, absent/false `exportTilesAllowed`, and attribution whitespace normalization produce the same immutable schema. | A permitted variant/extra field breaks, a required value changes silently, or parsing reaches network/disk. | `python -B -m unittest tests.test_gui_basemap.ServiceMetadataTests.test_parse_verified_world_imagery_fixture -v` |
| `ServiceMetadataTests.test_reject_every_unsafe_metadata_mutation` | Exercise every declared parser branch with named subtests. | Nonmapping root; missing/non-boolean/false fused cache; missing/wrong-type/empty capabilities or no exact comma-token `TilesOnly`; missing/wrong service or tile WKID; wrong/noninteger rows/columns; wrong/nonstring format; nonnumeric/nonfinite origin plus just-inside/outside `abs_tol=1e-12`; LOD container/item wrong types; noninteger/duplicate/extra/missing levels; nonnumeric/nonfinite/nonpositive/nonmonotonic resolutions plus level-0 relative and level-22 absolute just-inside/outside `rel_tol=1e-12, abs_tol=1e-18`; attribution wrong type/empty-after-normalization/>500, forbidden `Cc` versus allowed tab/CR/LF normalization, `Cf`, and surrogate cases; and `exportTilesAllowed` true/wrong-type all follow the exact accept/reject boundary. Every rejection returns a context-free closed-code/static-message `ServiceMetadataError`. | Any declared branch lacks a subtest, a boundary differs from `math.isclose`, unsafe input is accepted, raw provider content leaks, contextual/sentinel failure is fabricated, or an undocumented exception escapes. | `python -B -m unittest tests.test_gui_basemap.ServiceMetadataTests.test_reject_every_unsafe_metadata_mutation -v` |
| `TileMatrixTests.test_known_matrix_extents_and_route_order` | Prove level, row, and column conventions. | Levels 0, 1, 10, 15, and 22 match the verified WGS84 matrix; level 0 is two columns by one north-to-south row; URL order is level/row/column. | An extent, count, orientation, or route component differs. | `python -B -m unittest tests.test_gui_basemap.TileMatrixTests.test_known_matrix_extents_and_route_order -v` |
| `TileMatrixTests.test_half_open_edges_clamp_without_extra_tiles` | Prevent one-tile overfetch at exact east/south boundaries. | Half-open selection and legal row/column clamping return only intersecting tiles. | An exact boundary adds a tile, loses a valid tile, or creates an illegal index. | `python -B -m unittest tests.test_gui_basemap.TileMatrixTests.test_half_open_edges_clamp_without_extra_tiles -v` |
| `TileMatrixTests.test_antimeridian_columns_wrap_in_display_order` | Keep dateline views narrow and ordered. | Wrapped column IDs are legal while mosaic display order remains west-to-east through the unwrapped view. | The request spans most of the world, reverses tiles, or duplicates a seam. | `python -B -m unittest tests.test_gui_basemap.TileMatrixTests.test_antimeridian_columns_wrap_in_display_order -v` |
| `TileMatrixTests.test_adaptive_projected_extent_meets_source_pixel_bound` | Prove curved projected edges are sampled sufficiently. | Initial perimeter/interior samples adapt until midpoint deviation is <=0.25 selected-source pixel, within depth/pass caps and one-pixel padding. | Curvature exceeds tolerance, caps are bypassed, or a nonconverging view is silently accepted. | `python -B -m unittest tests.test_gui_basemap.TileMatrixTests.test_adaptive_projected_extent_meets_source_pixel_bound -v` |
| `TileMatrixTests.test_ground_resolution_lod_at_equator_and_high_latitude` | Prove LOD selection measures ground resolution instead of treating degrees as fixed metres. | Independent `Geod` calculations at exactly 0.0 and 60.0 degrees latitude confirm the chosen advertised LOD is the coarsest whose worst horizontal/vertical pixel distance is <=1.25 times requested ground resolution, before any tile-cap backoff. | Selection violates the threshold, uses a constant-degree shortcut, or returns an unsupported LOD. | `python -B -m unittest tests.test_gui_basemap.TileMatrixTests.test_ground_resolution_lod_at_equator_and_high_latitude -v` |
| `TileMatrixTests.test_invalid_extent_and_resource_caps_fail_safe` | Enforce finite geometry, tile count, and output dimensions. | Nonfinite/degenerate views return no request; LOD backs off to <=24 tiles; output dimensions remain within constants. | Invalid geometry escapes, a cap is exceeded, or backing off selects an unsupported LOD. | `python -B -m unittest tests.test_gui_basemap.TileMatrixTests.test_invalid_extent_and_resource_caps_fail_safe -v` |
| `TileCacheTests.test_lru_count_byte_immutability_and_clear` | Prove bounded, concurrent memory-only caching. | Hits promote; count/byte eviction is deterministic; oversized new/replacement values do not mutate state; same-key replacement subtracts prior bytes, keeps count, moves key to MRU; two synchronized same-key writers linearize, last lock acquisition wins, and accounting equals final arrays; returned arrays cannot mutate storage; clear releases all; neither cap is ever exceeded. | Count/bytes/order/final value drifts, race escapes, oversized replacement removes old value, mutation leaks, cap is exceeded, or clear retains data. | `python -B -m unittest tests.test_gui_basemap.TileCacheTests.test_lru_count_byte_immutability_and_clear -v` |
| `TileCacheTests.test_cache_never_uses_filesystem` | Prove the no-disk-cache contract. | Patched file/temp/path write APIs receive zero calls during put/get/evict/clear. | Any filesystem write/open intended for caching occurs. | `python -B -m unittest tests.test_gui_basemap.TileCacheTests.test_cache_never_uses_filesystem -v` |
| `RasterWarpTests.test_identity_wgs84_orientation_and_signed_extents` | Prove raster orientation in the simplest CRS and both signed axis directions. | For normal, inverted-x, inverted-y, and doubly inverted extents, the sentinel at signed `x0`/`y1` remains at screen left/top and opposite sentinels remain at screen right/bottom; geographic cardinal directions flip when their axes are inverted. | A flip, transpose, shifted half-pixel, sorted extent, or false geographic-north-up assumption appears. | `python -B -m unittest tests.test_gui_basemap.RasterWarpTests.test_identity_wgs84_orientation_and_signed_extents -v` |
| `RasterWarpTests.test_projected_utm_control_point_accuracy` | Validate inverse warp in northern and southern UTM. | EPSG:32615 and EPSG:32755 meet <=0.75 source-pixel maximum and <=0.5 source-pixel RMS at >=9 independent controls each. | Either numeric tolerance is exceeded or a valid control becomes transparent. | `python -B -m unittest tests.test_gui_basemap.RasterWarpTests.test_projected_utm_control_point_accuracy -v` |
| `RasterWarpTests.test_bilinear_rgb_alpha_and_nonfinite_masks` | Validate interpolation and validity behavior. | Known 2x2 RGB values interpolate correctly; partial/out-of-bounds/nonfinite cells receive correct alpha; opaque controls have alpha >=254. | RGB tolerance fails, invalid pixels remain opaque, or valid pixels disappear. | `python -B -m unittest tests.test_gui_basemap.RasterWarpTests.test_bilinear_rgb_alpha_and_nonfinite_masks -v` |
| `RasterWarpTests.test_antimeridian_mosaic_has_no_flip_gap_or_cap_escape` | Validate wrapped mosaic stitching and final resource bounds. | Constant/sentinel tiles join without a one-pixel gap/flip and output/tile caps remain enforced. | A seam/orientation defect appears or an allocation exceeds a declared cap. | `python -B -m unittest tests.test_gui_basemap.RasterWarpTests.test_antimeridian_mosaic_has_no_flip_gap_or_cap_escape -v` |
| `BasemapHttpTests.test_fixed_https_url_user_agent_and_redirect_policy` | Lock transport to the supplied HTTPS host. | Exact metadata/tile URLs and User-Agent are sent; non-HTTPS or off-host redirects are rejected before follow and final URL is revalidated. | User input can alter the host, route order is wrong, or a forbidden redirect is followed. | `python -B -m unittest tests.test_gui_basemap.BasemapHttpTests.test_fixed_https_url_user_agent_and_redirect_policy -v` |
| `BasemapHttpTests.test_retry_matrix_and_cancel_aware_delay` | Prove exhaustive tile retry classification and wake predicate. | Timeout, 408, 429, 500/503/599, and `URLError` reasons `TimeoutError`/`ConnectionError`/`socket.timeout`/`socket.gaierror` retry once only after a full 250 ms condition timeout while generation stays current; 400/401/403/405/410, unhandled final statuses, and other `URLError` reasons never retry; newer submit, `cancel_surface`, and shutdown wake/suppress retry. | Any status/reason is unclassified, attempt count/timing differs, a wake is lost, or cancellation retries/waits. | `python -B -m unittest tests.test_gui_basemap.BasemapHttpTests.test_retry_matrix_and_cancel_aware_delay -v` |
| `BasemapHttpTests.test_metadata_failure_cooldown_and_session_latch` | Lock exhaustive metadata lifetime, race, and explicit retry behavior. | Timeout/retryable URL reason/408/429/5xx or malformed/truncated JSON uses cooldown with no I/O at 29.999 s and one single-flight acquisition at 30.000 s; reset changes only `COOLDOWN` to `EMPTY`; 400/401/403/404/405/410, other final status/nonretryable URL reason, oversized body, explicitly non-JSON/unparseable content, or well-formed incompatible schema latches until restart; stale fetch cannot commit; parser errors use real request context. | Any status/reason/category/lifetime boundary is undefined/different, I/O occurs during cooldown/latch/reset, reset affects another state, stale fetch commits, or sentinel context appears. | `python -B -m unittest tests.test_gui_basemap.BasemapHttpTests.test_metadata_failure_cooldown_and_session_latch -v` |
| `BasemapHttpTests.test_response_limits_content_and_decoded_shape` | Reject unsafe payloads and lock decoder normalization. | Oversized body/wrong type/corrupt JPEG/wrong height-width/channel count/nonfinite float/unsupported dtype reject without cache insertion; 2-D and 1-channel grayscale repeat to RGB; 3-channel remains RGB; RGBA drops channel four; uint8 remains exact; finite float clips to `[0,1]`, uses `rint(*255)`, and yields one contiguous read-only 256x256x3 uint8 array. | Any branch differs, unbounded bytes are read, mutation is possible, or a rejected tile is cached. | `python -B -m unittest tests.test_gui_basemap.BasemapHttpTests.test_response_limits_content_and_decoded_shape -v` |
| `BasemapHttpTests.test_jpeg_header_dimension_guard_runs_before_decoder` | Bound JPEG decompression dimensions before allocation. | Valid SOI/standalone/length-bearing segments and each allowed 256x256 SOF class reach decoder; wrong SOI, invalid/overflowing length, SOS/EOI/no-SOF, invalid component count, huge/wrong dimensions, truncation, and contradictory SOFs reject with zero decoder calls. | Marker semantics differ, unsafe header reaches decoder, allocation follows declared dimensions, or a valid bounded header is rejected. | `python -B -m unittest tests.test_gui_basemap.BasemapHttpTests.test_jpeg_header_dimension_guard_runs_before_decoder -v` |
| `BasemapHttpTests.test_missing_tile_and_consecutive_failure_abort` | Distinguish complete, sparse, and failed coverage. | 404 becomes transparent and resets the non-404 counter; valid/cache hits reset it; one/two isolated exhausted failures may emit a frame satisfying `requested=valid+missing`, `valid>0`, and `is_partial==(missing>0)`; projection-only transparent alpha does not mark partial; three consecutive exhausted non-404 failures abort with one failure and no frame. | Count/partial/counter behavior differs, a 404 becomes fatal, failures continue unbounded, or aborted frame is presented. | `python -B -m unittest tests.test_gui_basemap.BasemapHttpTests.test_missing_tile_and_consecutive_failure_abort -v` |
| `BasemapWorkerTests.test_latest_request_replaces_same_surface_pending_job` | Bound rapid navigation work and prove generation cancellation. | Distinct same-surface generations 1 then 2 leave at most generation 2 pending/active; generation 1 observes cancellation before metadata-state commit/cache put/frame enqueue; only generation 2 may publish. | Pending jobs grow, old work misses a required cancellation point, or generation 1 mutates shared/applicable output. | `python -B -m unittest tests.test_gui_basemap.BasemapWorkerTests.test_latest_request_replaces_same_surface_pending_job -v` |
| `BasemapWorkerTests.test_metadata_single_flight_across_surface_slots` | Prevent duplicate/racing service discovery. | Main and Inspector released simultaneously against `EMPTY` produce exactly one metadata HTTP call; the nonowner waits cancelably without any GUI-facing lock held across I/O; both consume the same immutable `READY` object; a canceled waiter exits; no later transient state overwrites `READY`. | More than one metadata call overlaps/occurs, a caller/worker deadlocks, waiter ignores cancellation, shared objects differ, or accepted state is overwritten. | `python -B -m unittest tests.test_gui_basemap.BasemapWorkerTests.test_metadata_single_flight_across_surface_slots -v` |
| `BasemapWorkerTests.test_main_and_inspector_slots_do_not_starve_each_other` | Prove surface isolation and bounded registration. | Main and current Inspector each retain one dedicated lazy slot while sharing immutable metadata/cache; repeated unique Inspector register/deregister cycles keep latest-map/slot registry cardinality <=2, leave no old IDs/tombstones, and missing/epoch-mismatched old work cancels. | One surface starves the other, extra worker/cache appears, registry exceeds two/grows across cycles, or an old ID remains/apply succeeds. | `python -B -m unittest tests.test_gui_basemap.BasemapWorkerTests.test_main_and_inspector_slots_do_not_starve_each_other -v` |
| `BasemapWorkerTests.test_stale_cancel_checked_through_fetch_and_warp_chunks` | Prevent expensive stale work/publication and prove the exact synchronous-I/O cancellation boundary. | Cancellation is honored before/between fetches, every 128-row warp chunk, RGB/alpha passes, and enqueue. With `READY` metadata, main and Inspector are barrier-paused after one reservation each but before opener entry; canceling both and advancing the cache epoch authorizes no later reservation. Releasing the barriers may increase raw opener count by at most two, one per slot, but both returns produce no retry/next fetch/metadata or cache commit/response/publication; reservation maps drain to empty and no stale applicable frame appears. | A slot owns multiple reservations, any reservation is authorized after invalidation, more than two pre-authorized calls enter, a returned call retries/fetches/commits/enqueues, a cancelled warp completes material work without checks, a token leaks, or an applicable stale frame appears. | `python -B -m unittest tests.test_gui_basemap.BasemapWorkerTests.test_stale_cancel_checked_through_fetch_and_warp_chunks -v` |
| `BasemapWorkerTests.test_bounded_response_queue_fifo_overflow_and_prompt_shutdown` | Prove lifecycle, concurrent overflow, and shutdown bounds. | Single-producer fifth publish evicts the first; with four prefilled items and two producers released together, the shared response lock yields exactly two recorded linearized publications, evicts exactly the two oldest prefill items, retains both new items once in lock-acquisition order, never raises `Full`/`Empty`, and `poll()`/shutdown never wait on I/O. | Item selection/order/count differs, a race exception/block occurs, queue exceeds four, or caller shutdown waits on I/O. | `python -B -m unittest tests.test_gui_basemap.BasemapWorkerTests.test_bounded_response_queue_fifo_overflow_and_prompt_shutdown -v` |
| `BasemapWorkerTests.test_cancelled_fetch_cannot_repopulate_cleared_tile_cache` | Close the input-change/disable cache race. | Disable, input change, and shutdown each advance the cache epoch and clear it; a fetch/decode released afterward fails the atomic generation/epoch check and inserts nothing. | Any canceled in-flight job repopulates the cache after clear or a same-input enabled regeneration clears it. | `python -B -m unittest tests.test_gui_basemap.BasemapWorkerTests.test_cancelled_fetch_cannot_repopulate_cleared_tile_cache -v` |
| `BasemapWorkerTests.test_default_suite_cannot_open_network_socket` | Make offline determinism enforceable. | Patched opener/socket proves all normal basemap tests make zero live calls; live test reports skipped when the opt-in variable is absent. | A default test reaches network or the live test runs unrequested. | `python -B -m unittest tests.test_gui_basemap.BasemapWorkerTests.test_default_suite_cannot_open_network_socket -v` |
| `LiveEsriSmokeTests.test_live_metadata_and_sample_tile` | Optionally detect upstream service drift. | With the opt-in variable set, live metadata still validates and one bounded sample tile is JPEG 256x256; without it, test is skipped. | When explicitly enabled, schema/tile validation fails for a reason other than diagnosed external unavailability; normal discovery must never enable it. | `$env:JPG_BOUNDARY_LIVE_ESRI_TEST='1'; python -B -m unittest tests.test_gui_basemap.LiveEsriSmokeTests.test_live_metadata_and_sample_tile -v; Remove-Item Env:JPG_BOUNDARY_LIVE_ESRI_TEST` |

#### Scale tests: `tests/test_gui_scale_bar.py`

| Exact test target | Purpose | Expected result | Failure condition | Exact command |
| --- | --- | --- | --- | --- |
| `ScaleFormattingTests.test_nice_mileage_values_and_two_decimal_labels` | Lock nice-value selection and text formatting. | `10`, `2.5`, `0.25`, `0.05`, and `0.01` render exactly as Section 9.2; no visible label has >2 decimals. | Text differs, trailing zeros appear, or precision exceeds two decimals. | `python -B -m unittest tests.test_gui_scale_bar.ScaleFormattingTests.test_nice_mileage_values_and_two_decimal_labels -v` |
| `ScaleCalculationTests.test_utm_north_and_south_geodesic_accuracy` | Validate realistic projected CRSs in both hemispheres and fixed placement. | Independent `Geod` checks for EPSG:32615 and EPSG:32755 show <=0.25% endpoint error and legal 10%-25% axes width; every spec has `start_fraction=0.03`, `y_fraction=0.08`, and `end_fraction<=0.28`. | Accuracy, width, or exact anchor/constants fail. | `python -B -m unittest tests.test_gui_scale_bar.ScaleCalculationTests.test_utm_north_and_south_geodesic_accuracy -v` |
| `ScaleCalculationTests.test_web_mercator_latitude_and_nonmetre_crs_accuracy` | Ensure scale does not assume projected units equal ground metres. | EPSG:3857 views centered exactly at latitude 0.0 and 60.0 plus EPSG:2263 (US survey feet) all meet geodesic tolerance. | A planar/unit shortcut produces an out-of-tolerance label or a different high-latitude/non-metre fixture is substituted. | `python -B -m unittest tests.test_gui_scale_bar.ScaleCalculationTests.test_web_mercator_latitude_and_nonmetre_crs_accuracy -v` |
| `ScaleCalculationTests.test_inverted_limits_use_signed_axes_endpoints` | Prove scale calculation follows the visible signed axes geometry. | Normal, inverted-x, inverted-y, and doubly inverted limits produce independently verified bars at axes-fraction anchor `(0.03, 0.08)` with <=0.25% error; reversing an axis does not change corresponding ground-distance magnitude. | Endpoints are sorted incorrectly, the anchor differs, or any inversion misses tolerance. | `python -B -m unittest tests.test_gui_scale_bar.ScaleCalculationTests.test_inverted_limits_use_signed_axes_endpoints -v` |
| `ScaleCalculationTests.test_threshold_minimum_and_extreme_views` | Cover nice-step boundaries, minimum/hide behavior, and bisection bound. | Several 1/2/5 thresholds select the largest value within width 0.25; 0.01 mi is the minimum; convergence stops at <=0.0025 error; an injected nonconverging transform performs exactly 48 iterations then hides; other invalid/small views hide. | A value exceeds target span, drops below minimum, exceeds 48 iterations, returns an unverified bar, or leaves a misleading label. | `python -B -m unittest tests.test_gui_scale_bar.ScaleCalculationTests.test_threshold_minimum_and_extreme_views -v` |
| `ScaleArtistTests.test_bind_refresh_axes_clear_rebind_is_idempotent_and_passive` | Prove artist ownership, axes-clear recreation, and callback neutrality. | Repeated bind/refresh leaves one group; `axes.clear()` followed by refresh recreates exactly one group; clear removes it; rebind updates it; controller connects zero Matplotlib callbacks. | Artists disappear permanently, duplicate/leak, or the controller owns a callback. | `python -B -m unittest tests.test_gui_scale_bar.ScaleArtistTests.test_bind_refresh_axes_clear_rebind_is_idempotent_and_passive -v` |
| `ScaleArtistTests.test_resize_and_view_signature_recalculate_only_when_changed` | Validate signature invalidation and changed-state reporting. | A pixel-bounds/DPI/limit/CRS/generation change recomputes endpoints and returns changed; an identical signature performs no recomputation and returns unchanged. | Resize leaves stale scale, an unchanged signature recomputes, or a signature field is omitted. | `python -B -m unittest tests.test_gui_scale_bar.ScaleArtistTests.test_resize_and_view_signature_recalculate_only_when_changed -v` |
| `ScaleArtistTests.test_invalid_crs_transform_and_degenerate_axes_hide_without_raise` | Keep failure safe. | Missing/invalid CRS, transform failure, nonfinite/degenerate axes, and bisection failure clear/hide the bar without raising. | An exception escapes or stale/misleading scale remains. | `python -B -m unittest tests.test_gui_scale_bar.ScaleArtistTests.test_invalid_crs_transform_and_degenerate_axes_hide_without_raise -v` |

#### GUI integration tests: additions to `tests/test_gui_input.py`

| Exact test target | Purpose | Expected result | Failure condition | Exact command |
| --- | --- | --- | --- | --- |
| `GuiInputTests.test_preview_result_draws_vectors_and_scale_without_waiting_for_imagery` | Preserve preview-first behavior. | Current vector arrays draw immediately with one scale group and injected client receives a later nonblocking request. | Vector draw waits, data changes, scale duplicates, or real network is reached. | `python -B -m unittest tests.test_gui_input.GuiInputTests.test_preview_result_draws_vectors_and_scale_without_waiting_for_imagery -v` |
| `GuiInputTests.test_valid_basemap_frame_applies_below_vectors_without_mutating_view` | Validate image placement, partial status, and navigation-state contract. | Complete and partial frames create one RGBA artist at z-order -100 with empty sticky edges; status is exactly `""` for complete and `Imagery partial` only when `is_partial`; x/y limits, `dataLim.bounds`, autoscale flags, `use_sticky_edges`, aspect, adjustable, anchor, and vectors remain equal; later Home/autoscale yields baseline vector view. | Image/status is wrong or any protected view/navigation/vector property changes. | `python -B -m unittest tests.test_gui_input.GuiInputTests.test_valid_basemap_frame_applies_below_vectors_without_mutating_view -v` |
| `GuiInputTests.test_imagery_toggle_restores_original_background_and_retains_scale` | Prove the optional imagery layer can be removed without replacing the original theme, scale, or application state. | On both main and Inspector surfaces, toggle off calls `after_cancel` for each stored debounce ID and clears it, sets `Imagery off`, invalidates optional requests, clears submitted/applied signatures, removes every `AxesImage` and imagery-attribution artist, clears only decoded tiles, and restores both Figure and axes facecolors exactly to `matplotlib.colors.to_rgba(PALETTE.BACKGROUND_DEEP)` through the existing theme helpers. Manually invoking a captured canceled debounce while off rechecks the shared flag and performs no client creation, generation increment, signature mutation, submission, or attempt authorization. Exactly one scale group remains bound to the same geodesic controller; wheel zoom, direct pan, Home, Back, Forward, toolbar Pan, rectangle Zoom, Focus resize, and Inspector resize each refresh that controller/value/geometry as applicable while disabled, within the unchanged Section 9.2 accuracy contract. Disabling before first preview starts no client; re-enabling with no bound result still creates no client and makes no reset call. With an existing client and bound results, toggle on sets `Imagery loading...`, calls `reset_transient_metadata_failure()` exactly once, and resubmits each unchanged valid view after normal debounce with one new surface generation; with no existing client but a bound result, it skips reset and creates/submits lazily only when that debounce fires. No path regenerates the boundary. `_queue`, `_busy`, boundary-result cache/settings key, result generation, outputs, vectors, limits, scale ownership, Update, and Export remain unchanged. | A debounce survives/acts while off; a facecolor differs from the existing theme token; an image/attribution remains; the scale/controller disappears, changes identity, duplicates, stales, or falls outside its existing accuracy contract; a lazy worker starts while initially off; status/cache/signature/reset/submission/generation differs; re-enable creates a client only to reset, application state changes, a modal/block occurs, or boundary regeneration occurs. | `python -B -m unittest tests.test_gui_input.GuiInputTests.test_imagery_toggle_restores_original_background_and_retains_scale -v` |
| `GuiInputTests.test_all_navigation_paths_refresh_scale_and_schedule_one_debounced_view` | Cover direct and toolbar navigation. | Wheel, direct pan, Home, Back, Forward, Pan, rectangle Zoom, resize, and draw each refresh scale; a burst collapses to one final distinct signature, increments that surface generation exactly once when debounce fires, and replaces older active work without toolbar monkey-patching; an identical signature does not increment/submit. | Any path leaves stale scale, duplicates callbacks, increments/submits a duplicate, fails to cancel older work, or produces unbounded requests. | `python -B -m unittest tests.test_gui_input.GuiInputTests.test_all_navigation_paths_refresh_scale_and_schedule_one_debounced_view -v` |
| `GuiInputTests.test_scale_changed_state_allows_only_one_guarded_followup_draw` | Prevent draw-event recursion after scale artist updates. | A changed scale requests at most one guarded follow-up `draw_idle`; the resulting draw sees an unchanged signature and schedules no further draw; resize produces one new recalculation/draw cycle. | Draw count grows recursively, a guard remains stuck, or resize leaves a stale signature. | `python -B -m unittest tests.test_gui_input.GuiInputTests.test_scale_changed_state_allows_only_one_guarded_followup_draw -v` |
| `GuiInputTests.test_focus_preview_reuses_main_map_surface` | Prevent focus-mode duplication. | Enter/exit Focus repeatedly preserves the same main controller, callback IDs, image, scale, and request generation ownership. | A new controller/callback/worker is created or state is lost. | `python -B -m unittest tests.test_gui_input.GuiInputTests.test_focus_preview_reuses_main_map_surface -v` |
| `GuiInputTests.test_inspector_has_independent_view_with_shared_client_cache_and_preference` | Validate dual-surface design. | Inspector has independent signed limits/generation/artists/callbacks while sharing exactly one client/cache and imagery BooleanVar. | Views move together, state collides, or duplicate shared resources appear. | `python -B -m unittest tests.test_gui_input.GuiInputTests.test_inspector_has_independent_view_with_shared_client_cache_and_preference -v` |
| `GuiInputTests.test_inspector_close_reopen_rejects_stale_responses_and_leaks_nothing` | Validate window/client registry lifecycle. | Close calls `deregister_surface` for the unique old ID, cancels/disconnects, and leaves client latest-map/slot count at main-only <=1; reopen uses a new ID/generation; old responses are ignored; repeated cycles keep registry, callbacks, artists, pending requests, and workers bounded with no tombstones. | Old data applies, deregistration/registry cardinality differs, an old ID remains, or any lifecycle count grows. | `python -B -m unittest tests.test_gui_input.GuiInputTests.test_inspector_close_reopen_rejects_stale_responses_and_leaks_nothing -v` |
| `GuiInputTests.test_input_change_clears_optional_map_state_and_rejects_old_generation` | Prevent cross-input contamination. | Changing/clearing input increments each affected surface generation, clears bound result token/EPSG, removes image/scale/attribution, sets imagery status `""`, advances tile-cache epoch/clears cache, and rejects old frames; it does not fabricate a newly accepted result generation. | Old optional state/status survives, bound result remains, result counter advances without a result, or object identity is used. | `python -B -m unittest tests.test_gui_input.GuiInputTests.test_input_change_clears_optional_map_state_and_rejects_old_generation -v` |
| `GuiInputTests.test_same_limits_new_result_generation_rejects_old_frame` | Prove stale identity rejection is not based only on view geometry. | Accepting a different `BoundaryResult` with identical EPSG, signed limits, and pixel size increments the app-owned result generation; a frame carrying the prior result generation is discarded without artist/status mutation. | The frame applies because limits match, object `id()` is used, or current state changes. | `python -B -m unittest tests.test_gui_input.GuiInputTests.test_same_limits_new_result_generation_rejects_old_frame -v` |
| `GuiInputTests.test_basemap_failure_is_nonmodal_and_isolated_from_processing_export` | Prove provider failure cannot enter application processing/error flow. | Current timeout/HTTP/schema/decode/projection failures set exactly `Imagery unavailable`, remove invalid optional imagery, and store only <=160-code-point static diagnostics; stale/canceled failures do not alter current status; no dialog appears and Update/Export, `_queue`, `_busy`, boundary-result cache/settings key, outputs, core calls, vectors, and scale remain unchanged. | Visible/diagnostic status leaks or differs, stale response mutates status, a modal opens, app/core state changes, controls block, or vectors/scale disappear. | `python -B -m unittest tests.test_gui_input.GuiInputTests.test_basemap_failure_is_nonmodal_and_isolated_from_processing_export -v` |
| `GuiInputTests.test_repeated_draws_keep_exact_callback_and_artist_counts` | Enforce idempotent rendering. | Existing four direct callback IDs remain exactly four; map surface owns only planned draw/resize IDs; repeated redraw creates one image, scale group, and attribution. | Callback/artist counts grow or ownership differs from Section 3. | `python -B -m unittest tests.test_gui_input.GuiInputTests.test_repeated_draws_keep_exact_callback_and_artist_counts -v` |
| `GuiInputTests.test_attribution_remains_unobstructed_with_overlays_at_minimum_layout` | Prove every parser-accepted credit stays visible in the single-page GUI. | At supported minimum main/Inspector sizes, run the real live credit, a normalized exactly-500-character multiword credit, and an exactly-500-character single-token credit through responsive word wrapping with character-level fallback; at >=9 pt the complete text remains inside the visible figure and its rendered bbox does not intersect Settings, Key, scale, or a clipped client edge while each overlay is open; no imagery hides credit. | Any character is omitted, font shrinks, credit clips/overlaps/obscures at a required state, unsafe parsing occurs, or controls clip. Closing an overlay is not acceptable. | `python -B -m unittest tests.test_gui_input.GuiInputTests.test_attribution_remains_unobstructed_with_overlays_at_minimum_layout -v` |
| `GuiInputTests.test_toolbar_save_contains_imagery_scale_and_attribution_artists` | Preserve an attributed static preview export. | A captured figure save includes all three artists when imagery is valid and does not change vector-only KMZ export. | Figure output omits credit/scale/image or KMZ gains raster content. | `python -B -m unittest tests.test_gui_input.GuiInputTests.test_toolbar_save_contains_imagery_scale_and_attribution_artists -v` |

The fully qualified targets above must also pass together, under randomized or
ordinary discovery order, through the phase commands. A method rename, merged
scenario, or altered assertion contract requires the plan to be amended before
implementation rather than silently changing the test inventory.

### 9.1 Basemap unit tests

#### Metadata

- exact live-shape fixture accepted;
- missing/false fused cache rejected;
- missing/wrong-type/no-exact-`TilesOnly` capabilities rejected;
- service or tile WKID mismatch rejected;
- rows/cols mismatch rejected;
- PNG/unexpected format rejected for this implementation;
- origin just-inside/outside the exact `1e-12` absolute tolerance;
- level-0/level-22 resolution just-inside/outside the exact relative/absolute
  tolerances;
- duplicate/missing/nonmonotonic LOD rejected;
- empty copyright rejected;
- unknown extra fields tolerated;
- malformed root returns context-free `ServiceMetadataError` without exception
  escape or invented request context.

#### Tile math

- level 0:
  - row count 1;
  - column count 2;
  - column 0 is `[-180, 0]`;
  - column 1 is `[0, 180]`;
  - row 0 is `[90, -90]` north-to-south.
- representative levels 1, 10, 15, and 22;
- point on tile boundary follows half-open rule;
- east/south exact edge avoids extra request;
- row/column clamp;
- antimeridian request wraps column but preserves display order;
- equator/high-latitude ground-resolution LOD criterion;
- >24 tile view backs off LOD;
- nonfinite extent rejected;
- degenerate extent rejected.

#### Cache

- hit promotes entry;
- count eviction;
- byte eviction;
- oversized single entry not cached;
- mutation cannot alter stored tile;
- clear empties memory;
- no file API called.

#### HTTP/worker

- exact URL order level/row/column;
- timeout and one retry;
- 429 and 5xx one retry;
- 400/401/403 no retry;
- exact 30-second transient metadata cooldown and session-incompatible latch;
- 404 transparent missing;
- wrong type;
- oversized body;
- corrupt JPEG;
- pre-decode JPEG SOF rejects huge/wrong dimensions without decoder invocation;
- decoded pixel shape mismatch;
- exact grayscale/RGB/RGBA and float-to-read-only-uint8 normalization;
- nonfinite/unsupported decoded dtype rejection;
- off-host redirect;
- three-consecutive-failure abort;
- latest request replaces prior same-surface pending;
- main and Inspector both retain one pending;
- one atomic active HTTP-attempt reservation maximum per worker slot;
- cancel-both/cache-epoch race authorizes no post-commit reservation while up to
  two pre-authorized calls may return only to be discarded;
- stale before/after fetch/warp not emitted;
- disable/input clear cache epoch prevents in-flight cache repopulation;
- shutdown signal stops new work;
- fifth response evicts oldest and preserves newest four in FIFO order without
  blocking.

#### Raster

- signed-edge sentinel colors prove display orientation for all x/y inversion
  combinations without imposing false geographic north-up;
- identity-like EPSG:4326 synthetic view;
- EPSG:32615 inverse warp;
- EPSG:32755 inverse warp;
- bilinear known 2 x 2 values;
- partial validity alpha;
- out-of-bounds transparent;
- antimeridian mosaic;
- pixel/output caps;
- nonfinite transform mask.

Numeric raster acceptance:

- for at least nine independently transformed control points in each projected
  fixture, sampled source location error must be <=0.75 source pixel;
- root-mean-square control location error must be <=0.5 source pixel;
- opaque valid control regions must have alpha >=254;
- fully invalid regions must have alpha 0;
- exact tile seams in a constant-color fixture must not produce a one-pixel flip
  or gap.

### 9.2 Scale-bar unit tests

Formatting matrix:

| Input | Expected |
| --- | --- |
| `10` | `10 mi` |
| `2.5` | `2.5 mi` |
| `0.25` | `0.25 mi` |
| `0.05` | `0.05 mi` |
| `0.01` | `0.01 mi` |

Accuracy matrix:

- EPSG:32615 at a realistic Wisconsin location;
- EPSG:32755 at a southern location;
- EPSG:3857 centered at exactly 0.0 and 60.0 degrees latitude;
- EPSG:2263 as the non-metre projected CRS;
- 0.01-mile minimum;
- distances spanning several nice-value thresholds.

For every valid bar:

```text
relative_error =
    abs(measured_geodesic_miles - displayed_miles) / displayed_miles
```

Acceptance:

- `relative_error <= 0.0025` (0.25%);
- no more than two decimals;
- selected distance does not exceed the 25% target span;
- visual width is at least 10% of axes width within numeric tolerance because the
  worst `1/2/5` step is a selected value of 2 just below an available value of 5;
- invalid/extreme cases hide instead of mislabeling.

### 9.3 GUI integration tests

| Behavior | Automated assertion |
| --- | --- |
| Initial result draw | Vectors and one scale group; no blocking network |
| Valid frame apply | One RGBA image below all vector lines |
| Limit preservation | Signed x/y limits identical before and after |
| Navigation extent preservation | `dataLim`, autoscale flags, sticky-edge mode, and later Home/autoscale result identical |
| Aspect preservation | `aspect == 1.0`, `adjustable == "datalim"` |
| Toggle off/on | Both surfaces restore the exact existing `PALETTE.BACKGROUND_DEEP` Figure/axes colors, remove image/attribution, retain one live scale that updates through off-state navigation, cancel both debounce IDs, and authorize zero new submissions/HTTP-attempt reservations after disable commits; at most two pre-authorized calls, one per active slot, may enter/return only to be discarded; re-enable requests imagery without changing boundary-result/processing/output/vector/view state |
| Offline | Scale/vectors remain; no modal; Update/Export unaffected |
| Wheel/direct pan | Existing behavior plus one debounced latest view |
| Toolbar navigation | Draw signature schedules view without toolbar patch |
| Focus | Same main controller/callback IDs |
| Inspector | Independent limits/state, shared client/cache |
| Close/reopen | No old response/callback accepted |
| Input change | Old image/scale removed and stale response rejected |
| Repeated redraw | No duplicate artist/callback |
| Attribution | Present for valid imagery, absent otherwise |
| Settings/Key | View unchanged; attribution remains visible and unobstructed while either overlay is open |
| Minimum size | Toolbar toggle/status inside client bounds |
| Save | Figure contains basemap, scale, and attribution artists |
| Processing isolation | `_queue`, `_busy`, boundary-result cache/settings key, and core calls unchanged |

### 9.4 Manual validation matrix

#### Online

1. Launch on the current monitor and confirm window fit remains correct.
2. Drag/drop a JPG folder.
3. Browse a JPG folder.
4. Drag/drop KML and KMZ inputs.
5. Browse KML/KMZ.
6. Generate a preview.
7. Confirm vector preview appears before/independently of imagery.
8. Confirm imagery aligns beneath several distinct boundary corners/segments.
9. Toggle imagery off from the main toolbar and confirm both main and Inspector
   immediately show the exact original basic background, imagery/attribution
   disappear, and the scale remains visible.
10. While imagery is off, pan, wheel zoom, use toolbar navigation, and resize both
    surfaces; confirm the mileage label/bar updates while status remains
    `Imagery off` and no image/attribution/loading cycle appears. The deterministic
    reservation test in Section 9.0 proves the underlying
    no-new-authorization boundary and safe discard of up to two pre-authorized
    calls.
11. Toggle imagery on from the Inspector and confirm both controls synchronize and
    imagery reloads without regenerating or moving the vectors.
12. Wheel zoom at the cursor.
13. Direct left-drag pan.
14. Use toolbar Home, Back, Forward, Pan, and rectangle Zoom.
15. Confirm scale label/length updates for each operation.
16. Confirm labels have <=2 decimals.
17. Open Settings and Key separately; confirm attribution remains visible,
    unclipped, and unobstructed while each overlay is open.
18. Enter/exit Focus Preview repeatedly.
19. Open Inspector and navigate it independently.
20. Change main view and confirm Inspector view does not move.
21. Toggle imagery off/on from Inspector and confirm both controls and surfaces
    follow the shared preference, the off-state scale remains dynamic with no
    image/attribution/loading cycle, and no boundary regeneration occurs.
22. Close/reopen Inspector during a load.
23. Save with the toolbar only to the verified external
    `phase-6-validation-<GUID>/preview-save.png`; inspect
    basemap/scale/attribution.
24. Set output fields to the verified external
    `phase-6-validation-<GUID>/export-check.kmz`, export, and inspect that it
    remains vector-only.
25. Change buffer/sections/overlap and Update Preview; confirm existing behavior.

#### Offline/failure

1. Disable network or inject a blocked service.
2. Generate/update preview.
3. Confirm vectors and scale remain.
4. Confirm compact `Imagery unavailable`.
5. Confirm no modal appears.
6. Confirm Settings/Key/Focus/Inspector remain usable.
7. Confirm Update Preview and Export KMZ remain usable.
8. Restore network or toggle imagery off/on and confirm safe retry.
9. Close the app while a request is timing out; confirm prompt exit.

#### Visual readability

- bright urban imagery;
- dark forest/water imagery;
- long narrow corridor;
- one and maximum section counts;
- main supported minimum size;
- Inspector minimum and maximized size;
- Settings/Key overlays;
- attribution does not overlap scale;
- colored boundaries remain distinguishable with halos.

#### Independent scale check

At a minimum of three zoom levels and two locations:

1. Record the scale endpoints in projected axes data coordinates.
2. Independently inverse-transform them with pyproj.
3. Measure with a fresh `Geod` instance.
4. Confirm <=0.25% error against the label.

Do not validate scale by comparing to the same helper instance under test.

### 9.5 Protected regression tests

Required existing categories:

- all core regression tests;
- geometry hardening;
- KML/KMZ parsing;
- natural sectioning;
- outline strategies;
- polyline boundaries;
- section ordering;
- GUI input;
- GUI window placement.

Test accounting:

```text
Baseline discovered/passed: 161
New exact test methods:      50
Expected final discovered:  211
Expected default result:    210 passed, 1 skipped
Skipped by default:         live Esri smoke only
Unexpected count/skip/error: gate failure
```

### 9.6 Test applicability and fixtures

- Unit tests: Sections 9.0-9.2.
- Integration tests: the exact `GuiInputTests` additions in Section 9.0 and the
  assertions in Section 9.3.
- Regression/backward-compatibility tests: Section 9.5 plus the full 161-test
  baseline.
- Smoke tests: the environment-gated live service test plus the manual online and
  offline launch workflows.
- Negative/error-path tests: invalid metadata, HTTP, redirect, resource, transform,
  cancellation, stale-result, lifecycle, and offline rows in Sections 9.0-9.4.
- CLI/API tests: verified not applicable because the feature adds no user-facing
  CLI, local server, route, payload, or public API. Internal ArcGIS HTTP behavior is
  covered by `BasemapHttpTests`.
- Fixture policy: capture the minimum verified service metadata fields and
  synthetic JPEG bytes/arrays inside `tests/test_gui_basemap.py`; create no external
  fixture, downloaded tile, golden screenshot, or binary repository asset.
- Existing fixture files require no update.

## 10. Pre-implementation checklist

- [ ] Read this entire plan and the named planning guide.
- [ ] Confirm current branch, commit, and dirty status.
- [ ] Confirm no newer user change conflicts with allow-listed files.
- [ ] Confirm every referenced existing baseline file, class, method, and protected
      symbol still exists exactly where the plan records it.
- [ ] Confirm each proposed new module/test path is still absent or otherwise
      available for creation, and do not require proposed symbols to exist before
      their owning phase.
- [ ] Confirm `requirements_jpg_boundary_kmz.txt` remains the only relevant
      dependency manifest, no lock file exists, and no dependency edit is needed.
- [ ] Confirm `JPG_BOUNDARY_LIVE_ESRI_TEST` is the only new environment-variable
      contract and is absent/disabled by default.
- [ ] Confirm no existing config key/schema is changed and no new persisted
      preference is introduced.
- [ ] Confirm `Original Background` means calling the already-imported
      `style_matplotlib_axes(surface.figure, surface.axes)` path and using
      `PALETTE.BACKGROUND_DEEP`, not adding a theme import, duplicate color, or new
      rendering mode.
- [ ] Confirm the shared imagery preference defaults on, can be toggled from
      either surface, and does not start a lazy client or submit work while off.
- [ ] Confirm toggle-off cancels/clears both Tk debounce IDs and every debounce
      callback rechecks imagery enabled before client creation, generation
      increment, signature mutation, or submission.
- [ ] Confirm HTTP attempts use one atomic reservation maximum per worker slot;
      disable authorizes no later reservation while at most two pre-authorized
      calls may return only to be discarded.
- [ ] Confirm re-enable resets transient metadata only when a client already
      exists and does not defeat lazy construction for empty/unbound surfaces.
- [ ] Confirm scale ownership and refresh are independent of imagery enabled,
      loading, unavailable, and off states.
- [ ] Create and verify external temp backup.
- [ ] Verify external `phase-0` through `phase-5` snapshot locations are outside
      the repository and writable/readable.
- [ ] Record all Phase 0 hashes.
- [ ] Record protected-method AST manifest from working tree, not `HEAD`.
- [ ] Run 161-test baseline with `python -B`.
- [ ] Confirm no Python command writes bytecode.
- [ ] Confirm exact fixed service URL and no user-editable URL.
- [ ] Confirm service is EPSG:4326, not Web Mercator.
- [ ] Confirm row/column route order.
- [ ] Confirm no `/export`, offline cache, or disk cache is planned.
- [ ] Confirm attribution source and display requirements.
- [ ] Confirm raster is reprojected to current result EPSG.
- [ ] Confirm vector draw sources/bounds/aspect remain projected.
- [ ] Confirm scale uses geodesic endpoints and explicit display CRS.
- [ ] Confirm minimum and formatting rules.
- [ ] Confirm worker is lazy, daemon, bounded, and Tk-free.
- [ ] Confirm default tests inject/mask all network.
- [ ] Confirm main/Inspector surface identities are independent.
- [ ] Confirm focus reuses main.
- [ ] Confirm processing queue/busy/cache/output paths are protected.
- [ ] Confirm strict allow-list is enforceable.
- [ ] Confirm every unresolved item would be recorded in the required temporary
      decision sidecar before implementation.
- [ ] Confirm all decisions are propagated consistently and the final full-plan
      audit has been completed.
- [ ] Confirm Section 14 says `Implementation Ready: YES`.
- [ ] Confirm no temporary decision sidecar or stale sidecar reference exists.
- [ ] Stop if any prerequisite cannot be proven.

## 11. Post-implementation validation checklist

### Required command list

```powershell
python -B -c "from pathlib import Path; paths=['src/jpg_boundary_gui_basemap.py','src/jpg_boundary_gui_scale_bar.py','src/jpg_boundary_kmz_gui.py']; [compile(Path(p).read_text(encoding='utf-8'), p, 'exec') for p in paths]"
python -B -c "from pathlib import Path; ps=['src/jpg_boundary_gui_basemap.py','src/jpg_boundary_gui_scale_bar.py','src/jpg_boundary_kmz_gui.py','tests/test_gui_basemap.py','tests/test_gui_scale_bar.py','tests/test_gui_input.py','README_JPG_BOUNDARY_KMZ.md']; bad=[f'{p}:{i}' for p in ps for i,s in enumerate(Path(p).read_text(encoding='utf-8').splitlines(),1) if s.rstrip(' '+chr(9)) != s]; assert not bad, bad"
python -B -m unittest tests.test_gui_basemap -v
python -B -m unittest tests.test_gui_scale_bar -v
python -B -m unittest tests.test_gui_input -v
python -B -m unittest tests.test_gui_window -v
python -B -m unittest tests.test_core_regression tests.test_camera_preflight tests.test_geometry_hardening tests.test_kml_vector_input tests.test_natural_sectioning tests.test_outline_strategies tests.test_polyline_boundary tests.test_section_ordering -v
python -B -m unittest discover -s tests -v
python -B -m unittest discover -s tests -v
git diff --check
git status --short
```

No configured linter, static type checker, package build, or GUI bundling command
exists. That verified not-applicable state must be reconfirmed before release; do
not invent a tool or dependency merely to populate this checklist.

### Automated

- [ ] New modules import successfully with `-B`.
- [ ] Basemap unit tests pass.
- [ ] Scale unit tests pass.
- [ ] GUI integration tests pass.
- [ ] GUI window tests pass.
- [ ] Core regression tests pass.
- [ ] Full discovery passes twice.
- [ ] Live smoke remains skipped by default.
- [ ] Each discovery reports exactly 211 methods: 210 passed and exactly the live
      smoke skipped.
- [ ] `git diff --check` passes.

### Scope and contract

- [ ] Final changed paths are a subset of Section 7.
- [ ] Excluded file hashes match Phase 0.
- [ ] Tracked `.pyc` hash/status did not change during implementation.
- [ ] Protected-method AST hashes match.
- [ ] `_drain_queue` is unchanged.
- [ ] `_settings_key` is unchanged.
- [ ] Core result classes are unchanged.
- [ ] Core generation/export calls and profiles are unchanged.
- [ ] No raw tile/cache/temp file exists in repository.
- [ ] Preview/KMZ manual outputs used only the verified unique external temp child,
      were inspected/hashed, and were safely removed by exact path.
- [ ] Pre-manual GUI output name/location fields were restored.
- [ ] No new dependency or launcher change exists.
- [ ] No temporary, placeholder, `TODO`, mock-only production branch, debug print,
      dead compatibility shim, or unfinished path remains.
- [ ] No temporary unresolved-decision sidecar or stale sidecar reference remains.
- [ ] Public constructors remain backward compatible.
- [ ] No public core interface, persisted config structure, schema, CLI argument,
      processing queue payload, or output naming convention changes.

### GUI behavior

- [ ] Drag/drop retained.
- [ ] Browse folder retained.
- [ ] Browse KML/KMZ retained.
- [ ] Settings/Key retained and mutually exclusive.
- [ ] Focus retained.
- [ ] Inspector retained.
- [ ] Update/Export remain permanently visible.
- [ ] Projected vector bounds/aspect unchanged.
- [ ] Basemap aligned and below vectors.
- [ ] Toggle state is synchronized on main and Inspector.
- [ ] Toggle off restores the exact original Figure/axes theme colors, removes
      imagery/attribution, cancels both debounce IDs, and authorizes no new imagery
      submission/HTTP-attempt reservation after disable commits.
- [ ] At most one pre-authorized call per active worker slot (two total) may
      enter/return after disable; neither can retry/fetch/commit/publish/apply, and
      all reservation tokens drain.
- [ ] Toggle off retains exactly one scale per valid surface and scale updates
      continue through pan, zoom, toolbar navigation, and resize.
- [ ] Toggle on reloads imagery without regenerating or changing result/output
      state, and metadata reset does not instantiate an otherwise absent client.
- [ ] Scale updates for every navigation route.
- [ ] Scale <=2 decimals and <=0.25% endpoint error.
- [ ] Offline failure is nonmodal.
- [ ] Main/Inspector independent.
- [ ] Attribution visible whenever imagery visible.
- [ ] Toolbar-saved image contains attribution.
- [ ] KMZ contains no imagery.
- [ ] App closes promptly during an in-flight request.

### Documentation

- [ ] README no longer says there is no basemap.
- [ ] README does not call content unrestricted/free/open.
- [ ] README defines checked World Imagery and unchecked Original Background
      modes, including shared main/Inspector toggle behavior.
- [ ] README explains online/offline behavior.
- [ ] README identifies the toggle's `Original Background` mode and states that
      the mileage scale remains available and no new imagery request/HTTP attempt
      is authorized when imagery is off.
- [ ] README explains scale accuracy/precision.
- [ ] README explains attribution and privacy.
- [ ] README explains no persistent/offline cache.
- [ ] README explains imagery is excluded from KMZ.
- [ ] Official source links are included.

### Expected validation outputs

- all new and existing tests pass with only the explicitly gated live smoke skipped;
- both full-suite runs have identical pass/skip counts;
- syntax and whitespace checks produce no errors;
- manual evidence covers main, Focus, Inspector, online, offline, failure, saved
  image, minimum-size, and independent scale measurements;
- file/hash/AST review proves the final diff is allow-list clean and protected
  behavior is unchanged;
- final handoff identifies the exact changed files, test counts, manual results,
  known external dependency behavior, and rollback point.

## 12. Rollback and recovery

### 12.1 Recovery principles

- Never use `git reset --hard`, `git checkout --`, or another command that would
  erase the user's uncommitted GUI revamp.
- Restore only allow-listed files from the verified external Phase 0/phase snapshot.
- Create and hash-verify the successful-gate Phase 1-5 snapshots before beginning
  each downstream phase; a missing snapshot is a gate failure.
- Verify absolute source/destination paths before any recursive or overwrite action.
- New files have exact known names and may be removed only after verifying they
  are inside this repository and were created by this implementation.
- Preserve all pre-existing dirty/untracked files.
- Run tests after every rollback.

### 12.2 Phase rollback

| Failed phase | Restore/remove | Verification |
| --- | --- | --- |
| Phase 1 | Remove new basemap module/test only | 161 baseline tests |
| Phase 2 | Restore Phase 1 basemap module/test snapshot | Phase 1 plus baseline |
| Phase 3 | Remove new scale module/test only | Phase 2 plus baseline |
| Phase 4 | Restore GUI/test files from Phase 3 snapshot | Support suites plus baseline |
| Phase 5 | Restore GUI/test files from Phase 4 snapshot | Main integration plus full suite |
| Phase 6 | Restore README from Phase 5 if docs caused issue; otherwise return to the earlier phase that owns the defective code/test | Repeat owning-phase gate, then all Phase 6 validation |

### 12.3 Failure isolation

- Network/provider defect: disable/remove only basemap application; retain scale.
- Raster alignment defect: disable basemap integration until pure warp tests pass;
  do not convert vector axes as a shortcut.
- Scale defect: hide/remove scale controller only; do not alter preview coordinates.
- Inspector leak: disable Inspector basemap surface only; main remains.
- Shutdown defect: stop worker creation and restore normal close while investigating.
- Attribution defect: do not display imagery until attribution is corrected.
- Performance defect: reduce bounded output/tile caps within the fixed contract;
  do not move work to Tk.

### 12.4 Data/output recovery

No migration, database, schema, persistent cache, preference file, or output format
is introduced. Rollback requires no data conversion.

Manual validation writes only the exact new external temp `preview-save.png` and
`export-check.kmz` described in Phase 6, records their hashes, restores prior GUI
output fields, and removes only those resolved files plus their empty unique
directory. Basemap code must never make rollback depend on deleting a tile
directory because no such directory may exist.

### 12.5 Recovery completion

Rollback is complete only when:

- workspace matches the appropriate recorded phase hashes;
- all pre-existing dirty files remain;
- neither lazy basemap-client worker slot starts on app launch;
- baseline full suite passes;
- no downloaded/cache/temp artifact remains in repo;
- `git status --short` differs from Phase 0 only by intentionally retained
  completed-phase files.

## 13. Blockers or items requiring clarification

None.

Technical feasibility, service schema, attribution, caching boundary, display
architecture, scale definition, precision, failure behavior, file scope, tests,
and rollback are resolved.

The service is externally controlled and can fail or change, but that is not an
implementation blocker because imagery is explicitly optional at runtime and the
dark vector preview remains both the user-selectable Original Background and the
automatic failure fallback, with the scale independent of either imagery state.

## 14. Final readiness assessment

### Evidence audit

- Repository preview and lifecycle paths were inspected directly.
- Current result CRS/data structures were inspected directly.
- Current service metadata and a valid tile were queried directly.
- Invalid LOD and unsupported export behavior were probed directly.
- Official ArcGIS item metadata and terms language were inspected.
- Official tile and attribution documentation is linked.
- The current dirty working baseline is recorded with exact hashes.
- The complete 161-test suite was executed successfully.
- The architecture preserves projected preview geometry and isolates external
  behavior.
- Edge cases, risks, tests, phase gates, scope controls, and rollback are defined.
- The final plan was independently re-audited against the complete named planning
  guide; all prior contradictions were resolved and the exact inventory contains
  50 new test methods.
- No temporary open-decisions sidecar exists or is required.

### Readiness certification

Implementation Ready: YES

No unresolved questions, decisions, assumptions requiring confirmation, approvals, blockers, missing evidence, ambiguities, or required user input remain.
