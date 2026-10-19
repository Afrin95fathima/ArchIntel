# ArchIntel complete user guide

This guide explains the screens and fields in the current ArchIntel interface: what each screen is for, what you enter or select, what ArchIntel does with that input, and how to interpret its output. It is written for readers who have not used ArchIntel before.

ArchIntel's main workflow analyzes **compiled Java bytecode**. It does not compile or launch the uploaded application. Static results describe code structure, not proof of runtime behavior or business ownership. Readiness, confidence, candidate boundaries, and recommendations are evidence-based heuristics for investigation; they are not a guarantee of safe extraction, cost, duration, or success. Runtime coverage describes only selected sessions and exercised workloads. Security scanning is limited and available only when the relevant scanner and data are provisioned.

The usual sequence is: set up and sign in; upload compiled output; inspect static analysis; optionally collect runtime observations; capture and review an architecture version; create a modernization proposal; and export reports. Source tasks, model use, and security scanning have additional permissions and local setup requirements.

## 1. First access and navigation

### Administrator setup and sign-in

On first launch, an administrator creates the local workspace owner. The setup key is read on the server from `.data/security-bootstrap.key` and is consumed once during bootstrap. This is distinct from a normal session credential.

| Field or control | Input or purpose | Result |
|---|---|---|
| Setup key | One-time server bootstrap secret, only shown during initial setup. | Authorizes creation of the first administrator. |
| Username | Administrator or existing account name. | Identifies the account to create or authenticate. |
| Password | New password during setup (at least 12 characters), or current password when signing in. | Establishes the account session. Human sessions expire; users sign in again after expiry. |
| Create administrator / Sign in | Submits the form. | Opens the local workspace when accepted. Invalid credentials or expired sessions are reported. |

After sign-in, the bar above the workspace displays the current identity and provides **Security & access** and **Sign out**. Human browser sessions use an expiring reusable session credential. The runtime telemetry token is a separate credential, reusable by the OpenTelemetry exporter and scoped to one observation session.

### Sidebar, top bar, help, and navigation

The sidebar groups screens under **Portfolio**, **Analyze**, **Runtime**, **Plan**, **Evidence**, and **Deliver**. Select a name to open that screen. The portfolio **Applications** button returns to the application list. The bottom contains **Local setup**, **Design system**, and **Help & documentation**. Help opens a quick-start panel with links to the user and developer manuals.

The top bar shows the current screen, selected application where applicable, service readiness, and (on analysis screens) an analysis selector and **Export analysis** action. The analysis selector changes the static result used by that screen. **Ctrl+K** opens a searchable screen switcher; **Esc** closes it. The sidebar toggle collapses navigation. These controls change the visible workspace; they do not alter saved analysis records.

## 2. Applications (Portfolio)

This is the starting point for managing analyzed applications and launching analyses.

### Northstar Commerce sample

**Explore demo application** opens a pre-analyzed synthetic Java sample when a result exists, or requests the demo workflow. **Download sample JAR** downloads its compiled artifact. Northstar is synthetic demonstration code: it shows the real scanner and analysis pipeline, but its architecture is not a customer system.

### Application list

The **Cards / Table** control changes presentation only.

| Displayed value | Meaning |
|---|---|
| Application and project | Names recorded when the application was created. |
| Source type and version | Application metadata, not a bytecode version guarantee. |
| Latest analysis and date | Most recent saved analysis status and creation date. |
| Classes / packages | Counts from a completed analysis. |
| Readiness / confidence | Aggregate structural readiness and mean candidate-boundary confidence, when available. Both are heuristics. |
| Runtime coverage | Coverage from an available completed runtime session; otherwise “Not observed” or unavailable. |

Select an application card or row to open its latest analysis. If it has no analysis, the selection opens the upload workflow.

### Analyze application form

Click **Analyze application** or **Analyze another application**.

| Field | What to enter/select | What ArchIntel does / output |
|---|---|---|
| Project | Choose an existing project, or “Create a new project.” | Groups applications for workspace organization. |
| New project name | Name for a project when creating one. | Creates the project record; blank uses “My architecture workspace.” |
| Application name | A recognizable system name. | Labels the application; blank derives a name from the uploaded filename. |
| Version | Version label for this artifact. | Stores the label alongside the analysis so releases can be compared. |
| Java artifact or compiled project ZIP | Select `.jar`, `.war`, or supported `.zip` containing compiled output. | Uploads and validates the archive, then queues static analysis. Current configured upload limit is shown by the UI; it is a safety limit, not a tested capacity claim. |
| Start architecture analysis | Submits the form. | Creates or selects the project/application, stores the upload, validates it, and starts the worker. Progress and errors appear on the next screen. |

