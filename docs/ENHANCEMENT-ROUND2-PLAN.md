# Enhancement round 2: plan

Written before implementation, from a read of the code at commit `be4cfff`. Baseline tests: backend 391 passed, 14 skipped, 3 failed (before any change); frontend 36 passed.

Pre-existing backend failures (environment, not caused by this round):
`test_ai_gateway.py::test_context_limit_and_pii_block_policy_send_no_bytes`,
`test_domains.py::test_cluster_consensus_deterministic`,
`test_local_diagnostics.py::test_local_setup_diagnostics_separate_core_services_from_deferred_containers`.

Implementation order (dependencies first): content-check tooling, 10, 1, 2, 12, 11, 3, 5, 7, 8, 6, 4, 9.
Item 12 supplies the percentages used by 6 and 8. Item 11 supplies readiness and confidence used by 3 and 5.

## Item 1: Runtime mapping details

**Current behavior.** `backend/app/services/runtime/graph_builder.py` `build()` calls `map_class()` for every event and stores one mapping per runtime identity in `mappings`. When `class_name` is empty the mapping has `runtime_identity=None`, `static_id=None`, evidence "Telemetry did not supply an application class identity.". `frontend/src/runtime/RuntimeAnalysis.tsx:82` renders `m.runtime_identity||'No class attribute'` and `m.static_id||'Unresolved/resource'`. Mappings are keyed by `raw or identity`, so all attribute-less events collapse into the single resource node key and the count is lost.

**Root cause.** The mapping row carries no span name, scope, kind, missing attribute names, count, sample span ids or reason. Span name and instrumentation scope are dropped in `normalization.normalize()` (not stored in the event). `map_class` returns one of EXACT/NORMALIZED/PROXY_RESOLVED/LAMBDA_RESOLVED/NESTED_RESOLVED/UNRESOLVED with no candidate or similarity. Route-based resolution does not exist.

**Files.** `services/runtime/normalization.py` (keep span `name`, scope name/version, kind), `services/runtime/mapping.py` (rule names, closest candidate and similarity, reason codes), `services/runtime/graph_builder.py` (aggregate per mapping key with counts, samples, missing attributes), `services/runtime/entry_points.py` (route to handler), `runtime/schemas.py`, `frontend/src/runtime/RuntimeAnalysis.tsx`.

**Data source.** Stored `RuntimeEvent.data` plus static `classes`/methods from the analysis result. Closest candidate uses `difflib.SequenceMatcher` over simple names, reported with its ratio.

## Item 2: Database observations with an unknown caller

**Current behavior.** `services/runtime/intelligence.py` `derive()` looks only at the immediate parent of each DB span (`by_event.get((session, trace, parent_span_id))`) and maps that parent's `class_name`. No parent, a parent without code attributes, or a parent that does not map gives `caller=None`. `RuntimeAnalysis.tsx:84` prints `d.caller||'Unknown'`, `d.resource||'Unknown'`, `d.operation||'Unknown'`.

**Root cause.** No parent-chain walk, no use of the DB span's own code attributes, no reason codes, table names only from `db.collection.name` (never parsed, and SQL text is deliberately discarded by the allowlist).

**Files.** `services/runtime/intelligence.py` (chain walk, reason codes, depth, summary), `services/runtime/normalization.py` (allow `db.statement` only for table parsing, then discard the text; keep `peer.service`/thread attributes only if already allowed), `runtime/schemas.py`, `RuntimeAnalysis.tsx`.

**Privacy note.** The current design discards SQL text. To parse table names the statement must be read in memory during normalization and only the operation and table names stored. The raw statement is never persisted. This keeps the existing guarantee shown in the UI.

**Data source.** Events of the same session and trace; static class and method index.

## Item 3: Modernization description

**Current behavior.** `modernization/engine.py` builds `decision_brief` with fixed sentences (`headline`, `next_step`, `unresolved_questions`, `ACTION[...]` text, `order_rationale`, strategy rationales). `services/modernization.py` builds `explanation=f"{name} scores {readiness}/100 from cohesion, decoupling, cycle participation and database signals."` and a generic `formula` string. The UI (`PlanningWorkspace.tsx`, `Insights.tsx`) prints those strings.

**Root cause.** Text is assembled from templates that do not name the measured value or the blocker class, and several strings are identical for every application.

**Files.** `modernization/engine.py`, new `modernization/describe.py` (pure functions that turn assessment data into sentences), `services/modernization.py`, `PlanningWorkspace.tsx`, `Insights.tsx`.

**Data source.** The assessment document: component scores, weights, cycles, boundary pairs, god classes, shared repositories, waves.

## Item 4: Assistant placement

**Current behavior.** `App.tsx` has a nav item `assistant` ("Architecture assistant") that renders `AssistantChat` in the Analyze group. Conversation state lives in the component (`useState`), reloaded from the history endpoint.

**Files.** New `frontend/src/insight/AssistantDock.tsx` (+ test), `App.tsx` (remove tab and `legacy-assistant`), `AssistantChat.tsx` (extract the conversation body, accept a context prop), `insight.css`.

**Context.** The page and selection come from `view`, `selected` (analysis) and `focusNode` already held in `App.tsx`; session selection is already a prop on the chat.

## Item 5: Planning context

**Current behavior.** `PlanningWorkspace.tsx:54` shows `context.state | rule_version | calibration_version | validation.status` and `validation.scope`. `modernization/service.context()` returns `state` and a fixed note.

**Files.** `modernization/service.py` (new `planning_context()`), `modernization/routes.py`, `PlanningWorkspace.tsx`.

