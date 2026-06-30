# JPG Boundary to KMZ GUI

This local Python app accepts either a parent folder of geotagged JPG/JPEG
photos or an existing single-polygon KMZ. It builds or reads one generalized
outline, applies a buffer in feet, optionally splits the result into connected
overlapping sections, previews the result, and exports a KMZ polygon set.

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

1. Choose the parent folder that contains the flight folders, or choose an
   existing single-polygon KMZ.
   You can also drag and drop that input folder or KMZ onto the drop field.
2. Enter a buffer distance in feet. Use `0` for no added buffer.
3. Choose an outline mode for JPG folders. `Auto` is the default.
4. Use the default output file name, enter a custom file name, or choose a
   different `.kmz` path.
5. Leave `# of Shapes` at `1`, or enter a larger count to split the output.
6. For multiple shapes, set overlap feet and shape label.
7. Click `Scan / Preview`.
8. Click `Export KMZ`.
9. Click `View Output Folder` in the completion popup or main window to open
   the folder containing the KMZ.
10. Click `View Details` when you want the full scan/export summary.

## Behavior

- JPG discovery is recursive and case-insensitive for `.jpg` and `.jpeg`.
- GPS coordinates are read from EXIF.
- JPG folders default to `Auto` outline mode. Auto evaluates route-aware and
  lawnmower-envelope candidates, but falls back to the conservative concave
  hull when confidence or geometry guardrails are not met.
- Manual JPG outline modes are `Concave hull`, `Route-aware`, and `Lawnmower
  outer envelope`.
- Existing KMZ input must contain exactly one polygon with an outer boundary
  ring. KMZ files with multiple polygons or polygon holes are rejected because
  splitting starts from a single parent outline.
- Existing KMZ input bypasses JPG outline modes and uses source-polygon mode.
- Pasted and dropped paths may be quoted; `file://` paths are normalized when
  the operating system supplies them.
- If `tkinterdnd2` is installed, the input can be set by dragging and dropping
  a folder or `.kmz` file onto the app.
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
- When `# of Shapes` is greater than `1`, the app recursively splits the
  buffered outline into connected equal-area sections.
- Section overlap is clipped inside the parent outline. A `50 ft` overlap means
  adjacent sections overlap by roughly 50 ft along shared cut areas.
- Multiple-section KMZs contain one folder named from the output KMZ filename
  stem and one polygon placemark per section, such as `Example (1 of 3)`.
- If the app cannot create connected sections for the requested count, it fails
  before export instead of writing disconnected MultiPolygon placemarks.
- The preview is schematic only: it plots camera points and the exported
  boundary without an imagery basemap.
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
