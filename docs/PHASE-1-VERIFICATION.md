# Phase 1 delivery and verification

4 October 2026. Enterprise roadmap Phase 1 is delivered for user verification. Phase 2 has not started. This is a local security foundation, not a claim of production certification or completion of the full modernization platform.

## Work done and outcome

| Work | Outcome |
|---|---|
| Identity and sessions | One-time owner setup; human/service identities; password hashing; bounded sessions; login throttling; CSRF; logout/revocation; password changes invalidate other sessions |
| Workspace permissions | Management APIs require explicit permissions; projects, artifacts, analyses, runtime sessions/evidence and security records use authenticated tenant scope |
| Source security gateway | Explicit per-identity repository scope; full commit pinning; protected-path precedence; operator-approved roots; regular committed UTF-8 files only; bounded all-or-nothing reads |
| Policy and audit | Revision-checked policies; external transfer denied; source reads audited before release; metadata hash chains; database update/delete guards; audit verification UI/API |
| User interface | Setup/login shell and Security & access console, account/password administration, isolated workspaces, repository/scope forms and source requests |
| Existing behavior | Static analysis and runtime pipeline retained; deterministic assistants work; direct model calls disabled until Phase 2; shared four-job admission limit preserved |
| Handoff | User flow and developer internals in Markdown/HTML/PDF; main manuals refreshed; roadmap status updated |

## Executed validation

- Full backend run with real Java scanner tests enabled: **82 passed, 1 failed** in 476.53 seconds. The failure was a new test expecting a deliberately omitted tenant_id response field. It was corrected to check persisted ownership and endpoint isolation; the focused correction passed.
- Final complete security and runtime suites after that correction: **43 passed** in 178.01 seconds, covering login, CSRF, revocation/password changes, workspace isolation, explicit source grants, protected/path escape denials, pinned committed content, policy updates/limits, audit failure, migration preservation, runtime management and ingestion identities, existing runtime normalization/mapping/coverage/fusion/intelligence.
- Foundation regressions plus the added cross-workspace queue-capacity test after the final admission fix: **7 passed** in 25.05 seconds.
- Across the full run and subsequent corrected/added targeted runs, **all 84 current backend cases have passing results**. This is not represented as one uninterrupted 84-pass run.
- Final pinned-source regression after disabling Git lazy fetch: **1 passed**.
- Dependency consistency: `pip check` found no broken requirements; `npm.cmd ls --depth=0` passed. The live-check credential guard was also exercised and refused to proceed without a configured service token.
- Frontend unit tests: **5 passed**. Final TypeScript check and Vite production build passed.
- Real Chrome, isolated database and real prepared Java scanner: **3 passed** in 3.5 minutes. Tested first setup, login/logout, password change, restricted user UI/API denial, workspace creation, audit verification, full static investor walkthrough with report export, and fresh WAR upload through completed results.
- Browser harness initially generated different temporary paths per worker; the harness was corrected before the successful three-test run. It never initialized the real owner account.
- Operator scripts compile and now require an explicit service credential; no new live PetClinic telemetry run is claimed. Existing runtime browser fixture was not rerun in this phase. Runtime regression/API isolation tests did run.

Warnings: FastAPI/Starlette test-client dependency deprecations remain. Vite reports a roughly 775 KB minified JavaScript chunk; splitting it is a later performance task. These checks do not constitute a dependency vulnerability scan.

## Existing PostgreSQL data preservation

The database was at revision 0002 with no active scans or RUNNING runtime sessions before migration. A local pre-migration row snapshot was stored under `.data/phase1-migration-snapshot`. The additive migration reached 0003. Counts and canonical row hashes match before and after for every table below:

| Table | Rows | Result |
|---|---:|---|
| projects | 7 | Unchanged |
| applications | 7 | Unchanged |
| artifacts | 8 | Unchanged |
| analysis_runs | 8 | Unchanged |
| runtime_sessions | 3 | Unchanged |

Comparison records are `.data/phase1-before-migration.json` and `.data/phase1-after-migration.json`. The row snapshot is local preservation evidence, not a certified restore backup. PostgreSQL audit UPDATE and DELETE attempts were rejected by the installed trigger; the validation transactions were rolled back.

The live service responds on http://127.0.0.1:8000. Public health/readiness and setup status are available. Unauthenticated project/OpenAPI requests return 401. **Real administrator setup remains pending**, so the user chooses their own username and password; test credentials were confined to isolated databases.

## Remaining boundaries

- One local API process. No distributed authorization fencing/job leases, SSO, automated password recovery or credential renewal.
- Scoped ORM authorization is not database row-level security. Filesystem/DB operators remain trusted.
- Source reads are local and read-only. Sensitive-content classification/redaction and model routing belong to Phase 2. Filename blocking is not full secrets scanning.
- The audit chain detects ordinary modification but has no independent external anchor against a database owner replacing the entire chain. General business writes record intent; not all business outcomes are atomically audited.
- Production TLS/deployment, OS execution sandboxing, tested disaster recovery, automated transformations, extraction and modernization delivery workflows remain roadmap work.

## User verification checkpoint

1. Start/open ArchIntel, read `.data/security-bootstrap.key` locally, and create your own administrator.
2. Open a saved analysis and inspect Dynamic analysis to verify your existing work is visible.
3. Open Security & access, create a restricted test identity, sign out, and verify its restricted access.
4. Optionally register a local source checkout and verify one permitted and one protected-file request using PHASE-1-USER-FLOW.md.
5. Review audit verification and the documented limits.

After the user accepts this checkpoint, the next phase is the policy-controlled AI gateway with context filtering and validated model responses. No Phase 2 implementation is included here.
