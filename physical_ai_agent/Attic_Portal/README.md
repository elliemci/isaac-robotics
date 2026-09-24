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
