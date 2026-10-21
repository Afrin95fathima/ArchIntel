# Insight layer reference

The insight layer (`backend/app/insight/`) turns a completed analysis into evidence-backed views: technology
lifecycle, technical debt, metrics, cycles, explained graph, diagrams, next-test suggestions and the assistant.
Everything shown to a user is computed from (a) the analysis snapshot, (b) bytecode facts read from the uploaded
class files, (c) optional runtime evidence from selected sessions, and (d) two dated rules files. Where data is
missing the UI says "not available" and why.

## Data flow

1. Upload → `validate_archive` extracts and validates class files (unchanged).
2. Scan: jQAssistant (default) or the built-in reader (`SCANNER_ENGINE=bytecode`).
3. `app/insight/bytecode.py` parses every owned `.class` file as **data only** (nothing is loaded or executed):
   annotation values, parameter names (`MethodParameters` or `LocalVariableTable`), call sites with line numbers,
   field accesses, bytecode length and branch counts, synthetic/bridge flags, inner-class owners, lambdas,
   generic signatures, `@Deprecated`. Output is bounded (`bytecode_facts_max_bytes`; reductions are recorded).
4. `scan.supplement` adds dependency types the graph export does not distinguish (parameter, return, member
   annotations, exceptions, type arguments). `reconcile` makes class counts and the entry-point inventory agree
   with the bytecode facts.
5. Facts are stored in the snapshot (`result['bytecode']`); `source_store` keeps `.java` entries found in the artifact.
6. Views are pure functions of an `InsightModel` (cached per analysis id) and are served under
   `/api/v1/analyses/{id}/insight/…`. A snapshot that predates bytecode facts (no facts_available flag) shows "run a new analysis".

## Lifecycle rules (`app/insight/rules/lifecycle-rules.yaml`)

```yaml
schema_version: 1
rules_version: 2026.10.0      # release of the file
reviewed: 2026-10-19          # date every rule was checked against its source
max_age_days: 180             # UI warns when older (override: LIFECYCLE_RULES_MAX_AGE_DAYS)
rules:
  - id: log4j-1
    technology: Apache Log4j 1.x
    category: library            # platform | framework | library | namespace
    match:
      packages: ["org.apache.log4j."]            # used by application bytecode (class refs and call sites)
      artifacts: ["log4j:log4j", "log4j"]        # groupId:artifactId or bare artifactId (metadata / bundled jar names)
      # java_target: true                         # evaluate per class-file major version instead
    source: https://logging.apache.org/log4j/1.x/ # required
    status: end-of-life          # default when the version is unknown
    versions:                    # first matching range wins; ranges: <,<=,>,>=,== on dotted numbers, comma = AND
      - {range: "<2.0", status: end-of-life, note: "…"}
    alternative: Log4j 2 or SLF4J with Logback
    replacement: {from: org.apache.log4j, to: org.apache.logging.log4j}   # optional rename hint
    migration_notes: "…"
    effort: low                  # low | medium | high  (ordering aid only)
```

Statuses are **end-of-life / aging / current**. They describe vendor support, never vulnerabilities (the UI and
API say so). When a version is not found in the manifest (MANIFEST.MF, pom.properties), the finding states why and uses the default of its rule in lifecycle-rules.yaml. The effort
hint is a labelled heuristic index (`weight × affected classes`), not a time or cost estimate.
The dates in lifecycle-rules.yaml were compiled from the cited vendor pages on its reviewed_on date and must be
re-verified before use; the freshness banner appears when reviewed_on is older than the configured limit.

## Debt rules and thresholds (`app/insight/rules/debt-rules.yaml`)

`metric_thresholds` give `warn` ("near") and `over` limits per metric; `layering` lists the layers each layer may
depend on; `rules` documents each rule id, severity, description and action. Findings (`GET …/insight/debt`) carry:
rule id, entity (class, method, field or dependency), measured value, threshold, technical + plain explanation,
evidence items (with line numbers where bytecode provides them), suggested action and node ids for linking.

