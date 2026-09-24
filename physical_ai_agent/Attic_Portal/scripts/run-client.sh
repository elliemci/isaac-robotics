#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NODE_BIN="$ROOT/.tools/bin"

cd "$ROOT/frontend"
export PATH="$NODE_BIN:$PATH"
export VITE_SERVER_HOST="${VITE_SERVER_HOST:-127.0.0.1}"
export VITE_SIGNALING_PORT="${VITE_SIGNALING_PORT:-49101}"

exec npm run dev -- --host 0.0.0.0 --port "${ATTIC_PORTAL_CLIENT_PORT:-5176}" --strictPort
