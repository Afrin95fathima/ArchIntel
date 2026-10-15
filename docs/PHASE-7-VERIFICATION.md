# Phase 7 verification

Status: **Phase 7A acceptance remains open; Phase 7B has a boundary preview; Phase 7C now supports evidence-led discovery, generated proposals, independent plan approval and synthetic-only ephemeral SQLite testing. Production/database-specific migration and recovery validation remain open.**

## Historical checkpoint — 10 October 2026, before discovery-led 7C implementation

Added a version/source-bound data migration proposal API and task-workspace UI. A proposal records qualified source/target resources, explicit column conversions and key mapping, business invariants, conflict policy, backup/restore and rollback assertions, and ownership evidence references. A separate human security administrator reviews the ownership assertion; changing the mapping invalidates that review. Plans list the required test-environment checks and remain `PREVIEW_ONLY` with `execution_eligible=false`.

At this checkpoint the plan service did not connect to a database, inspect schemas, emit SQL, copy rows or execute a cutover. This text is retained as historical context; the synthetic-only local test runner is described in the current verification section below. Production database access, cutover, recovery drill and destructive-action approval are still unavailable.

Verification: full `test_transformation.py` regression file passed **28 tests, 1 skipped** (105.68 seconds); frontend tests passed **6 tests**; TypeScript and Vite production build passed (existing large-chunk advisory; 850.97 kB minified JS). Full backend regression suite and real database migration tests were not run.

## 10 October 2026 — Docker relocation and scanner validation

Docker Desktop's Linux engine was verified after its data directory was moved to D:. The dependency scanner was rebuilt and pinned as `sha256:4aadac03c02cda6512e4a309be6d197863799eed5646fa61edb86784a28f3aeb`. A real isolated scan of a controlled Spring Boot dependency archive identified `logback-classic` 1.2.3 and reported CVE-2023-6378 (HIGH); scanner and Java vulnerability databases were valid at scan time. The scanner implementation was corrected to use Trivy's `rootfs` Java archive analyzer for the staged JARs, rather than `filesystem` project-manifest analysis.

The SpotBugs/FindSecBugs image was rebuilt from immutable Maven/JDK base digests and pinned in `.env` as `sha256:ac0f5b742c54d7ebfb209780a55c872b38bd0a04ac04a78f881f62a780340432`. A real scan through ArchIntel analyzed one controlled Java class, detected `WEAK_MESSAGE_DIGEST_MD5`, and returned a complete SpotBugs report. Focused security/dependency tests passed: **12 passed**. The synthetic thin-JAR fixture correctly returned dependency coverage as inconclusive; this is not a dependency-scan failure, it marks dependencies that are not packaged inside that JAR as unproven.

Phase 6 build sandbox validation remains open. Concord is present at `E:\\concord\\concord` (clean checkout, commit `6649e56bda`) and its build uses Java 25 with Java 21 compiler release. A full 94-module `mvn -B -Plooper -DskipTests -Dmaven.gitcommitid.skip=true -Ddb.host=postgres package` run succeeded in the pinned `maven:3.9.11-eclipse-temurin-25` container (19m20s). The source was unpacked from a clean snapshot into a Docker Linux volume; the user's E: checkout remained unchanged. PostgreSQL migrations and jOOQ generation had already completed against an isolated PostgreSQL 14.21 container. All 94 reactor modules reported SUCCESS, including the console, server distribution, agent/operator, integration-test modules, and CLI. Checkstyle reported zero violations in the modules shown during the build.

