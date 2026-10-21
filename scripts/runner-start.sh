#!/usr/bin/env bash
# Start the host-side runner. It shares RUNNER_TOKEN with ArchIntel through the git-ignored .env file.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
env_file="$root/.env"
touch "$env_file"
if ! grep -q '^RUNNER_TOKEN=' "$env_file"; then
  printf 'RUNNER_TOKEN=%s\n' "$(openssl rand -hex 32)" >> "$env_file"
  echo "Created RUNNER_TOKEN in .env. Restart ArchIntel (docker compose up -d) so it reads the token."
fi
export RUNNER_TOKEN="$(grep '^RUNNER_TOKEN=' "$env_file" | tail -1 | cut -d= -f2-)"
export RUNNER_OTEL_AGENT="${RUNNER_OTEL_AGENT:-$root/runner/.tools/opentelemetry-javaagent.jar}"
if [ ! -f "$RUNNER_OTEL_AGENT" ]; then
  echo "OpenTelemetry Java agent not found at $RUNNER_OTEL_AGENT. Set RUNNER_OTEL_AGENT or place the agent there." >&2
fi
cd "$root/runner"
[ -d node_modules/rea-agents ] || npm ci --ignore-scripts --omit=optional --no-fund --no-audit
exec node src/server.mjs
