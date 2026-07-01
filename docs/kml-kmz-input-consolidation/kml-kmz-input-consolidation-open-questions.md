# KML/KMZ Polyline Input Consolidation Open Questions

Status: resolved decision worksheet.

This file records decisions answered before implementation. The main implementation plan is:

```text
docs\kml-kmz-input-consolidation\kml-kmz-input-consolidation-implementation-plan.md
```

Fixed decisions already captured from the user:

- JPG feature expansion is paused for this work.
- KML/KMZ input should be added directly to this app.
- Polyline KML/KMZ inputs should use the linework as the geometry source.
- Outputs should be exterior-only. Interior rings/holes should be cleaned up instead of exported.
- Section names should use `<shape-name> (1 of x)`.
- Section splits should look natural for orthomosaic crop usage, not just mathematically efficient.

## Answer Record

Resolved answers:

```text
D1: Always export KMZ.
D2: Prefer LineStrings when mixed LineString/Polygon files are loaded; ignore polygons and report that they were ignored.
D3: Option A
D4: Reject disconnected polyline buffer outputs for the first implementation.
D5: Accept single-polygon KML and KMZ inputs; ignore/fill polygon interiors.
D6: Option C: add user-facing split direction control now, with preview updates when direction changes.
D7: Apply overlap along shared split boundaries.
D8: Fail with a clear message if natural splitting cannot produce connected, clean sections.
D9: Visual regularity wins within area tolerance.
D10: Use 20 percent area variance tolerance from average base section area.
```

Resolved interpretation:

- D1: Always export KMZ.
- D2: Prefer `LineString` geometry when mixed LineString/Polygon files are loaded, ignore polygons for generation, and report that polygons were ignored.
- D3: Do not preserve source linework in exported KMZs.
- D4: Reject disconnected polyline buffer outputs for the first implementation.
- D5: Accept single-polygon KML and KMZ inputs. Polygon interiors are ignored/filled so only exterior boundaries drive output.
- D6: Add a user-facing split direction control now, and make preview updates respond to direction changes.
- D7: Apply overlap along shared split boundaries.
- D8: Fail with a clear message if natural splitting cannot produce connected, clean sections.
- D9: Visual regularity wins within area tolerance.
- D10: Use a 20 percent area variance tolerance from average base section area.

## D1. Should This App Continue Exporting Only KMZ, Or Mirror KML/KMZ Input Type?

### Context

The current app exports KMZ. Buffer-Zone-Generator writes outputs using the same file type as the source. The new workflow will accept both KML and KMZ input.

### Options

Option A: Always export KMZ.

Impact:

- Preserves this app's current export identity.
- Keeps one export path and one file picker behavior.
- Users can input KML but still receive KMZ.

Option B: Mirror the source file type.

Impact:

- Matches Buffer-Zone-Generator behavior.
- Adds KML output writer behavior to this app.
- Requires more UI and test coverage.

### Resolved Decision

Option A: always export KMZ for this app. The core goal is consolidation of input and geometry behavior, not adding a second output format.

## D2. If A KML/KMZ Contains Both LineStrings And Polygons, Which Geometry Should Be Used?

### Context

The Buffer-Zone output example preserves source `LineString`s and adds a generated buffer polygon. A user might accidentally feed a previously generated output back into this app.

### Options

Option A: Prefer `LineString`s when any are present.

Impact:

- Re-buffering a preserved-source output uses the original linework.
- Convenient for iterative buffer distances.
- Could surprise users who expected the existing polygon to be used.

Option B: Reject mixed LineString/Polygon files.

Impact:

- Most explicit and safest.
- Forces the user to provide a clean source or choose the intended geometry.
- Less convenient for reusing files that preserve source lines plus generated polygons.

Option C: Prefer polygons when any polygons are present.

Impact:

- Matches legacy KMZ-as-polygon behavior.
- Bad for the new polyline workflow because preserved generated polygons can mask the original linework.

### Resolved Decision

Option A. Prefer `LineString`s when any are present, ignore polygon geometry for generation, and report `Using source LineStrings; polygons ignored`.

## D3. Should Source Linework Be Preserved In The Exported KMZ?

### Context

Buffer-Zone-Generator can preserve source content in output. This app currently exports the generated boundary polygons, not the original JPG points or source linework as KML features.

### Options

Option A: Do not preserve source linework.

Impact:

- Cleaner crop KMZ output.
- Avoids feeding mixed LineString/Polygon files back into downstream tools.
- Better matches the current app's output style.

Option B: Preserve source linework as an optional checkbox.

Impact:

- Useful for debugging and visual QA.
- Adds UI state and possible confusion in production crop files.

Option C: Always preserve source linework.

Impact:

- Best traceability.
- Worst chance of cluttering crop KMZs and creating mixed-input ambiguity later.

### Resolved Decision

Option A for first implementation. Add source line preservation later only if debugging needs it.

## D4. How Should Truly Disconnected Polyline Buffers Be Handled?

### Context

Some KML/KMZ files may contain multiple disconnected routes. Direct buffering can return a `MultiPolygon`.

### Options

Option A: Reject disconnected outputs for now.

Impact:

