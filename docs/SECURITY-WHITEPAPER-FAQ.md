# ArchIntel security whitepaper and procurement FAQ

## Executive summary

ArchIntel is currently a customer-operated local prototype. Its verified workflow binds the UI/API to configured local hosts, stores analysis and identity data in a local PostgreSQL or SQLite database, scans submitted compiled Java artifacts, and can ingest OpenTelemetry traces into a selected static-analysis session. The product is not represented as production SaaS, a certified security product, or a language-agnostic scanner.

## Architecture and trust boundaries

The local customer environment contains the browser UI, FastAPI service, analysis worker, Java/jQAssistant tooling, PostgreSQL, configured data directory, and optional source-task/security tooling. Static graph extraction uses an isolated embedded Neo4j store per job. A runtime Java agent sends OTLP trace batches to a session-specific API route using a bearer token. Authenticated browser/API actions use account credentials, workspace permissions, CSRF checks for browser mutations, and an append-only hash-chained audit log stored in the database.

The application artifact is inspected as compiled bytecode; ArchIntel does not launch the submitted application during static analysis. Runtime observation is optional and requires the customer to run the application with an OpenTelemetry Java agent. Runtime attributes such as artifact hash are declarations from the sender, not cryptographic attestation.

## Data flow and egress

Static artifacts are uploaded to the local API and staged under the configured ArchIntel data directory for validation and scanning. On successful processing, uploaded artifacts are removed by default; structured analysis results, artifact identity/hash, and reports remain in configured storage. Runtime traces are sent from the customer application to the configured ArchIntel runtime endpoint. Runtime event retention and purging are bounded by local settings; aggregated session reports are retained separately.

The deterministic evidence assistant runs locally. Optional model features may send selected context to a configured model destination only when explicitly enabled and authorized; do not enable external destinations without customer data-transfer review. Initial installation/provisioning can download third-party tooling and public dependencies. Therefore no universal no-egress guarantee is claimed. The current prototype does not require routine vendor phone-home for the prepared local workflow, but a deployment-specific network capture is required before making an absolute egress statement.

Exports can contain class/package names, dependencies, findings, runtime coverage, and modernization metadata. Treat them as confidential engineering data. Review and authorize any export before sharing it outside the customer boundary.

## Implemented controls and limitations

Implemented in the local prototype: account sign-in, permission checks, tenant-scoped record access, short-lived human/service credentials, login throttling, browser CSRF checks, trusted-host and origin controls, body/upload bounds, session-specific runtime bearer tokens, token rotation, lifecycle audit events, and a hash-chained database audit log. Runtime bearer credentials are reusable for OTLP batches, displayed only at creation/rotation, and now expire 24 hours after issue. Rotation revokes the previous hash.

Limitations: a database owner can replace the entire audit chain without an independent checkpoint; external audit anchoring is not implemented. The runtime token is not a one-time token because an OTel exporter must reuse it for multiple batches. TLS termination, customer identity-provider integration, managed secrets, high availability, distributed worker isolation, production deployment hardening, and a universal network-egress proof are not established. Database encryption-at-rest and backup encryption depend on customer infrastructure and are not asserted by the application.

## Threat model

| Threat | Current mitigation | Remaining boundary |
|---|---|---|
| Unauthorized UI/API access | Sign-in, permission checks, login throttling, CSRF and host/origin controls | Customer must protect the host, database and bootstrap material |
| Cross-workspace record access | Tenant-scoped ORM and ownership checks | Not a substitute for independent penetration testing or database-level tenant isolation |
| Runtime token disclosure | Random bearer token, shown once, 24-hour expiry, rotation/revocation, scoped ingestion route | Reusable while valid; protect process environment and agent configuration |
| Malformed or oversized artifact/telemetry | Archive and request bounds, validation, per-session limits | Limits do not establish large-scale capacity or eliminate parser risk |
| Audit tampering | Append-only application path and hash chain | Database owner can replace all rows; no external checkpoint |
| Unintended data egress | Local deterministic mode and explicit model gateway policy | Provisioning downloads and deployment-specific egress must be independently reviewed |
| Incorrect architectural conclusion | Evidence references, explicit heuristic formulas and unknowns | Human review remains required; this is not vulnerability scanning or proof of behavior |

## Procurement FAQ

**Does source code leave our environment?** Static analysis accepts compiled Java artifacts and processes them in the configured ArchIntel environment. The application is not run. Optional source-task functionality can read explicitly granted repository files locally. External model transfer must be separately enabled and policy-authorized. Do not make a no-egress claim without reviewing the deployment and monitoring its network traffic.

**What data is retained?** By default, successful static-analysis upload artifacts are removed after processing. Analysis graphs, findings, hashes, runtime-derived records, audit events, and configured reports remain in the local database/data directory under their applicable retention behavior. Runtime raw-event retention is configurable and purged by the runtime retention service.

**Are runtime credentials one-time?** No. The runtime bearer token is shown only at creation/rotation, reusable by the OTel exporter, expires after 24 hours, and is revoked by rotation. It is scoped to one session's ingestion route.

**Is ArchIntel a vulnerability scanner?** The readiness/confidence values are architecture and evidence heuristics. They are not tool accuracy, vulnerability severity, or proof of safe modernization. Separate Java security scanning exists in gated workflows; complete dependency coverage is not established.

**Is the product certified?** No SOC 2, ISO 27001, or other certification is claimed in this prototype.

**How is audit evidence protected?** Application audit events are hash-chained in the database and ordinary update/delete operations are restricted. Independent external checkpoints are not implemented, so a database owner can replace the full chain.

**What deployment is supported?** The verified product workflow is a local Windows deployment. Docker and production SaaS deployments require their own environment-specific validation. Keep this prototype bound to localhost unless a reviewed deployment profile establishes the required controls.

**Does ArchIntel prove behavior or unused code?** No. Runtime coverage is limited to selected sessions and exercised workloads. “Unobserved” means not seen in those sessions, not unused.

**Does ArchIntel support every language?** No. The current static scanner and ingestion pipeline are Java-focused. Other language support is future work and must be evidenced by language-specific adapters and tests.

**What security evidence is available?** The repository includes focused security/runtime tests, implementation guides, and local diagnostic endpoints. These are not a substitute for an independent security assessment, penetration test, customer threat review, or contractual security commitments.
