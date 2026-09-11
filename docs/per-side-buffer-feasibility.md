# Per-side buffer feasibility

Status: feasibility investigation completed September 11, 2026. The feature is
now implemented; see the completion record in the implementation plan below.
The remaining discussion records the investigation that informed the design.

The finalized behavior and work sequence are in the
[implementation plan](per-side-buffer-implementation-plan.md), incorporating the
user's corrected full-distance defaults and the 200/200 ft zero-value exception.

## Recommendation

An optional two-field mode is feasible for open polyline inputs. Initially expose
it for KMZ files containing only supported open LineStrings, as requested. KML
could use the identical geometry implementation because the current loader sends
KML and KMZ LineStrings through the same processing path. Hide the option for
JPG folders, polygon inputs, mixed geometry, and unsupported line topology.
Closed rings and self-crossing paths should have separate tests and side semantics
before being included: the existing exterior-only output fills holes, so a ring's
inside buffer does not behave like a second outside margin.

Multiple source lines require a clear direction convention. The reviewed
`C52 + C53.kmz` contains six open, individually simple LineStrings with 71
coordinates. They do not merge into a single LineString; union/noding produces
10 line pieces. A polyline file is not necessarily a single directed route.

Use left/right relative to each ORIGINAL line's coordinate order, with arrows on
the main preview and Inspector while the mode is enabled. Side distances apply
locally to each directed line; union resolves overlaps at junctions. This does
not establish one global left/right for a branching network. A Swap sides action
is useful. Consistently orienting several imported paths would be a separate
route-orientation feature; do not infer it from polygon winding or merged output.

## Geometry and endpoints

The installed Shapely 2.0.7 / GEOS 3.13.1 supports signed single-sided line buffers.
Buffer each original projected line on its left and right BEFORE union, because
union/line merging may split or reorient source linework. Retain the current
projection, round joins, exterior-only cleanup, validity/source-coverage checks,
sectioning, and export simplification stages.

Single-sided buffering gives flat endpoints even when a round cap is requested.
A separate endpoint construction is therefore required to retain rounded ends.
The tested two-field rule joins the side offsets with a shifted semicircle:

- radius and forward endpoint extension: `(left + right) / 2`;
- sideways center shift toward the left: `(left - right) / 2`.

For 350 ft left / 150 ft right, the cap extends 250 ft beyond the endpoint and its
center shifts 100 ft toward the wider side. This is a proposed UX rule, not an
inherent requirement of asymmetric buffering. Equal side distances reproduce the
usual centered semicircle. One side can be zero when the resulting polygon stays
valid. An optional endpoint-distance control could be added later if independent
control proves useful; it is not needed to close the geometry.

For exact backward compatibility, disabled mode should run the existing unified
buffer implementation. Equal explicit side values can also use that path.
Per-side positive distances should be honored without silently rebalancing or
increasing them. If they cannot create one connected polygon, show an actionable
geometry error. Two zero values need an explicit rule; the recommended initial
behavior is to require positive width in per-side mode, while unified mode keeps
its existing zero/Auto search. Enabling the option copies the current positive
unified value into both fields (350 becomes 350/350). If the unified value is zero,
both fields default to 200 ft. Disabling it restores the retained unified value.

## GUI and state integration

The editable buffer currently appears in Boundary settings and the bottom footer.
Both should use shared enabled/left/right state. Enabling either checkbox replaces
the single field in both places; disabling it restores the single field. The
footer must reflow its field groups at narrow widths and larger DPI scales.
Summary text, hover help, Details, and Inspector should describe the active mode.

Use parsed geometry capabilities to determine eligibility, not just `.kmz` or
`source_line_count > 0`. The loader currently accepts mixed line/polygon files
and records ignored polygons; a strict pure-line capability must also account for
other geometry types. Keep parsing off the UI thread and invalidate capability
state when the input changes.

A typed buffer-settings value would avoid adding more positional values to the
current GUI input tuple. Include mode and both distances in the preview cache key,
worker request snapshot, export request, and output metadata. Changes mark the
preview stale; new input resets to unified mode. Existing busy/disabled states
must cover both copies of the checkbox and fields. Source direction remains
independent of how many output sections are generated.

## Prototype results and limits

An isolated prototype passed 15 synthetic cases: straight, right-angle, and hairpin
paths at equal, unequal, reversed, and zero-on-one-side distances. Checks covered
validity, source coverage, straight-line side extents, automatic cap extension,
and reversing a path while swapping left/right. Equal-side geometry matched the
ordinary buffer to about 1.1e-9 relative area error in those cases.

On the actual customer KMZ:

- 350/350 ft: one valid polygon covering all source linework; relative area
  difference from the current unified implementation was 1.72e-9.
- 350/150 ft: one valid polygon covering all source linework; splitting into four
  sections with 50 ft overlap succeeded, with section union area matching the
  asymmetric parent (zero measured symmetric-difference area).

The prototype used a one-micrometre union precision grid to join constructed caps.
That precision policy needs explicit production tests. This was not a completed
GUI feature or a full asymmetric export regression run. Production acceptance
should add large width ratios, small source gaps, short segments, reversed path
fragments, branch junctions, eligibility/reset behavior, stale worker results,
narrow/DPI layout checks, and preview/export agreement under simplification.

## Sources

- [Shapely buffering manual](https://shapely.readthedocs.io/en/stable/manual.html#object.buffer):
  side signs and forced flat single-sided caps.
- [Shapely line merging](https://shapely.readthedocs.io/en/stable/reference/shapely.line_merge.html):
  branch behavior and direction changes.
- Local implementation: `src/kml_vector_input.py`, `src/polyline_boundary.py`,
  `src/jpg_boundary_kmz_core.py`, and `src/jpg_boundary_kmz_gui.py`.
