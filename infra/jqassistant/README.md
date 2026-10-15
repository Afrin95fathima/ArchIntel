# Scanner integration decision

The working adapter is `backend/app/services/scanner.py`; the graph reader is `backend/scanner-java/ExportGraph.java`.

jQAssistant 2.7.0 scans application class directories with explicit Java classpath scope. Each run uses its own absolute, normalized embedded Neo4j home. After scanning, the Java reader opens the store directly and exports parameterized structural query results. This avoids the transient web-server lifecycle problem found in the initial Bolt spike.

Build the helper with `scripts/build_exporter.ps1`. The regression suite verifies ordinary JAR, WAR and Spring Boot layouts against known synthetic bytecode. See the developer guide for semantics and limits.

Reference: [official jQAssistant manual](https://jqassistant.github.io/jqassistant/current/). Runtime behavior was verified against the downloaded 2.7.0 distribution and bundled Neo4j 5.26.5, not inferred solely from current documentation.

The adjacent YAML is only a manual spike example. The application generates an absolute per-job store URI and does not use this file.
