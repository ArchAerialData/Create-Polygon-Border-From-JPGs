# Ortho crop section correction

Status: complete. Implementation, customer-file verification, and final regression
checks passed. No known blocker remains for the supplied case.
Date: September 11, 2026.

The [September 12 follow-up](workspace-bend-export-follow-up.md) adds an acute-cut
check, a bounded 35% area fallback, import recovery, compact layouts, and updated
export styling. Results below record the September 11 correction.

## Reproduced problem

Verified the supplied `C52 + C53-2_boundary.kmz` and its original
`C52 + C53-2.kmz`: six source polylines, 76 coordinates, EPSG:32615,
310 ft unified buffer, four sections, 50 ft overlap, simplified export.

The old Auto fallback accepted connected polygons with exactly equal areas,
including long cuts running down the corridor. Connectivity and equal area
alone did not guarantee usable ortho crops. The red and blue sections shared
the trunk lengthwise, producing long narrow tails. This was sectioning behavior,
not an input-buffer or preview-rendering error.

## Implemented behavior

- Both Auto splitters prefer short cross-cuts. A shared, scale-independent
  quality rule compares a cut's length with `2 * area / perimeter` of the polygon
  being split. That length approximates the width of a long corridor; a ratio
  above 2.5 is rejected. The allowance accommodates bends and junctions.
- The connected fallback tries end/branch sections before balanced halves,
  alternative directions and allocations, and backtracking. Exact areas are
  accepted only when the cuts also meet the quality rule.
- Relaxed-area candidate positions come from bends, junctions, and their
  intervening spans. A simplified outline supplies search positions only;
  all accepted sections are intersections of the original buffered polygon.
- Every final base section remains within 20% of the original average area.
  The limit is checked against that original average throughout recursion,
  so errors cannot accumulate through successive cuts.
- Search remains bounded: a 5-degree direction grid plus existing orientation
  hints, at most 256 relaxed positions per direction, four retained candidates
  per direction, and at most 1,024 recursion/candidate steps. Failure reports
  that no suitable connected cross-cut partition was found. It does not widen
  the parent or fall back to a known poor longitudinal cut.
- Explicit split directions retain their existing behavior. Unified and
  per-side buffers, overlap clipping, and visual numbering use the same pipeline.

## Export coverage hardening

An additional zero-overlap check reproduced about 60 square metres of interior
gaps from independent vertex simplification. Each simplified polygon passed
its individual area/deviation limits, but their shared edges no longer matched.

Export now checks the simplified sections together against the original union.
The existing 5 ft outer-edge deviation allowance remains; a newly uncovered
interior causes the entire set to retain its original vertices and report zero
simplification. Micrometre-scale numerical tolerances avoid treating projection
roundoff as a coverage gap. The simplify checkbox remains enabled.

## Verified results

- Corrected customer export: four valid connected, exterior-only polygons;
  unchanged 310 ft buffer and 50 ft overlap; maximum base-area variation
  **7.9093%**. No interior coverage gaps; all original polylines remain covered.
- Simplified customer export: **2,933 to 235 vertices**, maximum deviation
  **4.8011 ft**, maximum section area delta **0.3581%**.
- Customer preview matrix: **14 cases passed**. Includes 310 ft with 1, 2, 3,
  4, 6, 8, and 12 sections; four sections with zero overlap; 50 ft / four
  sections; 350 ft / eight sections; Auto zero / four sections; and asymmetric
  350/150 ft sides with 1, 4, and 8 sections. Maximum union-area error was below
  `1e-8` relative to the original parent. All requested positive buffers stayed
  unchanged. Timings on this machine ranged from 0.05 to 12.64 seconds.
- Four-section export checks passed for unified 310 ft and asymmetric 350/150 ft,
  each with zero and 50 ft overlap. The unified zero-overlap case correctly
  retained all 2,842 vertices; the other cases still simplified successfully.
- New portable regressions measure full trunk-width coverage after rotation,
  translation, and scaling; repeatable section assignment; overlap/parent
  preservation; Auto versus explicit directions; and simplification-induced gaps.
  The old splitter divided **610 m** of the synthetic trunk lengthwise; the
  corrected splitter has only **65 m** of partial-width transects near cross-cuts.
  The gap fixture reproduced **24.98 square metres** of lost interior coverage
  before the export guard and none afterward.
- Focused final checks: `python -B -m unittest tests.test_ortho_crop_sections
  tests.test_core_regression tests.test_per_side_core -v` — **33 tests passed**.
- Final full suite: `python -B -m unittest discover -s tests -v` — **275 tests
  run, no failures, one opt-in live Esri smoke skipped**, in 187.830 seconds.
- Final `git diff --check` passed.

Generated private review artifacts are in the ignored
`test_data/ortho-crop-review/` directory: corrected KMZ, before/after rendering,
generation details, test logs, and JSON validation records. The before/after image compares
the actual saved polygon coordinates, without imagery; it is not a GUI capture.
The supplied source and bad export were not overwritten.

## Limits and follow-up

The cross-cut score is a bounded geometry heuristic, not a universal measure of
human crop preferences. No algorithm can guarantee equally sized, connected,
full-width crops for every branched outline and requested count. Difficult cases
can take longer or need fewer sections or an explicit direction. Retaining
original vertices when simplification would create gaps increases export size.

No known blocker remains for the supplied case. Useful future work is optional
interactive cut placement for operator-specific crop choices, and simplification
that explicitly preserves shared edges to reduce vertices without requiring the
current conservative fallback. Neither is required for this correction.

## Code and regression references

- [Auto cut quality](../src/section_quality.py)
- [Parallel Auto sectioning](../src/natural_sectioning.py)
- [Connected fallback and export coverage](../src/jpg_boundary_kmz_core.py)
- [Ortho crop regressions](../tests/test_ortho_crop_sections.py)
- [Existing buffer/count and polygon regressions](../tests/test_core_regression.py)
