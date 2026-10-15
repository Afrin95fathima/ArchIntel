# Gemini service-generation setup

ArchIntel supports a gated one-service-at-a-time Gemini generation flow. Gemini receives the selected service's mapped source files and reviewed behavioral-contract summaries. It does not receive the entire source checkout unless those files are part of the selected candidate mapping. The generated code is untrusted and is stored locally as a separate Git repository in `GENERATED_UNVALIDATED` state. Do not use it as production-ready code.

## Configure the local credential

The key previously pasted into chat is exposed. Revoke it in Google AI Studio and create a replacement before use. Do not send the replacement through chat or put it in source control.

From the ArchIntel project folder, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\set-gemini-key.ps1
```

Enter the replacement key at the hidden prompt, then restart ArchIntel. The script stores it in the project-root `.env`, which is ignored by Git. Check `GET /api/v1/security/ai/gemini/status`; it reports whether the key exists and the selected model, never the key value. The default model is `gemini-3.8-flash`; set `GEMINI_MODEL` in local `.env` to use another supported Gemini model.

## Enable the source-transfer safeguards

1. Sign in as a workspace `SECURITY_ADMIN` and open **Security & access**.
2. In **Gemini source-transfer policy**, enable the setting only if that workspace is permitted to send selected source to Google for processing. This setting is off by default.
3. Register the exact source checkout and commit, grant the task identity only the needed source paths, and enable source tasks.
4. In **Modernization intelligence**, approve the planning proposal and select one candidate. Whole-system generation is not enabled.
5. Prepare a task from the candidate. Use a complete snapshot of the same repository commit, limit allowed paths to the task, run a passing baseline build, and add/review behavioral contracts for the behavior being extracted.
6. In that task's **Overview**, read the transfer notice and tick the per-request acknowledgement before generating. This authorizes only that single request. ArchIntel sends the mapped candidate files and reviewed contract summaries over HTTPS to Gemini.
7. Review the separate local Git repository and all unresolved questions. The generated repository has not yet passed its own isolated build, test, dependency/security scans, architecture comparison, or publication approval.

ArchIntel does not push, deploy, migrate production data, or claim that generated tests pass. Stop if a candidate has ambiguous source mapping, crossing cycles, missing baseline evidence, or incomplete contracts; resolve those blockers before requesting generation.
