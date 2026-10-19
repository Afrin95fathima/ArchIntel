# ArchIntel

A working local investor prototype for Java architecture and modernization intelligence.

**Start:** double-click **Start-ArchIntel.cmd**, then open **http://127.0.0.1:8000**.
Select **Explore demo application** for the real, pre-analyzed synthetic Northstar Commerce sample.

## What works

- Projects, application versions, JAR/WAR upload, queued real scanning, progress and saved history.
- jQAssistant → isolated embedded Neo4j → normalized class and package graphs.
- SCC cycles, package/class metrics, relative god-class detection and evidence-bearing issues.
- Candidate domains, database structural signals, explainable readiness and dependency-first sequence.
- Interactive Cytoscape explorer, issue filters, domain details, score breakdowns and JSON export.
- Offline evidence assistant with resolvable citations and separated recommendations.

The default assistant uses deterministic evidence explanations. Optional local-model evidence selection uses the Phase 2 policy-controlled gateway; no model is required for deterministic analysis. Candidate boundaries and readiness are heuristics, and runtime SQL/traffic remain unknown.

## Documentation

- [Complete user guide: screens, fields, inputs, and outputs](docs/ARCHINTEL-COMPLETE-USER-GUIDE.md)
- [Dynamic analysis user flow](docs/RUNTIME-USER-FLOW.md) · [PDF](docs/RUNTIME-USER-FLOW.pdf)
- [Runtime developer guide](docs/RUNTIME-DEVELOPER-GUIDE.md) · [PDF](docs/RUNTIME-DEVELOPER-GUIDE.pdf)
- [Dynamic verification](docs/RUNTIME-VERIFICATION.md)

Open **Dynamic analysis** to create a session, connect the OpenTelemetry Java agent, inspect coverage and compare runtime/unified evidence. The static engine and saved structural results are preserved. Runtime observation is bounded and incomplete; management APIs require authenticated workspace permissions.

- [User manual](docs/USER-MANUAL.md) · [PDF](docs/USER-MANUAL.pdf)
- [Developer guide and internal design](docs/DEVELOPER-GUIDE.md) · [PDF](docs/DEVELOPER-GUIDE.pdf)
- [Verification report](docs/VERIFICATION.md)
- [Screenshots](docs/screenshots)

The earlier phase plan and Phase 0 report are historical. The user subsequently authorized continuous delivery of the full investor prototype.

## Prepared Windows machine

Node is on PATH. Python, JDK, jQAssistant, the exporter and PostgreSQL are under `.runtime`. Results are persisted in `.data/postgres`.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stop.ps1
```

Wait for analysis to finish before stopping. Start-ArchIntel.cmd also opens the browser. Stop-ArchIntel.cmd preserves saved results.

For a fresh Windows x64 setup with Node 22 installed:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1
```

Setup downloads runtimes, installs locked dependencies, builds the UI/exporter/sample, and creates a random local PostgreSQL password when `.env` is absent. Existing settings are preserved. Do not commit `.env`.

## Development and checks

```powershell
.\.runtime\python\tools\python.exe -m pytest backend/tests -q
cd frontend
npm ci --legacy-peer-deps
npm test
npm run build
npm exec playwright test
```

Real scanner tests are opt-in; see the developer guide. Browser tests require the API and Chrome. Frontend development uses `npm run dev` on port 5173; the investor page is served by FastAPI on port 8000.

## Docker alternative

```powershell
docker compose up --build -d
```

The root build packages the frontend, Python API, JDK, jQAssistant and embedded Neo4j exporter. PostgreSQL is a separate service. A standalone Neo4j service is unnecessary because each scan has its own embedded store. This container configuration has not been runtime-verified on this machine because Docker is unavailable; the tested delivery is the local Windows launcher.

## Limits

This is a localhost prototype with authentication, workspace isolation, explicit permissions, source-read policy, audit and a controlled local-model gateway. It is not production SaaS. Distributed jobs, OS-level scanner isolation, SSO, external audit anchoring, manual domain editing and large real-world validation remain development work. Configured artifact/graph safety limits do not certify performance at those sizes.

Phase 2 handoff: [User flow](docs/PHASE-2-USER-FLOW.md), [developer internals](docs/PHASE-2-DEVELOPER-GUIDE.md), and [verification](docs/PHASE-2-VERIFICATION.md). Existing accounts need an explicit MODEL_USE_LOCAL grant and enabled workspace model policy.
