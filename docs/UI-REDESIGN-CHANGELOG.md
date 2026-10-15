# ArchIntel UI redesign changelog

## Current delivery

The redesigned shell and the core analysis, modernization, evidence, and reporting screens are implemented. The remaining items below are known acceptance gaps; they are not represented as completed.

### Phase 0 — audit

- Reviewed the React entry point, view composition, CSS layering, chart/graph dependencies and existing test setup.
- Existing graph visualization uses Cytoscape; no external charting dependency or CDN assets were added.
- Identified overlapping legacy shell styles, flat navigation, raw telemetry serialization and the text-first PDF renderer.

### Phase 1 — design foundation

- Added `frontend/src/design-tokens.css` with semantic brand, neutral, status, typography, spacing and motion tokens; moved legacy compatibility colors into that token file.
- Replaced `styles.css` with `screens.css`, removed `elite.css`, and consolidated shared presentation in `frontend/src/ui/components.css`.
- Bundled Inter and JetBrains Mono locally. No frontend color hex values remain outside `design-tokens.css`.
- Added reusable cards, KPI cards, status badges, confidence/coverage meters, evidence chips, skeletons and tooltips; added the `/ui-kit` in-app catalog view.

### Phase 2 — navigation and workflow

- Grouped navigation into Portfolio, Analyze, Runtime, Plan, Evidence and Deliver, with Local Setup and Help in the footer.
- Removed the investor prototype badge and placeholder avatar; added workspace/environment details and live service health.
- Added Ctrl/Cmd+K navigation, a persistent breadcrumb and a workflow stepper that checks existing analysis, session, version and proposal APIs.
- Combined modernization sequencing and proposal planning in one tabbed workspace; combined cycles and architecture metrics in a Dependencies workspace.

### Phase 3 — application screens (partial)

- Added application cards/table with API-backed analysis counts, readiness, evidence confidence and runtime coverage when available.
- Reworked the overview with seven source-backed KPIs, severity distribution, domain-size distribution, skew callout, prioritized risks, hotspots and blockers.
- Added sortable domain table/cards and detail view; converted digital-twin coverage and quality output into readable tables instead of JSON dumps.
- Added HTML report preview and print styling, plus an updated PDF renderer with evidence-driven bar charts and corrected proposal validation copy.
- Remaining: full graph minimap, severity filtering and 3,000-node interaction; complete candidate-service strategy comparison; exhaustive drawer/forms polish across every Runtime, Evidence, Task and Setup state.

### Phase 4 — reporting (partial)

- Reports now support an in-app HTML preview, browser Print/Save as PDF, the existing server PDF download, and digital-twin JSON export.
- PDF output now adds charts only when corresponding API values exist, explains unavailable graph projection, and labels proposal schema validation accurately.
- Verified in the Northstar browser fixture: the generated sample PDF is 8–14 pages and the rendered report has its visual sections. Remaining: verify this page count across additional real datasets, add table of contents/page references and selectable Letter/A4 layouts, and inspect the PDF visually.

### Phase 5 — copy and tone (partial)

- Replaced investor/prototype product chrome, surfaced missing telemetry as “Not observed”, and removed several internal phase references and misleading “VALIDATED” wording.
- Remaining: review every screen and generated document against the complete copy defect list.

### Phase 6 — quality (partial)

- Added route-level lazy loading; the Cytoscape graph is loaded on demand. The main production JavaScript chunk is about 308 KB and Cytoscape is a separate 444 KB chunk.
- Reduced motion and visible keyboard focus styles are included; layouts adapt down to narrow viewports.
- Captured all 15 main screens at 1280, 1440 and 1920 desktop widths. The Playwright matrix also creates an isolated architecture version and modernization proposal, opens the report preview, and checks the sample PDF page count.
- Remaining: full keyboard/contrast audit, graph performance validation above the current bounded API result, print inspection, and linting (the frontend package has no lint script).

## Verification

- `npm run build`: passed after the current UI changes.
- `npm test`: 5 files and 10 tests passed.
- `python -m pytest backend/tests/test_reports.py -q`: 2 report tests passed.
- Playwright screen/report matrix: passed at 1280, 1440 and 1920; screenshots are under `docs/screenshots/{1280,1440,1920}/`.
- Playwright investor walkthrough: passed across the live persisted analysis screens.

No API routes, request/response models, persisted storage keys, or business analysis algorithms were changed for the UI work. The PDF renderer change changes report presentation only.