Supported inputs include ordinary JARs, WARs, Spring Boot archives, and project ZIPs with compiled classes under recognized `target/classes` or `build/classes` trees or module JAR/WAR files. Source-only ZIPs are not compiled. Nested dependency archives and multi-release overrides have documented exclusions; conflicting duplicate class definitions are resolved deterministically and disclosed in the manifest. The application is not executed.

### Baseline drift and coverage gaps

When an application has at least two completed scans, this panel compares two saved analyses. **Baseline** and **Candidate** select the earlier and later result. The table shows class, dependency, candidate-domain, finding, and readiness count changes. It is a read-only comparison; it does not change either scan. Scanner or algorithm versions can change the results. Static analyses do not measure workload coverage; use **Dynamic analysis** for observed versus unobserved items.

## 3. Analysis progress

While a scan runs, the page shows status, progress percentage, current stage, and elapsed duration recorded for completed stages. Stages include validation, scanning, graph extraction/building, cycle analysis, metrics, domain discovery, issues, modernization analysis, and persistence.

You may leave the page and return later. One worker processes a job at a time; other jobs can queue subject to deployment limits. A failed or rejected job displays its error and stage. A failed analysis is not presented as a completed result; upload another artifact after addressing the error.

## 4. Overview

Overview is the summary of the selected completed scan.

| Field or panel | Purpose and output |
|---|---|
| Classes | Number of application bytecode classes discovered. |
| Packages | Number of packages discovered. |
| Dependencies | Distinct internal dependency pairs; typed links can be more numerous. |
| Candidate domains | Automatically inferred structural groups, not confirmed business domains. |
| High severity | Count of findings returned as Critical or High; these are structural findings, not a complete security scan. |
| Cyclic groups | Class and package strongly connected groups detected in the graph. |
| Modernization readiness | Mean heuristic structural prioritization score. It does not estimate cost or success. |
| Boundary evidence confidence | Mean heuristic support for inferred boundaries, not a probability. |
| Domain size distribution | Class counts assigned to candidate domains; concentration can prompt review. |
| Technical debt by severity | Counts of returned architectural findings grouped by severity. |
| Evidence panel | Artifact filename/hash, scanner version, analysis-engine version, and duplicate-class caveats. |
| Ask about this architecture | Opens the Architecture assistant for this analysis. |

Overview numbers are outputs of the selected analysis; there are no user-entered fields on this screen.

## 5. Application architecture

This screen presents a static blueprint of the analyzed artifact. The upper boundary card identifies the artifact and packaging and summarizes classes, packages, inferred modules, static dependencies, and external references.

### Diagram controls

| Control | Input | Effect |
|---|---|---|
| Diagram view | Dependencies, Modernization waves, or Before / after. | Displays static dependency relationships, proposal wave coloring, or a selected earlier scan against the current scan. |
| Diagram level | System, Module, or Package. | Changes graph aggregation/detail. The graph remains bounded for readability. |
| Before scan | Earlier completed analysis of this application (only in Before / after mode). | Chooses the comparison baseline. Counts apply to the nodes visible in the bounded map. |
| Color nodes by | Available dependency overlays such as domain, debt, or runtime coverage. | Colors nodes by the selected structural/evidence measure. Coverage requires an associated runtime session; wave colors require a proposal. |
| Runtime session | A session associated with the selected baseline (shown for coverage overlay when available). | Selects which observation session colors the map. |
| Export side | Before or After in comparison mode. | Chooses which graph is exported. |
| Mermaid / SVG / PNG | Export action. | Downloads the selected graph as a text diagram or image. |
| Print / PDF | Browser print action. | Opens the browser print dialog for a printable view. |

Arrows point from a dependent to its dependency; red borders indicate cycle participation. Colors indicate only the selected overlay. The lower module cards group package/class evidence into candidate modules and heuristic code layers (API, business, data, support). Select a module to inspect package names, class samples, incoming/outgoing/internal dependency counts, database signals, and connected modules. Class detail can be capped; totals shown in summaries come from the full analysis. These inferred modules are not proof of deployable services or runtime communication.

## 6. Architecture explorer

The explorer allows progressively detailed graph inspection.

