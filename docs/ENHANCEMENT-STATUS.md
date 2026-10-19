# Enhancement status (WP1–WP11)

Branch `enhancements/evidence-driven-ui`, one commit per work package (plus the shared foundation commit).
Plan: `docs/ENHANCEMENT-PLAN.md` · Defects found: `docs/BUGS-FOUND.md` · Reference: `docs/INSIGHT-REFERENCE.md`.

## Test results

| Suite | Before (baseline, this machine) | After |
|---|---|---|
| Backend `pytest backend/tests` (Python 3.13) | 281 passed, **2 failed**, 14 skipped | 392 passed, **2 failed**, 14 skipped |
| Frontend `vitest run` | 8 files / 14 tests passed | 16 files / 36 tests passed |
| `tsc --noEmit`, `vite build` | not run | pass |

The same two backend tests fail before and after and were not caused by this work:
`test_local_setup_diagnostics_…` needs the Windows `.runtime` Java/jQAssistant bundle, and
`test_context_limit_and_pii_block_policy_send_no_bytes` expects the evidence envelope to exceed 1024 bytes, which it does not here.
New tests: 11 backend files (≈ 100 tests: reader, roles, routes, lifecycle, cycles, metrics, debt, graph/details, diagrams,
next tests, extraction audit, assistant, API end-to-end incl. the real Northstar demo jar) and 7 frontend files rendering the
real backend output for the fixtures.

Assistant evaluation (`backend/tests/evaluation/`, deterministic mode, PetClinic fixture):
**39/39** questions passed, 0 answers with unknown identifiers or non-existent citations. The first run was 35/39; the failures
exposed five planner defects (route lookup, entity-in-controller intent, source lookup without config, external names in
evidence text), which were fixed. A second set of 12 paraphrases written afterwards scored **6/12** on first contact and 12/12
after general fixes (direction of "uses/relies on", acronyms, plural role words, fuzzy route keywords). Because those failures were
then used to fix the planner, that set is no longer held out; expect lower rates on unseen phrasing — the planner is keyword-based.
Model mode was exercised only with a scripted stand-in for Ollama (no model is available here).

## Per work package

| WP | Status | Tested | Remaining / caveats |
|---|---|---|---|
| 1 Aging frameworks | **DONE** | rules file validity, version ranges, freshness, edge-case fixture (Log4j 1, javax.persistence/servlet, JAXB, Commons Lang 2, Struts) with class + call-site lists, dependency-metadata versions, AI note verification; vitest on the page | The YAML dates and support statements are compiled from the cited public sources as of 2026-10-19 and **must be re-verified** (the stale-rules banner exists for this). Not covered: Hibernate/Spring versions resolved only through parent POMs (reported as "version not determinable"). |
| 2 Architecture diagrams | **DONE** (renderer verified in jsdom only) | HLD/LLD/sequence models on PetClinic and edge cases; layout geometry, expand-on-demand, Mermaid text, PDF structure, click → shared detail panel | **Not verified visually or in a real browser** (no browser tooling was run): pan/zoom feel, PNG/PDF export through canvas. Layout is a fixed layered layout; very large layer/edge counts are aggregated, not auto-routed around obstacles. Mermaid is exported from the HLD only. |
| 3 Explorer details | **DONE** | node/package/class/method details, connections, filters, breadcrumb, summary paragraph | Method-level runtime coverage is shown only through the next-tests view. |
| 4 Technical debt | **DONE** | each rule on fixtures, measured vs threshold, grouping, AI verification | Thresholds are conservative defaults in `debt-rules.yaml`, not calibrated to a corpus. "Deprecated API" covers `@Deprecated` application members and a short JDK list. Old percentile issues remain in the snapshot for Overview/planning pages. |
| 5 Metrics | **DONE** | hand-computed expectations on a 5-class fixture; bytecode sizes from real class files | — |
| 6 Cycles | **DONE** | 2-class, 3-class, package-level, overlapping, self-loop/nested, runtime-only edge | Cycle lists are bounded (membership is complete). |
| 7 Assistant | **PARTIAL** | tools, verifier (citations, identifiers, numbers), streaming, memory, budgets, refusal, model loop with a scripted model, fallback, 39+12 evaluation questions | **No decompiler**: the source store holds only `.java` entries present in the artifact; otherwise a labelled bytecode outline. Model mode was never run against a real model. Rate limiting is per user per hour; there is no token-level accounting beyond the existing policy limits. "Human approval for code changes" is enforced by having no mutating tool and refusing such requests. |
| 8 Next tests | **DONE** | routes, params, constraints, preconditions, greedy gain on PetClinic; done-marking via observed handlers; AI step | Handler-level "done" needs retained spans; otherwise falls back to class-level and says so. Gain is an upper bound from static reachability. |
| 9 Bug inspection | **PARTIAL** | 9 defects fixed with failing-first tests (see BUGS-FOUND) | **jQAssistant could not be run here**, so its Cypher export was not audited on real stores; listed risks are in BUGS-FOUND. |
| 10 Quality tab | **PARTIAL** | tab removed, content moved to Coverage → Evidence quality, e2e spec and guide updated | "Quality" was interpreted as the Dynamic-analysis telemetry-quality tab (the only tab with that name; the backend `quality` field stays because the evidence/digital-twin view uses it). The old Metrics tab content is replaced by WP5. **Screenshots were not regenerated** (`docs/screenshots/phase3-runtime-quality.png` is stale); the Playwright e2e was edited but not run. |
| 11 Graph representation | **DONE** (no edge bundling) | classification of unresolved names, runtime-only/proxy/unmatched, shown-vs-total/hidden messages, legend, adjustable edge threshold, neighbourhood highlight, layered layout | Edge bundling was not implemented; the user-adjustable threshold covers clutter. |

## Cross-cutting criteria

* **Evidence on every statement** — met for all new pages; each finding links to explorer nodes. Pre-existing pages (Overview, Candidate domains, Modernization, Evidence & twin, Reports, Source tasks) were **not** reworked, and their text may contain statements that predate this work (the generic cycle issue text and generic "exercise another entry point" strings were replaced).
* **Plain-language layer on every page** — present on all new/rewritten pages (lifecycle, debt, cycles, next tests, explorer detail, assistant). **Not** added to the untouched pages above.
* **Smoke test per page** — vitest renders each new page against real fixture output. Playwright smoke tests were not added or run (no browsers were driven in this session).
* **Documentation** — `INSIGHT-REFERENCE.md` (rules formats, metric formulas, assistant tools, AI data flow per mode), `.env.example`, `BUGS-FOUND.md`.

## Other changes worth knowing

* `scanner_engine=bytecode` analyses uploaded artifacts without a JDK/jQAssistant (class files are parsed as data only).
* Application scoping fix: classes under an external prefix (e.g. `org.springframework.samples.petclinic`) are kept when they carry application stereotypes.
* Migration `0010` adds `assistant_messages`; the migration-version assertion in `test_foundation.py` was updated.
* New settings: `scanner_engine`, `bytecode_facts_enabled`, `bytecode_facts_max_bytes`, `source_store_mode`, `insight_ai_mode`, `assistant_*`, `lifecycle_rules_max_age_days`.
