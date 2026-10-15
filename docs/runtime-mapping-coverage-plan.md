# Runtime mapping and coverage checkpoint

Historical inspection checkpoint. The user subsequently confirmed no runtime subsystem existed and authorized the full dynamic prototype. See [the delivery plan](dynamic-implementation-plan.md) and [runtime verification](RUNTIME-VERIFICATION.md) for the implemented result.

Inspection date: 16 September 2026. Scope: implementation-order steps 7 and 8 in the supplied dynamic-analysis master specification. Stop before fusion, unified APIs, guided discovery or modernization changes.

## Current architecture and prerequisite gap

This workspace contains the static prototype. No runtime session model, runtime migration, OTLP receiver, runtime normalization/graph builder, OTel agent configuration or PetClinic integration was found in backend, frontend, scripts, infrastructure or documentation. There is no Git metadata in the workspace root. The location of the described working runtime milestone must be established before integrating against its contracts.

Static ingestion validates archives and scans their compiled classes through jQAssistant. Each job owns an embedded Neo4j store; ExportGraph.java exports class identities, annotations, method/field counts and typed class dependency edges. The worker deletes temporary graph storage after persisting the completed AnalysisRun.result JSON snapshot. PostgreSQL stores projects, applications, artifacts and analysis runs through SQLAlchemy/Alembic. FastAPI exposes snapshots through schema-based routes. React/Cytoscape reads separate class, package and domain graphs. Domain discovery and modernization scoring are deterministic static services.

## Integration points

- Use the completed analysis snapshot as the immutable static input. Bind runtime evidence to its application, selected session IDs and exact analysis ID/version; reject mismatched applications or incompatible static baselines.
- Class node IDs are FQNs. Classes carry package_name and domain_id. Typed static edges carry source, target and dependency_type. Domain membership is already available; do not recluster from runtime observations for this step.
- The snapshot stores method counts, not a reliable method identity inventory. Do not calculate method coverage by dividing arbitrary span names by those counts.
- No statically enumerated entry-point method inventory is exported. Report entry-point coverage as unavailable with a reason until a reliable denominator is available; a controller class is not interchangeable with an HTTP entry point.
- Static METHOD_CALL edges provide an explicit executable class-pair denominator. Field types, inheritance and annotations are not observed invocations. Runtime parent-child spans must have supported application identities before counting a mapped static call pair.
- Keep runtime mappings and coverage results separate from AnalysisRun.result. Preserve static metrics, domain assignments, issue rules, exports and readiness scores.

## Proposed files and contracts (pending runtime source inspection)

Create services under the existing runtime module convention: mapping.py and coverage.py, associated Pydantic response schemas, tests for identity mapping and coverage, and a real PetClinic verification script/report. Extend the existing runtime session API/service and persistence model only after locating them. Do not invent a parallel session model or receiver.

Mapping outputs should retain the original runtime identity, mapped static identity or null, EXACT/NORMALIZED/PROXY_RESOLVED/UNRESOLVED state, rule/version, evidence, confidence and ambiguity candidates. Only documented, unambiguous normalization/proxy rules may resolve identities. Simple-name collisions, unknown generated proxies and missing class attributes remain unresolved and visible. Method resolution needs a reliable owner/name/signature contract; overload ambiguity must remain explicit.

Coverage outputs should include separate numerator, denominator, percentage or null, applicability/reason, static analysis ID, selected runtime session IDs, observation window and evidence IDs for each metric. Deduplicate identities and directed call pairs across selected sessions. Zero denominators mean not applicable, not 100%. Unresolved nodes cannot inflate static numerators. Domains are unobserved, partially observed or observed relative to their relevant static class members. An observed domain does not establish complete behavioral coverage. Unobserved static evidence must never be labelled unused.

Database changes: undecided until the existing runtime schema is available. Prefer extending its versioned derived-result storage; any new migration must be additive. API changes: mapping and coverage reads scoped to the existing session/application selection contract, with typed responses and isolation checks. No unified graph endpoint in this checkpoint.

## Implementation and validation order

1. Locate the working runtime milestone and inspect its schema, authenticated OTLP contract, normalizer, graph builder, installed agent version and real PetClinic evidence. Run its regression suite before edits.
2. Implement the smallest dedicated mapping layer with exact, normalized, safely supported proxy and unresolved cases. Preserve evidence and static snapshots.
3. Implement individual coverage metrics with reliable denominators, explicit unavailable method/entry-point results where needed, session isolation and deduplication.
4. Add tests for ambiguous identities, proxies, missing attributes, duplicate observations, cross-session selection, zero denominators, partial domain coverage, executable edge filtering and unchanged static outputs.
5. Validate against real PetClinic spans: initial workload, mapping evidence, coverage gaps, then an additional previously unobserved flow. Demonstrate increased applicable coverage without claiming unobserved dependencies are unused. Compare the static snapshot hash before and after.
6. Run existing static and runtime regressions and document actual results. Stop for review at mapping plus coverage; do not implement fusion or later phases.

## Inspection-time validation

Backend baseline: 30 passed, 3 opt-in real scanner tests skipped, 2 upstream deprecation warnings. Frontend baseline: 4 passed across 2 files; rerun outside the sandbox after esbuild filesystem access was denied. No runtime code has been implemented or validated in this checkpoint. Production source files and database schema remain unchanged during this inspection.
