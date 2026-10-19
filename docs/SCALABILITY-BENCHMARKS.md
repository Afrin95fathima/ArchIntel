# Scalability benchmark method

Run from the repository root:

```powershell
\.runtime\python\tools\python.exe scripts\benchmark_scalability.py `
  --classes 100 1000 5000 10000 --modules 7 --repeats 3 `
  --profile-classes 10000 --output docs\benchmarks\benchmark.json
```

The deterministic fixture contains modular dependency chains, package groups, and bounded cross-module dependencies. Reports include class/package/edge counts, SCC and issue counts, coupling density, largest package, compact result size, median analysis time, process peak working set where available, and an optional separate cProfile run. Profiling adds overhead and its timings must not be compared with unprofiled measurements.

The checked-in [Windows measurement](benchmarks/2026-10-15-local-windows.md) contains observed results for 100, 1,000, 5,000 and 10,000 classes. It measures only the pure in-process architecture analysis function. It excludes artifact upload/validation, jQAssistant, Neo4j extraction, PostgreSQL persistence, queueing, concurrent tenants, browser rendering, and runtime telemetry ingestion. Results depend on host load, Python and library versions, and graph shape. They are comparative observations, not supported-capacity claims.

The generator accepts the 7 x 40,000-class shape with `--classes 280000 --modules 7`; this workload has not been run or capacity-validated. Use it only on a host with sufficient free memory, and record its results separately. Do not overwrite customer data or make latency/capacity claims from synthetic measurements.

## Ingestion limits

`GET /api/v1/limits` reports effective deployment limits. Settings use the existing `Settings` environment names, including `MAX_UPLOAD_MB`, `MAX_EXPANDED_MB`, `MAX_ARCHIVE_ENTRIES`, `MAX_COMPRESSION_RATIO`, `MAX_CLASSES`, `MAX_EDGES`, `MAX_PACKAGES_PER_SCAN`, `SCAN_TIMEOUT_SECONDS`, `MAX_JOB_DISK_MB`, `RUNTIME_MAX_SPAN_SIZE_BYTES`, and `RUNTIME_MAX_SESSION_DURATION_HOURS`. Existing `RUNTIME_MAX_BODY_BYTES`, `RUNTIME_MAX_BATCH_SPANS`, `RUNTIME_MAX_SESSION_SPANS`, and `RUNTIME_RAW_TRACE_RETENTION_HOURS` remain enforced.

New defaults marked as unvalidated placeholders in `backend/app/config.py` are not capacity claims. `scripts/ramp_ingestion_limits.py` runs a synthetic in-process analysis ramp and emits a human-review suggestion at 75% of the largest completed size. Its memory budget is informational, not enforced. It excludes upload, extraction, the scanner/Neo4j, persistence, concurrency, and telemetry; run representative end-to-end tests under an OS/container resource limit before applying any suggested production values. The blank measurement record is [capacity.md](capacity.md).

Still requiring separate architecture work: per-tenant/project override storage and quotas; max modules and merged-project ceilings; OTLP per-second tenant/session rate limiting and retained-event count; API request-rate limiting; per-stage watchdogs and hard JVM/Python memory caps; and interruptible scanner cancellation. The current app is a single worker process, so its stage checks are cooperative boundaries rather than preemptive process isolation. Package/edge checks occur while converting/exporting scanner results, not during Neo4j’s internal graph construction.