| Control | Input / action | Output |
|---|---|---|
| Domains / Packages / Classes | Choose graph granularity. | Loads the corresponding graph level. |
| Domain filter | Select one candidate domain or all. | Narrows package/class results. |
| Double-click / Expand | Select a graph node and expand it. | Opens packages within a domain or classes within a package. |
| Node details | Click a node. | Shows name, type, annotations, counts, and available metrics. |
| Fit graph | Button in the graph corner. | Fits visible nodes to the viewport. |
| Clear package | Breadcrumb action. | Removes the package-level filter. |

The default graph is capped at 150 nodes and 2,000 edges; select a smaller domain/package to inspect a large system. An arrow points from dependent to dependency. A truncated view is a display subset, not a claim that omitted nodes do not exist.

## 7. Candidate domains

Candidate domains are automatically inferred clusters; domain owners should review names and membership.

| Field/control | Meaning |
|---|---|
| Sort by | Sorts by class count, readiness, confidence, or name. It does not affect analysis. |
| Table / Cards | Changes layout only. |
| Candidate domain | Inferred group name and counts of classes/packages. |
| Readiness | Structural score from the saved assessment, if available. See Modernization for formula and components. |
| Evidence confidence | Heuristic support for the boundary, not probability. |
| Runtime coverage | This static-only view says “Not observed”; use Dynamic analysis to attach session evidence. |
| Blockers / status | Assessment blockers and a reminder that the grouping is a review candidate. |
| Domain detail | Select a row/card to open evidence, database signals, dependency profile, blockers, and class membership. |
| How this score is calculated | Expands the readiness explanation, formula, component values, and weights. |

Database evidence can be absent or incomplete. Static class references do not prove data ownership, transactions, or business capability boundaries.

## 8. Technical debt

This screen lists returned architectural findings so a reviewer can build an investigation backlog.

| Filter or field | Meaning |
|---|---|
| Search issues or package | Case-insensitive search over finding title, entity ID, and evidence. |
| Severity | Show all, Critical, High, Medium, or Low. Findings are ordered with higher severities first. |
| Issue type | Limit to a returned structural rule type. |
| Domain | Limit to findings associated with a candidate domain. |
| Finding row | Shows severity, title, affected entity, and finding type. |
| Expanded finding | Shows why it matters, suggested investigation, evidence ID, and structured analyzer evidence. |

“No findings” means no items were returned for the selected analysis and filters. These findings do not constitute comprehensive vulnerability scanning.

## 9. Dependencies: circular dependencies and architecture metrics

The **Circular dependencies** tab groups strongly connected class or package nodes. The level filter selects class cycles, package cycles, or both. Each card displays severity, cluster level, member count, internal edges, affected candidate domains, and sample paths. Expand a card for complete cluster membership and bounded cycle samples. Large groups may skip sample enumeration while retaining membership and edge counts; no sample path does not mean no cycle.

The **Architecture metrics** tab reports package-level values:

| Field | Meaning |
|---|---|
| Classes | Number of classes in the package. |
| Ca | Distinct outside classes that depend on classes in this package. |
| Ce | Distinct outside classes that this package depends on. |
| Instability (I) | `Ce / (Ca + Ce)`; zero when there is no coupling. |
| Abstractness (A) | Abstract classes and interfaces divided by package classes. |
| Distance (D) | `abs(A + I - 1)`, distance from the plotted main sequence. |
| Isolated | Package has no external coupling for this metric. Interpret separately. |

The scatter plot visualizes abstractness versus instability; the dashed line is `A + I = 1`. Metrics describe structure, not automatic quality verdicts.

## 10. Architecture assistant

Enter a question (3–2,000 characters) about the selected static analysis and submit it. Suggested prompts provide examples. ArchIntel retrieves relevant structured evidence rather than sending the full artifact or graph. The response separates cited facts from investigation recommendations. Each fact links to an evidence record; **Sources and limitations** shows retrieval mode, source IDs, and limits. The default is local deterministic evidence retrieval. A separately configured, permission-controlled local model may help select citations. This assistant does not know runtime traffic, SQL transactions, or business ownership unless those have been supplied as evidence.

## 11. Dynamic analysis

Dynamic analysis receives OpenTelemetry traces from a running Java application. It does not start or manage that application. First create a static analysis, then create a session, configure the Java agent using the displayed environment variables, launch and exercise the application yourself, and stop the session.

### Create an observation session

