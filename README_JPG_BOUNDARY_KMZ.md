# JPG Boundary to KMZ GUI

This local Python app accepts a parent folder of geotagged JPG/JPEG photos,
a KML/KMZ file containing source LineStrings, or a single-polygon KML/KMZ.
It builds or reads one generalized exterior-only outline, applies a buffer in
feet, optionally splits the result into connected overlapping sections,
previews the result, and exports a KMZ polygon set.

## Run

From inside this app folder:

```powershell
python .\run_jpg_boundary_gui.py
```

From any other folder:

```powershell
python "C:\path\to\jpg_boundary_kmz_app\run_jpg_boundary_gui.py"
```

On Windows, you can also double-click `run_jpg_boundary_gui.bat`, or run it
from any shell location:

```powershell
"C:\path\to\jpg_boundary_kmz_app\run_jpg_boundary_gui.bat"
```

The app folder is portable as a unit. Move `jpg_boundary_kmz_app` anywhere and
keep the files inside it together; the launcher resolves the other scripts
relative to its own location.

In the app:

1. Drop a JPG folder, KML, or KMZ onto the welcome card, or choose it from
   `Input`. The source strip shows the selected folder/file name; hover to see
   the full path. `Input > Edit input path` also accepts a typed path.
2. Open `Boundary` to choose the JPG outline mode and buffer in feet.
   `Sections` contains shape count, overlap, naming, and split direction.
   `Output` contains the KMZ name, destination, and vector export options remain
   in `Boundary`. Simplify output vertices is enabled by default for KML/KMZ exports.
3. New inputs automatically preview in Auto mode at zero buffer. Linework that
   needs width uses the smallest connected whole-foot buffer and shows its selected value.
   After editing settings, click `Update Preview`. The bottom bar also provides
   buffer, shape-count, overlap, and shape-label edits. These share values with
   the settings panels; overlap and shape label activate for multiple shapes.
4. Click `Export KMZ`. Completion appears inline, with `Open saved folder`
   pointing to the actual exported file's folder.
5. Use `View` for the map legend, Focus Preview, the separate Inspector, and
   World Imagery. `Details` retains the full processing/export summary.

The folder, KML/KMZ, and save dialogs reopen in the last folder selected, including
after restarting the app. Canceling a dialog preserves that location. If the
folder is no longer available, the dialog uses the default location. On Windows,
this preference is stored in `%LOCALAPPDATA%\JpgBoundaryToKmz\last-browse-directory.txt`.

## Buffer and section behavior

- A valid positive polyline buffer stays at the requested distance, including
  concave and branching corridors. Auto no longer enlarges it to meet a
  perimeter/convex-hull regularity target.
- Zero-width linework or disconnected buffers use the smallest connected buffer
  in whole feet, searching up to 2,000 ft. Valid explicit distances above that
  search limit are still accepted. Details reports any adjustment.
- Auto sections first try parallel cuts, then connected recursive cuts with
  alternative directions and backtracking. Short cuts across the corridor take
  priority over exact equal areas; long cuts down narrow corridors are rejected.
  Cuts also avoid acute ends beside bends. Auto first seeks areas within 20%
  of average, then permits up to 35% when needed for clean junctions. Sectioning does not
  increase the parent buffer. A bounded search can still report a failure for
  an unsuitable count or geometry; custom directions remain explicit.
- Export simplification checks the sections together for interior coverage gaps.
  When simplifying would open a gap beyond the existing outer-edge tolerance,
  export retains the original section vertices.
- See [buffer validation](docs/polyline-buffer-hardening.md) and
  [ortho crop split correction and verification](docs/ortho-crop-sectioning.md),
  followed by the [import/layout/bend/export follow-up](docs/workspace-bend-export-follow-up.md).
- `New input` returns to the import screen and clears the previous preview.
  Failed imports with no displayed result restore the browse/drop controls.
- The header uses a single brand row. On wide windows, status, quick settings,
  export actions, and the saved-folder link share one footer row; smaller windows wrap.
- KMZ polygons export as unfilled colored outlines with Google Earth line width
  **5**, clamped to ground. Coordinates are always WGS84 longitude/latitude;
  projected UTM coordinates are used internally for distance and area calculations.

### Optional per-side buffers

For compatible **polyline-only KMZ** inputs, `Per-side buffer` appears in Boundary
settings and `Per-side` appears in the footer. Compatibility is checked during
background import. KML, JPG folders, polygons, mixed geometry, closed lines, and
self-crossing lines keep this option hidden.

- Checking either control replaces the unified field with synchronized **Left (ft)**
  and **Right (ft)** fields. Each initially copies the full unified distance:
  350 ft becomes 350/350 ft. A unified zero starts at 200/200 ft.