- Safest for crop generation.
- Avoids accidental giant unions or misleading section splits.
- User must process disconnected areas separately.

Option B: Export one KMZ with multiple parent polygons.

Impact:

- Supports more inputs.
- Requires broader metadata, preview, export, and section-splitting behavior.

Option C: Merge disconnected components with a convex hull or connector.

Impact:

- Produces one polygon.
- High risk of covering areas not represented by the linework.
- Not recommended.

### Resolved Decision

Option A for first implementation. Add multi-parent support only after the single-parent workflow is stable.

## D5. Should Existing Polygon KML Files Be Accepted, Or Only Polygon KMZ?

### Context

Legacy behavior accepts a single-polygon KMZ. Adding KML parsing makes single-polygon KML support possible.

### Options

Option A: Accept single-polygon KML and KMZ.

Impact:

- Consistent with vector input support.
- Low extra cost once KML parsing exists.
- Existing polygon KMZ behavior can share the parser.

Option B: Keep polygon support KMZ-only.

Impact:

- Smaller behavior change.
- Slightly confusing because LineString KML would work but polygon KML would not.

### Resolved Decision

Option A. Accept single-polygon KML and KMZ inputs. If the source polygon contains interior rings, ignore/fill interiors so only the exterior boundary is used.

## D6. How Should Natural Split Direction Be Chosen?

### Context

The user wants adjacent crops and overlaps to share a natural direction, avoiding sharp or irregular shapes. For polyline inputs, there may be source linework that can provide an orientation hint. For polygon inputs, only the parent polygon is available.

### Options

Option A: Automatically derive one global split axis from the parent polygon's dominant orientation.

Impact:

- Simple, predictable, and testable.
- Produces parallel crop strips.
- May be less ideal for strongly curved corridors.

Option B: Derive split direction from source polyline direction when linework is available, otherwise use polygon orientation.

Impact:

- Better for corridor inputs.
- More complex diagnostics and edge cases.
- Still keeps a deterministic fallback.

Option C: Add a user-facing split direction control now.

Impact:

- Gives maximum control.
- Adds UI complexity and more validation.
- Probably premature for first implementation.

### Resolved Decision

Option C. Add a user-facing split direction control now. The preview must update when the direction changes. The control should still provide an `Auto` option so users can start from the source-line or parent-polygon inferred direction.

## D7. How Should Section Overlap Be Applied?

### Context

The current implementation buffers each section outward by half the overlap and intersects with the parent polygon. That can create rounded or odd section edges. For orthomosaic crops, overlap usually needs consistency along shared crop boundaries.

### Options

Option A: Expand sections only along the split axis so overlap occurs at shared boundaries.

Impact:

- Produces cleaner, more crop-like sections.
- Keeps outer parent boundary unchanged.
- Best match for visually consistent orthomosaic crops.

Option B: Keep current all-direction half-buffer overlap.

Impact:

- Simpler reuse of current code.
- Can create visually odd bulges and overlaps around corners.

Option C: Make overlap mode user-selectable.

Impact:

- Flexible.
- Adds UI and test complexity.

### Resolved Decision

Option A for this workflow.

## D8. What Should Happen If Natural Splitting Cannot Produce Connected, Clean Sections?

### Context

Some parent polygons may be too concave or complex for same-axis clean splits.

### Options

Option A: Fail with a clear message.

Impact:

- Prevents weird crop shapes.
- User can choose fewer shapes or adjust source.
- Safest for output quality.

Option B: Fall back to the existing recursive splitter.

Impact:

- More likely to produce some output.
- Can reintroduce the odd shapes this work is meant to avoid.

Option C: Prompt for human review during implementation only, then decide case-by-case.

Impact:

- Useful during validation.
- Not a deterministic product behavior.

### Resolved Decision

Option A for production behavior. During implementation validation, stop for review if this happens on the known North 2 sample.

## D9. Should Area Equality Or Visual Regularity Win When They Conflict?

### Context

Equal-area splits may require awkward cuts on curved or irregular polygons. Natural crop shapes may have slightly different areas but better visual usability.

### Options

Option A: Area equality wins.

Impact:

- Predictable acres per crop.
- Can create less natural shapes.

Option B: Visual regularity wins within an area tolerance.

Impact:

- Better crop usability.
- Requires an accepted area variance threshold.

Option C: Strict visual regularity, no area tolerance target.

Impact:

- Best aesthetics.
- May produce unexpectedly uneven crop sizes.

### Resolved Decision

Option B. Use visual regularity first, with section area variance reported in details.

## D10. What Area Variance Is Acceptable For Natural Sections?

### Context

If visual regularity can beat perfect equal area, implementation needs a tolerance.

### Options

Option A: Keep sections within 10 percent of average base area.

Impact:

- Tight area consistency.
- May force less natural cuts on irregular outlines.

Option B: Keep sections within 20 percent of average base area.

Impact:

- More room for natural-looking sections.
- Still prevents extreme imbalance.

Option C: No hard threshold; report variance only.

Impact:

- Most flexible.
- Harder to enforce output quality.

### Resolved Decision

Option B for first implementation, with details output showing min/max section area.
