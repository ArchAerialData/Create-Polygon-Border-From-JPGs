# Temporary Open Decisions: Camera Boundary V2

Status: temporary decision worksheet.

Use this file to answer the remaining product and implementation decisions before Phase 3 or Phase 4 of the Camera Boundary V2 plan. The source decision list comes from `docs/camera-boundary-v2-implementation-plan.md`, section `15.12 User-Required Open Decisions`.

Related source files and planning references:

- `docs/camera-boundary-v2-implementation-plan.md`
- `agent_prompt_templates/detailed-implementation-audit/post_implementation_audit.md`
- `src/jpg_boundary_kmz_core.py`
- `src/jpg_boundary_kmz_gui.py`
- `C:\Users\rbake\Desktop\VS Code Shortcuts\Buffer-Zone-Generator\src\buffer_zone_generator\geometry.py`

## Quick Answer Format

You can answer by filling this out:

```text
D1:
D2:
D3:
D4:
D5:
D6:
D7:
D8:
Notes:
```

## D1. Should `Auto` Be The Default Outline Mode For JPG Folders?

### Context

The planned V2 engine can support multiple outline modes:

- `Auto`
- `Concave hull`
- `Route-aware`
- `Lawnmower outer envelope`

The current app effectively behaves like `Concave hull` for JPG folders. `Auto` would run the preflight classifier first and then select the safest strategy.

### Options

Option A: Default to `Auto`.

Impact:

- Best chance of improving difficult JPG folders without requiring user tuning.
- Uses route-aware and lawnmower-specific logic when the classifier is confident.
- Requires strong fallback behavior so ambiguous cases still use concave hull.
- User may see different output than the current version by default.

Option B: Default to `Concave hull`.

Impact:

- Most backward-compatible behavior.
- New algorithms are opt-in.
- Safer during early rollout, but users may miss the improved behavior unless they change the mode.

Option C: Remember last selected mode.

Impact:

- Convenient after first use.
- Adds UI state persistence complexity.
- Not recommended for first implementation unless persistence already exists, which it does not today.

### Recommended Decision

Default to `Auto`, but require conservative fallback to concave hull and show the selected strategy in details. This aligns with the goal of better output while limiting risk.

## D2. For KMZ Polygon Input, Should Outline Mode Be Hidden, Disabled, Or Visible But Ignored?

### Context

JPG folders need outline inference. KMZ polygon input already supplies a polygon, so route-aware and lawnmower modes do not apply unless the app later supports reinterpreting polygon edges, which is not part of this plan.

### Options

Option A: Hide the outline mode control for KMZ input.

Impact:

- Cleanest UI for KMZ workflows.
- Avoids implying that camera-pattern logic applies to polygon input.
- Requires dynamic UI behavior when input type changes.

Option B: Disable the outline mode control with explanatory status text.

Impact:

- Makes it clear the feature exists but does not apply to KMZ files.
- Slightly more visible and transparent than hiding.
- Adds a small amount of UI state handling.

Option C: Leave visible but ignore it.

Impact:

- Simplest implementation.
- Highest confusion risk because selected mode appears meaningful but is ignored.
- Not recommended.

### Recommended Decision

Disable the control for KMZ input and show text such as `KMZ input uses the source polygon outline`. This is clearer than hiding and safer than silently ignoring.

## D3. Should Advanced Classifier Thresholds Be Internal Or Exposed In The GUI?

### Context

The classifier will need thresholds for confidence, row detection, gap detection, area ratios, route-order quality, and candidate rejection. Exposing these gives power users control but also increases UI complexity and support burden.

### Options

Option A: Keep thresholds internal.

Impact:

- Simpler UI.
- Easier to test and document.
- Reduces risk of users creating invalid or surprising outputs.
- Requires good default thresholds and clear fallback diagnostics.

Option B: Expose advanced controls in a collapsible advanced section.

Impact:

- Useful for edge cases and calibration.
- Adds more validation, caching, docs, and tests.
- Users can accidentally weaken safety gates.

Option C: Expose thresholds only through constants/config, not GUI.

Impact:

- Keeps UI simple while allowing developer tuning.
- Less accessible for non-technical users.
- Good middle ground if thresholds are still experimental.

### Recommended Decision

Keep thresholds internal for the first version. Add rich details output so we can inspect classifier behavior before deciding which controls deserve UI exposure.

## D4. What Acceptance Target Matters Most For Real Outputs?

### Context

Different success targets can push the algorithm in different directions. For example, maximizing point containment may over-buffer lawnmower flights, while matching a reference KMZ may preserve real boundaries better but requires reference data.

### Options

Option A: Visual inspection.

Impact:

- Practical and fast.
- Best when no ground truth exists.
- Hard to automate and subjective.

Option B: Maximum boundary deviation.

Impact:

- Quantitative and testable when a reference polygon exists.
- Similar in spirit to the other repo's Hausdorff-style verification.
- Requires reference geometry or generated expected geometry.

Option C: Area tolerance.

Impact:

- Easy to measure.
- Does not guarantee corners or intersections are correct.
- Useful as a guardrail, not a sole acceptance target.