| Field | What to supply | Effect |
|---|---|---|
| Application | Application with a completed static analysis. | Scopes the runtime session. |
| Static baseline | Completed analysis for that application. | Provides the static identities against which telemetry is compared. |
| Session name | Descriptive workload/test name. | Labels this evidence set. |
| Environment | Environment label, such as LOCAL, test, or staging. | Records context for later interpretation; it does not verify deployment identity. |
| Instrumentation depth | BOUNDARY, STANDARD, or DEEP. | Chooses breadth of selected Java-method instrumentation and expected overhead. Preview the plan first. |
| Application package prefixes | Optional comma-separated Java package prefixes to include. | Narrows/selects application code for instrumentation. |
| Exclude package prefixes | Optional comma-separated package prefixes to exclude. | Removes matching areas from the instrumentation plan. |
| Telemetry binding | STRICT or COMPATIBLE. | STRICT requires declared service and artifact resource identity; COMPATIBLE permits missing identity to remain unverified. Sender attributes are declarations, not proof of binary identity. |
| Preview instrumentation plan | Action. | Shows which classes/methods would be instrumented and why, before creating a session. |
| Create runtime session | Action. | Creates a session and returns an expiring, reusable, session-scoped bearer token plus agent setup instructions. The token is displayed at creation/rotation; store it securely. |

The session list displays name/environment, state, agent status, received trace/span counts, and dropped telemetry. **Start** opens ingestion for a created session; **Stop** closes it; **New token** rotates the credential, invalidating the previous one. Select sessions to combine evidence only when they share the same static baseline.

### Runtime result tabs

| Tab | What it shows and controls |
|---|---|
| Coverage | Observed/total/percentage for classes, entry points, methods, dependencies, and domains. Select a tile to filter/search/page exact observed/unobserved items. Coverage means seen in selected sessions only. |
| Quality | Accepted, duplicate, conflicting, dropped, unverified, and unmapped telemetry; method mapping and session binding details. Use these counts to assess evidence quality. |
| Graph | Unified, runtime-only, or static graph; choose domains/packages/classes. Select an edge to inspect call counts and sanitized evidence references. |
| Mapping | Runtime identities compared to static identities, with resolution state and supporting evidence. |
| Flows | Observed request groups by entry route, trace count, errors, participating classes, and average entry duration. This is not a complete execution order. |
| Database | Observed caller/system/resource/operation/call counts. SQL text and parameter values are discarded; unknown resources remain unknown. |
| Modernization | Structural/runtime/combined scores, observation confidence, and difficulty. Low coverage lowers confidence, not structural readiness. |
| Assistant | Ask a runtime evidence question; the answer links to runtime evidence. |
| Export evidence | Downloads a JSON report for the selected runtime evidence. |

Coverage gaps are workload-dependent: not observed does not mean unused. Exercise representative routes, jobs, and message flows, check data quality, and capture a successor architecture version if you want the new evidence included in the digital twin.

## 12. Modernization

The **Modernization** sidebar screen has **Proposal workspace** and **Extraction sequence** tabs. It turns a selected architecture version into a reviewable plan; it does not execute a migration.

### Proposal workspace inputs

| Field/control | Meaning and output |
|---|---|
| Planning application | Application whose evidence is used. |
| Planning architecture version | Frozen static/runtime evidence snapshot. Capture one in Evidence & digital twin first. |
| Target strategy | User-selected option: modular monolith, microservices, hybrid, cloud refactor, Java upgrade, or framework upgrade. It is an input, not an automatically selected winner. |
| Planning objective | Free-text goal (up to 1,000 characters). Appears in the saved proposal/report and frames recommendations. |
| Preview modernization plan | Computes a draft decision brief, assessments, findings, and dependency waves without saving. |
| Save modernization plan | Saves the currently matching preview as a frozen proposal. |
| Saved planning proposal | Selects an earlier saved proposal for inspection/review/export. |

Runtime evidence is optional. Missing observations remain explicit. The decision brief explains strategy fit, evidence sufficiency, unknowns, risks, priority actions, questions, and next step. Strategy statuses are evidence/review states, not predicted outcomes.

### Proposal tabs

| Tab | Purpose / fields / outputs |
|---|---|
| Decision brief | Summary, selected strategy, rationale, confidence label, heuristic effort band (when available), strategy comparison, linked risks, open questions, and next step. No extra input. |
| Microservice modernization | Candidate boundaries, class lists, dependencies/consumers, static data signals, blockers, risks, rollout scope, and setup needs. **Modernization scope** selects a rollout mode such as one-by-one. **Prepare this service task** passes a reviewed candidate to Source tasks when prerequisites and planning approval are satisfied. Candidate services are hypotheses, not confirmed business services. |
| Decisions | Per-domain proposed action and blockers. **Explain why** retrieves supporting findings and fact provenance. |
| Readiness & confidence | Structural readiness, runtime observation score, combined and adjusted scores, confidence, status, effort/risk bands, formula, components, weights, cost drivers, recommendations, and missing evidence. Values are heuristics and displayed formula/version is authoritative. |
| Target & waves | Proposed target components/interfaces/alternatives and dependency-ordered waves, with prerequisites, coupled groups, blockers, entry/exit criteria, and expected impact. These are planning proposals. |
| Review | **Planning review outcome** is Approved planning / Changes requested / Rejected. **Planning review note** records rationale (required). Recording review approves agreement with the plan only, not code changes or deployment. |
| Graph | Evidence graph with bounded neighborhood. **Planning graph neighborhood** chooses the sample/root. **Rebuild planning graph** refreshes the optional projection; the saved proposal and review history remain authoritative. |

