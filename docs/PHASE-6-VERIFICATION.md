# Phase 6 verification checkpoint

Phase 6 is **in progress**. The controlled source-task foundation and a real local Docker sandbox are implemented; the full phase exit gate remains open. A controlled fixture passed actual offline build/isolation checks, while customer artifact reproduction and the broader contract/security capabilities listed in the developer handoff are not completed. The user subsequently authorized Phase 7; its progress is tracked in [Phase 7 verification](PHASE-7-VERIFICATION.md).

## Implemented scope

- Additive task/changeset/contract/build persistence and private Git snapshots from explicit committed source scope.
- Current version/approved-plan checks, tenant isolation, source grants, policy gates and audited source access.
- Bounded exact patches, expected file hashes, conservative risk, human staging approval, expiry and authorization invalidation.
- Private staging/rollback preserving original dirty customer work and original branch/commit.
- Contracts, baseline artifact/test gates, pause/revision controls, idempotent preparation and interrupted-operation recovery.
- Fail-closed offline local Docker adapter; no customer host build execution.
- Source tasks UI, security policy controls, user guide and developer handoff.

## Validation results

- Initial focused source-task suite: **20 passed**.
- Full backend regression with scanner, local model, PostgreSQL and Neo4j integrations enabled: **188 passed, 1 failed** in 669.67 seconds. The new PostgreSQL test omitted the new CSRF token after restarting/signing in; the server correctly denied rollback. After correcting that test client, its focused rerun **passed** in 22.55 seconds. All **189 backend cases** have passing results across these runs; no production authorization was weakened.
- [PostgreSQL integration report](phase6-integration-validation.json): the staged task and review survived restart unchanged; rollback restored private baseline bytes while preserving the original dirty checkout and commit. The temporary schema was removed.
- Final full browser regression: **8 passed**, no skips, in **4.2 minutes**, with real local model and Neo4j integrations enabled. Covers account setup/isolation, local AI, runtime, evidence, planning, source preparation/review/staging/rollback, the investor walkthrough and actual artifact upload/scanning.
- Earlier browser failures were test synchronization/locator issues and excessive repeated sign-ins reaching the existing rate limit. Tests now wait for the password/preparation HTTP responses, use accessible-role locators for populated controls, and reuse a worker-owned authenticated session across feature pages. Application login limits and permissions remain unchanged.
- Source-task screenshot: [reviewed private staging](screenshots/phase6-source-task.png).
- Frontend unit tests: 5 passed across 3 files.
- TypeScript and production Vite build passed; the existing large-bundle warning remains (about 826 kB minified JavaScript).
- Python dependency check: no broken requirements. npm direct dependency check passed. These are consistency checks, not vulnerability audits.
- Docker follow-up (10 October 2026): the full Concord 2.46.1-SNAPSHOT reactor packaged successfully in Docker with Java 25 (94/94 modules; tests skipped). ArchIntel’s build sandbox was rebuilt and pinned to `sha256:9847fa2c085e6b1dfc3a7921d16184ee1925c20fc50b50d76fd8433ba8acfd81`. Its real `sandbox.run` adapter built a controlled offline Maven fixture, passed 1 JUnit test and captured a validated JAR under the network-disabled, read-only-root, non-root resource-bounded container settings. Focused sandbox unit checks: **3 passed**. The full Concord reactor has not been executed through this constrained adapter; broad customer compatibility remains open. Follow-up Concord unit tests in Linux showed exact-output CRLF/LF failures in serializer and Ansible configuration tests, and the migration test requires a Docker socket unavailable under the isolation policy. The reactor test suite therefore has no full PASS.

## 10 October Docker follow-up

The pinned Java 25 ArchIntel sandbox now contains the offline Maven repository captured from the successful Concord package build. The sandbox runner points Maven at that immutable cache instead of duplicating it into the bounded writable workspace. The smoke build and test passed, but this is not a complete Concord integration test. The new image digest is recorded in the Phase 7 verification and developer handoff.

## 12 October compiled project ZIP intake

The static-analysis upload now accepts a bounded project ZIP containing compiled classes under module `target/classes` or `build/classes`, or module JAR/WAR artifacts in build-output folders. It safely extracts only Java bytecode, combines modules into one graph, rejects source-only ZIPs and unsafe/oversized archives, and does not execute the project or compile Java source. Identical duplicate class definitions collapse. Different definitions with the same fully qualified name are resolved by normalized archive path order and their selected/skipped origins appear in the manifest and Overview.

- Ingestion and archive-safety tests plus an API-to-analysis-pipeline ZIP test: **13 passed**.
- Frontend unit suite: **6 passed**; TypeScript/Vite production build passed (existing large-chunk warning remains).
- Concord packaging smoke: `scripts/package-java-project-zip.ps1` collected 3,881 class entries (15.5 MiB uncompressed) into a 6.8 MiB archive. ArchIntel found 3,867 unique class names and reported two conflicting duplicate definitions.
- Real jQAssistant + Neo4j extraction and architecture analysis completed against the Concord ZIP: 3,867 classes, 227 packages, 15,948 distinct dependencies, 19,252 typed dependency pairs, and 2 heuristic domains. This proves the project-ZIP bytecode path works; it is not a source-level build, full Concord test run, or business-boundary validation.
- A ready-to-upload archive is at `E:\\concord\\concord-compiled-classes.zip`. It contains compiled classes only; the original checkout is unchanged.

## Evidence boundaries

Source-task tests use controlled Java text fixtures and real local Git operations. Passing baseline/artifact-gate unit tests replace the Docker runner with structured mock results. Browser source-task tests prove preparation/review/staging/rollback behavior; they do not bind that fixture to a real rebuilt application artifact.

The source-task scope is additive. Existing static/runtime, AI gateway, evidence and planning behavior is regression-tested separately. [Live workspace preservation report](phase6-preservation-validation.json): migration `0006 -> 0007` passed. All compared rows/hashes were unchanged, including 7 applications, 8 analyses, 3 runtime sessions, the existing principal and policy revision. No test account, provider, source task or architecture version was added to the actual workspace. The live API reports ready at `http://127.0.0.1:8000`; authenticated Neo4j connectivity passed.

## Open exit criteria

- Prepare reviewed offline dependency caches for each supported customer build and validate reproducible baseline/candidate artifacts and contracts.
- Extend actual isolation/resource/timeout/cleanup acceptance with hostile fixtures and production deployment packaging.
- Complete broader Phase 6 characterization/test-gap and generated-code security scanner integration, plus remaining task/source graph lineage from the master specification.
- Obtain user verification before proceeding into Phase 7.

[User flow](PHASE-6-USER-FLOW.md) | [Developer handoff](PHASE-6-DEVELOPER-GUIDE.md)


