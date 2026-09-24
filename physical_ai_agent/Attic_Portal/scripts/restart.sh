#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT/logs"

for pid_file in "$ROOT/logs/server.pid" "$ROOT/logs/client.pid"; do
  if [[ -f "$pid_file" ]]; then
    pid="$(cat "$pid_file")"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      cmd="$(ps -p "$pid" -o args= 2>/dev/null || true)"
      if [[ "$cmd" == *"$ROOT"* ]]; then
        kill "$pid" 2>/dev/null || true
        sleep 1
      fi
    fi
  fi
done

# Stop orphaned dev-server children from earlier restarts. Killing only
# the npm PID can leave Vite alive and holding the requested port.
while read -r stale_pid stale_args; do
  [[ -z "$stale_pid" || "$stale_pid" == "$$" ]] && continue
  if [[ "$stale_args" == *"$ROOT"* ]] && { [[ "$stale_args" == *"frontend/node_modules/.bin/vite"* ]] || [[ "$stale_args" == *"npm run dev"* ]] || [[ "$stale_args" == *"sh -c vite"* ]]; }; then
    kill "$stale_pid" 2>/dev/null || true
  fi
done < <(ps -eo pid=,args=)
sleep 1
while read -r stale_pid stale_args; do
  [[ -z "$stale_pid" || "$stale_pid" == "$$" ]] && continue
  if [[ "$stale_args" == *"$ROOT"* ]] && { [[ "$stale_args" == *"frontend/node_modules/.bin/vite"* ]] || [[ "$stale_args" == *"npm run dev"* ]] || [[ "$stale_args" == *"sh -c vite"* ]]; }; then
    kill -9 "$stale_pid" 2>/dev/null || true
  fi
done < <(ps -eo pid=,args=)

nohup setsid env \
  ATTIC_PORTAL_PUBLIC_IP="${ATTIC_PORTAL_PUBLIC_IP:-127.0.0.1}" \
  ATTIC_PORTAL_SIGNALING_PORT="${ATTIC_PORTAL_SIGNALING_PORT:-49101}" \
  ATTIC_PORTAL_HEALTH_PORT="${ATTIC_PORTAL_HEALTH_PORT:-8082}" \
  "$ROOT/scripts/run-server.sh" \
  > "$ROOT/logs/server.stdout.log" 2>&1 < /dev/null &
echo "$!" > "$ROOT/logs/server.pid"

nohup setsid env \
  VITE_SERVER_HOST="${VITE_SERVER_HOST:-127.0.0.1}" \
  VITE_SIGNALING_PORT="${VITE_SIGNALING_PORT:-49101}" \
  ATTIC_PORTAL_CLIENT_PORT="${ATTIC_PORTAL_CLIENT_PORT:-5176}" \
  "$ROOT/scripts/run-client.sh" \
  > "$ROOT/logs/client.stdout.log" 2>&1 < /dev/null &
echo "$!" > "$ROOT/logs/client.pid"

CLIENT_PORT="${ATTIC_PORTAL_CLIENT_PORT:-5176}"
SERVER_HOST="${VITE_SERVER_HOST:-127.0.0.1}"
SIGNALING_PORT="${VITE_SIGNALING_PORT:-49101}"
HEALTH_PORT="${ATTIC_PORTAL_HEALTH_PORT:-8082}"

echo "server_pid=$(cat "$ROOT/logs/server.pid")"
echo "client_pid=$(cat "$ROOT/logs/client.pid")"
echo "browser_url=http://127.0.0.1:${CLIENT_PORT}/?server=${SERVER_HOST}&signalingport=${SIGNALING_PORT}"
echo "health_url=http://127.0.0.1:${HEALTH_PORT}/healthz"
