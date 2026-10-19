# ArchIntel enhancement plan (WP1–WP11)

Status: plan written before implementation on branch `enhancements/evidence-driven-ui`.
Scope: Java only. Every user-visible statement must come from graph, bytecode, runtime or rules-file data.

## Baseline (before any change)

| Suite | Result |
|---|---|
| Backend `pytest backend/tests` (Python 3.13 venv) | 281 passed, 2 failed, 14 skipped |
| Frontend `vitest run` | 8 files, 14 tests passed |

The two backend failures are pre-existing and environment related:
`test_local_setup_diagnostics_...` needs the Windows `.runtime` Java/jQAssistant bundle (no Java runtime on this
machine), and `test_context_limit_and_pii_block_policy_send_no_bytes` expects the evidence envelope to exceed
1024 bytes, which is not the case for the fixture on this platform.

## Cross-cutting finding that shapes every package

The scanner export (`backend/scanner-java/ExportGraph.java`) returns, per class: FQN, labels, method/field
counts, annotation *types* and method name/signature/annotation types; and class-to-class edges of 8 types.
It does **not** export:

* annotation values (so every route is `http_method='UNKNOWN', path='UNKNOWN'`),
* bytecode size per method, access flags (synthetic / bridge / static), field names,
* call sites (which method calls which method),
* deprecation markers, inner-class ownership, class-file version per class.

jQAssistant needs a JDK, which is not available in this environment, so the exporter cannot be
re-verified here. Instead a **pure-Python class-file reader** (`app/insight/bytecode.py`) runs in the
existing pipeline on the already extracted, validated `classes/` directory (no customer code is loaded or
executed). It produces bounded "bytecode facts" stored in the snapshot under `result['bytecode']`.
All new analysis is computed from snapshot + bytecode facts + optional runtime evidence by pure functions in
`app/insight/`, exposed by `app/insight/routes.py` under `/api/v1/analyses/{id}/insight/...`.
Snapshots that predate bytecode facts degrade to "not available — this analysis predates bytecode facts; run
a new analysis".

Fixture: a compiled Spring PetClinic (real class layout and routes of spring-petclinic 3.x, compiled against
minimal annotation/interface stubs so bytecode carries the genuine annotation descriptors and values) plus an
`edgecases` package (scheduled/listener/servlet/filter/lambda/inner/bridge/overload cases). Compiled `.class`
files are committed under `backend/tests/fixtures/petclinic_classes/` so tests do not need Java; the source
and build script are committed next to them.

## WP1 Aging framework detection

* Current: `services/tech_stack.py` detects Java target majors, Spring Boot version from manifest/POM/jar names,
  javax/jakarta *counts*; lifecycle fields are hard-coded `NOT_CHECKED`.
* Change: `app/insight/rules/lifecycle-rules.yaml` (versioned, dated, per-rule source URL / last-reviewed /
  status / alternative / migration notes / effort hint); `app/insight/lifecycle.py` matches rules against
  (a) dependency metadata and bundled jar names, (b) class-file major versions, (c) package usage from external
  edges and bytecode call sites (class + method + line). Replaces `NOT_CHECKED` with `EVALUATED` or
  `NOT_AVAILABLE` + reason. Rules freshness is computed from `reviewed` and a configurable max age.
* UI: new "Technology lifecycle" page.
* Optional AI: per class group migration note via gateway (`purpose=MIGRATION_NOTE`), labelled and cited.
* Data: bytecode call sites, dependency inventory. Risk: rules go stale (warned in UI); version unknown when
  parent-managed (shown as "version not determinable", never guessed). Labels are "end-of-life / aging",
  never "vulnerability".

## WP2 Application architecture (HLD/LLD)

* Current: `ArchitectureBlueprint.tsx` reuses Cytoscape at domain/package level and a regex-on-name layer guess;
  Mermaid only as text.
* Change: `app/insight/roles.py` (role from annotations first, then naming/structure, with the reason);
  `app/insight/diagrams.py` builds HLD (layers + external systems, edges labelled with static dependency counts
  and runtime call counts) and LLD (per package/domain: classes, roles, entry methods, call flow, entities;
  sequence diagram from runtime traces or, when absent, static call sites labelled "static"). Mermaid export
  stays as a secondary format. Frontend: `diagram/` SVG renderer (layered layout, zoom/pan, click → detail
  panel, legend, "how to read", export SVG/PNG/PDF), aggregation with expand-on-demand.
* Risk: role inference on unannotated code → shown as "role unknown" with reason.

## WP3 Explorer node details

* Current: inspector shows raw metric keys.
* Change: `app/insight/details.py` → `/insight/node?id=` returns role+reason, size, dependencies/dependents
  with counts and edge types, the class-to-class references behind each package edge, cycles, entry points,
  runtime coverage, debt + aging findings, deterministic summary paragraph. Explorer gets search, filters
  (role, coverage, debt, cycle), breadcrumb, readable labels with FQN on hover.