- Unchecking restores the saved unified value. Re-enabling seeds both sides again
  from that value. Loading another input resets to unified mode.
- Left/right follows the white direction arrows on each original source line in
  the preview and Inspector. Several imported lines can have different directions.
- Endpoints round off automatically. Their extension is the average of the two
  side distances, so no separate endpoint field is needed.
- One side may be zero; both cannot be zero. The entered side distances are
  preserved. If they produce disconnected areas, generation explains the failure
  instead of automatically increasing them. Unified Auto behavior remains available.
- Use `Update Preview` after edits. Preview, splits, export, and Details share the
  active side settings. Export simplification preserves original vertices when
  simplification would lose source-line coverage.

Diagnostic helper: `python -B src/polyline_compatibility.py "C:\path\input.kmz"`.
It prints eligibility and a reason as JSON (exit 0 for eligible, 1 otherwise).
See the [completed implementation and validation record](docs/per-side-buffer-implementation-plan.md).
The [follow-up audit](docs/per-side-buffer-follow-up-audit.md) records edge-case
fixes, export failure protection, display checks, and regression coverage.

## GUI layout and workflow

- Windows startup enables system DPI awareness before creating Tk windows, so
  text and controls render at system resolution instead of being bitmap-scaled.
  The embedded preview also uses Matplotlib's DPI scaling. Moving the window to
  a monitor with a different scale can still require per-monitor DPI support.
- Field headings stay white, including headings for disabled controls. Loading
  an input through Browse, drag-and-drop, or committing a typed path starts a
  background preview with buffer reset to zero and outline mode reset to Auto.
- On Windows, JPG-folder, KML/KMZ, and Save As dialogs start at **This PC**.
  Other platforms start at the home folder. The suggested output filename is retained.
- The AALLC-inspired navy header, charcoal surfaces, blue primary controls,
  larger text, rounded buttons and fields, and high-contrast checkboxes share centralized
  theme tokens. The app remains a native Tk desktop application.
- The preview is the only expanding workspace. Named settings panels replace
  a crowded toolbar; each opens one focused page with labels above the fields.
  The custom angle appears when Custom split direction is selected. Panels scroll
  within the available height and retain the current map view.
- The header reflows based on measured button widths. Short windows use a
  compact brand header and welcome card. Footer controls remain available and
  wrap on narrow windows; the duplicate destination caption is hidden as needed.
  All original settings menus remain available.
- Original imported polylines and their arrows appear in white with a dark outline
  in both the main preview and Inspector, above the generated boundary. White is
  reserved for source lines so they remain distinct from colored sections. The
  legend identifies them as `Source polylines`.
- `Input polylines`, beside `World Imagery` in both previews, instantly hides or
  restores source lines, arrows, and their legend entry. It starts enabled and
  shares the current choice between views, including when Inspector is reopened.
  The checkbox is disabled when the preview has no imported polylines. This is
  a display setting: it preserves zoom, generated polygons, and KMZ export content.
  Both layer toggles stay together when the toolbar wraps in a narrow window.
- Startup sizing still uses the monitor's taskbar-safe work area. Resizing is
  coalesced into an idle layout pass; fonts and checkbox indicators respect
  Tk's display scaling. Focus Preview and Inspector retain their existing
  monitor-fitting behavior.
- Processing and export continue on the existing background workers. An inline
  activity card shows elapsed time, action labels indicate the operation, and
  duplicate submissions are blocked while work is running. Completion does
  not open a modal dialog. Processing errors and overwrite confirmation retain
  their existing dialogs.
- Editing preview settings marks the existing result `Preview out of date`;
  selecting a different input clears it. No new automatic generation is added.
- Hover/focus help explains common controls and shortcuts. The input command
  menu supports keyboard navigation. `Escape` closes the active overlay first.
- World Imagery remains a shared session preference across the main preview,
  View menu, and Inspector, without changing generated geometry.
- The UI refresh does not change geometry algorithms, input parsing, sectioning,
  or the KMZ format. See [UI design references and validation](docs/gui-workspace-refresh.md).

Keyboard shortcuts:

- `F5` or `Ctrl+Enter`: update the preview.
- `Ctrl+E`: export the KMZ.
- `Ctrl+,`: open or close settings.
- `Ctrl+L`: open Input & Geometry and focus the input path.
- `Escape`: close the active overlay first, then exit Focus Preview.

## Preview imagery and scale

- `World Imagery` is checked by default. With an internet connection, the app
  requests Esri World Imagery tiles for the visible map area and renders them
  behind the existing vector preview. Imagery is display-only: it never enters
  boundary processing and is never embedded in the exported KMZ.
