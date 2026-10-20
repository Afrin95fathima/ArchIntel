# Content audit

Result of the Item 9 audit. `python scripts/check_content.py` reports 0 violations in the files listed below; `backend/tests/test_content_rules.py` runs the same scan and fails on any new violation. The repository has no CI configuration, so pytest is the gate.

## What is checked

| Source | Files scanned | Method |
|---|---|---|
| UI text | `frontend/src/**/*.tsx` | tokenizer for JSX text, attribute strings and string literals |
| Backend messages and templates | `backend/app/**/*.py` | `ast` extraction of messages, reasons, notes and concatenations |
| Rule files | `backend/app/**/rules/*.yaml` | string values |
| Docs | README.md, USER-MANUAL.md, INSIGHT-REFERENCE.md, ENHANCEMENT-ROUND2-PLAN.md, ENHANCEMENT-ROUND2-STATUS.md | markdown prose without code blocks |

Rules live in `backend/app/content/content-rules.yaml`:

- **Banned phrases** (regexes): leverage, seamless, robust, comprehensive, holistic, powerful, cutting-edge, "it is important to note", "in today's", delve, streamline, unlock, "ensure that", "provides insights into", various, several, and 14 more (30 regexes in total).
- **Specific sentence**: a sentence of 7 or more words must contain a digit, a placeholder, a product term, a class/package/rule name, a definition marker (`=`, "means") or a data marker ("not measured", "this version").
- **Runtime enforcement**: `ai/grounded.py verify_sentences` drops AI sentences with `BANNED_PHRASE` or `NOT_SPECIFIC`. `insight/assistant/evidence.py check_answer(content_rules=True)` does the same for assistant model output.

## Scoping decisions

These narrow the check. Each can be reversed in `content-rules.yaml`.

1. API error messages and `cannot(...)` abstentions (`message_calls`, `message_files`) are checked for banned phrases only. A message such as "Request could not complete" states a rule that is the same for every application.
2. Glossary and definition files (`definition_files`: glossary.py, debt_rates.py, blockers.py, metrics.py, diagrams.py, roles.py, debt-rules.yaml, GlossaryPanel.tsx) skip the specificity test. They are the definitions.
3. Model system prompts (`prompt_files`: 6 files) skip the specificity test. Model output is enforced at runtime (see above).
4. Product help (`product_help_files`: 8 frontend files for access, AI console, security console, task workflow and local setup) is checked for banned phrases only. Those texts describe the tool's own controls.
5. Imperative instructions ("Copy the key now") and questions skip the specificity test but not the banned-phrase test.
6. `allow:` is empty. No single sentence is exempted.

## Violations rewritten

The first full scan flagged banned phrases and unspecific sentences across 50+ files. The last 232 were rewritten in this pass:

| Area | Count | Example (before -> after) |
|---|---|---|
| Backend transformation | 30 | "This is a static boundary preview…" -> "The ExtractionPlan is a static boundary preview…" |
| Rule files | 4 | lifecycle-rules.yaml "several were removed" -> "some, such as sun.misc.BASE64Encoder, were removed" |
| Frontend | 131 (79 rewritten, 52 moved to product help) | "How the analyzed application is put together." -> "Modules, packages and dependencies." |
| Docs | 65 | "Neither high nor low instability is inherently good or bad." -> "A high I (near 1) or a low I (near 0) is not a defect on its own." |

Earlier in the round the modernization, report, access, evidence, insight and services messages were rewritten with the items that touched them.

## Remaining exemptions to review

- The specificity heuristic is lexical. A sentence can pass by containing one code token and still say little. Human review of new text stays necessary.
- Strings built at runtime from several variables are counted as specific without inspection.
- Playwright e2e specs and test files are not scanned.
- The `Complete user guide` and other `docs/*.md` files outside the 5 listed are not scanned.
