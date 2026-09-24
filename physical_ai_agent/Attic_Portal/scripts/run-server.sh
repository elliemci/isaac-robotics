#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION_ROOT="${SESSION_ROOT:-$(cd "$ROOT/.." && pwd)}"
LOG="$ROOT/logs/server.log"

python_has_required_imports() {
  "$1" -c 'import importlib; [importlib.import_module(name) for name in ("ovrtx", "ovstream", "warp", "numpy")]' >/dev/null 2>&1
}

find_python() {
  if [[ -n "${ATTIC_PORTAL_PYTHON:-}" ]]; then
    if ! python_has_required_imports "$ATTIC_PORTAL_PYTHON"; then
      echo "ATTIC_PORTAL_PYTHON does not import ovrtx, ovstream, warp, numpy: $ATTIC_PORTAL_PYTHON" >&2
      exit 1
    fi
    printf '%s\n' "$ATTIC_PORTAL_PYTHON"
    return
  fi

  for candidate in \
    "$SESSION_ROOT/area_51b_ovrtx_minimal/.venv/bin/python" \
    "$SESSION_ROOT/../evidence-lab-ovrtx-minimal/.venv/bin/python" \
    "$HOME/evidence-lab-ovrtx-minimal/.venv/bin/python"; do
    if [[ -x "$candidate" ]] && python_has_required_imports "$candidate"; then
      printf '%s\n' "$candidate"
      return
    fi
  done

  if command -v python3 >/dev/null 2>&1 && python_has_required_imports "$(command -v python3)"; then
    command -v python3
    return
  fi

  echo "missing Python with ovrtx, ovstream, warp, numpy. Set ATTIC_PORTAL_PYTHON=/path/to/python" >&2
  exit 1
}

PYTHON="$(find_python)"
MISSION_STAGE="${ATTIC_PORTAL_MISSION_STAGE:-$SESSION_ROOT/Attic_NVIDIA/OldAttic_Mission.usda}"

mkdir -p "$ROOT/logs" "$ROOT/artifacts"
export OVRTX_SKIP_USD_CHECK=1

exec "$PYTHON" "$ROOT/server/attic_portal_server.py" \
  --stage "$MISSION_STAGE" \
  --width "${ATTIC_PORTAL_WIDTH:-960}" \
  --height "${ATTIC_PORTAL_HEIGHT:-540}" \
  --fps "${ATTIC_PORTAL_FPS:-30}" \
  --signaling-port "${ATTIC_PORTAL_SIGNALING_PORT:-49101}" \
  --health-port "${ATTIC_PORTAL_HEALTH_PORT:-8082}" \
  --public-ip "${ATTIC_PORTAL_PUBLIC_IP:-127.0.0.1}" \
  --log "$LOG"