During `concord-console2`, pinned Node 24.14.0 was provisioned, `npm ci --legacy-peer-deps` installed 452 packages, and Vite built 1,555 modules successfully. npm reported 14 dependency advisories (5 moderate, 9 high); Vite emitted the existing unbundled `/api/service/console/cfg` script and large-chunk advisory. Maven test execution was intentionally skipped in the successful packaging pass; integration-test modules were compiled, not executed. Separately, the console unit-test run passed 23 tests with 1 skipped. Follow-up Concord reactor unit-test runs were partial: 19 exact-output cases in `ProjectSerializerV2Test` failed because expected CRLF text differed from Linux LF output; 229 YAML parser tests passed and 2 were skipped. Excluding that serializer class and Docker-dependent `MigrationTest` let the suite progress through the server implementation and runtime modules, then `AnsibleConfigTest` showed the same CRLF/LF mismatch. The migration test requires Testcontainers and could not run without a Docker socket, which was deliberately not mounted into the build container. No complete Concord test-suite PASS is claimed. No Docker socket was mounted into project code. The ArchIntel build-sandbox image was rebuilt from pinned Maven/JDK digests and the Concord offline dependency cache; its image ID is `sha256:9847fa2c085e6b1dfc3a7921d16184ee1925c20fc50b50d76fd8433ba8acfd81`. The adapter capability check reported the pinned Linux image available. A smoke Maven project ran through ArchIntel’s `sandbox.run` adapter under `--network=none`, read-only root, non-root UID 1000, dropped capabilities, and resource limits; its JUnit test passed (1/1), a valid JAR was captured and archive-validated, and the SHA-256 was `da5d3e523aa6a25bf5d060d57da47f50ffe9bbbb20ce7308251dad219e766975`. The runner now reads the image’s baked `/opt/m2/repository` cache directly rather than copying it into the 512 MB work tmpfs. Focused sandbox regression selection: **3 passed**. This smoke fixture is controlled evidence only. Concord’s 94-module package was built in Docker, but its tests were skipped and the full Concord reactor has not been run through the bounded ArchIntel adapter; runtime compatibility remains unproven. The local API was not running at verification time, so restart it to load the new `.env` image ID. Do not treat controlled scanner fixtures as customer-application evidence.

## Historical development checkpoint — 10 October 2026 (pre-7C implementation)

Implemented the first Phase 7B slice: a version/source-bound extraction-boundary preview, authenticated task API, stale-input reporting, and an Extraction plan view. The planner reports file-name mapping uncertainty, cross-boundary dependencies/cycles, contract prerequisites, and the missing data-ownership review. It never edits files and never marks extraction executable. Phase 7B generation remains pending.

Verification: the focused backend extraction/API selection passed **4 tests**; frontend suite passed **6 tests**; TypeScript and Vite production build passed with the existing large-bundle advisory (842.91 kB minified JS). Docker was not invoked. The broad backend suite and Docker-backed execution were not run.

## Implementation continuation — 9 October 2026

Implemented the plan-specific expected-improvement measurement and human review, canonical candidate `ArchitectureVersion` publication, and a separate final approval bound to the current validation fingerprint. Candidate publication requires all validation gates and creates the version and task binding atomically. Final approval checks a fresh validation, a separate authorized security administrator, and reviewer independence. The UI exposes these steps in the task Validation tab.

Packaged dependency scanning now enumerates embedded JARs in Spring Boot JARs, WARs, and generic `lib/` archives, extracts them into a bounded temporary directory, and scans offline with a host-mounted Trivy database. Unsupported/external runtime classpaths remain explicitly incomplete. Provisioning is not yet validated: Docker's WSL disk image on C: filled while downloading the Trivy Java database, leaving the Docker metadata store read-only. The vulnerability database is on D:, but the Java database and pinned scanner image are not provisioned; no real dependency scan PASS is claimed. C: had approximately 2 MB free at the last check. The user must move Docker Desktop's disk image to D: or free space on C: before provisioning can resume.

Verification: the latest focused transformation/dependency suite passed **25 tests** in 95.22 seconds with two dependency deprecation warnings. A prior run had one fixture lookup failure; the case passed in isolation and both subsequent full reruns passed. Python compilation passed. The frontend TypeScript/Vite production build passed with the existing 835.77 kB chunk-size warning. An initial system-Python collection attempt lacked the `community` package; using ArchIntel's bundled Python resolved the environment issue. The real Trivy scan and broad regression suite remain outstanding. Since that checkpoint, Phase 7B boundary-planning implementation has started; code generation/extraction is not delivered, and Phase 7C data migration remains unstarted.

Delivered: one bounded JavaParser interface recipe, deterministic baseline/candidate comparison, exact patch binding on candidate builds, reviewed contract consistency checks, candidate artifact capture, task-linked static re-analysis and structural diff, persisted comparison fingerprints/history, stale-result detection and UI/user/developer guidance. Security and final acceptance remain blocked.

The recipe image was built from immutable Maven/JDK base image digests and pinned as `sha256:702dd9dd754af3d78336b764b3750aefa442b821ab1ba90cee450bd9e906d8cd`. A real container invocation parsed the Java fixture and generated the expected implementation/interface outputs. A second real test generated the recipe, compiled the result offline and passed `local.archintel.AppTest#preservesValue`.

