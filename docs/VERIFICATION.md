# ArchIntel prototype delivery and verification

Verified on 10 September 2026 on the prepared Windows x64 workspace. The working application is available at http://127.0.0.1:8000. Start it again with `Start-ArchIntel.cmd`.

## Delivery phases and outcomes

The original multi-week plan was superseded by the request to deliver a working investor prototype immediately. These phases describe the completed prototype work, not a claim that all production engineering has been compressed into one day.

| Phase | Work completed | Outcome |
|---|---|---|
| 1 — Foundation and ingestion | Local runtimes, PostgreSQL migrations, project/application records, validated uploads, worker stages and persistence | JAR/WAR/Boot artifacts enter a real analysis pipeline; progress, failures and completed history are stored. |
| 2 — Architecture analysis | jQAssistant, isolated embedded Neo4j, Java exporter, normalization, typed dependencies, SCCs, metrics and issue rules | Actual bytecode produces inspectable architecture findings. Uploaded application code is not executed. |
| 3 — Modernization intelligence | Candidate domains, repository/entity evidence, component scores, coupled groups and dependency-first sequencing | Recommendations carry their supporting structural evidence and expose unknown runtime information. |
| 4 — Product experience | Workspace, overview, graph explorer, domains, debt, cycles, metrics, modernization, evidence assistant and export | The complete investor journey works in a real Chrome browser against persisted backend results. |
| 5 — Validation and handoff | Automated tests, real packaging scans, browser walkthroughs, restart verification, launch scripts, user and developer manuals | The local demonstration is ready; production limitations and further development priorities are documented. |

## Executed checks

| Check | Observed result |
|---|---|
| Backend suite | **30 passed**, 3 opt-in scanner tests skipped in the default run. Includes graph arithmetic, cycles, scoring, assistant grounding, API/database behavior, upload validation and failure cleanup. |
| Real scanner integration | **3 passed in 111.65 seconds**, covering JAR, WAR and Spring Boot packaging with real Java/jQAssistant/Neo4j. All eight supported dependency categories were observed. These ran before the final repository/entity classification refinement; that refinement passed the algorithm regression and a fresh live JAR scan. |
| Frontend unit tests | **4 passed** across 2 files. |
| Production frontend build | TypeScript and Vite build passed. A non-blocking bundle-size warning remains for the approximately 744 KB uncompressed JavaScript chunk. |
| Live Chrome tests | **2 passed**: all-screen investor walkthrough and a fresh WAR upload completing analysis. The final updated build additionally passed the full walkthrough again in 43.3 seconds. |
| Repository/entity regression | Algorithm suite **15 passed**, including assertions that entities are not classified as repositories and repository-to-entity mappings remain correct. These are part of the backend suite, not additional unique tests. |
| Python dependency consistency | `pip check`: no broken requirements found. |
| Frontend dependency audit | npm reported **0 vulnerabilities** after the locked dependency update. This is a point-in-time package advisory check, not a security certification. |
| Evidence and manuals | All **8** citations from the Payment explanation returned real evidence records; unsupported weather questions abstained; both manual downloads succeeded; both generated PDFs have valid PDF signatures. |
| Restart persistence | API restarted successfully; the same completed analysis and identical exported snapshot fingerprint remained available. See `verification-data.json`. |
| Script/configuration checks | All six PowerShell scripts parsed successfully. Docker Compose YAML parsed with the expected two services. |

Windows sandbox restrictions initially blocked esbuild; rerunning with approved local execution passed. This was an execution-environment restriction. Two upstream test-client deprecation warnings remain in the backend suite.

## Demonstration result

The synthetic Northstar Commerce application is compiled from the source under `samples/commerce/src`; it is deliberately designed to contain architectural problems. It is not customer data or a benchmark proving real-world accuracy.

The final real scan uses algorithm version **0.2.1** and produces:

- 40 application classes and 7 packages.
- 97 distinct internal dependency pairs; 116 typed internal edges and 108 external edges.
- 7 candidate domains and 14 issues: 2 critical, 6 high and 6 medium.
- 2 class-level cyclic SCCs and 1 package-level cyclic SCC.
- Average heuristic readiness of 72.6/100.

The final analysis ID, snapshot hash, live readiness response and verification timestamp are in [verification-data.json](verification-data.json). Screenshots from the live browser run are in [screenshots](screenshots).

## Dependencies and operating assumptions

The prepared machine uses Python 3.12.10, Node 22.17, Java 21, jQAssistant 2.7.0 with embedded Neo4j 5.26.5, and a workspace PostgreSQL 18.4 runtime. Exact Python and npm package resolutions are committed in `backend/requirements.lock`, `frontend/package-lock.json` and `infra/local-postgres/package-lock.json`.

The default assistant is `LOCAL_EVIDENCE`: deterministic explanations with citations. It needs neither an API key nor a language-model service. Optional Ollama citation selection has unit-tested fallback behavior but has not been validated against a running model in this delivery.

The scanner integration used dead HTTP/HTTPS proxy settings to check that scanning needed no additional plugin downloads. This does not establish OS-enforced network isolation.

## Limits of this verification

- The prepared local Windows path is verified. Docker Desktop is now available and the Phase 6 pinned build sandbox passed a controlled offline Java/Maven build; see `PHASE-6-VERIFICATION.md`. A fresh-machine execution of the complete setup script and a production Docker deployment were not performed.
- Automated browser coverage verifies the principal workflows; it does not prove every browser, screen size or malformed input combination.
- Large enterprise artifacts, 20,000-class workloads and external real-world application corpora have not been benchmarked. Configured bounds are safety limits, not capacity guarantees.
- Static dependencies cannot establish runtime traffic, reflection wiring, SQL transactions or true business boundaries. Domain confidence and readiness are heuristics requiring architect review.
- Authentication, enforced tenant isolation, distributed jobs, OS-level scanner sandboxing, manual domain editing and production operations remain future development work.
- Completed scans clean up their uploaded artifact and temporary store by default. Abandoned uploads and crash leftovers require the retention improvements described in the developer guide.

Use [USER-MANUAL.pdf](USER-MANUAL.pdf) for the presentation and [DEVELOPER-GUIDE.pdf](DEVELOPER-GUIDE.pdf) for the engineering handoff.
