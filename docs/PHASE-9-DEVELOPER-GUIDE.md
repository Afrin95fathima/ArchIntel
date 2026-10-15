# Phase 9 developer handoff

## Support-report workflow

`backend/app/system/service.py::support_bundle_preview` constructs a deterministic, minimal report from local system diagnostics. It intentionally selects only fixed status fields; it does not read logs, paths, environment values, configuration secrets, database rows, runtime events, or architecture snapshots. A SHA-256 fingerprint binds the explicit preview to the exact manifest and report.

`GET /api/v1/system/support-bundle/preview` returns the proposed content and exclusions. `POST /api/v1/system/support-bundle/export` requires the preview fingerprint and recomputes current content. A mismatch returns 409. A matching export is audited before response. The client downloads JSON locally; there is no upload path and no server-side bundle retention.

The UI is in `frontend/src/LocalDiagnostics.tsx`. Keep preview and export as separate user actions. Any future file/log additions require strict allowlisting, redaction tests, bounded size, updated disclosure, and audit review.

## Scope and limitations

This is a safe support-status report, not the complete Phase 9 support-bundle specification. It does not prove deployment security. No Docker image/Compose path, signing/update manager, license verifier, encryption/key lifecycle, encrypted backup restore, or offline install has been accepted. Full Phase 9 remains open.
