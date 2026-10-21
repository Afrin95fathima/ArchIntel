#!/usr/bin/env bash
# Store the Anthropic API key in the git-ignored .env with hidden input, then restart ArchIntel so it reads it.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"; env_file="$root/.env"; touch "$env_file"; chmod 600 "$env_file"
printf 'Anthropic API key (input hidden): '; IFS= read -rs key; echo
case "$key" in ''|*[[:space:]]*) echo "The key must be one non-empty token." >&2; exit 1;; esac
tmp="$(mktemp "$root/.env.XXXXXX")"; grep -v '^ANTHROPIC_API_KEY=' "$env_file" > "$tmp" || true
printf 'ANTHROPIC_API_KEY=%s\n' "$key" >> "$tmp"; mv "$tmp" "$env_file"; chmod 600 "$env_file"; unset key
(cd "$root" && docker compose up -d backend >/dev/null)
echo "Key saved to .env (git-ignored) and ArchIntel restarted. Remove it after testing with scripts/remove-anthropic-key.sh."
