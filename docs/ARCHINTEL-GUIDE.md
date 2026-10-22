# ArchIntel: the full flow, screen by screen

ArchIntel takes a compiled Java application and turns it into an evidence-backed modernization plan, and optionally
into a locally tested microservice. Every conclusion is traceable to evidence from the code (static analysis), from
running the application (dynamic analysis), or from a human review.

This guide explains the end-to-end flow first, then what each screen and tab does, in sidebar order.

---

## 1. The flow at a glance

```
 Sign in ──► Applications ──► Static analysis ──► Analyze pages (Overview … Dependencies)
                 │ upload JAR/WAR/ZIP     (bytecode only, never executed)
                 ▼
          Dynamic analysis ── manual session (OpenTelemetry agent)  or  Explore automatically (REA)
                 │ completed runtime sessions
                 ▼
     Evidence & digital twin ── capture an Architecture version (code + sessions + domain review)
                 │ a frozen, fingerprinted snapshot
                 ▼
          Modernization ── Preview → Save plan → Review: APPROVED_PLANNING
                 │
      ┌──────────┼──────────────────────────────┐
      ▼          ▼                              ▼
   Reports   Conversion trial (Claude/Gemini)   Source tasks (supervised source change)
   PDF/HTML  generate → Docker build → REA      contracts, patches, isolated builds,
             compare → Move to production       validation, final approval
             (hand-off package, never deploys)
```

| Step | Screen | You get | Needed for the next step |
|---|---|---|---|
| 1 | Applications | An application with an uploaded artifact | Static analysis |
| 2 | (Progress page) | A completed static analysis | All Analyze pages, the assistant, Dynamic analysis |
| 3 | Dynamic analysis | Completed runtime sessions (spans, coverage) | Optional, but raises plan confidence; required for the conversion trial |
| 4 | Evidence & digital twin | An architecture version | Modernization, Reports, Source tasks |
| 5 | Modernization | A saved plan, then an approval | Reports (saved plan); conversion and Source tasks (approved plan) |
| 6a | Modernization → Conversion | A generated, locally running service and a verdict | Hand-off package |
| 6b | Source tasks | A validated, approved source change | Your own CI/CD |
| 7 | Reports | PDF / HTML report, JSON evidence exports | — |

The **workflow strip** at the top of every page (after an analysis is selected) shows these six steps — Upload,
Static analysis, Runtime evidence, Review architecture, Modernization proposal, Report — with their state, and a
**Next recommended action** button that opens the right screen.

---

## 2. Around every screen

- **Sign in** — on first run ArchIntel asks for the one-time setup key (`.data/security-bootstrap.key`) to create the
  administrator; afterwards it asks for username and password.
- **Access bar** (dark top strip) — your username, **Security & access** (toggles with **Back to analysis**), **Sign out**.
- **Top bar** — sidebar toggle, breadcrumb, **Search (Ctrl K)** command palette to jump to any screen, service status
  (**Services ready**). On Analyze pages also **Select analysis** and **Export analysis** (JSON).
- **Ask** (bottom right, Ctrl /) — the Architecture assistant. Answers questions from the selected analysis with
  citations; works without an AI model. Its context chip follows what you selected on the page (a class, domain,
  finding or runtime session).
- **Optional AI blocks** — "Generate" / "Add AI wording (optional)" buttons on several screens use a *local* model
  configured in Security & access → AI gateway. Without one, they explain why they are unavailable.
- **Help & documentation** (sidebar bottom) — quick start plus the downloadable User manual and Developer guide.

---

## 3. Portfolio

### Applications (home)
**Purpose:** start here; upload applications and see their status.

- **Analyze application** — opens the upload dialog: project (existing or new), application name, version and the
  file (**JAR, WAR, or project ZIP with compiled `target/classes` or built JARs**; source-only ZIPs are not supported;
  up to 100 MB). **Start architecture analysis** creates the application, uploads, validates and starts the analysis.
- **Explore demo application** — loads the Northstar Commerce sample; **Download sample JAR** gives you the file.
- **Application cards / table** — status, latest analysis, classes/packages, readiness/confidence, runtime class
  coverage. Click a card to open its Overview.
- **Baseline drift and coverage gaps** — appears once an application has two completed analyses; compares classes,
  dependencies, domains, findings and readiness between a Baseline and a Candidate analysis.
- **Progress page** — while analysis runs, every Analyze page shows the stages (validating, scanning, graph
  extraction, cycles, metrics, domain discovery, issues, modernization, persisting). The application is never executed.

