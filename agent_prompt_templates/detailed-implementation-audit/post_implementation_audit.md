Please perform a strict post-implementation audit and hardening pass on the completed changes.

This is a verification, correction, and closeout task. The objective is to scrutinize the implementation, identify and resolve any bugs, gaps, regressions, edge cases, UI issues, weak code paths, missing tests, or incomplete behavior, and continue iterating until the feature is fully implemented, hardened, polished, validated, and ready to close.

Treat this as a production-grade post-implementation audit, not a quick review.

## Required Audit Process

### 1. Implementation Discovery and Change Review

First, inspect the completed implementation before making additional changes.

Review:

- All files changed by the implementation
- Related modules, utilities, configs, schemas, services, routes, components, tests, scripts, and build files
- Any files that import or consume the changed code
- Any downstream UI, API, CLI, database, or integration workflows affected by the change
- Existing tests and fixtures related to the changed behavior
- Any temporary, placeholder, mock, debug, or incomplete logic introduced during implementation

Do not assume the implementation is complete because the original task appears finished. Verify behavior directly from the repository.

For each finding, include:

- Exact file path
- Relevant function, class, method, component, config key, schema, route, command, or test name
- What was verified directly from code
- Whether the issue is confirmed, likely, uncertain, or not reproducible
- Whether a patch is required

### 2. Original Requirement Compliance Check

Compare the final implementation against the original requested behavior and implementation plan.

Verify that:

- Every stated requirement was implemented
- Acceptance criteria are satisfied
- No requirement was partially implemented or skipped
- No behavior was implemented in a way that only works for the happy path
- Public interfaces, naming conventions, routes, payloads, config structures, schemas, and UI behavior remain consistent
- The feature is usable through the intended UI/workflow, not just technically present in code

Document any requirement that is:

- Fully satisfied
- Partially satisfied
- Missing
- Implemented but fragile
- Implemented but not sufficiently tested
- Blocked by unclear requirements

### 3. Edge Case and Failure Mode Audit

Actively search for edge cases and failure modes that may not have been handled.

Check for:

- Empty, null, missing, undefined, malformed, or unexpected inputs
- Invalid IDs, paths, URLs, payloads, states, or user selections
- Permission and authorization issues
- Large inputs, slow operations, or performance-heavy workflows
- Race conditions and async timing issues
- Partial failures and retry behavior
- Caching or stale-state conflicts
- State management inconsistencies
- Backward compatibility problems
- Schema, type, migration, or version mismatches
- Windows/Linux path differences where applicable
- Local vs deployed runtime differences
- UI refresh, loading, disabled, error, and success states
- Duplicate submissions or repeated actions
- Legacy workflows or parallel code paths that could conflict with the new implementation

Patch confirmed issues directly. If an issue cannot be safely resolved, document it as an unresolved risk with exact reasoning.

### 4. Conflict and Regression Audit

Identify whether the implementation conflicts with any existing behavior.

Review potential regressions involving:

- Existing functionality
- Existing tests
- Legacy workflows
- Deprecated logic still in use
- Feature flags
- Background jobs
- Scheduled tasks
- API consumers
- CLI users
- Database migrations
- External integrations
- Deployment scripts
- Build tooling
- Dependency versions
- Lock files
- Type definitions
- Linting and formatting rules

Do not introduce broad refactors, unrelated cleanup, formatting-only changes, dependency updates, or opportunistic improvements unless required to fix a confirmed implementation issue.

### 5. Code Quality and Maintainability Audit

Review the changed code for production readiness.

Check for:

- Overly complex logic
- Duplicated logic
- Fragile assumptions
- Poor separation of concerns
- Weak error handling
- Missing logging where useful
- Excessive logging or debug output
- Inconsistent naming
- Inconsistent patterns compared to the surrounding codebase
- Unused imports, dead code, TODOs, mocks, placeholders, console logs, print statements, or commented-out implementation fragments
- Missing types or weak type coverage
- Incomplete validation
- Security or data exposure risks
- Accessibility or UI usability issues where applicable

Patch issues that materially affect correctness, maintainability, safety, or user-facing quality.

### 6. Test Coverage Expansion

Audit and extend tests before declaring the task complete.

Add or update tests for:

- Main happy-path behavior
- Important edge cases
- Negative/error-path behavior
- Regression coverage for adjacent workflows
- Backward compatibility where relevant
- UI behavior where applicable
- API/CLI behavior where applicable
- State transitions, loading states, and failure handling where applicable

For each test added or updated, ensure:

- The test has a clear purpose
- The test would fail without the implementation or patch
- The expected result is specific
- The test is not overly brittle
- The test follows existing project conventions

Do not rely only on manual inspection if automated tests can reasonably cover the behavior.

### 7. Iterative Error Resolution

Run the appropriate validation commands and resolve failures iteratively.

Validation should include, as applicable:

- Relevant unit tests
- Relevant integration tests
- Full test suite if practical
- Type checks
- Lint checks
- Formatting checks
- Build command
- UI smoke test or manual verification steps
- Any project-specific validation commands

If any command fails:

1. Investigate the root cause.
2. Patch the issue.
3. Re-run the failed command.
4. Continue until the validation passes or the failure is proven unrelated and documented with evidence.

Do not stop after the first fix if additional failures remain.

### 8. UI and End-to-End Usability Verification

If the implementation affects the website UI, verify that the completed behavior is actually usable through the UI.

Check:

- The feature is visible or reachable from the expected location
- User actions trigger the correct behavior
- Loading, empty, success, and error states behave correctly
- Data shown in the UI matches backend/source behavior
- The UI does not require hidden manual steps
- The page does not break on refresh or navigation
- The behavior works for realistic user inputs
- The feature is polished enough to be considered complete from the user’s perspective

If browser-based testing is available in the repo, use it. If not, document exact manual verification steps and expected results.

### 9. Strict Patch Scope Control

Only modify files necessary to fix confirmed audit findings, test gaps, or validation failures.

Before making changes, identify the patch scope:

- Exact files expected to be touched
- Reason each file may need changes
- Risk level of each change
- Tests or validation that will cover each change

After changes are complete, confirm:

- No unrelated files were modified
- No generated files, dependency files, lock files, or formatting-only changes were introduced unless required
- No temporary/debug/placeholder code remains
- No broad refactor was performed outside the audit scope

### 10. Final Validation Requirements

Before declaring the task complete, provide a final validation summary including:

- Commands run
- Whether each command passed or failed
- Any failures fixed during the audit
- Any failures that remain and why
- Tests added or updated
- Files changed during the audit
- Remaining risks or limitations
- Manual UI verification performed, if applicable
- Confirmation that the implementation is ready to close or a clear explanation of why it is not

### 11. Final Output Format

Return the audit results using this structure:

1. Executive summary
2. Original requirement compliance review
3. Files inspected
4. Issues found
5. Patches applied
6. Edge cases and failure modes reviewed
7. Tests added or updated
8. Validation commands run
9. UI/manual verification results
10. Regression risk assessment
11. Remaining risks, blockers, or unresolved items
12. Final readiness assessment

The final readiness assessment must clearly state one of the following:

- Ready to close
- Ready to close with documented minor risks
- Not ready to close

Do not mark the task ready to close unless the implementation has been audited, patched where necessary, tested, validated, and verified as usable through the intended workflow.
