# Polyline buffer and section hardening

## Reproduced failure

Verified locally on `C52 + C53.kmz` (six source lines, 71 coordinates),
September 11, 2026. No customer geometry is added to the repository.

At 350 ft the direct buffer was a valid, connected exterior-only polygon.
The old Auto code nevertheless selected 461 ft because the perimeter divided
by the convex-hull perimeter was 1.614098, above its 1.55 threshold.
At 461 ft the ratio fell to 1.549542. The minimum connected whole-foot buffer
was only 2 ft. This was a shape-complexity rule, not a geometry validity failure,
and happened before sectioning.

## Behavior

`src/polyline_boundary.py` now preserves valid explicit positive distances.
Auto adjusts only when the requested distance cannot produce a usable connected
polygon, selecting the minimum whole-foot distance. It searches up to 2,000 ft,
instead of stopping at the former initial 500 ft limit. Valid explicit distances
above the search limit are accepted. Every candidate must be valid, have positive
area, and cover all projected source linework. The former regularity score is
retained as a diagnostic with its enforcement target disabled.

`src/jpg_boundary_kmz_core.py` still tries natural parallel sections first.
Its recursive fallback now tries alternative connected cuts, complementary
section allocations, and a finer 5-degree direction grid, and backtracks when
later sections cannot split. Exact equal areas are preferred. If that search
fails, it tries nearby area allocations while bounding every final section to
20% of the original average area, preventing cumulative recursive imbalance.
Both passes have bounded search work. Parent buffering remains independent of
section count; overlap is clipped to that parent.

Very thin, branched corridors may take tens of seconds to search. Auto is not a
guarantee that every count or custom direction is geometrically feasible. An
exhausted search reports an error rather than widening the parent to make a cut
possible. Explicit custom directions retain their existing behavior.

## Verification

- `python -B -m unittest tests.test_polyline_boundary tests.test_natural_sectioning tests.test_core_regression -v`: **42 tests passed**.
- Portable branched KMZ regression: 50, 250, and 350 ft; 1, 3, 4, and 8 sections;
  50 ft overlap. Checks requested buffer, identical parent outline, valid
  connected exterior-only sections, section union matching the parent, source
  coverage, and area variance. This replaces the former unavailable private
  KML fixture and its obsolete regularity-threshold assertion.
- Buffer tests cover fractional explicit distances, concave corridors, minimum
  connected whole-foot selection, gaps needing more than 500 ft, invalid numeric
  values, disconnected inputs beyond the search limit, and valid explicit
  buffers above that search limit.
- Actual customer KMZ: 350 ft with 1–6, 8, and 12 sections; 250 ft with 3 sections;
  50 ft with 3, 5, and 8 sections; Auto zero with 1 and 4 sections (selects 2 ft).
  Verification checks section validity, count, source coverage, and union-area
  error below 1e-8 relative to the parent.
- Actual customer KMZ export at 350 ft / 4 sections / 50 ft overlap saves four
  polygons and retains all original source lines inside the output. Simplified
  export maximum deviation is 4.9443 ft, with a maximum per-section area delta of
  0.4167%, within the existing 5 ft / 1% limits. Source files are unchanged.
- Geometry-only rendering was inspected at 350 ft / 4 sections, showing original
  linework and the complete parent outline. This was not a native GUI screenshot.

The focused run covers backend generation and export; unrelated GUI tests were
not rerun for this backend patch.