---

## 4. Analyze (static analysis results)

All Analyze pages need a **completed analysis** selected in the top bar.

### Overview
**Purpose:** one-page summary and where to begin.
- KPI tiles: classes, packages, dependencies, candidate domains, high-severity findings, cyclic groups.
- **Your domain map** (click to open the explorer), **Where should you begin?** (readiness score and the first
  business candidate to investigate), **Technical debt by severity**, **Domain size distribution**, **Top risks**,
  **Hotspot classes**, **Blockers**, and **Evidence you can inspect** (scanner, artifact SHA-256).

### Application architecture
**Tabs:**
| Tab | Shows |
|---|---|
| High-level (HLD) | Layers, entry points and external systems; expand packages; click a box or arrow for details |
| Low-level (LLD) | Classes of a chosen package, their roles, database tables; click ▶ on an entry method for its **sequence diagram** |
| Candidate-domain blueprint | Candidate modules and their layers; views Dependencies / Modernization waves / Before-after; colour by debt, coverage or wave |

Every diagram can be zoomed and exported (SVG, PNG, PDF, Mermaid).

### Architecture explorer
**Purpose:** navigate the dependency graph interactively.
- Packages / Classes level, search, filters (role, debt, in a cycle, minimum references).
- Click a node for its detail panel (what it is, depends on / depended on by with **why?**, methods, entry points,
  debt, aging technology, libraries). Double-click a package to drill in; click an edge for its explanation.
- **External and unresolved** table lists references outside the application.

### Candidate domains
**Purpose:** the business boundaries ArchIntel discovered — the future service candidates.
- Table or cards: classes, readiness, static boundary evidence, blockers.
- Click a domain for the readiness breakdown (each input, weight, and how to raise it), why the boundary exists,
  database signals, dependency profile, blockers and classes.
- Names and membership are corrected later, on **Evidence & digital twin** (domain review).

### Responsibilities
**Purpose:** what each class does and which concerns it carries.
| Tab | Shows |
|---|---|
| Components | Every class with its functional responsibility, non-functional concerns, status and confidence; filter and open a class |
| Capabilities | Per-domain capabilities and what they mean for modernization |
| Cross-cutting | Shared components and libraries used across domains |
| Risks | Risk indicators by category and severity, with consequence and "Investigate" |
| Method and limits | The taxonomy, confidence levels and what the labels do not prove |

### Technical debt
**Purpose:** rule-based findings with the measured value and threshold.
- Problem rates (whole application / per domain / per package), **Debt by package** index.
- Findings table: severity, class, rule, measured vs threshold, plain-language explanation, suggested fix; expand a
  finding for technical detail, evidence and an optional AI refactoring proposal.

### Technology lifecycle
**Purpose:** which libraries and frameworks are end-of-life or aging, and where they are used.
- Filter by status; each technology shows the version found, affected classes and call sites, the recommended
  alternative and an effort hint.

### Dependencies
| Tab | Shows |
|---|---|
| Circular dependencies | Class- and package-level cycles, loop diagrams, and which dependency to cut first |
| Architecture metrics | Coupling/instability/abstractness per package or class, worst offenders, the A-vs-I scatter plot, and each metric's formula |

---

## 5. Runtime

### Dynamic analysis
**Purpose:** observe the application while it runs, so the plan knows which code is really used.
Needs a completed static analysis (the *baseline*).

**A. Explore automatically (REA)** — the hands-free way.
- Requires the local runner (`./scripts/runner-start.sh`); the panel shows **Runner ready** with Java, Chrome,
  OpenTelemetry agent, REA and Docker versions.
- Upload a **runnable JAR/WAR**, set **Most pages** / **Most forms**, choose **Instrumentation** (Deep recommended),
  confirm the copy uses a disposable test database, then **Start exploration**.
- The runner starts the application with the OpenTelemetry agent, REA visits pages and submits forms with synthetic
  values, then stops it. Steps, routes observed, forms, class coverage and spans are listed; anything not covered is
  explained. The result is an ordinary completed runtime session.

**B. Create an observation session** — the manual way.
- Choose application, static baseline, name, environment, instrumentation depth (Boundary / Standard / Deep), package
  prefixes and telemetry binding. **Preview instrumentation plan**, then **Create runtime session**.
- **Connect your Java application** shows the environment variables and launch command (the token is shown once).
  Use the application yourself, then **Stop** the session.

**C. Runtime sessions** table — Start, Stop, New token; tick one or more sessions to view their evidence.

