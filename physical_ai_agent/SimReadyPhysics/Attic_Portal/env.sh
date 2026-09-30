#!/usr/bin/env bash
# Environment for launching the Attic Portal on this VM.
# Use:  source env.sh && ./scripts/restart.sh
# Any variable already set in your shell wins over the default below.

_ATTIC_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_ATTIC_OLD_TREE="$HOME/Documents/physical_ai_agent/RTXViewport"

# Python with ovrtx, ovstream, warp, numpy (ovphysx/ovstage come from .tools/pydeps).
export ATTIC_PORTAL_PYTHON="${ATTIC_PORTAL_PYTHON:-$_ATTIC_OLD_TREE/area_51b_ovrtx_minimal/.venv/bin/python}"

# Protected base scene that the composite stage sublayers.
export ATTIC_PORTAL_BASE_STAGE="${ATTIC_PORTAL_BASE_STAGE:-$_ATTIC_OLD_TREE/Attic_NVIDIA/Attic_NVIDIA.usd}"

# Scene the server launches with (Mission 2).
export ATTIC_PORTAL_MISSION_STAGE="${ATTIC_PORTAL_MISSION_STAGE:-$_ATTIC_ROOT/../OldAttic_Mission_2.usda}"

# WebRTC needs a routable address, not 127.0.0.1.
export ATTIC_PORTAL_PUBLIC_IP="${ATTIC_PORTAL_PUBLIC_IP:-$(hostname -I | awk '{print $1}')}"
export VITE_SERVER_HOST="${VITE_SERVER_HOST:-$ATTIC_PORTAL_PUBLIC_IP}"

# 5176 is often held by an orphaned vite from the RTXViewport/Attic_Portal copy.
export ATTIC_PORTAL_CLIENT_PORT="${ATTIC_PORTAL_CLIENT_PORT:-5177}"

unset _ATTIC_ROOT _ATTIC_OLD_TREE
echo "Attic Portal env ready: host=$VITE_SERVER_HOST client_port=$ATTIC_PORTAL_CLIENT_PORT"