## WP4 Technical debt

* Current: `services/issues.py` percentile rules with generic text ("This class is a coupling outlier").
* Change: `app/insight/debt.py` with documented rule ids and absolute thresholds
  (`rules/debt-rules.yaml`): god class, high coupling, cycle membership, layer violation (caller & callee named),
  large method (bytecode length), too many dependencies, entity in controller, static mutable state,
  deprecated API usage, aging framework usage (WP1), unobserved at runtime. Each finding: measured vs threshold,
  technical + plain-language text, evidence, suggested action, node link. Package summary with the formula
  shown; effort is a labelled heuristic index with inputs. Existing `issues` remain (other pages depend on them).

## WP5 Architecture metrics (replaces Quality)

* Current: package Ca/Ce/I/A/D only, shown as a scatter.
* Change: `app/insight/metrics.py` per package and class: Ca, Ce, I, A, D, fan-in/out, cycle count/size, layer
  violations, size, bytecode complexity (sum of method code length, max method length, branch instruction
  count); each metric with formula, inputs (class lists), plain meaning, threshold indicator; worst offenders.
  Tests with hand-computed values on a small fixture graph.

## WP6 Circular dependencies

* Current: SCC + bounded `simple_cycles`, members only, generic "Changes may propagate" text.
* Change: `app/insight/cycles.py`: SCCs at class and package level (self-loops reported separately), ordered
  cycle paths, per-edge evidence (edge types from typed edges, call sites `A.m() → B.n()`, field names from
  bytecode, source static/runtime), crossing packages/layers, cut-edge ranking (weight, runtime calls, direction
  vs layering, cycles broken) labelled "suggestion – requires human review", two-layer template explanations,
  small per-cycle diagram. Fixtures: 2-class, 3-class, package-level, overlapping, self-loop.

## WP7 Assistant

* Current: keyword-routed fact selection; the model may only *select* fact ids.
* Change: `app/insight/assistant/`: tool registry (get_package, get_class, get_dependencies, get_dependents,
  get_cycles, get_debt_findings, get_runtime_coverage, get_entry_points, get_aging_findings, get_class_source,
  search_classes, get_metrics) scoped to tenant/analysis; deterministic planner for the no-model mode;
  optional model loop through the existing gateway (policy, sanitisation, audit, local-only enforcement) where
  the model requests tools and writes an answer citing evidence ids; citation verifier removes/flags unknown
  ids and class names; per-analysis conversation memory, NDJSON streaming, rate budget and cache.
  Source store (`app/insight/source_store.py`): bounded, tenant-scoped per analysis, holds `.java` entries found
  in the artifact or a deterministic bytecode outline; deployment switch `source_store_enabled`.
  Evaluation harness with ≥30 PetClinic questions and a hallucinated-class check; pass rate reported.

## WP8 Suggested next tests

* Current: fixed sentence "Exercise a representative request…" for every unobserved item.
* Change: `app/insight/test_suggestions.py`: from routes (composed class+method paths), parameter types,
  validation annotations, static call graph reachability; outputs entry point, exercised classes/methods,
  user action, sample request, preconditions, expected coverage gain; ranked; marked done when a later session
  observes it. Optional AI step for human action steps and edge cases, labelled and cited.

## WP9 Extraction bug inspection

* Audit scanner normalisation, entry-point detection and mapping against the compiled fixture; each bug gets a
  failing test first, a fix and an entry in `docs/BUGS-FOUND.md`.

## WP10 Remove the Quality tab

* The "Quality" tab exists in Dynamic analysis (`RuntimeAnalysis.tsx`, telemetry quality) — it is backed by the
  `quality` field of the runtime evidence response, which Evidence/digital twin also uses. Remove the tab only;
  keep the backend field (other consumers depend on it) and move its content into the Coverage tab as
  "Evidence quality". Old metrics content moves to the new Metrics page (WP5).

## WP11 Graph representation

* Change: `app/insight/unresolved.py` classifies external/unresolved nodes (external library, JDK, runtime-only,
  generated/proxy, unmatched) with first reference; graph endpoint adds per-node/edge explanations, edge type
  counts and source; "External and unresolved" collapsible cluster; legend; "What am I looking at?" panel;
  layered layout by role, package clustering otherwise, adjustable edge-weight threshold, neighbourhood
  highlight.

## Risks / limits recorded up front

* jQAssistant scanning could not be executed here; scanner changes are covered by unit tests on the Python
  normalisation layer, and the Python bytecode reader is verified on real compiled classes.
* No decompiler is bundled; the source store holds real `.java` sources only when the artifact contains them,
  otherwise a bytecode outline clearly labelled as such.
* AI features are tested with a fake Ollama adapter (as the existing gateway tests do); no external model is
  ever called by default.
