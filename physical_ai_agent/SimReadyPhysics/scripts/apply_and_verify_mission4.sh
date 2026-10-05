#!/usr/bin/env bash
# Mission 4: build the physical stage, install, build, test, restart, and prove
# the portal is physics-ready.
#
# Safe by construction: it never clicks Play, never sends physics.play, never
# creates an ovphysx instance or pose binding, never steps physics, and never
# runs a drop test. The cube falls only when the user clicks Play afterwards.
#
# Needs no other browser attached to the stream: the portal serves ONE WebRTC
# client, so close any open Attic tab first.
set -euo pipefail

SESSION_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$SESSION_ROOT/Attic_Portal"
cd "$APP"
export ATTIC_PORTAL_MISSION_STAGE="$SESSION_ROOT/OldAttic_Mission_4_Physics.usda"
# shellcheck disable=SC1091
source ./env.sh

echo "== install"
[[ -d frontend/node_modules ]] || (cd frontend && npm install --no-audit --no-fund)

echo "== source hashes before"
SOURCES=("$SESSION_ROOT/OldAttic_Mission_3_Fixed.usda" "$SESSION_ROOT/OldAttic_Mission_2.usda" "$SESSION_ROOT/C9_ContainmentPod.usda" "$SESSION_ROOT/C9_ContainmentPod_Mission_3_Fixed.usda")
for f in "${SOURCES[@]}"; do [[ -f "$f" ]] || { echo "missing source scene: $f" >&2; exit 1; }; done
BEFORE="$(sha256sum "${SOURCES[@]}")"
echo "$BEFORE"

echo "== build frontend and server"
(cd frontend && npm run build)
"$ATTIC_PORTAL_PYTHON" -m py_compile server/*.py

echo "== build physical stage (pxr only; no physics)"
"$ATTIC_PORTAL_PYTHON" server/r17_physics_stage.py build --outlines "$APP/artifacts/R17_PhysicsOutlines.usda" | tail -25

echo "== focused checks (temp dirs; no ovphysx)"
"$ATTIC_PORTAL_PYTHON" validation/mission4_stage_contract_check.py
"$ATTIC_PORTAL_PYTHON" validation/mission4_play_guard_check.py

echo "== restart"
# The server log accumulates across restarts; judge only what this run writes.
LOG_START=$(( $(wc -l < logs/server.log 2>/dev/null || echo 0) + 1 ))
./scripts/restart.sh
for _ in $(seq 1 60); do curl -sf localhost:8082/healthz >/dev/null && break; sleep 2; done
curl -sf localhost:8082/healthz >/dev/null || { echo "server did not become healthy" >&2; exit 1; }
sleep 8

if tail -n +"$LOG_START" logs/server.log | grep -q 'WebRTC connected=True'; then
  echo "Another browser is attached to the stream; close the Attic tab and re-run." >&2
  exit 2
fi

echo "== readiness smoke (clicks nothing)"
SMOKE_LOG_START="$LOG_START" "$ATTIC_PORTAL_PYTHON" validation/browser_mission4_ready.py

echo "== final checks"
if tail -n +"$LOG_START" logs/server.log | grep -q 'physics.play'; then echo "FAIL: physics.play in this run's log" >&2; exit 1; fi
AFTER="$(sha256sum "${SOURCES[@]}")"
[[ "$BEFORE" == "$AFTER" ]] || { echo "FAIL: a source hash changed" >&2; exit 1; }
echo "OK: stage built, physics-ready, nothing played, sources unchanged."
echo "App open: http://127.0.0.1:${ATTIC_PORTAL_CLIENT_PORT}/?server=${VITE_SERVER_HOST}&signalingport=49101"
echo "Click Play to drop the Memory Cube (manual test)."