- Uncheck `World Imagery` to use `Original Background` mode. Both preview
  surfaces immediately return to the original dark background, remove imagery
  and provider attribution, and stop authorizing new imagery requests or HTTP
  attempts. Vectors, navigation, preview generation, export, and the mileage
  scale remain active.
  At most one request already reserved in each of the two preview worker slots
  may return afterward; such results are discarded without retry, a subsequent
  tile fetch, metadata or tile-cache commit, response publication, or display.
- Before the first imagery frame arrives, the original dark surface remains
  visible beneath the vectors and scale as a nonblocking loading background.
  This automatic loading state is separate from intentionally selecting
  `Original Background`.
- If the service or internet connection is unavailable, the app keeps the dark
  vector preview operational and shows a nonmodal `Imagery unavailable` status.
  `Update Preview` and `Export KMZ` do not depend on the basemap.
- The scale bar is calculated geodesically from the current projected view,
  displays statute miles using a readable length, and shows at most two decimal
  places. It updates after result fitting, pan, wheel or toolbar zoom,
  Home/Back/Forward navigation, resize, Focus Preview, and Inspector changes.
  It remains available while imagery loads, fails, or is turned off.
- Visible imagery always includes `Powered by Esri` and the service-provided
  data attribution inside the Matplotlib figure. Preview images saved with the
  Matplotlib toolbar therefore retain the imagery, scale, and attribution.
- Tiles are held only in a bounded, session-memory cache. The app creates no
  persistent or offline basemap cache, exposes no raw-tile export, and clears
  transient tile state when the input changes, imagery is disabled, or the app
  closes.
- The service is public and currently does not require an app token, but its
  content is proprietary and governed by Esri terms. Tile requests disclose
  the requested map-tile locations and normal connection information, such as
  the client IP address, to Esri.

The automated suite is offline by default. A deliberately bounded live service
smoke test can be opted into with:

```powershell
$env:JPG_BOUNDARY_LIVE_ESRI_TEST = "1"
python -B -m unittest tests.test_gui_basemap.LiveEsriSmokeTests -v
```

## Behavior

- JPG discovery is recursive and case-insensitive for `.jpg` and `.jpeg`.
- GPS coordinates are read from EXIF.
- JPG folders default to `Auto` outline mode. Auto evaluates route-aware and
  lawnmower-envelope candidates, but falls back to the conservative concave
  hull when confidence or geometry guardrails are not met.
- Manual JPG outline modes are `Concave hull`, `Route-aware`, and `Lawnmower
  outer envelope`.
- For a confident boundary trace, `Auto` and `Route-aware` use camera positions
  in capture order as the exterior when the last photo is within 2.5 typical
  photo intervals of the first. This preserves concave turns in closed flights
  without adding a spacing-based buffer. The requested buffer still applies.
  Crossing/degenerate loops and routes with large capture gaps are rejected;
  uncertain candidates retain the concave-hull fallback. Open traces retain
  their spacing-based corridor buffer. These outlines follow GPS camera
  positions, not the ground footprints or visible contents of the photos.
- KML/KMZ files containing `LineString` geometry use that linework as the
  source geometry and buffer it directly in a projected CRS.
- If a KML/KMZ contains both `LineString` and `Polygon` geometry, the
  LineStrings are used and polygons are ignored with a details note.
- LineString KML/KMZ inputs require a buffer greater than `0 ft`.
- Single-polygon KML and KMZ inputs are accepted.
- Polygon holes and buffer-created interior rings are filled before preview,
  sectioning, and export. Outputs are exterior-only.
- KML/KMZ vector input bypasses JPG outline modes and uses source-vector mode.
- `Simplify KML/KMZ output vertices` is off by default in the GUI so manually
  drawn source vertices are preserved during export. Turn it on for dense
  programmatic KML/KMZ shapes when smaller output polygons are preferred.
- Export remains KMZ even when the input is KML.
- Source linework is not preserved in exported KMZs.
- Pasted and dropped paths may be quoted; `file://` paths are normalized when
  the operating system supplies them.
- If `tkinterdnd2` is installed, the input can be set by dragging and dropping
  a folder, `.kml`, or `.kmz` file onto the empty or compact input target.
- The default KMZ location is the app-local `outputs` folder, so exporting does
  not require manually choosing an output path.
- Editing `Output file name` keeps the current output folder and updates the
  final `.kmz` path.
- `View Output Folder` opens the directory for the current or just-exported
  Output KMZ path.
- Relative output paths typed manually are resolved from the app folder, not the
  shell's current working directory.