The proposal page also provides **Download consolidated PDF report** and **Export frozen modernization proposal (JSON)**. The PDF assembles static findings, selected runtime evidence, digital twin, and proposal; the JSON is machine-readable.

### Extraction sequence

This tab orders candidate domains by dependency waves and then readiness within a wave. Columns include order, domain, readiness, boundary confidence, extraction difficulty, wave, and key risk. Select a row for component scores, weights, formula, risks, blockers, sequence explanation, and unknown-database sensitivity range. Domains in a coupled cyclic group require coordinated investigation. No ordering is an execution plan or success forecast.

## 13. Evidence & digital twin

This workspace captures a versioned snapshot that binds an analysis to selected runtime sessions and evidence. The **Facts**, **Discovery**, **Graph**, and **Twin** tabs inspect that snapshot.

### Capture architecture version fields

| Field | Input and effect |
|---|---|
| Evidence application | Selects the application. |
| Evidence baseline | Selects one of its completed static analyses. |
| Version name | Human-readable snapshot label. |
| Parent version | Optional earlier snapshot used for lineage and observation comparison. |
| Completed runtime sessions | Selects completed sessions attached to this same static baseline. No selection creates static-only evidence. |
| Review domain names and membership | Optional review mode; enables name and class-membership edits before capture. |
| Domain name | Revised candidate label. |
| Domain for class | Assigns the displayed class to an existing candidate. All classes must remain assigned exactly once to a nonempty existing domain. UI preview lists the first 300 classes. |
| Domain review reason | Required explanation for reviewed changes. |
| Preview architecture version | Builds counts/fingerprint for review; does not save. |
| Save architecture version | Stores the reviewed version as a new immutable record. Existing findings/scores stay tied to the original static analysis. |

After capture, **Architecture version** selects a saved version. Version scope shows the source baseline, session IDs, rules version, projection state, and fingerprint. **Rebuild graph projection** refreshes the optional graph representation; canonical records remain saved if the projection is unavailable. **Export canonical evidence** downloads the version data. **Compare observations with parent** shows percentage-point changes in coverage measures when a parent exists.

### Version tabs

| Tab | Output |
|---|---|
| Facts | Paginated structural/observational relationships. Select **Inspect evidence** to see observation payload, collector, timestamp, confidence, and resolvable trace references. |
| Discovery | Prioritized suggestions for closing observation gaps. **Discovery update note** explains each status change; statuses are Open, Planned, Exercised, or Dismissed. Marking Exercised is a human note and does not itself increase measured coverage. History records actor/time/reason. |
| Graph | Persistent graph projection, bounded node/edge counts, optional root neighborhood, and clickable relationships. Facts is the source for complete evidence. |
| Twin | Candidate domains and counts, coverage by evidence type, telemetry quality, and explicit unknowns. Unobserved means absent from selected observations, not unused. |

## 14. Reports

Choose **Application**, **Architecture version**, and **Saved proposal**. The application selection scopes available snapshots; the proposal must belong to the selected version. **Preview report** displays an HTML review report. **Print / Save PDF** opens the browser print dialog. **Download PDF report** obtains the consolidated server-rendered report. **Export digital twin JSON** downloads structured evidence for the selected version.

The report includes an executive summary, evidence identifiers and fingerprints, domain/readiness summaries, highest-priority findings, selected-session coverage, proposal/waves, and open questions. Treat it as a confidential engineering record. Heuristic scores are not probabilities, and runtime coverage applies only to selected sessions. A report requires a captured version and saved proposal; without them the UI explains the missing prerequisite.

## 15. Source tasks

Source tasks are advanced, gated workflows. They use a pinned repository snapshot and explicit path permissions, and keep changes in a private task workspace. The original checkout is not modified. A planning approval alone does not grant repository access or approve a patch. Container builds, static re-analysis, security scans, and optional Gemini source generation depend on configured tools, policy, and human review. No merge or deployment is enabled.

