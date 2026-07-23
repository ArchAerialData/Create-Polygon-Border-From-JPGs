
Please review and harden this implementation plan before making any code changes.

This is a planning-first task. Do not edit, create, delete, move, format, or refactor implementation files until the hardened implementation blueprint is complete and the approved file allow-list is defined. The main plan and the temporary unresolved-decision sidecar required below are planning artifacts and may be created, updated, or removed during planning; this exception does not authorize production code, runtime data, configuration, template, dependency, or other implementation changes.

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

### 4. Mandatory Temporary Decision Sidecar and Readiness Certification

If any unresolved question, decision, ambiguity, approval, assumption requiring confirmation, missing evidence, blocker, or required user input exists anywhere in the plan, the plan is not implementation-ready.

The agent must create a temporary Markdown sidecar in the same directory as the main plan. Use this naming convention:

- If the main filename ends in `_PLAN.md` or `_BLUEPRINT.md`, replace that suffix with `_OPEN_DECISIONS.md`.
- Otherwise append `_OPEN_DECISIONS.md` to the main filename stem.

The sidecar is a temporary decision interface, not a second source of implementation truth. While it exists, the main plan remains the authoritative technical blueprint and must identify the sidecar in its blockers/readiness sections.

#### Sidecar trigger and completeness rules

- Create the sidecar as soon as the first unresolved item is identified; do not wait until the end of planning.
- Review the entire plan and repository evidence for unresolved items. Do not include only the most obvious blockers.
- Include technical ambiguities that would cause materially different implementations, even if the agent has a recommendation.
- Resolve routine implementation details directly from verified repository evidence when there is one clearly safer, contract-preserving choice. Do not manufacture unnecessary user decisions.
- Do not begin implementation while any sidecar item is pending or while the readiness certification is `NO`.
- If the plan has no unresolved item, do not create a sidecar merely for process compliance.

#### Required sidecar structure

The sidecar must contain:

1. A title identifying the main plan.
2. A clear temporary status banner and a link/path to the main plan.
3. Instructions explaining both supported response methods:
   - reply in chat using the stable decision number/ID and option, for example `1A, 2C, 3A`; or
   - edit the `User decision` fields directly in the sidecar for complex answers.
4. An implementation-readiness status of `NO` while any item is pending.
5. A compact decision index showing stable IDs, short titles, status, and recommended options.
6. One numbered section for every unresolved item, each containing:
   - stable ID such as `D-001`;
   - status (`PENDING`, `ANSWERED`, `NEEDS FOLLOW-UP`, or `SUPERSEDED`);
   - the question or decision required;
   - why it matters and what behavior/files/contracts it affects;
   - direct repository evidence and relevant main-plan sections;
   - mutually exclusive options when possible, labelled `A`, `B`, `C`, and so on;
   - operational impact and tradeoffs for every option;
   - one clearly identified recommended option with rationale;
   - a `User decision` field;
   - a `User notes` field for complex or conditional direction;
   - follow-up requirements, if any.
7. A response template the user can copy into chat.
8. A resolution checklist covering propagation, full-plan review, readiness certification, and sidecar deletion.

Do not record secrets, tokens, credentials, or unnecessary sensitive data in the sidecar.

#### Receiving answers and handling follow-ups

When the user answers in chat or edits the sidecar, the agent must:

1. Re-read the complete sidecar and the complete main plan.
2. Map every answer to its stable decision ID; do not rely only on answer order if IDs are present.
3. Record the selected option or custom answer, answer source (`chat` or `sidecar`), and resolution date in the sidecar while it is still active.
4. Verify whether the answer changes scope, contracts, risks, file allow-list, phases, tests, acceptance criteria, rollback, or decommission behavior.
5. Propagate the decision into every affected section of the main plan. Removing the item only from the blockers section is insufficient.
6. Re-run repository investigation when an answer introduces new scope or contradicts prior evidence.
7. Update an existing sidecar item when follow-up is required; retain its stable ID and set `NEEDS FOLLOW-UP`.
8. Add newly discovered decisions as new stable IDs without renumbering or silently replacing earlier items.
9. Mark obsolete items `SUPERSEDED` and identify the replacement ID rather than deleting unresolved history while the sidecar is active.
10. Repeat until every sidecar item is answered and all necessary follow-ups are resolved.

