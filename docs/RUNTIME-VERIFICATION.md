# Dynamic analysis verification

Delivery checkpoint: 17 September 2026. The measurements below come from executed tests and the real PetClinic/Java-agent run, not generated demonstration traces.

## Implemented and preserved

Added isolated runtime session/event storage and migration, authenticated OTLP HTTP protobuf/JSON ingestion, deduplication and bounded retention, agent method plans, class mapping, class/package/domain runtime graphs, separate coverage metrics, additive fusion, observed flow/persistence summaries, configurable runtime/combined review scores, evidence assistant, report export and an integrated dynamic-analysis UI.

The existing static pipeline, stored results, structural scoring and static user workflows remain functional. Static export now additionally includes method identities/annotations for new scans. A checksum comparison in the real validation proved that runtime observation did not mutate the selected static snapshot.

## Executed verification

| Check | Result |
|---|---|
| Backend regression and runtime unit/API suite | **50 passed**, 3 opt-in scanner tests skipped in this invocation. |
| Real static scanner regressions | **3 passed**, real JAR/WAR/Spring Boot scans after the additive method export change; 153.44 seconds. |
| Frontend tests | **5 passed** across 3 files, including the runtime baseline prerequisite. |
| Production frontend build | TypeScript and Vite passed; non-blocking large-bundle warning remains. |
| Live Chrome workflows | **3 passed**: existing investor walkthrough, fresh WAR upload, and the real PetClinic runtime evidence UI. |
| Dependency consistency | Python `pip check` reported no broken requirements. |
| Real Java-agent pipeline | Passed with pinned PetClinic revision and OpenTelemetry Java agent 2.31.1. |

The final graph-selection/presentation build passed and the targeted runtime Chrome check passed again (3.1 seconds), covering static/runtime/unified mode switching and report export. The completed report remained readable after an API restart; both manual downloads returned HTTP 200 and both runtime PDFs were generated. The two backend warnings are upstream Starlette/httpx and AnyIO deprecations. Windows filesystem sandbox denials required approved execution for Java compilation and esbuild; successful results above refer to the reruns.

## Real application evidence

Application: Spring PetClinic, source revision `30aab0ae764ad845b5eedd76028756835fec771f`, Spring Boot 3.5.0, running with the workspace Java 21 JDK and OTel agent 2.31.1. The build fixture targets Java 17. The Maven fixture build skipped PetClinic's own tests; ArchIntel's integration checks exercised the resulting application.

The driver first exercised owner flows, then added vet, pet and visit flows. It received **79 traces and 186 spans**. Runtime aggregation produced **18 nodes and 18 edges**, with no missing parents in this sample.

| Observation metric | Initial workload | Expanded workload |
|---|---:|---:|
| Classes | 3/25 — 12% | 9/25 — 36% |
| Declared methods | 9/94 — 9.57% | 22/94 — 23.40% |
| Explicit entry points | 4/17 — 23.53% | 7/17 — 41.18% |
| Executable dependency pairs | 1/26 — 3.85% | 6/26 — 23.08% |
| Domains with observations | 2/5 — 40% | 3/5 — 60% |

Class-pair fusion produced **34 STATIC_ONLY**, **12 DYNAMIC_ONLY** and **6 STATIC_AND_DYNAMIC** relationships. Resource/framework observations remain visible and do not inflate class coverage. Nine runtime/resource nodes were unresolved against static class identities.

The final session reached COMPLETED, its report matched the final live report, and the static snapshot hash was unchanged. The exact IDs, artifact SHA-256, static snapshot SHA-256, timestamp and coverage details are in [runtime-validation.json](runtime-validation.json).

## Bugs found by real validation

1. The verified OTel method parser rejects `Class[*]`. Generated plans were changed to explicit declared method names and constructor/synthetic names were excluded. A regression test now checks this contract.
2. PetClinic's application namespace overlaps the default Spring framework exclusion. The validation driver includes `org.springframework.samples` while excluding Spring Boot loader classes, preserving the default configuration and all previous results.
3. jQAssistant includes some inherited-reference stubs with signatures but no parsed method names. Coverage now distinguishes them from declared methods instead of disabling the entire method inventory or pretending those stubs were declared methods.

## Tests cover

Exact/internal-name/descriptor/proxy/unresolved mapping; ambiguous simple names; parent reconstruction by both trace and session; duplicate ingestion; bearer-token isolation and rotation; lifecycle rejection; malformed data; protobuf/gzip handling and expansion bounds; session partial success; empty batches; retention and archived report preservation; compatible session unions; separate graph modes; method overload ambiguity and entry annotations; the required A/B/C/D/X fusion example; coverage increase; static snapshot immutability; and unknown runtime readiness retaining the structural score.

## Practical limits

- This is a single-user localhost prototype. Management APIs are not production-authenticated or tenant-isolated. Only ingestion is protected by session credentials.
- Runtime scoring is an explainable heuristic. The existing static dependency-first order is retained; calibrated runtime resequencing, full runtime issue taxonomy and production-grade flow intelligence are further work.
- Built-in selected-method instrumentation is implemented; no custom deep agent extension, JaCoCo adapter or instruction/branch coverage is claimed.
- Agent overhead, high-volume ingestion, enterprise-sized graphs, distributed workers and broad application compatibility have not been benchmarked.
- Method/entry-point coverage is bounded by available static identities and supported annotations. No observed metric establishes complete behavior coverage.
- Raw/sanitized event expiry prevents later recomputation of multi-session unions involving that expired evidence. Individual completed reports survive.
- Docker runtime deployment was not tested on this Windows machine. The verified application path uses the local launcher and workspace runtimes.

User flow: [RUNTIME-USER-FLOW.md](RUNTIME-USER-FLOW.md). Developer handoff: [RUNTIME-DEVELOPER-GUIDE.md](RUNTIME-DEVELOPER-GUIDE.md).
