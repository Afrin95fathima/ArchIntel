# Phase 4 delivery and verification

Delivered 4 October 2026 for user verification. Phase 4 evidence intelligence is implemented in the local prototype. Phase 5 has not started.

## Objective, reuse and outcome

The milestone adds evidence-to-fact provenance, reproducible architecture versions, guided runtime discovery and a persistent knowledge graph/digital twin. It reuses the validated static scanner, immutable analysis snapshots, runtime receiver/mapping/coverage/fusion, tenant permissions and AI gateway. It does not execute customer source code or introduce another analysis pipeline.

| Delivered work | Outcome |
|---|---|
| Canonical evidence and facts | Seven evidence source kinds, exact support references and STATIC_ONLY / DYNAMIC_ONLY / STATIC_AND_DYNAMIC dependency facts |
| Architecture versions | Frozen manifests/digests, idempotent capture/backfill, explicit parent lineage and baseline/session compatibility |
| Domain review | Version-scoped names/membership with stable existing domain IDs, actor/reason and confirmation evidence; original snapshots unchanged |
| Guided runtime discovery | Prioritized entry-point, scheduler, consumer, dependency, domain and high-risk investigation suggestions; revision-checked status/note history |
| Persistent knowledge graph | Separate authenticated Neo4j Community 5.26.30, version/tenant scopes, indexes/constraints, transactional replay and SQL outbox retries |
| Digital twin and UI | Version preview/selector, fact provenance, bounded graph/neighborhood, coverage/unknowns, discovery, observation comparison and canonical export |
| Failure handling | Stale/missing/incomplete graph detection, readable SQL evidence through graph outage, retention-aware span references and successful rebuild |
| Handoff | Phase 4 user and developer guides in Markdown/HTML/PDF; roadmap, current/target/security architecture and main manuals updated |

Primary implementation files are in `backend/app/evidence/`, `frontend/src/evidence/` and migration `0005_evidence.py`. Lifecycle integration uses `scripts/install_knowledge_graph.py`, `scripts/knowledge_graph.py`, the normal start/stop scripts and the existing main application background-worker pattern.

Security boundaries: existing workspace-scoped ORM/access checks, ANALYSIS_READ/WRITE plus RUNTIME_READ for runtime-containing versions, bounded mutation bodies and query pages, fixed parameterized Cypher, literal loopback graph destinations, no credentials in exported evidence, and no source/model gateway bypass. Limits and remaining production work are documented in the developer guide.

## Executed tests

| Check | Result |
|---|---|
| Full backend run with real scanner, model, PostgreSQL and graph integrations enabled | **142 passed, 1 failed**, 763.71 seconds; the sole failure was the old test expectation of migration 0004 |
| Final targeted evidence/security/migration run | **41 passed**, 273.65 seconds; verifies corrected 0005 expectation, all 16 current evidence cases and the new bounded-body rejection |
| Current backend coverage across those runs | **144 distinct cases have passing results**; not claimed as one uninterrupted 144-test run |
| Frontend unit tests | **5 passed** across 3 files |
| Final TypeScript/Vite build | Passed |
| Initial Chrome suite | **5 passed, 1 failed**; only the new evidence selector's test locator failed after successful version/provenance/graph operations |
| Focused evidence/twin Chrome rerun | **1 passed** in 2.5 minutes including isolated server setup; all **6 workflows** have passing evidence across runs |
| Python dependency consistency | `pip check`: no broken requirements |
| Frontend dependency consistency | `npm ls --depth=0`: passed |
| Pinned graph distribution | Official archive SHA-256 verified; installer replay passed |

The browser test now locates the version selector by its accessible combobox role. Existing security, AI registration/model answer, runtime quality/graph/export, investor static walkthrough and actual WAR-upload workflows passed in the initial browser run. The final evidence rerun covered preview, capture, canonical support, discovery status, real graph projection, twin unknowns, export and reload persistence. Small final explanatory-text/neutral-color changes passed the final production build.

Warnings remaining: existing FastAPI/Starlette test-client deprecations, Vite's approximately 800 KB minified bundle, and Neo4j informational schema-already-exists/query-planner notifications. Projection endpoint matching uses unique IDs despite the planner's disconnected-pattern notification. These checks are not a production performance certification or a dependency vulnerability scan.

## PostgreSQL + real Java evidence + Neo4j integration

The integration reused the **real Phase 3 PetClinic capture of 190 spans / 83 traces**. It did not fabricate spans or claim a new Phase 4 Java traffic run. The capture was copied into a generated temporary PostgreSQL schema and projected into test-owned graph scopes; these were removed afterward.

| Result | Verified value |
|---|---:|
| Canonical dependency facts | 52 |
| Canonical evidence records | 399 |
| Persistent graph nodes | 708 |
| Persistent graph relationships | 1,008 |
| Observed classes | 11 / 25 (44%) |
| Observed declared methods | 26 / 94 (27.66%) |
| Static snapshot after capture | Identical |
| Canonical export after API restart | Identical |
| SQL evidence while graph endpoint unavailable | Accessible and identical |
| Graph after rebuild | Identical |

See [phase4-integration-validation.json](phase4-integration-validation.json). Its IDs identify isolated test records and are not sessions/versions in the live user workspace.

A separate actual graph JVM restart retained identical content hashes for two browser-validation graph versions: **1,092 nodes and 1,650 relationships**. See [phase4-graph-restart-validation.json](phase4-graph-restart-validation.json). This verifies local persistence/recovery, not a production backup/restore procedure.

## Live installation and preservation

Before restart there were zero active analyses and zero accepting/processing runtime sessions. The live PostgreSQL database migrated from **0004 to 0005**, adding five tables. Before/after row hashes matched for:

| Existing records | Rows preserved |
|---|---:|
| Projects | 7 |
| Applications | 7 |
| Artifacts | 8 |
| Analysis runs | 8 |
| Runtime sessions | 3 |
| Retained raw runtime events | 0 |
| Security principals | 1 |
| Policy revisions | 1 |
| AI providers | 0 |

Account permissions, bootstrap setup and model policy were preserved. No existing application was automatically captured into a new version, and no existing customer analysis was sent to a model. [phase4-preservation-validation.json](phase4-preservation-validation.json) records the comparisons.

The application is ready at **http://127.0.0.1:8000**. The separate graph listens on authenticated loopback Bolt port **17687**, with HTTP disabled and persistent files under `.data/knowledge-graph`. Normal start/stop scripts include its lifecycle. Its password key is separate from the workspace bootstrap key.

## Boundaries and next gate

This remains a supported single-process local deployment. No distributed projection leases, production graph RBAC/backup acceptance, cryptographic administrator-proof audit, complete business workflows, proven data ownership, code-coverage provider, calibrated modernization decisions or code transformation is claimed. Domain review preserves existing domain identities; new-domain/merge/split workflows remain future work. Historical findings/scores remain baseline-scoped rather than being silently recomputed from edited domains.

User verification:

1. Open **Evidence & digital twin** and select a completed analysis.
2. Preview/save a static-only version, or include compatible completed runtime sessions.
3. Inspect a dependency's evidence and check its classification.
4. Review Discovery, add a note and change an item to PLANNED. Coverage must not change merely from that status update.
5. Rebuild/open the persistent graph and inspect Twin's explicit unknowns.
6. Export the canonical version. Optionally review domain membership in a successor version and inspect the preserved baseline.

Read [the user flow](PHASE-4-USER-FLOW.html) and [developer handoff](PHASE-4-DEVELOPER-GUIDE.html). Phase 5 requires the user's next authorization after this checkpoint.
