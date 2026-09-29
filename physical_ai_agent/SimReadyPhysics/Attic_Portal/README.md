# Attic Portal

Browser-streamed Omniverse Realtime Viewer for `/home/nvidia/Desktop/Session_1/Attic_NVIDIA/OldAttic_Mission.usda`.

## Setup

```bash
cd /home/nvidia/evidence-lab-ovrtx-minimal
attic-portal/scripts/setup.sh
```

## Run

Terminal 1:

```bash
cd /home/nvidia/evidence-lab-ovrtx-minimal
OLD_ATTIC_MISSION_STAGE_PATH=/home/nvidia/Desktop/Session_1/Attic_NVIDIA/OldAttic_Mission.usda ATTIC_PORTAL_PUBLIC_IP=10.110.50.187 attic-portal/scripts/run-server.sh
```

Terminal 2:

```bash
cd /home/nvidia/evidence-lab-ovrtx-minimal
attic-portal/scripts/run-client.sh
```

Open `http://127.0.0.1:5173/?server=10.110.50.187&signalingport=49100`.

Health check:

```bash
curl -fsS http://127.0.0.1:8081/healthz
```

The server writes its first direct RTX frame to `attic-portal/artifacts/attic-portal-first-frame.png` and logs `First BGRA frame ready: 960x540` after the render path is valid.

## Physics Probe (Mission 1)

The panel's **Run Physics Simluation** section has a **▶ PLAY** button. Play sends
`physics.play` over `r17-command-v1`; the renderer-owner thread then loads the
composed stage (`artifacts/attic-portal-composite.usda`) into ovphysx, advances
it by one fixed `dt = 1/60` step, reads `RIGID_BODY` position/orientation, and
releases the runtime. Results are published under `physics` in `state.json` and
in every `r17-state-v1` payload.

The current authored scene has no PhysX rigid bodies, so the expected result is
`status=NOT_SIMULATION_READY`, `rigidBodyCount=0`, `bridgeReady=false`, and a
rendered scene that does not move. The probe is read-only: it authors no USD and
writes no pose back to ovrtx.

ovphysx and ovstage are installed beside the app (`.tools/pydeps`, added to
`PYTHONPATH` by `scripts/run-server.sh`) so the shared ovrtx environment is not
modified. `scripts/setup.sh` installs them with `--no-deps`. If the protected
scene is not a sibling `Attic_NVIDIA/` directory, set `ATTIC_PORTAL_BASE_STAGE`
to `Attic_NVIDIA.usd`.

Validate against a freshly started server:

```bash
python validation/browser_physics_smoke.py   # writes artifacts/r17-physics-probe.png
```
