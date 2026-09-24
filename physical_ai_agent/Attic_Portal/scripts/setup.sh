#!/usr/bin/env bash
set -euo pipefail

APP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION_ROOT="${SESSION_ROOT:-$(cd "$APP/.." && pwd)}"
PYPROJECT_ROOT="${ATTIC_PORTAL_PYPROJECT_ROOT:-$SESSION_ROOT/area_51b_ovrtx_minimal}"
NODE="$APP/.tools/bin"

cd "$PYPROJECT_ROOT"
uv sync
uv run python - <<'PYSETUP'
import ovrtx, ovstream, warp as wp
print('ovrtx', ovrtx.Renderer().version)
ovstream.initialize()
ovstream.shutdown()
wp.init()
print('ovstream+warp ok')
PYSETUP
if [ ! -x "$NODE/node" ]; then
  mkdir -p "$APP/.tools"
  curl -L https://nodejs.org/dist/v20.19.0/node-v20.19.0-linux-x64.tar.xz -o "$APP/.tools/node.tar.xz"
  tar -xf "$APP/.tools/node.tar.xz" -C "$APP/.tools" --strip-components=1
fi
cd "$APP/frontend"
PATH="$NODE:$PATH" npm install
PATH="$NODE:$PATH" npm run build
