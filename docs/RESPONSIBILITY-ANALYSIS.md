# Functional and non-functional responsibility analysis

ArchIntel now says what each class does, which business capability it supports, and which non-functional concerns it implements or affects. Every finding carries its evidence and a status, and the results feed the modernization plan. This page is the implementation report: what exists, how it works, what was validated and what is not done.

## What was found in the repository first

| Question | Finding |
|---|---|
| Evidence available | The snapshot holds bytecode facts per class: annotations with values, supertypes, field/parameter/return types, call sites with line numbers, `new` and cast references, branch counts. No source files, no configuration files for a project ZIP. |
| Existing reusable parts | `InsightModel` (roles, owners, edges, `references()`), candidate domains with a documented confidence, debt rules and issues, the plan's `finding()`, blocker and `planning_graph` mechanisms, the grounded `explain()` helper, the assistant's tool and evidence-id system, YAML rule files. |
| Graph | Analysis results are normalized into PostgreSQL; each scan uses an isolated embedded Neo4j. The persistent Neo4j (`knowledge_graph_enabled`) is off by default. The plan's `planning_graph` is projected generically (`ArchIntelEntity` nodes with a `kind`, `ARCH_LINK` edges with a `kind`), so new kinds need no schema change. |
| LLM | Optional, local, policy-gated, with a verifier that drops uncited or invented sentences. |

No second graph, pipeline or backend was added. The analysis is a derived view over the immutable snapshot (computed once per snapshot and cached on `InsightModel`), so there is no migration and older analyses without bytecode facts report `NOT_AVAILABLE` with a reason.

## The model

- **Primary classification** of a class: `FUNCTIONAL`, `FUNCTIONAL_SUPPORT` (data access, domain model), `NON_FUNCTIONAL`, `MIXED` or `UNCERTAIN`. `MIXED` needs a detected functional responsibility and a non-functional concern that the class's own code runs (it calls the API or holds an instance). A declared annotation such as `@Transactional` makes an additional concern, not a mix.
- **Labels** are multi-label, per method and per class: 8 functional categories and 17 non-functional categories (the 15 you listed plus `CROSS_CUTTING_INFRASTRUCTURE` and `INTERNATIONALIZATION`, registered through the YAML file without code changes).
- **Status**: `DETECTED` (a bytecode fact establishes it), `INFERRED` (a reasoned reading), `UNVERIFIED` (its evidence did not resolve to the snapshot).
- **Confidence**: an ordinal heuristic (`HIGH`, `MEDIUM`, `LOW`) from evidence strength, always marked `calibrated: false`. A name alone yields only a `LOW`, `INFERRED` label and the class stays `UNCERTAIN`.
- **Evidence**: id, kind, text, strength, class, method signature, and a location. Call sites and type references carry an exact bytecode line. Annotations, signatures and structural patterns carry the method-body line range and say that bytecode does not record where the annotation was written. File paths are derived from the package and the `SourceFile` attribute and are marked derived unless the artifact contains `.java` files.
- **Business capability**: the existing candidate domain (with its heuristic boundary confidence). A domain is `BUSINESS`, `TECHNICAL` or `MIXED` from the classes inside it; a technical domain is not offered for extraction.
- **Dependencies** come from the existing edges, typed `BUSINESS`, `BUSINESS_CROSS_CAPABILITY`, `DATA_ACCESS` or `TECHNICAL`, with the first references as evidence. A component is **cross-cutting** when classes of two or more *other* candidate domains use it, or when two or more domains include a library. Guidance is a library or module, never a service by default.
- **Risks** (11 rules): each reports the indicator's detection status and a consequence that is always `INFERRED`, with affected components, evidence, impact on modernization, what to investigate and whether runtime validation is needed. They are ordered by severity and the number of affected components; there are no numeric risk scores.

## Where it is wired in

| Area | Change |
|---|---|
| API | `GET …/insight/responsibilities` (summary), `…/components` (filter by classification, functional category, concern, capability, status, confidence, risk, text; paginated), `…/component?id=` (evidence resolved), `…/risks` (filters), `POST …/explain` (optional AI wording). |
| UI | New **Responsibilities** screen: Components, Capabilities, Cross-cutting, Risks, Method and limits, with a detail panel per class. |
| Plan | Per domain: findings, **soft** blockers (`SECURITY_CONTROL_REVIEW`, `SHARED_DATA_MODEL_REVIEW`, `CROSS_CUTTING_REVIEW`, `TRANSACTION_BOUNDARY_REVIEW`, `TECHNICAL_DOMAIN_REVIEW`), a second recommendation that names what to decide, and a `nonfunctional` document section. Scores, decisions, waves and readiness labels are unchanged (a test compares plans with the analysis on and off). |
| Brief and report | A "Non-functional constraints" brief section with every number registered in the fact table; report tables under Risks and unknowns and a plain-language sentence under Modernization plan. When the analysis cannot run, both state that the recommendation does not account for these concerns. |
| Graph | `planning_graph` gains `BusinessCapability`, `NonFunctionalConcern`, `NonFunctionalRisk` and `SharedComponent` nodes and `ASSOCIATED_WITH`, `HAS_CONCERN`, `CONCERNS`, `AFFECTS`, `DEPENDS_ON` links with deterministic ids. |
| Assistant | New tool `get_responsibilities`; evidence ids `resp:` and `risk:` that the verifier checks. |
| Rules | `app/insight/rules/responsibility-rules.yaml`: 64 evidence rules, 13 library families, 11 risk definitions. |

