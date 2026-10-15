# Phase 2 delivery and verification

Delivered for user verification on 4 October 2026. The local AI gateway slice of the enterprise roadmap is implemented. Phase 3 has not started. Remote providers, code generation/execution and production deployment certification are outside this delivery.

## Work completed and outcome

| Work | Outcome |
|---|---|
| Central model gateway | Static and runtime assistants use the same authorization, filtering, budget, dispatch and response-validation path |
| Local adapter and registry | Installed Ollama model registration, model digest checks, enable/disable and connectivity controls; qwen2.5:0.5b installed and exercised |
| Context minimization | At most 12 facts; source scopes enforced through the existing gateway, then explicit bounded line ranges; opaque model citation IDs |
| Filtering | Offline detect-secrets adapter, supplementary credential patterns, Unicode/injection checks and known-identifier redaction/block policy; exact outgoing user envelope rescanned |
| Model policy | Explicit MODEL_USE_LOCAL, disabled-by-default policy, operator-approved loopback endpoint, context/output/attempt budgets and no external fallback |
| Response validation | Only valid, unique supplied evidence IDs accepted; generated prose, commands, tool responses and forged references cannot become displayed facts |
| Audit | Correlated durable request/outcome events plus metadata-only invocation history, with no prompt, source text or raw reply persistence |
| Product UI | Model registration/check/state, policy controls, identity permission toggle, authorized source-range query and invocation history |
| Handoff | Updated roadmap, main manuals, Phase 2 user flow and developer guide in Markdown, HTML and PDF |

## Executed tests

| Verification | Result |
|---|---|
| Complete backend suite with real scanner and model integration enabled | **114 passed** in 403.26 seconds |
| Final AI suite after metadata/config updates, including newly added real runtime-model integration | **31 passed** in 135.23 seconds |
| Added real PostgreSQL + Ollama integration in an isolated schema | **1 passed** in 27.04 seconds; temporary schema removed |
| Frontend unit tests | **5 passed** |
| TypeScript and Vite production build | Passed |
| Real Chrome setup/access, investor static walkthrough/export, and fresh WAR upload | **3 passed** in the browser suite |
| Real Chrome AI registration, connection, policy enablement, real model-assisted answer, history and disablement | **1 passed** in the corrected focused rerun (1.9 minutes including server setup) |
| Python dependency consistency | pip check: no broken requirements |
| Frontend dependency consistency | npm ls --depth=0: passed |

There are **116 current backend cases with passing evidence across the full and subsequent targeted runs**: the final runtime-model and PostgreSQL checks were added after the 114-test run. This is not claimed as one uninterrupted 116-test run. Likewise, the four browser workflows passed across the original run and corrected focused rerun.

The initial detector integration treated all high-entropy plugin candidates as secrets before applying the plugin's entropy threshold. Correcting the adapter fixed the false positives; the full 114-test run occurred afterward. The initial AI browser test timed out on a label locator; the control's accessible combobox locator was used in the successful rerun. These were fixed before handoff.

Security tests exercised: zero-byte denial for non-allowlisted/remote endpoints; no external fallback; real loopback HTTP redirect and oversize rejection; ignored proxy environment; missing model permission; tenant-scoped provider/history/policy references; hourly budgets; model digest changes; source scope and source revocation during inference; provider revocation; PII redaction/block; secret/injection rejection; filter/audit failure; malformed/additional/duplicate/forged response fields; pinned source-range selection; actual static and runtime model execution.

The real PostgreSQL integration used the installed local model, verified accepted invocation storage and audit integrity, then verified the hourly budget denial. It created its own test schema and removed it afterward; it did not initialize, modify or grant privileges to the real user account.

Warnings remaining: FastAPI/Starlette test-client deprecations and a Vite minified JavaScript chunk of approximately 784 KB. Dependency consistency is not a vulnerability scan. No new PetClinic traffic capture or model-quality benchmark is claimed.

## Database preservation and live state

Startup migrated the real PostgreSQL database from 0003 to 0004. No active scans or accepting runtime sessions were present before restart. A private local row snapshot and hash checks were stored under `.data/phase2-migration-snapshot`.

| Existing table | Rows | Before/after comparison |
|---|---:|---|
| projects | 7 | Unchanged |
| applications | 7 | Unchanged |
| artifacts | 8 | Unchanged |
| analysis_runs | 8 | Unchanged |
| runtime_sessions | 3 | Unchanged |
| security_principals | 1 | Unchanged |
| security_policy_revisions | 1 | Unchanged |
| security_repositories | 0 | Unchanged |
| security_source_grants | 0 | Unchanged |

The additive migration creates ai_providers and ai_invocations only. Existing user permissions and workspace model policy were deliberately preserved. The installed model was exercised with synthetic test evidence; no existing customer analysis was automatically sent to it.

The updated application responds ready at http://127.0.0.1:8000. To use local AI in the real workspace, the administrator must grant MODEL_USE_LOCAL, register the installed model, and enable the workspace policy. Deterministic static/runtime analysis remains available while the model policy is off.

## Limits and next gate

- Only the local Ollama adapter is enabled. The provider contract supports future adapters, but remote/customer-enterprise/private-cloud/external-approved connections and their secret-management/approval flows are not implemented.
- Detection is heuristic and limited to the documented credential/identifier patterns. It does not certify that every sensitive datum or adversarial instruction is recognized.
- Application-level loopback/redirect/proxy restrictions are enforced and tested. OS firewall rules, isolation of an independently managed model server, offline distribution and air-gap certification remain deployment work.
- Models select citations; they do not generate accepted architecture facts, modify code, execute commands or prove modernization correctness. The small model's relevance quality is not benchmarked.
- One API process remains the supported deployment. Distributed authorization/budget fencing and an independent immutable audit anchor are not implemented.
- An already sent local request cannot be unsent; policy/permission/source changes suppress output at the post-inference authorization check.

## User verification

1. Sign in and open Security & access.
2. Grant your account MODEL_USE_LOCAL using Allow local model if needed.
3. Register Local Ollama at http://127.0.0.1:11434 with qwen2.5:0.5b; check its connection.
4. Select the provider and enable the workspace model policy.
5. Ask a supported question in the Architecture assistant and inspect LOCAL_MODEL_ASSISTED plus the gateway request ID in Sources and limitations.
6. Inspect Model invocation history. Disable the model policy and verify the assistant still works in deterministic mode.
7. Optionally test a specifically granted source range using PHASE-2-USER-FLOW.md.

After the user accepts this checkpoint, proceed to the approved Phase 3 runtime-foundation scope. Do not confuse a completed local gateway slice with completion of the whole enterprise modernization application.