## Candidate re-analysis checkpoint — 6 October 2026

A real Docker integration test passed (251.70 seconds). It compiled and tested two controlled Java fixtures, captured and validated both JARs, ran both through the existing AnalysisWorker/jQAssistant pipeline, and verified the expected removed directed METHOD_CALL dependency with unchanged class inventory. The candidate edit was hand-authored; this does not validate automatic refactor generation, full behavioral equivalence or customer artifact reproduction.

Additional regression results for this checkpoint:

- Transformation and comparison suite: 36 passed, 1 opt-in PostgreSQL test skipped.
- Final validation, ingestion, foundation and dependability suite: 39 passed (includes comparison cases overlapping the first suite, plus artifact collision/corruption checks).
- TypeScript and frontend production build passed; existing bundle-size warning remains.
- The first browser run exhausted its 180-second budget during source preparation while backend checks ran concurrently. The sequential retry passed: 1 browser workflow in 1.5 minutes (1.7 minutes including setup), with a 360-second budget. It covers source preparation, staging, validation blockers, rollback and stale comparisons; API and Docker integration tests separately cover the completed re-analysis path.
- The local API was restarted with no active main-workspace analysis/build/runtime jobs. Readiness returned `ready`, with PostgreSQL and scanner OK.
- User/developer guides were regenerated as Markdown, HTML and PDF. No customer policy or source grant was changed.

The earlier table is historical evidence for the 5 October checkpoint. This continuation did not rerun the complete 191-test historical backend suite; checks were scoped to the changed transformation, ingestion, static analysis and job workflow.

Executed on 5 October 2026:

| Check | Result |
|---|---|
| Focused transformation and comparison tests | 34 passed, 1 opt-in integration test skipped |
| Complete default backend suite | 191 passed, 11 opt-in integration tests skipped; 296.29 seconds |
| Frontend unit tests | 5 passed across 3 files |
| TypeScript and Vite production build | Passed; existing bundle-size warning remains |
| Browser source-task flow | 1 passed: real demo static scan, source preparation, reviewed staging, missing-evidence comparison, rollback and stale result; no browser errors |
| Local application after restart | Ready at http://127.0.0.1:8000; PostgreSQL and scanner reported OK |
| User/developer documentation | Markdown, HTML and PDF generated |

The default suite skips opt-in installed-model, PostgreSQL, persistent-graph and dedicated scanner integration checks. The browser flow did exercise the real demo static scanner in isolated test storage. Comparison tests use mocked build results; they do not establish a real customer refactor or new Docker build validation. The main workspace had no active analysis, build or runtime jobs before its API restart. No customer policy, source grants or existing analysis records were intentionally modified.

Browser evidence: [validation screen](screenshots/phase7-validation.png).

Remaining implementation at this historical checkpoint: complete runtime dependency coverage, actual module/service extraction generation, integration contracts and Phase 6 acceptance gaps. Candidate ArchitectureVersion publication, expected-impact review and final human approval have since been implemented; Phase 7A validation remains open.

## Recipe hardening and Java security checkpoint — 6 October 2026

- Recipe API guard tests: 3 passed. Public type/file naming, sibling output paths and execution policy are enforced. Imported signature types are preserved; unsupported generic/nested scopes, static imports, name collisions and overloaded selections are rejected.
- Real Docker integration: 2 passed in 56.31 seconds. The generated interface with an imported `List<String>` signature compiled offline and preserved the fixture contract. SpotBugs/FindSecBugs accepted the clean fixture and detected the deliberately weak MD5 fixture. This does not prove compatibility with every Java application.
- Transformation, comparison and security regression suite: 49 passed, 1 opt-in PostgreSQL check skipped (276.61 seconds).
- Subsequent security/dependency/comparison suite: 28 passed (110.92 seconds), including authenticated scan recording, failed retry invalidation and artifact corruption rejection. API tests mock scanner results; the two Docker cases above exercise the real Java tools.
- Frontend TypeScript/Vite production build passed after extracting the security-results component; the existing bundle-size warning remains.
- Final lightweight checks after strict XML error attributes and database-freshness validation: 26 passed, 2 API cases deselected (the earlier 28-test run covered those API cases).
- Markdown/HTML manuals were updated. PDF regeneration and a fresh browser run were deferred because of the disk-space blocker; existing PDFs are historical.
- The API was restarted only after confirming zero active analysis/build/accepting-runtime jobs. The updated process reported ready with PostgreSQL and the static scanner OK at `http://127.0.0.1:8000/`.
- Build helper image: `sha256:c65f64010c61a03935843792fffa95b8fc1d0975a8be1e93415a2f3a74dd8db9`.
- Java security image: `sha256:1d5b59bf35c2c2bc128c68084afef34962b3531e17a489a8a5c70ae8dd85fdda` (SpotBugs 4.10.4, FindSecBugs 1.14.0).