## Validation on real applications

The Walmart e-commerce repository named in the brief is not on this machine, so it was not used. Two real compiled applications were analyzed in the running application through Chrome.

**Spring PetClinic** (pinned revision, built here, uploaded as a project ZIP; 25 classes). 9 functional, 9 functional support, 3 mixed, 4 non-functional; 43 detected and 26 inferred labels; 148 evidence items, none rejected; 4 candidate domains (3 business, 1 technical); 10 risk indicators (4 high, 6 medium); analysis time 0.05 s. Checked against the source and bytecode:
- Call-site lines match the source file: `BindingResult.hasErrors` at lines 77 and 141, `rejectValue` at 104 and 147, `PageRequest.of` at 129.
- `OwnerController`, `PetController` and `VisitController` are `MIXED` because their own code calls `WebDataBinder.setDisallowedFields` (input-binding restriction); `VetController` has no binder method and is not.
- The missing-access-control risk reports 17 HTTP entry points, 5 of them changing data, which equals the 12 GET and 5 POST routes in the code. It is marked `INFERRED` and notes that binding restrictions do not control who may call.
- `VetRepository` is `FUNCTIONAL_SUPPORT` with caching and transaction concerns (`@Cacheable`, `@Transactional`); a question about transactions returns only that class.
- Eager-fetch risks name `Owner.pets`, `Pet.visits` and `Vet.specialties`, which are the `FetchType.EAGER` fields in the entities. This agrees with the Performance tab, which measured about 13 database calls per `/owners` request.
- The existing "god class" flag on `Owner` is relative to the application's own 95th percentile (20 methods against 13.8 across 25 classes); the maintainability evidence now says it is relative, not an absolute limit.

**Northstar Commerce** (the repository's own sample; 40 classes in 6 candidate domains). 11 functional, 12 functional support, 17 uncertain; 4 shared components. 17 classes are `UNCERTAIN` because they are plain classes with no annotation, supertype or call that establishes a responsibility; the engine does not guess from names. `LedgerRepository` is reported as used from 4 domains; an independent `javap` scan finds it referenced from `CustomerService`, `ApplicationCoordinator`, `PaymentService` and `ReportingService`, in 4 packages.

**Defects found by this validation and fixed:** shared components were over-reported (34 on Northstar, because one other domain calling a class counted as shared; now 4); annotation evidence showed the method's first code line as if it were the annotation's line; the Modernization page scrolled horizontally because a long proposal name widened a grid track.

**Cost.** Synthetic applications of 100, 1,000, 2,000 and 4,000 classes analyze in 0.06, 0.12, 0.28 and 0.76 seconds.

## Tests

Added: `test_insight_responsibility.py` (rule semantics, negative cases, evidence validation, PetClinic ground truth, determinism), `test_insight_responsibility_api.py` (real pipeline, filters, pagination, errors, optional AI with a fake model), `test_modernization_nonfunctional.py` (plan, scores unchanged, graph, limits), additions to the report and assistant tests (9 new assistant evaluation questions with ground-truth answers), and `Responsibilities.test.tsx` on real exported fixtures. Several tests were checked by breaking the code on purpose and confirming they fail.

Results on a clean rebuild of the repository state: backend 532 passed, 11 skipped, 3 failed and 37 errors; frontend 100 passed (27 files) with a clean type check.
The 3 failures and 37 errors are the same set as before this work and none touches it: `test_ai_gateway::test_context_limit_and_pii_block_policy_send_no_bytes` fails identically with the original `routes.py`; `test_ramp_limits` needs `/app/scripts`, which the image does not contain; `test_transformation*` and `test_security` need `git`, which the image does not contain. Two test files were not run: the scalability benchmark (a collection error in the image) and the real-scanner integration tests.

## Limits and remaining work

- Configuration files are not retained from a compiled artifact, so `CONFIGURATION` rests on annotations; values and environment differences are not analyzed. No configuration value is read or shown.
- Bytecode records neither `catch` blocks nor loops, so error handling and repeated work (for example a query in a loop) cannot be established. Eager fetching and unbounded repository queries are the structural proxies, and they are labelled as such.
- Business capabilities are heuristic candidate domains and need an architect's review.
- The AI step explains one class from recorded evidence; classification itself is deterministic and never depends on a model.
- The planning graph is verified structurally (unique deterministic ids, resolvable edges); projection into a live Neo4j was not run because the persistent graph is disabled here.
- Not built: incremental analysis across revisions (the view is cached per snapshot), runtime validation of the risk indicators beyond the existing Performance tab, and an editable capability model.
