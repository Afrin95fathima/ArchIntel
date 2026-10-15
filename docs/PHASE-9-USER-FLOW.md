# Phase 9 user flow: preview and download a local support report

Open **Local setup** and find **Local support bundle**. Select **Preview included data** and inspect the file list, exclusions, local-download-only statement, and fingerprint. Choose **Confirm and download** only after reviewing the preview. If the status changes between preview and confirmation, ArchIntel rejects the export and you must preview again.

The resulting `archintel-support-bundle.json` contains limited health/status metadata. It does not include source code, secrets, environment values, logs, database contents, runtime payloads, or architecture/customer data. ArchIntel does not upload the file; share it only through a channel you choose.

This first Phase 9 slice does not provide signed updates, licensing, Docker/Compose deployment, encrypted backup/restore, or air-gap acceptance.