The initial helper rebuild failed on Docker DNS resolution. The successful provisioning retry used the host-resolved Maven Central address as a temporary build-only host mapping, with TLS validation enabled. Runtime builds and scans remained offline.

Trivy 0.75.0 was downloaded by immutable digest, but provisioning its vulnerability databases exhausted C: disk space. The Java database download alone is approximately 934 MiB compressed. No dependency image was configured and no real dependency scan pass is claimed. Unit checks cover stale/future database timestamps, empty inventories and preservation of unfixed findings. Complete runtime dependency coverage remains unimplemented even after packaged-dependency scanning is provisioned.

Disk exhaustion interrupted a roadmap write. The 640-line roadmap was restored by replaying its saved patch/string-edit history in memory, with all patch contexts checked; a recovery copy was saved at `D:/ArchIntel-recovery-20261006/ARCHINTEL_IMPLEMENTATION_ROADMAP.md`. Some generated test outputs were moved to that recovery folder; protected temporary Git directories remain in their original test folders. No main application source repository, policy or grants were changed. Application readiness still reported PostgreSQL/scanner OK after recovery. Further Docker provisioning and browser/PDF validation require adequate system-drive space.




# Phase 7C discovery-led modernization verification — 10 October 2026

Implemented a source-evidence discovery workflow and synthetic-only target migration test. The primary task tab no longer asks the customer to define all ownership rules or a target schema before analysis. Discovery returns what the supported parsers found, its source path/hash/line provenance, parser coverage, inferred ownership with confidence, conflicts, limitations and focused missing-input questions. A target proposal is generated even when no source schema was found; such a proposal is explicitly incomplete and cannot be approved for execution.

The generated proposal is bound to the repository commit and source manifest, architecture version/fingerprint and artifact, discovery/schema fingerprint, target schema version and mapping version. Mapping changes create a new plan revision. A separate `SECURITY_ADMIN` reviewer must be distinct from the task author, decide every ownership claim and acknowledge unresolved non-hard risks. The post-review fingerprint includes the customer-confirmed decisions. Approval only permits an ephemeral synthetic test.

The test runner accepts synthetic rows only, uses SQLite `:memory:`, persists no raw fixture or database URL, and reports copy/count, key, relationship, conversion and supported-invariant checks. It discards the database after the run. Backup/restore remains explicitly untested; no production adapter, live data access, cutover or production authorization path is implemented.

Validation performed for this checkpoint:

- Discovery-to-review-to-synthetic-migration API journey: passed, including independent reviewer, commit/mapping bindings, exact reviewed fingerprint, fixture non-retention, successful ephemeral test, and rejection of a superseded plan.
- Discovery and migration-runner unit tests: passed, including absent-schema proposals, failed type conversion, renamed mapping columns, explicit uniqueness and nullability invariants.
- Transformation and Phase 7C API/unit selection: **33 passed, 1 skipped** before the final stale-plan check; the latest targeted end-to-end and runner selection then passed **5 tests**.
- Complete default backend suite: **228 passed, 14 skipped** in 279.00 seconds. `compileall` passed.
- Frontend tests: **6 passed**. TypeScript/Vite production build passed; Vite reports the existing 863.97 kB minified-chunk warning.
- Read-only Concord source probe on E: included 2,469 `.java`, `.xml` and `.sql` files and reported 58 schema entities and 440 access-path candidates. The probe intentionally marked the snapshot `PARTIAL`; package-to-domain architecture evidence was not supplied, so ownership conclusions were not validated. It reported unresolved column types and primary keys. No Concord database or application was run.
- Docker, Concord database compatibility and production migration validation: not run; only the read-only source parser probe ran against Concord.