**Data source.** `ArchitectureVersion` (fingerprint, manifest, counts, document coverage), `AnalysisRun.result` (summary, artifact hash, cycles, lifecycle, entry points), `RuntimeSession` rows, the previous version for the diff.

## Item 6: Report

**Current behavior.** `reports/modernization_pdf.py` (587 lines) is a hand-written PDF writer driven by `_report_lines()`; sections: executive overview, static, dynamic, plan. The HTML preview is `Reports.tsx` `ReportHtmlPreview`, built separately in the browser from several endpoints. The two do not share a data model.

**Root cause.** Two independent renderers; no single report model; generic "in everyday terms" sentences.

**Files.** New `reports/model.py` (single report model built from API data), `reports/templates` (HTML), `reports/modernization_pdf.py` (render from the model), `modernization/routes.py` (add `report.html`), `Reports.tsx` (render the server HTML or the model), `docs`.

**PDF/HTML.** The PDF stays dependency-free (existing writer). The HTML is generated server-side from the same model, so figures are identical by construction; a test also compares both with the API JSON. Diagrams: the HLD SVG already exists (`insight/diagrams.py`); it is embedded as SVG in HTML and drawn as vector shapes in the PDF writer (no raster dependency is available).

## Item 7: AI-driven modernization plan

**Current behavior.** `engine.py` has `STRATEGIES` and `strategy_rows`; the Java/framework rows say "compatibility validation is not implemented in Phase 5". `insight/lifecycle.py` + `lifecycle-rules.yaml` give per-technology status, alternative and migration notes. No target versions, no feasibility checks, no AI plan.

**Files.** New `insight/modernization_plan.py` (deterministic plan + feasibility checks), extend `lifecycle-rules.yaml` with `replacements` (candidate, target version, minimum Java, namespace change, conflicts), `insight/routes.py` (endpoints), `ai/grounded.py` use for optional wording, `PlanningWorkspace.tsx` tab, tests on the PetClinic fixture and a new aging-dependency fixture.

**Rule.** Every recommendation cites a class or rule id that exists; others are dropped. Anything outside the curated candidates is labelled "unverified, confirm before use". A review state (`PROPOSED`, `APPROVED`) gates "active plan".

## Item 8: Decision brief

**Current behavior.** `engine.build()` `result_brief` plus `validation.py`. The brief mixes data with fixed sentences (`headline`, `next_step`, `unresolved_questions`, `strategy_fit.rationale` with a `class_count <= 250` threshold).

**Files.** New `modernization/brief.py` (fact table + brief), `modernization/validation.py` (consistency check), `PlanningWorkspace.tsx`.

## Item 9: Content audit

No glossary and no content check exist today (`grep -ri glossary` finds nothing). Add `backend/app/content/banned_phrases.yaml`, `scripts/check_content.py`, `backend/tests/test_content_rules.py`, `docs/CONTENT-AUDIT.md`. The check scans `frontend/src/**/*.tsx` string literals, `backend/app/**/*.py` string literals in templates, `docs/*.md`.

## Item 10: "Explain why" button

**Current behavior (found).** `PlanningWorkspace.tsx:59-60`: every button renders `disabled={busy}` and calls `action()`, which sets the single component-level `busy` flag and the single `explanation` state. Clicking one button disables all of them (looks like all were triggered), and the result is rendered once below the whole list, not under the clicked item, so the user sees "no output" next to the item.

**Same pattern elsewhere.** `AiExplain` is used by `TechnicalDebt.tsx`, `Cycles.tsx` and `TechnologyLifecycle.tsx`; its state will be checked in the same pass.

**Files.** `PlanningWorkspace.tsx` (per-item state keyed by decision id), `modernization/service.answer()` (return rule id, measured values, thresholds, classes/edges, evidence ids), `PlanningWorkspace.test.tsx` (new, failing test first).

## Item 11: Domains, readiness and confidence

**Hard-coded values found** (see `ENHANCEMENT-ROUND2-STATUS.md` for replacements):
- `services/modernization.py:12` `db_score = 25.0 / 65.0 / 45.0` (45 stands for "unknown").
- `services/modernization.py:15` `cohesion ... else 50.0` when cohesion is unmeasured.
- `services/runtime/intelligence.py:65` `persistence=25 if shared else 50` (50 stands for "unknown").
- `modernization/engine.py:159-161` `behavioral_validation=0`, `data_ownership=0` counted as measured zeros inside the confidence sum, plus fixed weights.
- `modernization/engine.py:149` `.6/.4` combine weights; `:185` effort band cut-offs; `:315-318` "20% reduction" targets; `:319` `class_count <= 250`.
- `services/domains.py:730` confidence weights `0.5/0.3/0.2` and `size_factor = len/8`.

**Files.** `services/modernization.py`, `services/runtime/intelligence.py`, `modernization/engine.py`, new `modernization/scoring.py` (readiness and confidence with excluded inputs), `Insights.tsx`, new `frontend/src/Glossary.tsx`.

## Item 12: Technical problems with percentages

**Current behavior.** `insight/debt.py` returns counts per severity and per rule (`by_rule`) but no percentages and no denominators; `TechnicalDebt.tsx` shows counts.

**Files.** New `insight/debt_rates.py` (per-rule denominator definitions and counts), `insight/routes.py` (`/debt` adds `rates`), `TechnicalDebt.tsx` (percentage list, click to list classes), glossary entries, tests with hand-computed values on the PetClinic fixture.

## Cross-cutting

- `NOT MEASURED` convention: `{value: null, reason: str}` in API payloads, rendered as "not measured: reason".
- Banned phrase list in `backend/app/content/banned_phrases.yaml`; one loader shared by the test and the script.
- Commits: one per item, test results recorded in `ENHANCEMENT-ROUND2-STATUS.md`.