### Prepare a source task

| Field | What it means |
|---|---|
| Task application | Application linked to the source task. |
| Task architecture version | Snapshot whose candidate boundary is being considered. |
| Approved planning proposal | Saved proposal with a recorded planning review. |
| Task decision | Specific domain decision to bind to the task. |
| Registered repository ID | Repository registered under Security & access. |
| Task pinned commit | Full source commit SHA to read; task is bound to this revision. |
| Task objective | Human-readable work goal. |
| Expected change | Intended outcome/constraint. |
| Snapshot files | Authorized committed files to include, one path per line (comma also accepted). |
| Files allowed to change | Explicit change scope, one path per line (comma also accepted). |
| Built artifact path | Expected output path, default `target/application.jar`. |
| Prepare isolated task | Creates a task record/private workspace if authorization and validation pass. |

### Task list and task-wide controls

The progress table shows objective, state, blocker count, validation state/freshness, and suggested next action. **Open source task** chooses a task. Task header shows state, revision, pinned commit, private branch, and whether the source snapshot is complete. **Operation or review note** (at least eight characters) accompanies supervised actions: Pause, Resume, Recheck, and Rollback. These actions are recorded; the workflow does not advance by itself.

### Task tabs

| Tab | Purpose and visible controls |
|---|---|
| Overview | Prerequisites, source file hashes, history, and task state. For a microservice candidate, a Gemini section can appear. Sending source externally requires configured Gemini, policy enablement, task prerequisites, and checking the per-request source-transfer approval box. Google receives the selected Java source/contracts. Generated output is not validated until later checks. |
| Extraction plan | **Preview extraction boundary** computes target classes/packages/source mapping, incoming/outgoing dependencies, crossing cycles, shared files, blockers, and prerequisites. It is a version-bound preview, not an executable extraction. |
| Data migration | See the data discovery and proposal fields below. |
| Contracts | Add a named behavior contract with test file, exact JUnit `Class#method`, scenario, and expected behavior. Review a contract before it is counted. Description alone is not a passing test. |
| Patch review | Create a bounded “introduce interface” recipe or manually propose a file change. Select implementation/output Java file, interface name, methods; or select allowed file, operation (Modify/Add/Delete), and replacement content. Load current content, inspect the exact diff, then approve/reject staging. Higher-risk actions require an independent authorized reviewer. |
| Builds | Run baseline or candidate build in a configured pinned isolated sandbox. Output includes test/failure/error counts and artifact hash where available. Build logs are not retained. This is not a deployment. |
| Validation | Compare baseline/candidate build, contracts, security gates, and static re-analysis. Refresh stale evidence. Review gates, contract results, fingerprints and expected static impact. Publish a candidate architecture version only when its gates pass; final approval requires a separate human security administrator with source scope. |

### Data migration fields (within a source task)

**Discover source data architecture** inspects authorized pinned source and linked runtime evidence. Results show candidate schema entities/columns/types/keys/relationships, read/write access paths, ownership hypotheses, parser coverage, provenance, unresolved questions, and limitations. Findings are facts or hypotheses with status, not confirmed ownership.

| Field/control | Meaning |
|---|---|
| Operation/review note | The task-wide note (minimum eight characters) required for the action. |
| Discover source data architecture | Runs bounded supported-source discovery; it does not connect to a production database. |
| Isolated proposal/test target | `SQLITE_TEST` enables a disposable synthetic test; `LOGICAL` creates a logical proposal without test execution. |
| Machine-checkable invariants (JSON) | Optional assertions supplied as JSON and applied to proposal/test validation. |
| Generate target schema and migration proposal | Proposes target tables, columns, mappings, conversions, alternatives, and unresolved risks from available evidence. |
| Source column to refine | Selects a proposed mapping to override. |
| Target column / Target type / Conversion | Reviewer-chosen destination name, data type, and conversion rule. |
| Reason for mapping decision | Rationale for the override; required for a new revision. |
| Save mapping as a new plan revision | Creates a new frozen proposal revision rather than editing the prior one. |
| Unresolved risk checkbox | Explicitly acknowledges a non-hard unresolved risk. Hard schema/key/type/resource blockers cannot be waived here. |
| Confirmed owner / Reason | Reviewer’s ownership decision and rationale for each resource. `SHARED` preserves a known shared boundary. These are review decisions separate from discovery evidence. |
| Approve this exact plan for synthetic testing | Binds approval to the proposal fingerprint; requires resolved hard blockers, ownership decisions, and acknowledged remaining risks. |
| Synthetic rows JSON | Synthetic fixture records only. They are submitted to an ephemeral in-memory SQLite database and not retained. |
| Run synthetic migration test | Executes only the approved plan and fixture; results list checks, counts, and recovery state. It does not validate customer database compatibility or production recovery. |