**Acceptance boundary:** the discovery-led proposal and local synthetic-test implementation slice is complete. Phase 7C is not a production migration capability and should not be described as end-to-end production-ready. Remaining acceptance work includes parser coverage against representative Concord constructs, a real isolated Concord/PostgreSQL schema and migration test when Docker/Concord are available, operational persistence/recovery behavior for long-running migration jobs, and backup/restore rehearsal. Production execution remains disabled.

## Microservice modernization proposal slice — 11 October 2026

Modernization plans now carry a `microservice_decomposition` proposal derived from the frozen architecture domains, typed dependency graph, domain assessments, findings, and static repository/entity signals. Each candidate includes class/package membership, incoming/outgoing domain links, evidence/fact references, readiness/confidence, risks, blockers, unconfirmed data ownership, and required standalone setup. Plans expose both whole-system and one-service-at-a-time rollout modes. The UI adds a **Microservice modernization** tab. Candidate boundaries remain explicitly heuristic and review-only; service generation stays disabled.

Validation:

- Focused modernization regression: **24 passed, 2 skipped**.
- Frontend tests: **6 passed**; TypeScript/Vite production build passed with the existing large-chunk advisory.
- Real static sample exercise: pinned Spring PetClinic 3.5.0 artifact scanned through the installed jQAssistant pipeline: **123 classes, 2,023 typed edges, 5 candidate domains**. The new decomposition output passed the independent proposal validator. This run had **zero runtime sessions**, kept generation disabled, and changed no PetClinic source files.
- The ArchIntel API was stopped during this check, so a browser/API workflow and Concord UI workflow were not run. Concord's existing recorded source probe remains partial and has no runtime session.

This is the analysis/proposal foundation only. It does not generate microservice code, standalone repositories, Docker Compose/deployment setup or data migrations. The current AI gateway supports local Ollama evidence selection only; no code-generation provider, API credentials, external source-transfer policy, or code-generation invocation is configured. See [microservice modernization implementation](MICROSERVICE-MODERNIZATION-IMPLEMENTATION.md) for the staged delivery and acceptance criteria. Do not start stress testing this feature yet.

### Candidate-to-source-task binding — 11 October 2026

An approved one-by-one candidate can now be carried from the **Microservice modernization** tab to source-task setup. The task request binds candidate ID, rollout mode, plan fingerprint, architecture version ID and architecture version fingerprint. The API rejects a candidate that does not match the task's approved plan decision. The user must still register/grant a complete source checkout and specify its file scope; this task setup does not generate code, create a service repository or enable whole-system execution. The whole-system action stays disabled.

Validation performed:

- Candidate task binding API test: **1 passed**; rejects mismatched candidate IDs and verifies frozen plan/version fingerprints.
- Frontend tests: **6 passed**; TypeScript/Vite production build passed with the existing large-chunk advisory.
- Post-change modernization/transformation regression selection: **54 passed, 3 skipped**. The focused candidate-binding test passed again after adding an API-level rejection for the not-yet-implemented `WHOLE_SYSTEM` mode.

### Gemini provider foundation — 11 October 2026

ArchIntel now has a fixed-host Gemini `generateContent` adapter with structured JSON output, no redirects/proxies, strict response limits and non-sensitive errors. The API key is an environment-backed `SecretStr`; `.env` is ignored. A hidden-input PowerShell helper can set a replacement key locally. One-by-one generation requires workspace policy opt-in and a human per-request source-transfer acknowledgement, then stores validated output in a separate local Git repo marked `GENERATED_UNVALIDATED`. The UI shows the local repo contents and model questions. No actual Gemini API call has been made, because no key is configured locally.

- Gemini adapter and output-validation tests: **10 passed** (fake provider only); API gate confirms generation fails closed when no local credential is configured.
- Full backend regression: **244 passed, 14 skipped**. Final focused Gemini/source-task/security and interrupted-generation recovery selection after the remaining hardening: **14 passed**. No live Gemini call was made.
- The credential posted in chat is exposed. Revoke/rotate it before placing a replacement in local configuration.
- Official contract checked against [Gemini structured outputs](https://ai.google.dev/gemini-api/docs/generate-content/structured-output) and [Gemini models](https://ai.google.dev/gemini-api/docs/models); selected default `gemini-3.8-flash` per current Google model documentation.