If the user edits the sidecar directly, inspect the actual file changes and resolve conflicting or incomplete entries before treating them as decisions.

#### Final full-plan audit and mandatory certification

After all answers are received and propagated, re-read the entire main plan from beginning to end and confirm all of the following:

- No unresolved questions remain.
- No decisions or approvals remain pending.
- No ambiguity remains that could lead to materially different implementations.
- No assumption still requires user confirmation.
- No blocker or missing evidence remains.
- No required user input remains.
- All decisions are reflected consistently in scope, constraints, risks, allow-list, phases, tests, acceptance criteria, rollback, decommission, and readiness sections.
- The strict file allow-list is complete for the final chosen implementation.
- The plan contains no stale language saying a resolved decision is still pending, recommended, proposed, or awaiting approval.

The final readiness assessment and the agent's chat response must use one of these explicit certifications:

```text
Implementation Ready: YES
No unresolved questions, decisions, assumptions requiring confirmation, approvals, blockers, missing evidence, ambiguities, or required user input remain.
```

or:

```text
Implementation Ready: NO
Remaining decisions are documented in <sidecar path/link>.
```

Never state `Implementation Ready: YES` merely because the required sections exist. State it only after the full-plan audit proves the sentence is true.

#### Sidecar cleanup

Once and only once all decisions are final, fully propagated into the main plan, and the full-plan audit supports `Implementation Ready: YES`, the agent must:

1. Preserve any decision rationale needed for implementation in the main plan, including a concise dated decision record or completion note.
2. Remove links or dependencies in the main plan that require the temporary sidecar to exist.
3. Delete the temporary sidecar before implementation begins.
4. Verify through repository status/search that the sidecar is gone and no stale references remain.
5. State clearly in chat that the plan is implementation-ready and that the temporary sidecar was removed.

Do not delete a sidecar while any item is pending, answered but not propagated, or awaiting follow-up. If new ambiguity is discovered before implementation, recreate or update the sidecar and return readiness to `NO`. If new ambiguity is discovered during implementation, pause implementation, create or restore the sidecar, revise the plan and allow-list, resolve the item, repeat the full-plan audit, and resume only after `Implementation Ready: YES` is valid again.

### 5. Edge Case and Failure Mode Review

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

### 6. Conflict and Regression Analysis

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

### 7. Strict File Allow-List

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

### 8. Phase Gates

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

### 9. Testing and Regression Requirements

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

### 10. Pre-Implementation Checklist

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
- Every unresolved item is captured in the temporary decision sidecar
- Every sidecar decision has been propagated into all affected main-plan sections
- The full-plan audit has been completed
- The final readiness certification is `Implementation Ready: YES`
- The temporary sidecar has been deleted and stale references have been removed

### 11. Post-Implementation Validation

Define the required validation before merge/approval, including:

- Full relevant test command list
- Lint/type/build commands
- Manual verification steps if needed
- Expected outputs
- Regression checks
- Files changed review
- Confirmation that no non-allow-listed files were modified
- Confirmation that no temporary, placeholder, TODO, mock, or debug logic was introduced
- Confirmation that no temporary unresolved-decision sidecar or stale reference to one remains
- Confirmation that public interfaces, config structures, schemas, CLI arguments, API payloads, and naming conventions remain consistent

### 12. Rollback and Recovery

Include rollback/recovery planning for risky changes, including:

- How to revert each phase
- Whether migrations are reversible
- Whether generated outputs need cleanup
- Whether config changes are backward compatible
- How partial failure is isolated
- How to restore previous behavior if validation fails

### 13. Final Output Format

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

When blockers or required decisions exist, Section 13 must link to the temporary sidecar and Section 14 must state `Implementation Ready: NO`. When none remain, Section 13 must explicitly state that there are no unresolved items and Section 14 must include the exact `Implementation Ready: YES` certification defined above.

The final output should be a production-grade implementation blueprint. The goal is to eliminate avoidable follow-up work caused by incomplete planning, shallow repository analysis, stale assumptions, missed integration risks, or failure to inspect enough of the codebase before implementation.
