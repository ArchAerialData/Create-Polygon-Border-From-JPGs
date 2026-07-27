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

1. Drop the parent JPG folder, KML, or KMZ onto the empty-state target, or use
   `Browse Folder...` / `Browse KML/KMZ...`. After selection, the large input
   target collapses into the compact top strip; dropping another input and
   `Change Input` remain available.
2. Open `Settings` and use `Input & Geometry` to set the buffer and JPG outline
   mode. Use `0` for no added buffer on JPG folder and polygon KML/KMZ inputs.
   LineString KML/KMZ inputs require a buffer greater than `0`. For KML/KMZ
   inputs, turn on `Simplify KML/KMZ output vertices` only when dense vector
   geometry should be reduced during export.
3. Use `Sections` to set the shape count and, for multiple shapes, overlap,
   shape label, split direction, and optional custom degrees.
4. Use `Output` to set the file name or `.kmz` path.
5. Click `Update Preview`. Buffer, shape count, and applicable overlap values
   can also be adjusted from the bottom action bar for quick iterations.
6. Click `Export KMZ`. `Update Preview` and `Export KMZ` remain in the fixed
   action area as the window changes size.
7. Use `Details` for the full scan/export summary, and `View Output Folder`
   from the output settings or completion popup to open the KMZ folder.

## GUI layout and workflow

- The dark, blue-accented interface is a single-page shell with no navigation
  sidebar, tabs, or page-level scrolling. The preview is the only expanding
  area.
- Startup sizing uses the taskbar-safe work area of the monitor under the
  pointer at launch, with current-window, primary-monitor, and Tk fallbacks.
  The app centers itself and applies a measured or conservative fit so the
  decorated window remains usable on shorter or offset monitors.
- The compact top strip contains the selected input plus `Change Input`, `Key`,
  `Settings`, `Focus Preview`, and `Open Inspector`.
- `Settings` opens a temporary overlay over the right side of the preview.
  Its `Input & Geometry`, `Sections`, and `Output` accordion groups expand one
  at a time and can be collapsed; the drawer can scroll internally on a short
  display without making the primary shell scroll.
- `Key` opens a separate preview-key overlay. The Settings and Key overlays are
  mutually exclusive and do not permanently reduce the preview.
- The responsive bottom action bar keeps status, quick buffer/section controls,
  `Details`, `Update Preview`, and `Export KMZ` accessible. It changes from one
  row to two rows when horizontal space is limited.
- Editing a preview-affecting option keeps the last drawing visible and marks
  it `Preview out of date`; click `Update Preview` to regenerate it. Selecting
  a different input clears the prior drawing instead.
- `Focus Preview` expands the main preview to a taskbar-safe maximized or
  near-fullscreen fit while reusing its canvas, toolbar, overlays, and state.
  `Open Inspector` retains the large detachable preview window with independent
  section controls, key, pan/zoom, and `Apply Preview`.
- Drag-and-drop and both browse workflows remain available. If optional
  drag-and-drop initialization is unavailable, the browse buttons continue to
  work.
- The redesign changes GUI presentation and in-memory workflow state only. It
  does not add, remove, or alter the boundary-processing and KMZ-export
  contracts described below.

Keyboard shortcuts:

- `F5` or `Ctrl+Enter`: update the preview.
- `Ctrl+E`: export the KMZ.
- `Ctrl+,`: open or close Settings.
- `Ctrl+L`: open Input & Geometry and focus the input path.
- `Escape`: close the active overlay first, then exit Focus Preview.

## Behavior

- JPG discovery is recursive and case-insensitive for `.jpg` and `.jpeg`.
- GPS coordinates are read from EXIF.
- JPG folders default to `Auto` outline mode. Auto evaluates route-aware and
  lawnmower-envelope candidates, but falls back to the conservative concave
  hull when confidence or geometry guardrails are not met.
- Manual JPG outline modes are `Concave hull`, `Route-aware`, and `Lawnmower
  outer envelope`.
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
  `Auto`, a connected equal-area fallback is used when one parallel direction
  cannot produce the requested count cleanly.
- Split direction can be `Auto`, `0 deg / East-West`, `90 deg / North-South`,
  or a custom degree value. `Auto` uses source-line orientation when available
  and otherwise uses the parent polygon orientation.
- Section overlap is clipped inside the parent outline and applied along shared
  split boundaries. A `50 ft` overlap means adjacent sections overlap by
  roughly 50 ft along shared cut areas.
- Natural section base areas must stay within 20 percent of the average base
  section area. If neither the natural splitter nor the connected `Auto`
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
- The preview is schematic only: it plots camera points and the exported
  boundary without an imagery basemap.
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