Option D: Point containment.

Impact:

- Ensures camera points are not unexpectedly excluded.
- For lawnmower flights, not every interior point should define the boundary, so this must distinguish required boundary/control points from interior row points.

Option E: Comparison against hand-drawn/reference KMZ.

Impact:

- Best calibration path if available.
- Requires representative reference files.
- Enables meaningful regression tests and threshold tuning.

### Recommended Decision

Use reference KMZ comparison when available. Otherwise use a combined acceptance target: visual inspection plus area guardrails, required control-point coverage, and boundary-deviation diagnostics.

## D5. Do We Have Representative Real JPG Folders For Calibration?

### Context

Synthetic tests are necessary but not enough. The classifier will need real folders to tune thresholds for actual camera spacing, GPS noise, image ordering, and mixed capture patterns.

### Needed Sample Types

- Perimeter or boundary trace.
- Pure lawnmower/grid flight.
- Mixed route plus lawnmower.
- Complex corners or intersections.
- Any known failure cases from current output.

### Options

Option A: Provide sample folders before Phase 3.

Impact:

- Best chance of tuning Auto mode correctly.
- Lets tests and diagnostics reflect real data.
- May require adding only anonymized/synthetic fixtures to repo if real data should stay local.

Option B: Implement with synthetic tests first, then calibrate later.

Impact:

- Allows development to proceed.
- Auto thresholds should remain conservative.
- More likely to need follow-up tuning.

Option C: Require reference KMZs with sample folders.

Impact:

- Strongest validation.
- More upfront work.
- Best for objective acceptance criteria.

### Recommended Decision

Proceed with synthetic tests through Phase 2. Before Phase 3 threshold finalization, provide at least one real sample for each major pattern if possible.

## D6. Pin `shapely>=2.0` Or Implement Manual Segment Densification Fallback?

### Context

The other repo uses Shapely's `segmentize`, and the local machine has Shapely 2.0.7. The current requirements file does not pin versions. If another machine installs an older Shapely version, `segmentize` may not exist.

### Options

Option A: Pin `shapely>=2.0` in `requirements_jpg_boundary_kmz.txt`.

Impact:

- Cleaner implementation.
- Matches the local environment already verified.
- May force package upgrades on other machines.
- Requires dependency-file change.

Option B: Implement manual densification fallback.

Impact:

- More compatible with older Shapely versions.
- More code to test and maintain.
- Slightly higher implementation risk.

Option C: Runtime error with clear message if Shapely lacks `segmentize`.

Impact:

- Simple and explicit.
- Poorer user experience on older environments.
- Acceptable only if dependency installation guidance is clear.

### Recommended Decision

Pin `shapely>=2.0` unless there is a known machine that must stay on older Shapely. The app already relies on modern Shapely behavior such as concave hull.

## D7. Is There A Practical KMZ File-Size Or Vertex-Count Ceiling?

### Context

Higher buffer resolution and `segmentize(10m)` improve shape fidelity, especially around curves and corners. They also increase the number of exported vertices and can make KMZs larger or slower in Google Earth and downstream tools.

### Options

Option A: No explicit ceiling for now.

Impact:

- Simplest.
- Best geometry fidelity.
- Risk of very large outputs on large or highly curved projects.

Option B: Set a soft warning threshold.

Impact:

- Output still exports.
- Details can warn when vertex count is high.
- Good balance for first version.

Option C: Set a hard maximum vertex count.

Impact:

- Prevents huge KMZs.
- May force simplification and reduce boundary fidelity.
- Requires clear error or auto-simplification behavior.

### Recommended Decision

Use a soft warning threshold first. Do not block export unless a real downstream ceiling is known.

## D8. When `Auto` Is Uncertain, Should Fallback Be Silent Or Shown As A GUI Warning?

### Context

Auto mode should fall back to concave hull when the classifier is uncertain or a better candidate fails safety gates. The question is whether that should be visible in the normal UI or only in details.

### Options

Option A: Silent fallback, details only.

Impact:

- Less noisy UI.
- Users may not realize Auto did not use new logic.
- Good if fallback is common and expected.

Option B: Non-blocking warning in status/details.

Impact:

- More transparent.
- Helps users understand why output did not change.
- Slightly more UI messaging to manage.

Option C: Blocking dialog.

Impact:

- Very visible.
- Too disruptive for normal fallback behavior.
- Not recommended unless output may be unsafe.

### Recommended Decision

Use a non-blocking status/details warning, not a modal dialog. Example: `Auto used Concave hull fallback: row confidence was too low.`

## Summary Of Recommended Answers

```text
D1: Auto default for JPG folders, with conservative concave fallback.
D2: Disable outline mode for KMZ input with explanatory status text.
D3: Keep advanced thresholds internal for first version.
D4: Prefer reference KMZ comparison; otherwise use visual + guardrail metrics.
D5: Use synthetic tests through Phase 2, then calibrate with real samples before final Auto thresholds.
D6: Pin shapely>=2.0 unless older environments must be supported.
D7: Use a soft vertex-count warning, no hard ceiling unless required.
D8: Show non-blocking fallback warning in status/details.
```

