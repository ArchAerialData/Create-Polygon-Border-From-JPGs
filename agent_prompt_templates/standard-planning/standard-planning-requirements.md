Please review this task and create a concise but thorough implementation plan before making any code changes.

This is a planning-first task. Do not edit, create, delete, move, format, or refactor any files until the implementation plan is complete and the expected file changes are clearly identified.

The goal is to maximize the chance of a clean one-shot implementation while avoiding unnecessary over-planning for a relatively contained task.

## Required Review Process

### 1. Understand the Existing Code

Before proposing changes, inspect the relevant parts of the codebase and identify:

- Existing files related to this task
- Relevant functions, classes, routes, schemas, configs, tests, or utilities
- Current behavior that must be preserved
- Any nearby logic that could be affected by the change
- Existing tests or fixtures related to this area

Do not rely only on the files mentioned in the request. Follow imports, shared utilities, and direct consumers where needed to avoid missing obvious conflicts.

### 2. Verify Before Assuming

For every proposed change, verify that referenced paths, modules, functions, classes, commands, config keys, and tests actually exist.

If something cannot be verified from the repository, clearly label it as an assumption or open question instead of treating it as fact.

### 3. Identify Likely Edge Cases

Consider the most likely edge cases for this task, including:

- Missing or invalid inputs
- Empty data
- Bad file paths
- Permission issues
- Unexpected config values
- Backward compatibility issues
- Existing workflows that may depend on current behavior
- Local vs deployed/runtime differences, if relevant

Focus on realistic risks rather than theoretical edge cases that do not apply to this task.

### 4. Define a File Change Allow-List

Before implementation, list the exact files expected to be touched.

For each file, include:

- Exact path
- Planned change
- Why the change is necessary

Do not modify files outside this list unless the plan is updated first with a clear justification.

Avoid unrelated cleanup, broad refactors, formatting-only changes, dependency changes, or opportunistic improvements unless they are directly required for this task.

### 5. Create a Short Implementation Plan

Break the work into clear steps.

Each step should include:

- What will be changed
- Which file or symbol is involved
- What could go wrong
- How the change will be verified

Keep the plan practical and focused.

### 6. Testing Requirements

Before coding, identify the tests that should be run or added.

Include:

- Existing tests that must still pass
- New tests needed for the change
- Regression tests for nearby behavior
- Manual verification steps if automated tests are not available

For each test or check, include:

- Exact command, if known
- Expected result
- Failure condition

If no test coverage exists, propose the smallest reasonable test addition or explain the manual validation required.

### 7. Implementation Gates

Use simple gates before moving forward:

1. Baseline check completed
2. File allow-list confirmed
3. Implementation completed only within allowed files
4. Tests/checks passed
5. Final changed-files review completed

Do not continue if a gate fails. Document the failure and revise the plan before proceeding.

### 8. Final Validation

After implementation, verify:

- Only allow-listed files were changed
- No unrelated formatting or refactoring was introduced
- No temporary, placeholder, TODO, mock, or debug logic was added
- Existing behavior still works
- New behavior works as intended
- Tests/checks pass
- Any assumptions or unresolved risks are documented

## Final Output Format

Return the plan using this structure:

1. Summary of task
2. Relevant existing files/symbols reviewed
3. Assumptions or open questions
4. Expected file allow-list
5. Implementation steps
6. Edge cases to account for
7. Tests and validation commands
8. Final gate checklist

The output should be detailed enough to prevent lazy implementation mistakes, but not so heavy that it creates unnecessary planning overhead for a contained task.
