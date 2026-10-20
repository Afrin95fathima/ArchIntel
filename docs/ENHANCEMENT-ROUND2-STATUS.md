# Enhancement round 2: status

Commits are one per item (Items 1 and 2 share `acf2f75`). Item 9 is the last commit.

## Test results

| Suite | Baseline (`be4cfff`) | After round 2 |
|---|---|---|
| Backend pytest | 391 passed, 14 skipped, 3 failed | 499 passed, 14 skipped, 3 failed |
| Frontend vitest | 36 passed | 81 passed (25 files) |
| `tsc --noEmit`, `vite build` | clean | clean |
| `scripts/check_content.py` | no tool | 0 violations |

The 3 failures are the same as the baseline and are environment related: `test_ai_gateway.py::test_context_limit_and_pii_block_policy_send_no_bytes`, `test_domains.py::test_cluster_consensus_deterministic`, `test_local_diagnostics.py::test_local_setup_diagnostics_separate_core_services_from_deferred_containers`.

Playwright e2e specs (3) were edited for the dock and were not run. Nothing was run against Docker or a live application.

## Items

| # | Item | Status | Tests added | What remains |
|---|---|---|---|---|
| 1 | Runtime mapping details | DONE | `test_runtime_mapping_details.py` (23, shared with 2), `RuntimeMappingTables.test.tsx` | Mapping reasons use class names from the scanned artifact only |
| 2 | Database callers | DONE | same files | Callers behind async boundaries without context propagation stay unresolved with a reason code |
| 3 | Modernization descriptions | DONE | `test_modernization_description.py` (7), `ItemDescription.test.tsx` | none |
| 4 | Docked assistant | DONE | `AssistantDock.test.tsx`, `TechnicalDebt.test.tsx` addition | e2e specs not run |
| 5 | Planning context | DONE | `test_planning_context.py` (6), `PlanningContext.test.tsx` | none |
| 6 | Report (10 sections, HTML and PDF) | DONE | `test_reports.py` (6), `Reports.test.tsx` | PDF layout was checked by reading rendered pages, not by a visual regression test |
| 7 | Technology plan | PARTIAL | `test_technology_plan.py` (18), `TechnologyPlan.test.tsx` | Only 25 curated candidates; 19 of 25 have no lifecycle entry in `lifecycle-rules.yaml` and say so |
| 8 | Decision brief | DONE | `test_decision_brief.py` (9), `DecisionBrief.test.tsx` | none |
| 9 | Content audit | DONE | `test_content_rules.py` (22) | The check is lexical; see `CONTENT-AUDIT.md` |
| 10 | Explain why | DONE | `PlanningWorkspace.test.tsx` (5), `ChangesetCard.test.tsx`, 3 backend tests | none |
| 11 | Readiness and confidence | DONE | `test_scoring.py` (6, hand computed) | Weights are configuration, not calibrated against outcomes |
| 12 | Problem percentages | DONE | hand-counted PetClinic and edgecases values in `test_insight_debt.py`, `DebtRates.test.tsx` | none |

Item 7 is PARTIAL because most candidates cannot show a vendor support status. The UI prints "not covered by lifecycle-rules.yaml" for them instead of inventing one.

## Hard-coded or fallback values found

| Value | Location | Replaced by |
|---|---|---|
| `cohesion = 50` when unmeasured | `services/modernization.py` | component excluded, weights renormalised, listed in `not_measured` |
| database score 25 / 45 / 65 (45 = unknown) | `services/modernization.py` | measured from repositories and entities, excluded when unknown |
| `persistence = 25 if shared else 50` | `services/runtime/intelligence.py` | measured or "not measured" |
| `behavioral_validation = 0`, `data_ownership = 0` inside confidence | `modernization/engine.py` | excluded with `confidence_not_measured` |
| runtime gap cost of 4 points and `risk_band` HIGH from `observation_score` 0 with no runtime | `modernization/engine.py` | omitted when no session is attached |
| "Not observed" literal on the Domains page | frontend | "not measured here" |
| `class_count <= 250` strategy rule | `modernization/engine.py` | recommendation rule from blockers and extraction readiness (`brief.py`) |
| generic `ACTION` map | `modernization/engine.py` | `describe.decision_action` names domain, measured value and blocker |
| always-appended "Runtime SQL…" risk | modernization risk list | risks now come from findings and blockers with measured values |
| lifecycle status copied to candidates (Log4j 2 got Java 21's status) | my first `modernization-candidates.yaml` draft | `lifecycle: null` plus a test |

Constants kept as configuration, named and shown in the glossary: `CONFIDENCE_WEIGHTS` (static .30, runtime_coverage .30, review .15, unresolved_references .15, runtime_data_quality .10), `CONFIGURED_SHARE = .8`, `CLOSE_MATCH = .85`, and the combine weights .6 / .4.

## Scope decisions to confirm

- Item 4 deleted `Assistant.tsx` and its test. The docked assistant uses the same conversation hook.
- `backend/app/access/middleware.py` still has the uncommitted diagnostic edit from the first turn (503 catch-all). Commits 27c25c8 to cc73855 do not include that file.
- Docs not updated for this round: the removed assistant tab is still described in `docs/ARCHINTEL-COMPLETE-USER-GUIDE.md`.
