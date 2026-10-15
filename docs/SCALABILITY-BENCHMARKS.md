# Scalability benchmark method

Run `python scripts/benchmark_scalability.py --classes 100 500 1000 --repeats 3` from the repository root. The deterministic synthetic fixture creates a fixed 20-package dependency graph with a repeatable edge pattern. Each run reports actual class/edge/domain counts, per-run elapsed time, the median, host/runtime details, and process maximum resident set size.

The script measures only the pure in-process architecture analysis function. It does not measure artifact upload or validation, jQAssistant, Neo4j extraction, PostgreSQL persistence, queueing, concurrent tenants, browser rendering, or runtime telemetry ingestion. Results depend on host load, Python and library versions, and graph shape. They are comparative observations, not supported-capacity claims.

Use the same machine, dependency lock, power mode, and command when comparing revisions. Preserve raw JSON with the commit and environment details. Do not overwrite customer data; benchmark output should go to an explicitly chosen path. Avoid large sizes on constrained hosts until a small run establishes memory behavior.

No benchmark result is checked into this repository yet. Run the command in the target customer environment before making performance or capacity statements.