**D. Evidence tabs** (for the ticked sessions):
| Tab | Shows |
|---|---|
| Coverage | Observed vs unobserved classes, entry points, methods, dependencies, domains; evidence quality |
| Next tests | Ranked untested entry points with expected coverage gain and a sample request |
| Performance | Latency per entry point (p50/p95), slowest code, DB calls per request, time per domain |
| Graph | Unified / runtime-only / static graph at domain, package or class level |
| Mapping | Which runtime identities matched static classes, and which did not |
| Flows | Observed request groups |
| Database | Observed persistence signals |
| Modernization | Structural, runtime and combined readiness per domain |
| Assistant | Ask a question about the first selected session |

**Export evidence** downloads the runtime report JSON.

---

## 6. Evidence

### Evidence & digital twin
**Purpose:** freeze the evidence into an **architecture version** — the snapshot every plan and report cites.

**Capture a new version** (three steps)
1. **Choose the evidence** — application, static baseline, version name, parent version, and the completed runtime
   sessions to include (none = static-only version).
2. **Review domain boundaries (optional)** — rename domains and drag classes between them, with a reason. This is the
   human domain review (workflow step 4).
3. **Preview architecture version**, then **Save architecture version** (only after previewing the same inputs).

**Version summary**
- **What this version tells you** — a plain verdict on coverage against the plan's target (80% class coverage by
  default) and the next step.
- **What this version contains** — baseline, sessions, rules; **Rebuild graph projection**, **Export canonical evidence**.
- **Compare with an earlier version** — coverage, domain changes, dependencies and suggestions between two versions.

