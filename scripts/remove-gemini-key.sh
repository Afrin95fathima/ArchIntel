#!/usr/bin/env bash
# Remove the Anthropic API key from .env, restart ArchIntel, and verify the running backend no longer has it.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"; env_file="$root/.env"
if [ -f "$env_file" ]; then tmp="$(mktemp "$root/.env.XXXXXX")"; grep -v '^GEMINI_API_KEY=' "$env_file" > "$tmp" || true; mv "$tmp" "$env_file"; chmod 600 "$env_file"; fi
(cd "$root" && docker compose up -d backend >/dev/null)
sleep 3
if (cd "$root" && docker compose exec -T backend sh -c 'test -n "$GEMINI_API_KEY"'); then echo "The backend still has GEMINI_API_KEY set." >&2; exit 1; fi
echo "Removed from .env and from the running backend."
echo "Now revoke the key in the Google AI Studio (API keys) so no copy can spend."
