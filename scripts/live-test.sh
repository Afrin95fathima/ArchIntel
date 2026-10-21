#!/usr/bin/env bash
# Run one live test step inside the backend container. Steps: preflight, claude-smoke, explore, convert, status.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
step="${1:?usage: scripts/live-test.sh <preflight|claude-smoke|explore|convert|status> [options]}"; shift
if [ "$step" = explore ] && [ -n "${JAR:-}" ]; then (cd "$root" && docker compose cp "$JAR" backend:/tmp/petclinic.jar >/dev/null); fi
cd "$root" && exec docker compose exec -T -w /app/backend backend python /app/scripts/live_tests.py "$step" "$@"
