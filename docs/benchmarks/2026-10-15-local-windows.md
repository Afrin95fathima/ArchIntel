# ArcIntel analysis benchmark

## Measured run

This run used the repository's synthetic modular fixture on Windows 11, Python 3.12.10, an Intel Core-class CPU reported as family 6/model 154, and 8 logical CPUs. Each workload was analyzed three times; the table reports median in-process analysis time. The fixture contained seven balanced modules, package groups capped at 1,000 classes, internal dependency chains, and up to 40 cross-module checkpoints per module.

| Classes | Packages | Dependency pairs | Class SCCs | Issues | Result JSON size | Median analysis time |
|---:|---:|---:|---:|---:|---:|---:|
| 100 | 7 | 100 | 1 | 2 | 113,699 bytes | 0.0287 s |
| 1,000 | 7 | 1,238 | 35 | 36 | 960,504 bytes | 0.3317 s |
| 5,000 | 7 | 5,266 | 39 | 40 | 4,051,152 bytes | 1.4057 s |
| 10,000 | 14 | 10,266 | 39 | 587 | 8,243,589 bytes | 3.2459 s |

Peak process working set across the full run was **125,603,840 bytes**. This is a process high-water mark, not memory attributed to an individual case. The exact environment, sample times, and additional graph counts are in [the machine-readable result](2026-10-15-local-windows.json).

## Profile observation

A separate profiled 10,000-class run placed `discover_domains` first among substantive cumulative-cost stages. The Python Louvain `best_partition` call accumulated 6.53460 seconds under cProfile, with `__one_level` at 5.55306 seconds. Profiler timings include instrumentation overhead and should not be compared to the unprofiled median above. The community input now omits unused class metadata while preserving topology, edge-weight precedence, and the seeded partition. Further changes to the community algorithm could alter inferred candidate boundaries, so they remain open pending equivalence and scale validation.

## Case-study summary

- **Scope:** deterministic static analysis of generated graphs; no customer source, bytecode, runtime data, archive scanning, persistence, API queueing, or browser rendering.
- **Observed result:** the 10,000-class graph produced 10,266 dependency pairs, 39 class strongly connected components, 587 issues, and an 8,243,589-byte compact JSON representation in a 3.2459-second median across three runs.
- **Memory:** 125,603,840-byte process peak across all four workloads; per-workload allocation was not measured.
- **Scale status:** the generator supports a 7-module x 40,000-class workload (`--classes 280000 --modules 7`), but that workload was **not run**. The measurements do not establish its completion time, memory needs, throughput, or customer capacity.
- **Limitations:** synthetic topology and local host conditions are not representative of every enterprise graph. This does not include jQAssistant extraction, archive handling, Neo4j, database writes, API concurrency, or UI costs, and is not an SLA or capacity guarantee.

## Reproduction

```powershell
\.runtime\python\tools\python.exe scripts\benchmark_scalability.py `
  --classes 100 1000 5000 10000 --modules 7 --repeats 3 `
  --profile-classes 10000 --output docs\benchmarks\2026-10-15-local-windows.json
```

Use the scale shape only on a host with adequate available memory. It is opt-in because the generated classes, edges, intermediate graphs, and analysis result coexist in memory.