Production migration execution is not implemented.

## 16. Local setup

The **Environment checks** panel reports required local components and optional/deferred tools as Ready, Action required, Deferred, or another diagnostic state. Each check includes detail and a suggested next step. “Core ready” means configured local analysis dependencies passed their readiness checks; it is not a performance or production-readiness certification.

**What works in local mode** lists workflow availability. Docker may be optional for static analysis but required for certain isolated build or scanner workflows.

### Support bundle

**Preview included data** asks the local server for a manifest/fingerprint. Review included and excluded categories before export. **Confirm and download** sends the displayed fingerprint back and downloads a local JSON bundle. The manifest describes the bundle; the application does not upload it. **Cancel** closes the preview.

## 17. Security & access

Open this screen from the identity bar after sign-in. Sections are permission-gated: security administrators see identity, policy, repository, and grant controls; auditors see the audit trail; users with source-read permission can request authorized source context.

| Section/field | Purpose and output |
|---|---|
| Change your password | Current password verifies identity; new password (12–128 characters) replaces it and revokes other sessions. |
| New username / Identity type | Creates a HUMAN or SERVICE identity. Humans require an initial password; service credentials are generated by the server and expire after seven days. |
| Explicit permissions | Check individual permissions such as analysis read/write, runtime read/write, source read, audit read, security admin, and local-model use. Grant only what is needed. |
| Create identity | Saves identity and permissions. A service token is displayed once; copy it securely. |
| Identity list / Allow model access / Revoke | Shows active state and permissions; allow/remove local model use or revoke a different identity. Revocation invalidates its credentials. |
| Create isolated workspace | Platform-owner-only fields: workspace name, administrator username and password. Creates a separate workspace; existing data is not copied. |
| Source policy | Shows revision, max files/bytes, external-transfer default, and telemetry policy. Toggle source reads to create a new policy revision. |
| Gemini source-transfer policy | Enables/disables the external source-transfer path. Even enabled, every request needs human approval and only selected scoped source/contracts are sent to Google. |
| Source task policy | Enables/disables source tasks and isolated builds. Build use also requires an installed pinned image. |
| Application ID / Repository name / Server checkout path / Commit SHA | Registers a checkout already under the configured server source root. Use a full 40-character commit SHA. Registration does not clone or execute code. |
| Principal / Repository / Allowed paths / Protected paths | Grants exact files or directory prefixes to an identity. Protected paths take precedence. New scope replaces the prior grant for that identity/repository. |
| Request source context: Repository ID / Pinned commit / Files / Purpose | Reads only allowed committed UTF-8 files. Purpose is audited; do not put secrets in it. This operation does not contact a model. Returned source is displayed locally. |
| Audit trail / Verify audit chain | Displays recent metadata events. Verification checks the stored hash chain; it is not an independent external checkpoint. |

Management APIs require authenticated workspace permissions. This local prototype is not a claim of production SaaS hardening, SSO, customer identity-provider integration, managed key service, or comprehensive egress control.

## 18. AI gateway

The AI gateway is embedded in Security & access. The default architecture assistant remains available without an external provider. Optional local-model citation selection requires registering an installed local model, enabling it, granting the user `MODEL_USE_LOCAL`, and enabling workspace model policy.

| Field/control | Meaning |
|---|---|
| Provider name / Local model endpoint / Installed model name | Registers a locally installed model endpoint and model; the endpoint must be allowed by server configuration. Registration checks connectivity and pins a model digest. |
| Check connection / Enable provider | Verifies an existing provider or makes it selectable by workspace policy. |
| Approved model | Selects an enabled registered local provider. |
| Model context bytes | Maximum context sent to the local model (UI range 1,024–32,768). |
| Model calls per hour | Workspace invocation budget (UI range 1–120). |
| Sensitive-data policy | Redact recognized PII or block dispatch when recognized PII is present. Suspected secrets block dispatch. |
| Enable / Disable model policy | Controls local-model dispatch. Deterministic evidence answers remain available if disabled. |
| Source repository ID / Source commit / Source file / Start line / End line | Selects an authorized source range for a source question. Requires source-read scope, local-model permission, explicit grant, and enabled policy. |
| Source question / Source purpose | Question and audit rationale. Use minimum needed context; prompt and raw model output are not retained in invocation metadata. |
| Invocation history | Auditors can inspect request outcome, reason, context size, and redaction metadata, not prompt/source contents. |

