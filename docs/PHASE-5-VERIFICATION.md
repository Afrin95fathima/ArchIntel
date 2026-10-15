# Phase 5 verification

Phase 5 implements modernization intelligence for a local, single-process prototype. Implementation and regression validation are complete. This is the Phase 5 user-verification checkpoint (5 October 2026 local time).

## Delivered behavior

- Immutable, idempotent planning proposals bound to captured architecture versions, source digest and derivation versions.
- Existing structural scores preserved; reviewed domain memberships recomputed without modifying source snapshots.
- Separate structural/runtime/combined readiness and component-based evidence confidence. Missing runtime remains unavailable, not zero readiness.
- Canonical evidence-linked findings, conservative decisions and explicit extraction blockers.
- Six target strategy proposals, dependency-first waves and coupled cyclic groups.
- Independent proposal publication validator; no client/model-supplied scores or unsupported execution.
- Actor-attributed planning review revisions with stale-context rejection.
- Typed deterministic explanations, canonical fact provenance and frozen JSON exports.
- Separate persistent Neo4j planning scope with idempotent rebuild, graph integrity checks and relational fallback.
- Modernization intelligence workspace, user/developer manuals and browser workflow.

## Validation record

- Focused initial Phase 5 suite: **20 passed**, including a real Neo4j projection. An initial test fixture aliasing issue was corrected before this passing run.
- New browser workflow: **passed**, including preview/save, explanation, scores, waves, planning review, export, reload and Neo4j display.
- Existing frontend unit tests: **5 passed** across 3 files.
- TypeScript and production Vite build: **passed**. Existing large-bundle warning remains (~812 kB minified bundle).
- Python dependency check: **no broken requirements**. npm direct dependency check: **passed**.
- Full backend regression: **167 passed**, no failures or skips, in 550.75 seconds with scanner, model, PostgreSQL and graph integration flags enabled.
- Final focused Phase 5 suite after the context-privacy refinement: **23 passed**, including PostgreSQL restart and Neo4j isolation checks.
- Browser regression: **all 7 workflows have passing results across the full and focused runs**. The full run passed 6 and timed out on the existing local-model registration assertion. The test now awaits and checks the registration HTTP response; its focused rerun passed with an actual local-model response and validated citation history. No application AI policy or behavior was changed for this test correction.

## Real-data integration

[Integration report](phase5-integration-validation.json): an isolated PostgreSQL schema imported the retained real Phase 3 PetClinic capture (190 spans, 83 traces). It generated 5 domain assessments, 2 waves and a separate planning graph with 213 nodes / 864 relationships. Validation passed; original static and canonical evidence snapshots were unchanged. An API restart preserved the frozen export, planning review and Neo4j graph. Temporary database and graph scopes were removed afterward.

This reuses previously validated real Java telemetry. It does not claim a fresh Java workload or a performed modernization transformation.

## Preservation and deployment

The additive migration is `0005` to `0006`. Before restart, the actual local workspace had no active analyses/runtime collection. Before/after canonical row hashes were compared for projects, applications, artifacts, analysis/runtime snapshots, principals, policy revisions, AI providers and canonical evidence tables. Existing user policy and model registrations are not changed by Phase 5.

[Preservation report](phase5-preservation-validation.json): all compared records were unchanged, including 7 projects, 7 applications, 8 artifacts, 8 analysis runs, 3 runtime sessions, 1 principal and 1 policy revision. No provider or canonical version was created in the user's workspace by validation. The live API reports ready with PostgreSQL/scanner available; authenticated Neo4j connectivity passed. The updated application is running at `http://127.0.0.1:8000`.

Known non-failing diagnostics: existing Starlette/httpx deprecation warnings, Vite bundle-size warning, and Neo4j informational messages for existing constraints/indexes and unique-ID endpoint matching. Dependency checks are not a security-vulnerability audit.

## Deliberate limits

- Scores and confidence use transparent, fixture-validated heuristics; no empirical success-probability calibration is claimed.
- Domain observation measures selected workloads, not behavioral test coverage.
- Source/build identity, contracts, data ownership and human change approval remain blockers. Phase 5 cannot publish EXTRACT_NOW or execute source changes.
- Cloud, Java and framework targets are review proposals with compatibility-inventory blockers, not validated upgrade plans.
- Review approval is planning-only. The latest captured application version defines current context; historical proposals remain readable.
- Graph rebuild is manual after planning projection failure; no new distributed scheduler or leases are introduced.
- Limits remain 500 domains / 30,000 facts per proposal, bounded graph projections/queries, single API process and local Neo4j. No enterprise deployment, load certification or production backup/restore claim is made.
- No new model access, external destination, provider registration or data export to a third party is introduced.

Phase 6 is not part of this delivery.
# Decision-brief and strategy-comparison enhancement (11 October 2026)

The planning proposal now contains a readable decision brief and an evidence-linked comparison of all six currently supported strategies. The selected option is explicitly labeled as user input. The engine does not rank strategies or claim a winner. Comparison statuses indicate review evidence sufficiency only; they are not calibrated probabilities, cost estimates or outcome predictions. Cloud and upgrade options continue to expose the missing compatibility inventory. The frozen export includes the brief, comparison, risks, unknowns and evidence finding references.

The UI now opens saved plans on the **Decision brief** tab and shows the evidence scope, selected option, strategy rationales, related finding text, unresolved questions and suggested discovery step. The independent validator checks comparison finding references and rejects automatic-winner claims. The derivation rule version is now `modernization-intelligence-2`; calibration remains `fixture-calibration-1` because score calculations did not change.

Validation for this enhancement: focused modernization tests **22 passed, 2 skipped**; frontend tests **6 passed**; frontend production build succeeded. The frontend build still reports its pre-existing large-chunk advisory. The two skipped backend tests require optional live database/graph services. This validates deterministic fixtures and application compilation, not a new real-application modernization outcome or empirical strategy calibration.