| Rule | Fires when |
|---|---|
| DEBT-GOD-CLASS | ≥ 2 of method count, field count, fan-in, fan-out, bytecode size are over their thresholds |
| DEBT-HIGH-COUPLING | fan-in + fan-out > 30 distinct classes |
| DEBT-CYCLE-MEMBER | class is in a cyclic group of top-level classes (entity-pair associations are LOW) |
| DEBT-LAYER-VIOLATION / DEBT-LAYER-SKIP | dependency to a layer not allowed by `layering`; presentation → data access when a service layer exists |
| DEBT-LARGE-METHOD | method bytecode > 1000 B (MEDIUM) / > 8000 B (HIGH, HotSpot HugeMethodLimit) |
| DEBT-COMPLEX-METHOD | branch instructions + 1 > 10 (MEDIUM) / > 20 (HIGH) |
| DEBT-TOO-MANY-DEPENDENCIES | > 30 distinct referenced types |
| DEBT-ENTITY-IN-CONTROLLER | a presentation class uses a persistence entity |
| DEBT-STATIC-STATE | non-final static field, or static final collection that is mutated |
| DEBT-DEPRECATED-API | call to an application `@Deprecated` member or a listed deprecated JDK member |
| DEBT-AGING-FRAMEWORK | class uses a technology rated aging (MEDIUM) or end-of-life (HIGH) |
| DEBT-UNOBSERVED | no span of the selected sessions maps to the class (INFO; never called "unused") |

Package debt index = 3×HIGH + 2×MEDIUM + 1×LOW (+4×CRITICAL); density = index / classes. Package debt index = 3×HIGH + 2×MEDIUM + 1×LOW (+4×CRITICAL) orders packages; it is not an effort estimate in days.

## Metric formulas

Counted entities are top-level classes (nested/anonymous/local classes are folded into their owner).

| Metric | Formula |
|---|---|
| Fan-in / fan-out | distinct internal classes that depend on / are depended on by C |
| Ca (afferent) / Ce (efferent) | distinct classes outside package P that depend on P / that P depends on |
| Instability I | Ce / (Ca + Ce); 0 if both 0 |
| Abstractness A | (abstract classes + interfaces) / classes in P |
| Distance D | \|A + I − 1\| (not shown for packages with no internal dependencies) |
| Bytecode size | sum of `Code` attribute lengths (bytes) |
| Bytecode complexity | sum over methods of (conditional branches + switch cases + 1); max per method also reported |
| Distinct dependencies | referenced types, internal and external, excluding `java.lang.*` |
| Cycle groups / largest cycle | strongly connected components containing C (or a member of P) |
| Layer violations | dependencies from C to layers it may not use |

Every metric in the API and UI carries its formula, input lists, plain meaning and threshold state.

## Cycles

Strongly connected components (networkx/Tarjan) on the top-level class graph and on the package graph; elementary
cycles are enumerated per component (length ≤ `max_cycle_length`, ≤ `max_cycles_per_scc` per component). Each cycle
lists ordered members, each edge's types, code references (field, call with line, inheritance, annotation), and
whether the edge is static and/or runtime. Cut candidates are ranked by: breaks the whole group, cycles broken,
against layering, fewest references, fewest runtime calls — every cut candidate carries the label "suggestion, requires human review" (field review_label).

## Responsibility rules (`app/insight/rules/responsibility-rules.yaml`)

The file registers the taxonomy (8 functional and 17 non-functional categories, each with a `limit` that states what a label does not prove), 64 evidence rules, 13 library families and 11 risk definitions.
A rule reads one kind of recorded fact: an annotation (with values such as `fetch: FetchType.EAGER`), a supertype, a type reference or a call site. Names of classes or packages are never sole evidence: a name gives only a WEAK, INFERRED label.
A class is FUNCTIONAL, FUNCTIONAL_SUPPORT, NON_FUNCTIONAL, MIXED or UNCERTAIN. MIXED requires a detected functional responsibility and a non-functional concern that the class's own code runs (it calls the API or holds an instance of it); a declared annotation such as `@Transactional` is an additional concern, not a mix.
Confidence is an ordinal heuristic (HIGH, MEDIUM, LOW), never a calibrated probability. A component is cross-cutting when classes of two or more other candidate domains use it. Details, API and validation results: `docs/RESPONSIBILITY-ANALYSIS.md`.

## Assistant

