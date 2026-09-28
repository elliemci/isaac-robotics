#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SESSION_ROOT = ROOT.parent
BASE_STAGE = Path(os.environ.get("ATTIC_PORTAL_BASE_STAGE", SESSION_ROOT / "Attic_NVIDIA/Attic_NVIDIA.usd"))
MISSION_STAGE = Path(os.environ.get("ATTIC_PORTAL_MISSION_STAGE", SESSION_ROOT / "Attic_NVIDIA/OldAttic_Mission.usda"))
MEMORY_CUBE_PATH = "/Root/Workshop/Cube"
EXPECTED_ROLE = "Memory Cube"
EXPECTED_HASHES = {
    str(BASE_STAGE): "12db25c282bcf57ba371381d96c5ea11dd0709386493b27e99b2c6c70992502c",
    str(MISSION_STAGE): "80b9adfcef7a587caddd0eb04dfa85d84baff52f4bb80712d9f19bad29657739",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    missing = [str(path) for path in (BASE_STAGE, MISSION_STAGE) if not path.is_file()]
    if missing:
        raise SystemExit(f"missing stage inputs: {missing}")

    hashes = {path: sha256(Path(path)) for path in EXPECTED_HASHES}
    if hashes != EXPECTED_HASHES:
        raise SystemExit(f"protected stage hash mismatch: actual={hashes} expected={EXPECTED_HASHES}")

    mission_text = MISSION_STAGE.read_text(encoding="utf-8")
    marker = 'custom string mission:role = "Memory Cube"'
    if mission_text.count(marker) != 1:
        raise SystemExit(f"expected one {marker!r} marker")

    matches = [(MEMORY_CUBE_PATH, EXPECTED_ROLE)]
    print(f"base_stage={BASE_STAGE.expanduser().resolve()}")
    print(f"mission_stage={MISSION_STAGE.expanduser().resolve()}")
    print(f"memory_cube_matches={matches}")


if __name__ == "__main__":
    main()
