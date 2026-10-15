# Customer integration and security guide

## Deployment boundary

The verified product workflow is a local Windows deployment using the project launcher, PostgreSQL, the local API/UI, a Java runtime, jQAssistant and its graph exporter. Docker is an optional alternative whose runtime behavior is not claimed here. Keep the prototype bound to localhost. It is not a production SaaS deployment, and no SOC 2 or ISO certification is claimed.

The uploaded artifact is scanned as bytecode; ArchIntel does not launch the application. Successful analysis removes the upload by default while retaining structured analysis data and artifact hashes. The database and workspace data directory contain saved results and should be included in customer-approved backup, access-control, retention and recovery procedures. Do not delete `.data` to troubleshoot: it holds persisted results.

## Identity and access

Initial administrator setup and sign-in are required. Accounts, workspace permissions, audit history, CSRF protections, and tenant-scoped records are implemented in this prototype. Create individual accounts and grant only the required permissions. Runtime-management operations and source access have separate permissions. Audit events are hash-chained in the database; independent external checkpoints are not implemented. The local API is not a substitute for a customer identity provider, managed key service, TLS ingress, or production network boundary.

## Static analysis integration

Upload a compiled `.jar`, `.war`, or supported compiled project ZIP through the UI or authenticated `/api/v1` API. Source-only ZIPs are rejected. The application itself is not executed. API requests require the established session/CSRF flow; use the UI or documented authenticated client rather than embedding credentials in automation. Review `/openapi.json` locally for endpoint contracts and limits.

Safety ceilings are protective input bounds, not performance guarantees. For current values and supported packaging, consult the user manual. The dedicated benchmark script measures only the pure analysis stage and excludes scanning and persistence.

## Runtime telemetry integration

Dynamic analysis uses an OpenTelemetry Java agent to send OTLP telemetry to a session-specific endpoint. Create a session against the intended completed static baseline, use the generated endpoint and bearer token as shown in the UI, start the application under observation, and exercise representative workflows. Treat agent service/resource attributes as declarations, not proof of binary identity. Keep tokens secret and revoke/close sessions under your retention policy.

Coverage reports what the selected sessions observed. It is workload-dependent: not observed does not mean unused or unreachable. Review dropped/duplicate/conflicting telemetry and unresolved nodes before comparing versions. Capture a successor architecture version to preserve runtime evidence alongside its static baseline.

## Models, source tasks, and security scanners

The deterministic evidence assistant works without external model calls. Optional local-model features are policy- and permission-gated. Do not configure external model destinations without customer review of data transfer and security policy. Source transformation tasks require a separately registered repository, explicit source scope and grants, and gated review/validation. Candidate Java security tools and container-dependent flows can be unavailable when their scanners/databases are not provisioned; the UI reports this state. Full dependency coverage is not established.

## Backup, upgrade, and support

Back up PostgreSQL and the configured ArchIntel data directory together. Test restore into an isolated environment before upgrades. Keep `.env` and runtime credentials outside version control; rotate local credentials if exposed. A customer-facing production upgrade/rollback system, managed secret integration, high availability and air-gapped release lifecycle are not delivered by the local prototype.

Support bundles or exports can contain architecture-sensitive metadata. Review their contents and obtain customer authorization before sharing them. Analysis JSON and modernization PDFs should be handled as confidential engineering records.

## Operational verification

Use Local setup diagnostics to confirm database, scanner, and data-folder readiness. Check `/api/v1/ready` before starting an analysis. Follow job progress through completion before stopping the service. Use the user manual for launcher, upload and workflow steps, and the runtime guide for agent setup and coverage interpretation.

See [User Manual](USER-MANUAL.md), [Dynamic Analysis User Flow](RUNTIME-USER-FLOW.md), [Security Architecture](ARCHINTEL_SECURITY_ARCHITECTURE.md), and [Scalability Benchmark Method](SCALABILITY-BENCHMARKS.md).