- The projected CRS is auto-detected from the coordinate centroid using the
  standard UTM zone formula.
- The outline is intentionally generalized so it bridges small lawnmower-path
  divots instead of tracing every row-end wiggle.
- Auto containment padding and user buffers use high-resolution rounded joins,
  geometry cleanup, and projected segment densification before export.
- Details report preflight pattern, camera order source, selected strategy,
  confidence, candidate summary, and any non-blocking Auto fallback reason.
- When `# of Shapes` is greater than `1`, the app first tries connected
  same-direction sections intended to look natural as orthomosaic crops. In
  `Auto`, a connected fallback with short cross-cuts and balanced areas is used
  when one parallel direction cannot produce the requested count cleanly.
- Split direction can be `Auto`, `0 deg / East-West`, `90 deg / North-South`,
  or a custom degree value. `Auto` uses source-line orientation when available
  and otherwise uses the parent polygon orientation.
- Section overlap is clipped inside the parent outline and applied along shared
  split boundaries. A `50 ft` overlap means adjacent sections overlap by
  roughly 50 ft along shared cut areas.
- Natural section base areas must stay within 20 percent of the average base
  section area; the connected Auto fallback can allow up to 35 percent to retain
  clean junctions. If neither the natural splitter nor the connected `Auto`
  fallback can produce usable sections, generation fails before export.
- Section numbers use a static north-up map viewpoint and are assigned only
  after section geometry is complete. Horizontal-dominant runs read from left
  to right; vertically dominant runs read from top to bottom.
- Compact two-dimensional layouts read by visual rows: top to bottom, and left
  to right within each row.
- Branched outlines number the longest visible main run first. Branches then
  follow their attachment points along that run and number from each junction
  outward; branches at the same attachment read top to bottom, then left to
  right. Ordering changes names, legend order, and colors but not polygons,
  areas, overlap, buffering, or simplification.
- Multiple-section KMZs contain one folder named from the output KMZ filename
  stem and one polygon placemark per section, such as `Example (1 of 3)`.
- The preview always plots the existing camera/boundary vectors and can
  optionally place Esri World Imagery behind them.
- The preview preserves map scale instead of stretching long or narrow shapes
  to fill the available panel.
- The full preview canvas is the interactive viewing area for pan and zoom.
- The preview includes Matplotlib navigation controls for resetting the view,
  panning, zooming, and saving a preview image.
- Mouse wheel zooms while the cursor is over the preview, and left-click drag
  pans the preview without requiring the toolbar Pan button.
- Full scan/export details are hidden by default so the preview can use the
  main content area.

## Dependencies

The current machine already has the required packages available:

- `tkinter`
- `exifread`
- `numpy`
- `scipy`
- `shapely>=2.0`
- `pyproj`
- `simplekml`
- `matplotlib`
- `tkinterdnd2`

For another machine, install the pip-managed packages with:

```powershell
python -m pip install -r "C:\path\to\jpg_boundary_kmz_app\requirements_jpg_boundary_kmz.txt"
```

`tkinter` is included with most standard Python installs on Windows.

## Sources

- Shapely concave hull: https://shapely.readthedocs.io/en/stable/reference/shapely.concave_hull.html
- Shapely buffer: https://shapely.readthedocs.io/en/stable/reference/shapely.buffer.html
- Shapely segmentize: https://shapely.readthedocs.io/en/stable/reference/shapely.segmentize.html
- Shapely splitting/intersection behavior: https://shapely.readthedocs.io/en/stable/manual.html#splitting
- pyproj Transformer: https://pyproj4.github.io/pyproj/stable/api/transformer.html
- simplekml documentation: https://simplekml.readthedocs.io/
- simplekml folders and polygons: https://simplekml.readthedocs.io/en/latest/kml.html
- Tkinter file dialogs: https://docs.python.org/3/library/dialog.html#module-tkinter.filedialog
- Matplotlib Tk embedding: https://matplotlib.org/stable/gallery/user_interfaces/embedding_in_tk_sgskip.html
- Google KML reference: https://developers.google.com/kml/documentation/kmlreference
- Esri World Imagery service:
  https://wi.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer
- Esri World Imagery item:
  https://www.arcgis.com/home/item.html?id=898f58f2ee824b3c97bae0698563a4b3
- ArcGIS Map Tile REST resource:
  https://developers.arcgis.com/rest/services-reference/enterprise/map-tile/
- Esri and data attribution:
  https://developers.arcgis.com/documentation/esri-and-data-attribution/
- Esri data attributions and terms:
  https://www.esri.com/en-us/legal/terms/data-attributions
