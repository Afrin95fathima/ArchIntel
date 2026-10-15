# Dynamic analysis delivery plan

The user authorized the complete dynamic prototype on 16 September 2026, superseding the previous mapping/coverage-only checkpoint. Static engine, graph snapshots and structural scoring remain authoritative and unchanged.

1. Add additive runtime session/event models and migration, schema-based lifecycle APIs, per-session hashed ingestion tokens, bounded OTLP HTTP protobuf/JSON normalization and safe attribute allowlisting.
2. Reconstruct parent-child relationships within a session and trace; aggregate class/package/domain graphs, duration/error evidence and unresolved identities. Implement conservative mapping and separate coverage metrics with explicit unavailable denominators.
3. Fuse selected compatible sessions with the immutable static snapshot. Expose evidence classifications, guided discovery, flows, persistence signals and separately explainable runtime/combined assessments. Low coverage affects confidence, not structural readiness.
4. Integrate runtime session setup, status, graph/evidence inspection and coverage into the existing frontend, plus deterministic runtime assistant context. No replacement frontend or static engine.
5. Validate with regression/security/algorithm/API tests and a real Java agent connection. Exercise additional workload and verify changing observation coverage. Document actual results and unverified limits.
6. Deliver runtime user flow and developer design/runbook documents.

New code will live under app/runtime (models, schemas, routes) and app/services/runtime (normalization, mapping, graph, coverage, fusion, intelligence, session service). Existing edits are limited to application/router registration, additive configuration, Alembic metadata, dependency manifests and frontend navigation. PostgreSQL stores sanitized bounded events separately from the static snapshot. Runtime conclusions are reproducible from selected events and pinned static analysis ID. No raw payload/body/SQL storage, no uploaded application execution, no claimed production tenant security or agent overhead benchmark.

Delivery implementation is recorded in [RUNTIME-VERIFICATION.md](RUNTIME-VERIFICATION.md). Real validation required an additional, additive method/annotation inventory in the Java static exporter and scanner normalization; existing static calculations and old snapshots remain intact. Production hardening and advanced runtime resequencing are explicitly outside the demonstrated prototype.
