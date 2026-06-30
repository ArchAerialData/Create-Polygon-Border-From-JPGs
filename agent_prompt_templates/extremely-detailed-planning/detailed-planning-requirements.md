Please review and harden this implementation plan before making any code changes.

This is a planning-first task. Do not edit, create, delete, move, format, or refactor any files until the hardened implementation blueprint is complete and the approved file allow-list is defined.

The objective is to maximize the likelihood of a successful “one-shot” implementation with minimal follow-up fixes, rewrites, regressions, or emergency patches. Treat this as a production-grade implementation review, not a lightweight task list.

## Required Planning Process

### 1. Repository Discovery and Impact Analysis

Perform a deep codebase review across all related:

- Modules
- Utilities
- Config files
- Schemas
- Services
- Tests
- Scripts
- Build/deployment files
- Pipelines
- CLI entry points
- API contracts
- Database models/migrations
- Frontend/backend consumers
- Downstream workflows

Do not limit analysis to files explicitly referenced in the initial request. Trace:

- Imports and exports
- Shared utilities
- Inheritance chains
- Feature flags
- Environment variables
- Config loading paths
- API payload structures
- Database interactions
- Serialization/deserialization logic
- Async behavior
- Caching behavior
- File path assumptions
- Runtime/deployment assumptions
- Existing tests and fixtures
- Legacy or parallel implementations

### 2. Evidence Requirements

Every proposed change must be backed by direct repository evidence.

For each finding, include:

- Exact file path
- Relevant function, class, method, config key, schema, route, command, or test name
- Why the file is relevant
- Whether the finding was verified directly from code, inferred, or still uncertain

Do not rely on stale documentation, assumptions, memory, or naming guesses. Verify that all referenced paths, modules, functions, classes, environment variables, commands, and test files actually exist before including them in the plan.

If something cannot be verified from the repository, label it as an unresolved risk or blocker instead of treating it as fact.

### 3. Assumptions and Unknowns

Explicitly document all assumptions.

For each assumption, classify it as:

- Verified from code
- Likely but not fully proven
- Unverified risk
- Blocker requiring clarification

Any assumption that cannot be verified from the codebase must be treated as a risk and either investigated further or isolated from implementation.

### 4. Edge Case and Failure Mode Review

Identify edge cases, bugs, and gaps that may not have been accounted for in the initial plan, including:

- Empty/null/missing inputs
- Invalid or unexpected file paths
- Permission issues
- Large inputs or performance-heavy workflows
- Race conditions
- Async timing issues
- Partial failures
- Retry behavior
- Caching conflicts
- Backward compatibility issues
- Schema/version mismatches
- Environment-specific behavior
- Windows/Linux path differences
- Local vs deployed runtime differences
- Existing legacy workflows that may still be active
- Duplicate or parallel logic that could conflict with the new implementation

### 5. Conflict and Regression Analysis

Identify potential conflicts with:

- Existing functionality
- Existing tests
- Legacy workflows
- Deprecated logic
- Feature toggles
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
- Linting/formatting rules

Define regression risks for all adjacent workflows that could be unintentionally impacted.

### 6. Strict File Allow-List

Create a strict file allow-list before implementation begins.

For every file proposed to be modified, created, deleted, or moved, include:

- Exact path
- Type of change
- Reason the change is necessary
- Related tests that must cover the change
- Risk level
- Rollback notes

No files outside the allow-list may be touched unless explicitly justified in a revised plan before implementation.

Avoid broad refactors, unrelated cleanup, formatting-only changes, dependency updates, generated file changes, or opportunistic improvements unless they are required for the implementation and explicitly approved in the plan.

### 7. Phase Gates

Break the implementation into phases.

Each phase must include:

- Goal
- Exact files allowed to be touched
- Specific implementation tasks
- Required tests
- Required lint/type/build commands
- Expected outputs
- Failure conditions
- Pass/fail criteria
- Rollback/recovery notes

No downstream phase should begin until all validation checks, tests, linting, builds, and acceptance criteria from the current phase pass successfully.

### 8. Testing and Regression Requirements

Define concrete testing requirements before implementation.

Include:

- Unit tests
- Integration tests
- Regression tests
- Smoke tests
- CLI/API tests where applicable
- Fixture updates if needed
- Negative/error-path tests
- Backward compatibility tests
- Existing tests that must continue passing

For each test, specify:

- Exact test file path
- Test name or proposed test name
- Scenario being tested
- Expected result
- Failure condition
- Command used to run the test

Testing must cover both the new behavior and adjacent existing workflows that could regress.

### 9. Pre-Implementation Checklist

Before any code changes begin, verify:

- Current branch/status is clean or documented
- Relevant files and symbols exist
- Existing tests related to the target area are identified
- Existing behavior is understood
- Dependencies and lock files are checked
- Environment variables/config keys are verified
- Known risks and unknowns are documented
- File allow-list is complete
- Implementation phases and gates are defined
- Rollback strategy is documented

### 10. Post-Implementation Validation

Define the required validation before merge/approval, including:

- Full relevant test command list
- Lint/type/build commands
- Manual verification steps if needed
- Expected outputs
- Regression checks
- Files changed review
- Confirmation that no non-allow-listed files were modified
- Confirmation that no temporary, placeholder, TODO, mock, or debug logic was introduced
- Confirmation that public interfaces, config structures, schemas, CLI arguments, API payloads, and naming conventions remain consistent

### 11. Rollback and Recovery

Include rollback/recovery planning for risky changes, including:

- How to revert each phase
- Whether migrations are reversible
- Whether generated outputs need cleanup
- Whether config changes are backward compatible
- How partial failure is isolated
- How to restore previous behavior if validation fails

### 12. Final Output Format

Return the hardened plan using this structure:

1. Executive summary
2. Current repository findings
3. Exact impacted files and symbols
4. Risk matrix
5. Assumptions and unknowns
6. Edge cases and failure modes
7. Strict file allow-list
8. Implementation phases with gates
9. Testing and regression matrix
10. Pre-implementation checklist
11. Post-implementation validation checklist
12. Rollback/recovery plan
13. Blockers or items requiring clarification
14. Final readiness assessment

The final output should be a production-grade implementation blueprint. The goal is to eliminate avoidable follow-up work caused by incomplete planning, shallow repository analysis, stale assumptions, missed integration risks, or failure to inspect enough of the codebase before implementation.