Gemini source generation is a separate optional exception. It transfers the selected Java source and reviewed contracts to Google only after workspace policy and explicit per-request human approval. Review the destination and customer policy before enabling it.

## 19. Design system

The Design system page is a component catalog for UI developers and reviewers. It previews reusable interface components and visual tokens. It does not analyze a customer artifact or change workspace results.

## 20. Interpreting outputs and common terms

| Term | Plain-language meaning |
|---|---|
| Static analysis | Relationships and attributes discovered from submitted compiled Java classes. |
| Runtime observation | Telemetry received while a user runs and exercises an application. |
| Dependency edge | A directed static reference; arrows point from dependent code toward its dependency. |
| Candidate domain/module | Automatically inferred grouping for human review, not a confirmed business capability or deployment unit. |
| Strongly connected component (cycle) | A group whose members can reach one another through dependency paths. |
| Readiness | Weighted structural heuristic for ordering investigation. Not migration cost, probability, or success prediction. |
| Evidence confidence | Heuristic support for a candidate boundary/claim. Not probability. |
| Coverage | Fraction/count of static items observed in selected telemetry sessions. “Not observed” does not mean unused. |
| Blocker | Missing or conflicting evidence/check that prevents a stated planning or gated workflow step. |
| Fingerprint / hash | Identifier used to bind a result or approval to particular saved evidence/input. |
| Limit exceeded | A configured protective bound was crossed. Review the structured limit name, configured value, observed value, and suggested action. It does not itself state a tested capacity. |

## 21. Practical first walkthrough

1. Start ArchIntel and complete administrator setup/sign-in.
2. In **Applications**, select **Explore demo application**.
3. Read **Overview**, then inspect **Application architecture**, **Architecture explorer**, **Candidate domains**, **Technical debt**, and both **Dependencies** tabs.
4. Ask a question in **Architecture assistant** and open its evidence citations.
5. If you have a running Java application, create a **Dynamic analysis** session, review the instrumentation plan, configure the Java agent, exercise test workflows, and inspect coverage quality.
6. Capture a version in **Evidence & digital twin**, preview it, and save it.
7. In **Modernization**, preview a proposal, review its tabs and score formula, save it, and record a planning review note if appropriate.
8. Open **Reports** and preview/download the consolidated report or JSON evidence.

For a later open-source trial, build the selected Java project first and upload its compiled JAR/WAR or a supported compiled-output ZIP. Start with a small project, preserve its source/build version identifier, and inspect validation errors and duplicate-class disclosures before interpreting results. No capacity is implied by a configured safety limit.

## 22. Scope and limitations

- Static analysis is for compiled Java bytecode. The uploaded application is not launched or compiled by the analyzer.
- Results are bounded by archive validation, scanner availability, analysis rules, configured limits, and graph display caps.
- External dependency references can be identified structurally, but nested library contents and runtime-resolved classpaths are not necessarily analyzed.
- Architectural findings and candidate groupings are limited rule/heuristic outputs, not comprehensive security findings or confirmed business boundaries.
- Runtime evidence is optional, selected-session evidence. It depends on instrumentation choices, identity mapping, telemetry quality, and exercised workloads.
- Optional local AI and Gemini paths have separate permission/policy requirements. Gemini source generation sends selected source/contracts outside the local installation after explicit approval.
- Security scanners are optional and gated by installed tools and current databases; their coverage is limited to supported scan targets and is not comprehensive.
- Source-task, build, and data-migration workflows do not merge, deploy, or execute a production migration. Synthetic SQLite checks do not establish customer-database compatibility or recovery.
- Configured artifact and graph limits are safety bounds. Advertised capacity should be stated only as “tested up to” a value that has actually been measured under a documented end-to-end workload.

## Related documentation

- [User manual](USER-MANUAL.md)
- [Customer integration and security guide](CUSTOMER-INTEGRATION-SECURITY.md)
- [Runtime user flow](RUNTIME-USER-FLOW.md)
- [Evidence and digital twin user flow](PHASE-4-USER-FLOW.md)
- [Modernization user flow](PHASE-5-USER-FLOW.md)
- [Source task user flow](PHASE-6-USER-FLOW.md)
- [Data workflow user flow](PHASE-7-USER-FLOW.md)
- [Security architecture](ARCHINTEL_SECURITY_ARCHITECTURE.md)
