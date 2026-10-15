> **Current delivery:** See [the authoritative implementation roadmap](ARCHINTEL_IMPLEMENTATION_ROADMAP.md). Phases 1 through 7 are authorized. Phase 6 source tasks and a controlled Docker fixture are implemented; broader acceptance remains open. Phase 7A adds baseline/candidate validation comparison; refactor recipes, re-analysis and security acceptance remain pending. See [Phase 7 checkpoint](PHASE-7-VERIFICATION.md). This earlier plan is retained as historical context.

# ArchIntel: four-week implementation and verification plan

## Product contract

ArchIntel analyzes compiled Java JAR/WAR structure without executing customer applications. It discovers dependencies, shows separate class/package graphs, identifies candidate domains and architectural debt, and explains modernization readiness and sequencing. An assistant explains retrieved analysis evidence and labels recommendations separately.

Static dependencies are evidence, not proof of runtime calls, business boundaries, shared database tables, or safe service extraction. Reflection, generated classes, dynamic configuration, and SQL can leave gaps. Report unsupported features and missing evidence explicitly. Scores and domain confidence are heuristics, not probabilities or guarantees.

## Delivery assumptions

20 working days, with verification at each phase boundary. Days are relative to kickoff. Fast feedback and a working Docker development machine are prerequisites. The four-week target is aggressive, not a guarantee: scanner compatibility and large artifacts are critical risks. Preserve correctness and narrow supported artifact variants when necessary; report those limits instead of simulating success. Each phase includes backend, usable UI where applicable, tests, and documentation. Stop after each phase for user verification.

| Phase | Days | Work and tangible output | Acceptance gate |
|---|---|---|---|
| 0: Foundation | 1–2 | FastAPI, typed React/Vite/Tailwind, PostgreSQL, Neo4j, Compose, configuration, health/readiness, analysis placeholder, scanner development recipe | Frontend build/tests and backend tests pass; Compose services become healthy; scanner integration decision documented |
| 1: Ingestion and graphs | 3–5 | Projects/applications and migrations, bounded uploads, isolated jobs, real jQAssistant spike and adapter, stage progress/errors, raw and filtered class/package graphs, upload/progress UI | Known JAR and WAR produce expected classes and typed edges; external edges retained separately; invalid/traversal/oversized archives rejected; failure cleanup tested |
| 2: Architecture intelligence | 6–10 | SCC cycles with caps, Ca/Ce/I/A/D, fan-in/out, relative god-class detection, evidence-bearing issues, overview/issues and progressive Cytoscape explorer | Hand-calculated fixture metrics match exactly within floating tolerance; cycle level/severity/caps correct; large SCC never fully enumerated; UI does not load all classes |
| 3: Domains | 11–13 | Seeded Louvain and package/name/annotation heuristics, candidate confidence/evidence/membership, AUTO/MANUAL/HYBRID schema support, domain detail, database signals | Repeat runs produce stable results; known synthetic boundaries explained; normalized cross-domain coupling verified; unknown database evidence remains unknown |
| 4: Modernization | 14–15 | Component scores, configurable weights, readiness/difficulty, dependency-aware ranking, risks/blockers, modernization UI | Scores bounded 0–100 and reproducible from stored components; unknown signals handled explicitly; cyclic groups expose blockers; every rank has a reason |
| 5: Pilot validation | 16–20 | Bounded context builder, vendor-neutral provider and one configured provider, cited facts/recommendations, regression/performance tests, demo/docs/Compose packaging | Full 14-step user journey works on real artifacts; answers cite valid analysis evidence and abstain when absent; offline artifact analysis works; release checks pass |

## Correctness and quality gates

- Separate class and package graphs; define edge direction as dependent → dependency and document deduplication/aggregation semantics. Retain dependency kinds and evidence. Filter configurable external dependencies before scoring.
- Define Ca/Ce counting units before implementation and use them consistently. Count an abstract/interface type once in abstractness. Define zero-denominator behavior in tests.
- Every algorithm has meaningful tests: clean graph, same-package/cross-package/cross-domain cycles, large SCC, capped enumeration, isolated nodes, outliers, high coupling, and shared repositories. Cycle severity is enriched after domain discovery.
- Domain discovery cannot prove business meaning. Store supporting/conflicting signals, deterministic seed and rule versions. Avoid interpreting confidence as calibrated accuracy.
- Store every score component, weight, denominator, evidence reference, and algorithm version. Unknown database coupling must not be silently treated as zero risk.
- Analysis stage status/duration/failure is observable. Persist only complete coherent result sets; never expose partial results as successful. Define restart/retry behavior before accepting jobs.
- Customer artifacts use random isolated directories, archive/decompression limits, time/resource limits and cleanup on success/failure. Do not execute them or log contents. Preload scanner dependencies before offline analysis. Reserve tenant ownership in the first persistence migration; local development is not authenticated multi-tenant hosting.
- AI facts must reference retrieved analysis records. Reject invalid references and abstain when context is insufficient. Test unsupported questions and instruction-like artifact names. Do not send whole graphs or artifacts to the provider. Without a configured provider, report unavailable rather than returning fake AI answers.

## Performance acceptance

During Phase 1 pin scanner/tool versions and establish reference machine specifications plus small, medium, and large fixture sizes. Proposed pilot envelope: up to 20,000 internal classes and 200,000 typed edges on 8 CPU/16 GB RAM, subject to measurement before commitment. Record peak memory and stage times. At Phase 5 publish measured limits and failures; do not claim this envelope passed without measurements. Graph responses must be bounded and support progressive expansion. Timeouts and cycle caps must be tested independently of happy-path speed.

## Validation corpus

Use synthetic Java fixtures with known expected graphs and metrics. Add pinned, licensed versions of Spring PetClinic and an appropriate Struts sample; assess Broadleaf artifact availability and compatibility early. Record exact artifact versions/hashes, supported Java bytecode/packaging and observed limitations. Never claim all applications were validated if only one was exercised.

## Deferred scope

Runtime agents/instrumentation, code rewriting, generated microservices, other languages, Kubernetes, billing, external workflow integrations, extensions and MCP servers remain outside this MVP.

## Phase reporting

Before implementation: inspect repository; state objective, files/modules, decisions, steps, tests, definition of done. After implementation: report Created, Modified, Tests, Remaining and outcome. User verifies before the next phase begins.
