# ArchIntel product completion plan

Status: Stage 1 in progress. Existing static and runtime analysis remain the regression baseline.

## Local POC continuation — 9 October 2026

The agreed current focus is the single-machine local POC. Docker installation, container images, and enterprise packaging are postponed until the local workflow is developed. Existing functionality is retained; container-backed source builds/refactor execution/security scans remain gated and are not reported as passed. The new **Local setup** diagnostics checks local database connectivity, Java/jQAssistant/exporter availability, local data-folder access, and optional OpenTelemetry/local-AI configuration without invoking Docker or contacting an AI provider. The read-only endpoint is `GET /api/v1/system/diagnostics`.

The user has declined a guided onboarding feature. Current implementation focus is the remaining Phase 7 modernization-factory work, beginning with Phase 7B extraction. Enterprise deployment, distributed workers, and cloud/provider delivery remain later scope.

Delivery follows the agreed order. Each stage needs implementation, automated checks, user/developer documentation, and a reviewable outcome. A prototype demonstration does not establish production readiness. Earlier real PetClinic evidence is historical; it must not be presented as a new validation run.

## 1. Dependability

- [ ] Accounts, workspace isolation, roles, session security, and audit records.
- [ ] Guided setup with dependency diagnostics and actionable recovery instructions.
- [ ] Durable job recovery, safe retries, duplicate execution protection, cancellation, and bounded retention.
- [ ] Deployment configuration, backup/restore exercise, and operational health checks.
- [ ] Documented Java/framework/packaging compatibility matrix backed by actual runs.

Acceptance: unauthorized and cross-workspace access denied; interrupted work has a documented recovery path; failures preserve retry inputs; existing static/runtime tests pass; clean installation and restore demonstrated on supported deployment targets.

## 2. Trustworthy conclusions

- [ ] Versioned domain edits with preview, provenance, and recalculation.
- [ ] Runtime mapping diagnostics, explicit ambiguity, and manual reviewed overrides.
- [ ] Coverage by scenario/time window with denominators, missing instrumentation, and optional code coverage import.
- [ ] Database ownership and shared-data evidence with uncertainty and safe attribute handling.
- [ ] Score calibration against reviewed examples, confidence reporting, and weight/version provenance.

Acceptance: immutable originals retained; changes reproducible; unresolved observations never become invented dependencies; incomplete coverage never implies unused code; score limitations visible.

## 3. Actionable modernization

- [ ] Editable modernization plans with prerequisites, owners, milestones, risks, and acceptance tests.
- [ ] Comments, review/approval history, and permissions.
- [ ] Version comparison using stable identities and explicit baseline compatibility.
- [ ] Engineering exports/integrations with preview, deduplication, and retry handling.

Acceptance: users can turn evidence into a reviewed plan, compare subsequent versions, and export work without duplicating it. External writes require the user's authorization and configured credentials.

## 4. Usability and evaluated AI

- [ ] Optional generative explanations grounded in evidence, with source links and abstention.
- [ ] Evaluation dataset, factuality checks, prompt-injection tests, privacy controls, and deterministic fallback.
- [ ] Richer reproducible reports with scope, versions, coverage, and limitations.
- [ ] Workflow refinement, accessibility, empty/error states, and end-to-end onboarding tests.

Acceptance: unsupported AI assertions fail evaluation; absent provider credentials do not break core analysis; an unfamiliar user completes the documented workflow.

## Checkpoints

Stage 1 starts with restart recovery, failed-artifact retention, duplicate job claims, and browser-origin protection. This first checkpoint does not supply authentication or qualify the service for shared/public exposure. Remaining stage-1 items must pass before stage 2 starts. User verification checkpoints follow the original requested phase-by-phase workflow.

### First implementation checkpoint (3 October 2026)

Implemented:

- Startup recovery of persisted queued/interrupted analyses with available inputs.
- Failed artifacts retained for retry; successful processing preserves the existing cleanup policy.
- Conditional database job claims, separate attempt directories, and pre-scan checksum verification.
- Browser Origin/fetch-metadata validation, trusted Host validation, and frame-embedding protection.
- Seven failure-path/security regression cases and updated user/developer manuals (Markdown, HTML, PDF).

Verification: backend 57 passed (three opt-in scanner cases skipped in that invocation); frontend five passed. Separate real scanner tests passed JAR and WAR. Spring Boot initially timed out during an abnormally long elapsed run, then passed an isolated rerun in 41.29 seconds. No fresh live PetClinic or browser end-to-end run is claimed for this checkpoint.

Still required in stage 1: account authentication/authorization, workspace isolation, auditing, cancellation, bounded artifact retention, distributed worker fencing if supported, deployment and backup/restore validation, and a broader compatibility matrix. The user explicitly declined a separate guided onboarding feature. Stages 2–4 have not started.

### Local POC diagnostics checkpoint (9 October 2026)

Implemented an authenticated, read-only Local setup page and `GET /api/v1/system/diagnostics`. It checks database reachability, required static-scanner files, local data-directory access, and optional OTel/local-model setup. Container build and security workflows report `DEFERRED`; diagnostics never starts Docker or contacts a model provider. Added backend and frontend regression tests and updated both manuals. This is environment guidance and does not alter the static-analysis or runtime-analysis pipelines.

Verification: targeted backend/security suite 26 passed; frontend suite 6 passed; TypeScript and production frontend build passed. The build reports the existing large-chunk advisory. Docker-dependent source builds and packaged-dependency scans remain intentionally unvalidated until Docker is reinstalled and local development is complete.