**Tabs**
| Tab | Shows |
|---|---|
| What we know | Every dependency fact, classified as confirmed by code and runtime / code only / runtime only; **Inspect evidence** shows its provenance |
| What is missing | **What would improve this plan** (unmet conditions, per-domain gaps, best next flows to exercise) and **Guided runtime discovery** suggestions you can mark Planned / Exercised / Dismissed |
| How it connects | The persistent knowledge graph around a chosen node |
| What it means | The digital twin: domains, coverage by domain, telemetry quality, unknowns, and **Current and proposed architecture** (today's domains next to the services of the saved plan) |

To raise coverage: exercise the suggested flows (manually or with Explore automatically), then capture a new version.

---

## 7. Plan

### Modernization
**Tabs:** **Proposal workspace** (default) and **Extraction sequence** (the order in which candidate domains could be
extracted, with readiness, difficulty, wave and key risk).

**Proposal workspace**
1. **Create planning proposal** — application, architecture version, **Target strategy** (Modular monolith,
   Microservices, Hybrid, Cloud refactor, Java upgrade, Framework upgrade) and objective.
   **Preview modernization plan**, then **Save modernization plan**. No source is changed.
2. **Planning context** — every fact the plan used (version fingerprint, artifact hash, coverage, sessions) and what
   it does not take into account.
3. **Saved planning proposal** — pick a plan; **Proposal status** with PDF and JSON exports.

**Plan tabs**
| Tab | Shows |
|---|---|
| Decision brief | The plan in prose, every number backed by a fact-table row, options compared |
| Technology plan | Phased upgrades: current → recommended technology, why, affected classes, steps, risks, feasibility checks |
| Microservice modernization | (Microservices plans) the candidate services, each with its boundary, dependencies, data signals, blockers and required setup; **Prepare this service task**; and the **Conversion trial** |
| Decisions | Each evidence-backed decision; **Explain why** shows the rule, measured value vs threshold and evidence |
| Readiness & confidence | Structural, runtime and combined readiness and confidence per domain |
| Target & waves | Target architecture, proposed interfaces, and extraction waves with entry/exit criteria |
| Review | **Record planning review**: Approved planning / Changes requested / Rejected, with a note. Approval agrees with the plan only — it does not approve code changes or deployment |
| Graph | The decision evidence graph |

### Conversion trial (inside Microservice modernization)
**Purpose:** let an AI model regenerate one candidate as a standalone service, run it locally next to the original,
and check that it behaves the same.

1. Pick the candidate (e.g. **Vet**) and the **Model provider** (Anthropic Claude or Google Gemini).
2. The **Conversion checklist** must be all *Met*: approved plan on the latest version, a business (not technical)
   domain, source-task policy, the provider's source-transfer policy, the provider's API key, the daily cap, a
   registered repository at a pinned commit with your file grant, a completed automated exploration, and the runner.
3. Choose the **Source repository**, tick the consent ("I approve sending the selected source … for this one
   generation"), and click **Convert with Claude/Gemini**.
4. Steps run in order: check gates → select source inside your grant → generate the service → build and start it in
   Docker (hardened, local port only) → start the original → **replay the recorded REA scenarios on both** → stop the
   original.
5. **Verdict:** *Every replayed scenario behaved the same* / *Some behaved differently* / *No recorded scenario covered
   this candidate*. You can open the running service, read every generated file with its rationale, the model's open
   questions, the source that was sent, the build log, and the token usage.
6. **Move to production** — record **Approve for hand-off** or **Reject** with a note (differences must be confirmed
   as reviewed when the verdict is not equivalent). After approval, **Download hand-off package**: generated source,
   the build recipe (Dockerfile), Kubernetes and Compose manifests with placeholders, and `PROMOTION.md` checklist.
   **ArchIntel never deploys**; production goes through your own pipeline.

See `docs/CONVERSION-RUNBOOK.md` for setup, live tests and cost controls.

---

## 8. Deliver

### Reports
**Purpose:** the shareable output.
- Choose application, architecture version and saved proposal.
- **Preview report**, **Download PDF**, **Download HTML** — a 10-section report, each section with an *In plain terms*
  summary and the technical detail.
- **Export digital twin JSON** — needs only a version.

### Source tasks
**Purpose:** a supervised, auditable source change for one decision of an approved plan, in a private workspace.
Needs: an approved plan, and in Security & access a registered repository, a file grant and *source tasks* enabled
(isolated builds also need the local sandbox).

- **Prepare a source task** — version, approved plan, decision, repository, pinned commit, objective, expected change,
  snapshot files, files allowed to change. (Opened pre-filled by **Prepare this service task** in Modernization.)
- **Supervised progress** — task list with state, blockers and next action; Pause / Resume / Recheck / Rollback with a note.

| Task tab | Does |
|---|---|
| Overview | Prerequisites and history; for service candidates, **generate the selected service with Gemini** into a local repository |
| Extraction plan | Preview the module boundary: mapped files, cross-boundary dependencies, blockers |
| Data migration | Discover the source data model, propose a target schema and migration, confirm ownership, run a synthetic migration test |
| Contracts | Behavioural contracts (JUnit test + expected behaviour) and their review |
| Patch review | Generate an interface recipe or propose a manual patch; inspect, approve and stage it |
| Builds | Isolated baseline and candidate builds |
| Validation | Java security scan, architecture re-analysis and comparison, expected-improvement check, publish the candidate version, final approval by a second administrator |

---

## 9. Settings and support

### Local setup
Environment checks (each with a next step), what works in local mode, and a **local support bundle** you preview
before download (no source, secrets or customer data).

### Design system
The interface catalogue (components, data states, accessibility). For reference only.

### Security & access (from the access bar)
| Section | Does |
|---|---|
| Change your password | Changes it and signs out your other sessions |
| People and service identities | Create people or service accounts with explicit permissions (ANALYSIS_*, RUNTIME_*, SOURCE_READ, AUDIT_READ, SECURITY_ADMIN, MODEL_USE_LOCAL); revoke; allow or remove local model access |
| Source policy | Enable/disable source reads |
| Gemini / Claude source-transfer policy | Separate switches allowing selected source to be sent to Google or Anthropic; each request still needs human consent |
| Source task policy | Enable source tasks; enable isolated builds |
| Register a pinned source checkout | Application, name, server path (e.g. `/app/sources/spring-petclinic`), full commit SHA |
| Grant repository scope | Which files an identity may read (e.g. `pom.xml, src/main/`); protected paths always win |
| Request source context | Read granted files at a pinned commit, with an audited purpose |
| AI gateway | Register a local model (Ollama), set the workspace model policy and budget, ask about an authorized source range, model history |
| Audit trail | The tamper-evident event log and **Verify audit chain** |

---

## 10. Quick recipes

**First analysis:** Applications → Analyze application → upload JAR → wait → Overview.

**Raise runtime coverage:** Dynamic analysis → Explore automatically (Deep) → Evidence → capture a new version with
the session → check *What this version tells you*.

**Get a report:** Evidence (capture a version) → Modernization (preview, save) → Reports → Download PDF.

**Convert a service locally:** Security & access (enable source tasks and the provider's transfer, register the
repository, grant files) → Modernization → save a Microservices plan → Review: Approved planning → Microservice
modernization → pick the candidate → Convert → review the verdict → Move to production → Download hand-off package.
