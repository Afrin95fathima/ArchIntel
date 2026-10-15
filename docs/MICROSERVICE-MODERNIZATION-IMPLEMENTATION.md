# Microservice modernization implementation

## Product outcome

After architecture analysis, ArchIntel should propose a reviewable decomposition, show each candidate service with dependencies/data/evidence, and let the user select either a coordinated whole-system migration or one independently buildable service at a time. Each generated service is an isolated local Git repository with its own build, runtime configuration, health checks, API contracts, data ownership/migration plan, tests, observability defaults, security/dependency reports, and run/rollback documentation. Original customer repositories are never rewritten directly.

LLM output is an untrusted proposal. ArchIntel must bind it to the exact source commit, architecture version, evidence, prompts/model revision, selected service and approved source-transfer policy. It must validate file paths and secret filtering, preserve human review, run isolated builds/tests/scans, compare architecture and behavior, and publish a local repository only after required checks pass. No model output can authorize production deployment.

## Implemented first slice

Modernization proposals now include `microservice_decomposition`:

- one candidate per captured architecture domain;
- exact class/package membership and dependency/consumer links;
- structural data repository/entity signals, explicitly marked unconfirmed;
- readiness, evidence confidence, typed findings, source evidence/fact references and blockers;
- whole-system and one-service-at-a-time rollout modes;
- required service/system setup checklists and execution prerequisites;
- a safety state that remains `PROPOSAL_ONLY` with execution disabled.

The UI shows candidate boundaries and their evidence in the **Microservice modernization** tab. For an approved plan, **Prepare this service task** carries a selected one-by-one candidate into source-task setup. The task API verifies that the candidate belongs to the selected plan decision and pins the candidate, plan fingerprint and architecture-version fingerprint in the task record. The resulting task displays that binding. The customer still has to register and grant a complete source checkout and choose its exact captured/change scope. This creates a source-task binding only; it does not generate code or publish a repository. Whole-system orchestration remains disabled and the API rejects that rollout mode.

### Gemini generation setup

The Gemini `generateContent` adapter uses JSON-schema output, a fixed HTTPS Google API host, a `GEMINI_API_KEY` secret setting, bounded request/response sizes, no redirects or environment proxies, and fixed errors that never include provider response bodies. The default model is `gemini-3.8-flash`; operators can override it locally. A readiness endpoint reports only whether a credential is configured.

The one-by-one generation route now sends only the selected candidate's source files that map unambiguously from the pinned analysis, plus reviewed behavior-contract summaries. Before sending, it requires a security-admin workspace opt-in, a human's explicit per-request acknowledgement, an unchanged pinned source task, complete source snapshot, passing baseline/contract gates, and an unambiguous extraction map. It validates every generated path/content, rejects secrets and PII, and stores the result in a separate local Git repository with state `GENERATED_UNVALIDATED`. The UI can inspect generated files and records unresolved questions. Generation does not modify the registered customer checkout or claim tests passed.

Standalone build/test/security execution, data-boundary review in the service workflow, candidate re-analysis, approval and export/publication gates are still required. No live Gemini call has been made; tests use mocked transports only. Whole-system generation remains disabled.

The key supplied in chat is exposed and should be revoked/rotated in Google AI Studio. It has not been copied into project files or stored by this implementation. After creating a replacement, run `powershell -ExecutionPolicy Bypass -File scripts/set-gemini-key.ps1`; the prompt hides input and writes the value only to the ignored local `.env`. Restart ArchIntel afterward. Do not paste the replacement key into chat or source files. Claude is not configured yet; a Claude provider adapter will be added when its preferred API contract is specified. See [Gemini service-generation setup](GEMINI-SERVICE-GENERATION-SETUP.md) for the gated user flow.

## Remaining implementation stages

1. **Provider integration and policy.** Select the API protocol and authentication scheme. Keep credentials in an OS/environment secret store, never in the database or source. Add explicit per-repository transfer consent, request/redaction limits, audit records, provider model/version pinning and deterministic test fakes. A provider/API key has not been supplied; no external call is enabled.
2. **Source-to-candidate workspace.** The first binding is implemented: an approved candidate is bound to its matching plan decision and pinned architecture version in a source task. Complete the workspace by verifying class-to-file mappings against the captured checkout, enforcing candidate-specific paths, and making the UI collect a complete source snapshot without requiring manual file-list transcription.
3. **Service generation.** Generate a bounded multi-file changeset for the selected boundary, including API/consumer adapters, service implementation, independent build/runtime setup, environment template, tests and operational documentation. For whole-system mode, coordinate service contracts and shared setup across candidates. Emit a local-only repository per service plus a parent orchestration repository. Validate manifests, safe paths, archive size, secret filters and model output schema before writing files.
4. **Validation and publication.** Run baseline and generated builds in the isolated sandbox, execute behavioral and contract tests, security/dependency scans, static re-analysis and data checks; report PASS/FAIL/INCONCLUSIVE with evidence. Require independent human reviews for boundaries, data ownership, patch staging and final local-repository publication. Export each accepted local Git repository without pushing or deploying.
5. **Existing-application pilot.** Configure an authorized source repository and contracts, capture static and representative runtime evidence, then complete one small service through proposal, generation, isolated validation, review and local repository export. Expand to the whole application only after the one-service pilot is reviewable and repeatable.

## Current blockers and limits

- The user will specify the LLM provider later. The current AI gateway only supports approved local Ollama for evidence selection; it cannot generate code or send repository source to an external API. Provider integration and secure secret configuration are still required before code generation.
- Static analysis of an artifact does not supply a complete editable source repository. Source modernization requires a registered, explicitly granted Git snapshot.
- Runtime is optional to create a planning proposal, but a trustworthy service split requires representative workload traces and reviewed business boundaries.
- Package/domain clustering is a candidate signal, not a business capability map. Database repository/entity references do not establish ownership.
- Concord has a partial source/data discovery probe but no captured Concord runtime session. A client-quality Concord service modernization has not been generated or validated.

## Acceptance tests

- Candidate proposals are deterministic, version/commit-bound and trace every recommendation to valid facts/findings/evidence.
- Shared persistence, cycles, missing runtime, incomplete source and unreviewed domains block service generation or lower scope to an explicit review-only state.
- The model cannot add files outside the approved service scope, modify protected files, leak secrets, invent passing tests or choose a target boundary.
- Each service repository builds independently with no implicit monolith classpath and contains the declared setup artifacts.
- Whole-system and one-at-a-time outputs use the same pinned source and model inputs and retain cross-service API/data dependencies.
- Failing, skipped or stale behavior/security/data checks prevent publication; successful test runs remain bound to source, model, patch and artifact fingerprints.
- The original repository, static baseline and runtime evidence remain unchanged throughout generation, validation and export.
