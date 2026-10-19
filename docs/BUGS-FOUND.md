# Extraction and mapping bugs found (WP9)

Method: a compiled fixture application (Spring PetClinic layout + an `edgecases` package with overloads, bridge
methods, lambdas, inner/anonymous classes, servlets, filters, listeners, JAX-RS, Struts, legacy javax APIs and known
cycles) is parsed by the built-in class-file reader and compared with what the existing extraction/mapping code
produces. Fixture sources and the build script are in `backend/tests/fixtures/java/`; the compiled classes are committed
in `backend/tests/fixtures/classes/`. Tests: `backend/tests/test_extraction_audit.py`. Every test below was written and
run **failing first**, then the fix was applied.

| # | Symptom | Cause | Fix | Test |
|---|---|---|---|---|
| 01 | Runtime spans for a nested class reported as `com.x.Outer.Inner` (canonical name, emitted by some agents) stayed UNRESOLVED, lowering coverage and creating "runtime-only" nodes. | `map_class` only tried the binary name `Outer$Inner`. | New `NESTED_RESOLVED` step tries `Outer$Inner`, `Outer$Inner$Deep` and accepts only a class that exists in the scan. | `test_dotted_nested_class_names_resolve` |
| 02 | Lambda classes (`Outer$$Lambda$14/0x…`), `FastClass`, `EnhancerByCGLIB`, Hibernate (`$HibernateProxy$`), Javassist (`_$$_jvst`) and ByteBuddy proxies were UNRESOLVED. | Only two Spring CGLIB suffixes were recognised. | Generated-suffix table; resolves to the declaring class with confidence 0.7 (`LAMBDA_RESOLVED` / `PROXY_RESOLVED`), never to a method. Unrelated `$Proxy` names stay unresolved. | `test_generated_classes_resolve_to_owner_with_lower_confidence`, `test_unrelated_names_still_unresolved` |
| 03 | A project's own `@GET`, `@Scheduled` or `@Path` annotation counted as a framework entry point; `@EventListener` was not an entry point at all. | `is_method_entry_point` compared simple names only. | Annotation + package match (javax/jakarta JAX-RS, Spring packages); added `EventListener`, `SqsListener`, `MessageMapping`. Bare simple names remain accepted for legacy snapshots. The domain inventory now passes full annotation names. | `test_entry_point_annotations_are_matched_by_package` |
| 04 | Method and entry-point coverage denominators included `lambda$…`, `access$000`, bridge and synthetic methods, which no test can call directly, so coverage looked lower than reality. | Population filter only removed names starting with `<`. | `is_declared_method` excludes initializers, lambda bodies, accessors, `$deserializeLambda$`, and methods flagged synthetic/bridge. Used by coverage and the coverage-details endpoint. | `test_coverage_population_excludes_synthetic_bridge_and_lambda_methods` |
| 05 | Exception and generic-type dependencies were grouped as `OTHER` in domain boundary analysis. | Group table lacked those edge types. | Added `EXCEPTION`, `GENERIC_TYPE`, `RETURN_TYPE`. | `test_edge_groups` |
| 06 | Parameter, return, method/field-annotation, declared-exception and type-argument dependencies were missing or only present as untyped `OTHER` edges. | The graph export distinguishes eight relation kinds but no parameter/return/member-annotation relations. | `supplement()` adds these from class-file facts (never duplicating a typed edge, dropping `OTHER` once a typed edge exists for the pair). Applied in the pipeline after the scan. | `test_supplemental_edges_add_missing_dependency_types` |
| 07 | Class counts disagreed between pages: summary counted nested/anonymous classes as classes; cycle analysis folded them into owners. | Two different definitions of "class". | Summary now also reports `top_level_class_count` and `nested_class_count`; the insight pages always state which they count. | `test_summary_reports_top_level_and_nested_counts` |
| 08 | Entry-point counts disagreed between pages and every HTTP route was `UNKNOWN`. | Inventory was built from annotation names; annotation values were not exported. | Snapshot inventory is rebuilt from bytecode annotation values (`reconcile`): composed class + method paths, HTTP methods, listener triggers. Same detector feeds the explorer, assistant and test suggestions. | `test_snapshot_inventory_and_insight_pages_agree_on_entry_points`, `test_petclinic_routes_are_exact`, `test_edgecase_entry_point_kinds` |
| 09 | `application` scoping dropped the whole Spring PetClinic app: the blanket `org.springframework.` external prefix matched `org.springframework.samples.petclinic`. | Prefix-only classification of internal vs external code. | `application_roots` keeps scanned classes under a common root whose classes carry application stereotypes; the decision and reason are stored in the snapshot (`configuration.application_roots`). | `test_petclinic_analyses_although_it_matches_the_spring_prefix` |

## Checked and found correct (regression tests keep them so)

Overloaded methods stay separate (`calculate(int)`, `(int,int)`, `(String)`); constructors and static initialisers are
identified as such; bridge and lambda methods are flagged and hidden from method lists; anonymous, inner and static nested
classes map to their top-level owner; dependency edges point dependent → dependency and are de-duplicated; class-level plus
method-level `@RequestMapping` paths compose; multiple paths and HTTP methods expand; `@DeleteMapping({"/{id}","/remove/{id}"})`
yields two routes; duplicate routes are reported; servlets, filters, Struts actions, JAX-RS, Kafka/JMS/Rabbit listeners,
`@Scheduled`, `@EventListener`, `@PostConstruct` and `main` are found
(`test_insight_foundation.py`, `test_extraction_audit.py`).

## Could not fix or verify

* **jQAssistant itself could not be run** in this environment (no JDK-bundled scanner runtime), so behaviour of the
  Cypher export on real stores is unverified. Known risks to check with a real scan: the `EXCEPTION` query includes
  `CATCHES` (a caught exception is a dependency but is not a declared `throws`); `METHOD_CALL` is attributed to the
  type that *declares* the callee, which can be a superclass of the type named at the call site; jQA method signatures
  versus JVM descriptors for runtime matching are only compared by signature text.
* Routes defined in XML, functional `RouterFunction` beans, `@RequestMapping` on interfaces inherited by controllers, and
  meta-annotations (composed annotations) are not resolved.
* Constants used in annotation values (`@GetMapping(Paths.OWNERS)`) are inlined by the compiler and appear correctly;
  values computed at runtime (placeholders `${…}`) are shown verbatim.
* Annotation-processor generated classes appear in bytecode but have no source; they are labelled by their role evidence only.
