#!/usr/bin/env bash
# Run one live test step inside the backend container. Steps: preflight, claude-smoke, explore, explore-api, convert, status.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
step="${1:?usage: scripts/live-test.sh <preflight|claude-smoke|explore|explore-api|convert|status> [options]}"; shift
if [ "$step" = explore ] && [ -n "${JAR:-}" ]; then (cd "$root" && docker compose cp "$JAR" backend:/tmp/petclinic.jar >/dev/null); fi
if [ "$step" = explore-api ] && [ -n "${DIST:-}" ]; then (cd "$root" && docker compose cp "$DIST" backend:/tmp/distribution.tar.gz >/dev/null); fi
if [ "$step" = explore-api ]; then                         # DIST_AGENT=<agent dist> and so on, for the recipe's other distributions
  for var in $(compgen -v DIST_ || true); do
    id="$(printf '%s' "${var#DIST_}" | tr 'A-Z_' 'a-z-')"; (cd "$root" && docker compose cp "${!var}" "backend:/tmp/distribution-$id.tar.gz" >/dev/null)
  done
fi
cd "$root" && exec docker compose exec -T -w /app/backend backend python /app/scripts/live_tests.py "$step" "$@"
