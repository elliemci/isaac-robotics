#!/usr/bin/env bash
# Mission 3 Part 2: install, build, test, restart, and prove readiness.
#
# Safe by construction: it never clicks "run fixes", never sends
# simready.fixTargets, and never writes the *_Mission_3_Fixed.usda outputs or
# R17_PhysicsOutlines.usda. It clicks only "run targets", confirms RB.MB.001
# enables "run fixes", then stops with the app left running.
#
# Needs no other browser attached to the stream: the portal serves ONE WebRTC
# client, so close any open Attic tab first.
set -euo pipefail

SESSION_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$SESSION_ROOT/Attic_Portal"
cd "$APP"
# shellcheck disable=SC1091
source ./env.sh

echo "== install"
[[ -d frontend/node_modules ]] || (cd frontend && npm install --no-audit --no-fund)

echo "== build"
(cd frontend && npm run build)
"$ATTIC_PORTAL_PYTHON" -m py_compile server/*.py

echo "== hashes before"
SOURCES=("$SESSION_ROOT/OldAttic_Mission_2.usda" "$SESSION_ROOT/C9_ContainmentPod.usda")
BEFORE="$(sha256sum "${SOURCES[@]}")"
echo "$BEFORE"

echo "== focused tests (temp copies only; no real outputs)"
"$ATTIC_PORTAL_PYTHON" validation/simready_fix_guard_check.py
"$ATTIC_PORTAL_PYTHON" validation/simready_fix_logic_check.py

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

echo "== idle-to-ready smoke (clicks only run targets)"
"$ATTIC_PORTAL_PYTHON" validation/browser_simready_part2_ready.py

echo "== checks"
if tail -n +"$LOG_START" logs/server.log | grep -q 'simready.fixTargets'; then echo "FAIL: simready.fixTargets in log" >&2; exit 1; fi
AFTER="$(sha256sum "${SOURCES[@]}")"
[[ "$BEFORE" == "$AFTER" ]] || { echo "FAIL: a source hash changed" >&2; exit 1; }
for f in "$SESSION_ROOT/OldAttic_Mission_3_Fixed.usda" "$SESSION_ROOT/C9_ContainmentPod_Mission_3_Fixed.usda" "$APP/artifacts/R17_PhysicsOutlines.usda"; do
  [[ ! -e "$f" ]] || { echo "FAIL: $f exists" >&2; exit 1; }
done
echo "OK: sources unchanged, no fix command sent, no outputs written."
echo "App open: http://127.0.0.1:${ATTIC_PORTAL_CLIENT_PORT}/?server=${VITE_SERVER_HOST}&signalingport=49101"
echo "Open it, click run targets, then run fixes (the manual test)."
