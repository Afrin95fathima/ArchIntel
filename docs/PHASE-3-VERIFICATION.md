# Phase 3 delivery and verification

4 October 2026. The local runtime-foundation implementation is delivered for user verification. Phase 4 has not started. This does not claim complete enterprise modernization or universal runtime compatibility.

## Work completed and outcome

| Work | Outcome |
|---|---|
| Saved instrumentation plans | Deterministic version/hash, include/exclude package boundaries, supported entry-point annotations, explicit omission reasons and size budgets; preview does not create sessions |
| Baseline association | Optional strict service/artifact declaration checks, atomic rejection of mixed/mismatched batches, backward-compatible mode with unverified diagnostics |
| Method mapping | Valid JVM descriptors preserved and matched to static overload signatures; invalid/ambiguous observations receive no guessed method coverage |
| Quality visibility | Duplicate/conflict/dropped/binding counters, method mapping states, missing and invalid parents, plan provenance and UI Quality tab |
| Runtime graph | Known database servers/namespaces and services remain distinct; cyclic span-parent links do not create graph dependencies; late parents can repair active graphs |
| Recovery and retention | Interrupted report generation becomes recoverable FAILED; one expired-session failure does not block others; purging is idempotent and keeps archived reports |
| Preservation | Existing static analysis, runtime reports, identities and policy retained; existing Phase 2 gateway remains the assistant path |
| Handoff | Phase 3 user flow and developer guide in Markdown, HTML and PDF; current main manuals and roadmap updated |

## Executed validation

| Verification | Result |
|---|---|
| Full backend suite with real scanner, local model and PostgreSQL integrations enabled | **128 passed**, 473.87 seconds; no skipped tests |
| Existing runtime suite before the full run | **20 passed** |
| New Phase 3 contract suite before the full run | **12 passed** |
| Frontend unit tests | **5 passed** across 3 files |
| TypeScript and final Vite production build | Passed |
| Python dependency consistency | `pip check`: no broken requirements |
| Frontend dependency consistency | `npm ls --depth=0`: passed |
| Chrome local AI workflow, investor static walkthrough and actual WAR upload | **3 passed** in the initial browser run |
| Chrome security and new runtime workflow | **2 passed** in the final focused rerun (1.5 minutes including isolated server setup) |
| Real PetClinic + Java agent | Passed; isolated capture, static preservation, frozen report and API restart verified |

The first browser run found a logout-test timing race and a new UI separator encoding problem. The security test now waits for the sign-in screen before checking denied access; the runtime text encoding was corrected and the production frontend rebuilt. These fixes passed in the focused rerun. All five browser workflows have passing evidence across the initial and focused runs; this is not claimed as one uninterrupted five-test pass. Browser fixtures use synthetic telemetry for UI assertions; real Java capture is verified separately.

Existing test-client deprecation warnings and Vite's approximately 787 KB minified chunk warning remain. Dependency consistency is not a security vulnerability scan. No new packages or schema migration were required for Phase 3.

## Real Java evidence

The validation used the pinned PetClinic revision `30aab0ae764ad845b5eedd76028756835fec771f` and OpenTelemetry Java agent `v2.31.1`. It read a matching previously scanned static artifact, then ran the sample on loopback port 18080 against an isolated ArchIntel API/database on port 18002. No uploaded customer application was executed.

| Observation | Result |
|---|---:|
| Accepted spans | 190 |
| Traces | 83 |
| Observed classes before additional flows | 5 |
| Observed classes after additional flows | 11 |
| Declared service/artifact matches | 190 |
| Unverified / binding-rejected / dropped spans | 0 / 0 / 0 |
| Missing / invalid parent links | 0 / 0 |
| Unique-name method observations | 45 |
| Ambiguous method observations, left unresolved | 11 |
| Runtime nodes / edges | 20 / 18 |
| Unified STATIC_ONLY / DYNAMIC_ONLY / STATIC_AND_DYNAMIC edges | 34 / 12 / 6 |
| Report after restart | Identical |
| Static snapshot and original workspace analyses | Identical |

Method descriptors are validated with contract tests. The standard agent's real capture had ambiguous overloads without descriptors, which were correctly left unobserved; this run does not claim every overload was resolved. Additional owner/veterinarian/pet/visit routes expanded the observation set; coverage stayed partial.

Reproducible script: `scripts/validate_phase3_runtime.py`. Machine-readable report: [phase3-runtime-validation.json](phase3-runtime-validation.json). Test credentials are not stored in that report. Isolated session IDs in this report do not refer to sessions in the live user workspace.

## Live application and data preservation

The application was restarted only after confirming zero active scans and zero accepting/processing runtime sessions. It reports ready at http://127.0.0.1:8000 using PostgreSQL and the installed scanner. Database revision stays 0004.

Before/after canonical row hashes matched for 7 projects, 7 applications, 8 artifacts, 8 analysis runs, 3 runtime sessions, 1 security principal, 1 policy revision and 0 AI providers. Account permissions and model policy were not changed. See [phase3-preservation-validation.json](phase3-preservation-validation.json).

## Remaining boundaries and user gate

The foundation retains one API process, explicit supported Java identities/annotations, sender-declared artifact binding and heuristic readiness scores. It does not add cryptographic runtime attestation, reviewed manual mapping overrides, full proxy/framework coverage, application-server runtime certification, scenario tracking, line/branch coverage or production load/overhead certification. These limitations remain explicit in the developer handoff and roadmap. Existing workload recommendations remain structural suggestions; Phase 4 guided discovery/evidence/twin has not been implemented.

For verification, open Dynamic analysis, preview a plan, create/start a strict session, use its generated Java configuration, exercise your application and inspect Coverage/Quality/Graph. Stop and export its report. No application connection is required to review the plan. Read [PHASE-3-USER-FLOW.html](PHASE-3-USER-FLOW.html) for the full workflow and [PHASE-3-DEVELOPER-GUIDE.html](PHASE-3-DEVELOPER-GUIDE.html) for developer details. Proceed to Phase 4 only after the user accepts this checkpoint.
