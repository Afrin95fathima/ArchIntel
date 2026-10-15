# The public database is mounted read-only from .runtime/trivy-cache on the
# host. This keeps its large files on the project's data drive, not Docker's
# WSL disk image. Runtime scans have no network access.
ARG TRIVY_BASE
FROM ${TRIVY_BASE}
USER 1000:1000
WORKDIR /work
ENTRYPOINT ["/bin/sh"]
