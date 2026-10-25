# REA exploration and Claude conversion: setup and live tests

ArchIntel can now explore a running Java web application automatically with REA, and convert one service candidate of an
approved plan into a standalone service with Claude, build and run it locally, and compare it with the original.
Production is a reviewed hand-off package; ArchIntel never deploys.

## How the pieces fit

| Piece | Where it runs | What it does |
|---|---|---|
| ArchIntel backend | Docker container | Plans, gates, jobs, audit; calls the runner and Claude |
| Runner (`runner/`) | Your Mac (`scripts/runner-start.sh`) | Starts the application with the OpenTelemetry agent, drives it with REA 6.7.0 browser scenarios, builds and runs generated services in Docker, replays scenarios against two origins |
| REA (`rea-agents` 6.7.0, pinned, signature-verified) | Inside the runner | Headless Chrome scenarios: navigate, fill, select, check, submit; returns page HTML and every request |
| Claude (`claude-opus-5-5` by default) or Gemini (`GEMINI_MODEL`, default `gemini-3.8-flash`) | Anthropic or Google API | Generates one service repository as a strict JSON bundle; you choose the provider per conversion |

The runner and ArchIntel share `RUNNER_TOKEN` through the git-ignored `.env`. The runner listens on 127.0.0.1:8790 and only
drives applications and services it started itself.

## Already prepared (no action needed)

- Runner installed in `runner/`, OpenTelemetry agent in `runner/.tools/`, token in `.env`.
- PetClinic source cloned to `sources/spring-petclinic` at commit `30aab0ae764ad845b5eedd76028756835fec771f`; it is visible to
  ArchIntel read-only as `/app/sources/spring-petclinic`.
- Automated exploration of PetClinic (DEEP): 17 of 17 entry points, 22 of 25 classes, 73 of 88 methods, 1,660 spans.
- Architecture version "Automated exploration (DEEP)" captured from that session (meets the plan's 80% runtime rule).
- MICROSERVICES plan "Live conversion test: extract Vet with Claude" saved on that version and approved for the test
  (reject it in the Review tab if you do not want it).

## Your one-time setup (security settings are yours to change)

1. Start the runner if it is not running: `./scripts/runner-start.sh` (keep the terminal open).
2. In **Security & access**:
   - **Repositories**: register application *Spring PetClinic*, name `spring-petclinic`, path `/app/sources/spring-petclinic`,
     commit `30aab0ae764ad845b5eedd76028756835fec771f`.
   - **Grants**: give your own account `pom.xml` and `src/main/` on that repository (no protected paths needed).
   - **Policy**: enable *source tasks* and *Claude source transfer* or *Gemini source transfer* (each provider has its own switch).
3. Set the key: `./scripts/set-anthropic-key.sh` or `./scripts/set-gemini-key.sh` (hidden input, written to `.env`, backend
   restarted). Give the key a small spend limit in the provider's console first.

## Live tests, one at a time

Run each from the ArchIntel folder; each prints PASS/FAIL lines and exits non-zero on failure.

| # | Command | Calls Claude | Checks |
|---|---|---|---|
| 1 | `./scripts/live-test.sh preflight` | No | Runner, REA, Chrome, Java, Docker, agent, key present |
| 2 | `./scripts/live-test.sh claude-smoke` or `gemini-smoke` | Yes, one tiny call, no source | Key, model and structured output; prints tokens (and cost for Claude) |
| 3 | `JAR=<path to petclinic jar> ./scripts/live-test.sh explore` | No | Optional repeat of the automated exploration |
| 3b | `DIST=<concord-server-*-dist.tar.gz> ./scripts/live-test.sh explore-api --application "Walmart Concord" [--passes 5] [--mode DEEP]` | No | API exploration with the Concord launch recipe: fresh PostgreSQL, generated admin token, GET crawl, scenario steps, coverage passes |
| 4 | `./scripts/live-test.sh convert --yes` (add `--provider GEMINI` for Gemini) | Yes, one generation | All gates, source within grant, Claude bundle, Docker build, original start, scenario replay, verdict, cost |
| 5 | Modernization → Microservice modernization → Vet | No | The same conversion is shown with steps, verdict, differences, running service link, generated files |
| 6 | In the conversion: **Move to production** → note → Approve for hand-off → Download | No | Package with source, Dockerfile, Kubernetes and Compose manifests, PROMOTION.md |
| 7 | `./scripts/live-test.sh status` | No | All jobs and verdicts |

Test 4 can also be started from the UI (step 5) with the *Convert with Claude* button; both create the same job.

If test 2 reports `PROVIDER_REJECTED`, set `CLAUDE_REFUSAL_FALLBACK=false` in `.env`, run `docker compose up -d`, and repeat it.
The first Docker build downloads the Maven and Temurin images and the Maven dependencies; allow several minutes.

## Cost controls

- One generation per conversion; `CLAUDE_MAX_GENERATIONS_PER_DAY` (default 5) stops further calls for 24 hours.
- Each result shows input and output tokens and an estimate at $4 / $20 per million tokens for Claude Opus 5.5
  (set `CLAUDE_MODEL=claude-sonnet-5-5` in `.env` for $2 / $10).
- `CLAUDE_EFFORT` (default `high`) and `CLAUDE_MAX_OUTPUT_TOKENS` (default 64000) bound a single call.

## After testing: remove the key

1. `./scripts/remove-anthropic-key.sh` or `./scripts/remove-gemini-key.sh` removes it from `.env`, restarts the backend and
   verifies the backend no longer has it.
2. Delete the key in the Anthropic Console or Google AI Studio so no copy can spend.
3. Optionally disable the provider's source transfer in Security & access.

## What the trial does and does not prove

- Equivalence covers only the recorded scenarios replayed for the candidate; untested behaviour is unknown.
- The reproducible baseline build of the source-task lane is replaced by the recorded behaviour of the original application.
- Data ownership and migration are not decided by a trial; a shared database stays an open question in the checklist.
- Nothing is merged, published or deployed; production goes through your own pipeline with the hand-off package.