Tools (all read-only, scoped to one analysis, size-bounded): `get_package`, `get_class`, `get_dependencies`,
`get_dependents`, `get_cycles`, `get_debt_findings`, `get_runtime_coverage`, `get_entry_points`,
`get_aging_findings`, `get_class_source`, `search_classes`, `get_metrics`, `get_responsibilities` (`GET …/insight/assistant/tools`).
Evidence ids: `class:`, `package:`, `edge:a->b`, `finding:`, `cycle:`, `entry:`, `aging:`, `metric:entity:key`,
`runtime:`, `source:`, `layer:`, `resp:` (one evidence item of the responsibility analysis), `risk:` (one responsibility risk indicator), `summary:analysis`. The verifier removes any sentence whose citation does not
exist, that names a class/package/method not present in the analysis or tool results, or (model mode) that states a
number absent from the cited results. If 0 sentences pass verification, the deterministic answer is used; if no tool returns data, the answer is "cannot determine" plus the tool names tried. There is no tool that changes code or data; change
requests are refused and pointed to Source tasks (human approval). Memory: `assistant_messages` (per principal and
analysis = application version), `GET/DELETE …/assistant/history`. Streaming: `POST …/assistant/chat` (NDJSON
events `start`, `tool_call`, `tool_result`, `sentence`, `done`); non-streaming: `POST …/assistant/ask`. Budgets:
`ASSISTANT_REQUESTS_PER_HOUR` per user, `assistant_max_tool_calls` per question, workspace model-call budget and
context/output limits from the AI policy. Identical deterministic questions are cached (256 entries).

## AI data flow — what leaves the environment

The insight layer calls no external model; only a local Ollama on a loopback address is allowed. Its only model path is `app/ai/grounded.py`, which reuses the
existing gateway rules: fresh authorization (`MODEL_USE_LOCAL` + workspace policy `model_enabled`), provider must be
a **local Ollama** on an operator-allow-listed loopback address, digest pinned, hourly budget, every outgoing string
sanitised (credentials block, PII redacted/blocked per policy, prompt-injection patterns block), size limit,
schema-constrained JSON output, output sanitised, then citation/identifier verification.

| Mode | Setting | What is sent where |
|---|---|---|
| No AI (default behaviour of every view) | `INSIGHT_AI_MODE=OFF`, or no enabled workspace model policy | Nothing is sent anywhere. All findings and the assistant's deterministic mode work. |
| Local model | `INSIGHT_AI_MODE=LOCAL_ONLY` + enabled local provider in the workspace policy | Evidence text (finding explanations, dependency/call-site descriptions, class names, optional source or bytecode outline of the classes in question, your question) goes to the loopback Ollama process on the same host. Nothing leaves the machine. |
| External models | not supported by the insight layer | The pre-existing, separate Gemini code-generation path (Source tasks) is unchanged and opt-in; the insight layer does not use it. |

Switches that disable AI or source access: `INSIGHT_AI_MODE=OFF`; workspace policy `model_enabled=false`;
revoke `MODEL_USE_LOCAL`; `SOURCE_STORE_MODE=DENY` (no `.java` stored or read; outlines are also withheld from
`get_class_source`); `BYTECODE_FACTS_ENABLED=false`. Audit: each model call writes the existing content-free
`MODEL_INVOCATION` event (purpose, hashes, counts); each question, tool call and answer writes
`ASSISTANT_QUESTION` / `ASSISTANT_TOOL_CALL` / `ASSISTANT_ANSWER` events (hashes only). The full text of prompts and
answers is kept in the tenant-scoped `assistant_messages` table for review.

## Where AI is used

| Place | Endpoint | Evidence check |
|---|---|---|
| Migration note per class group (WP1) | `POST …/insight/lifecycle/explain` | sentences must cite the rule/class evidence supplied; unknown class names dropped |
| Plain-language cycle rewrite (WP6) | `POST …/insight/cycles/explain` | must cite loop edges (`edge:`); unknown names dropped |
| Refactoring proposal per finding (WP4) | `POST …/insight/debt/explain` | must cite evidence; method names must be declared or invoked in the classes read |
| Test steps and edge cases (WP8) | `POST …/insight/tests/explain` | as above |
| Assistant tool loop and wording (WP7) | `POST …/assistant/ask`, `…/assistant/chat` | citations exist, identifiers exist, numbers present in results; else deterministic fallback |

## Fixtures and tests

`backend/tests/fixtures/java/` holds Java sources and `build.sh` (needs a JDK) for the committed compiled classes in
`backend/tests/fixtures/classes/` (Spring PetClinic layout + an `edgecases` package). Frontend tests render the real
backend output exported by `python scripts/export_insight_fixtures.py`.
