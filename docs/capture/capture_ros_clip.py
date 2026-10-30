"""Opens a USD in headless Isaac Sim, plays it, then starts the frame recorder.

Run: isaac-sim.sh --no-window --enable isaacsim.ros2.bridge --exec docs/capture/capture_ros_clip.py
Env: CLIP_USD (scene), plus the CAP_* variables of isaacsim_recorder.py.
The scene is opened, never saved. A ROS 2 CLI publisher drives the robot from outside.
"""
import asyncio
import os
from pathlib import Path

import omni.kit.app
import omni.timeline
import omni.usd


async def _main():
    app = omni.kit.app.get_app()
    for _ in range(60):
        await app.next_update_async()
    await omni.usd.get_context().open_stage_async(os.environ["CLIP_USD"])
    for _ in range(200):
        await app.next_update_async()
    omni.timeline.get_timeline_interface().play()
    exec(compile((Path(__file__).parent / "isaacsim_recorder.py").read_text(), "isaacsim_recorder.py", "exec"), globals())


asyncio.ensure_future(_main())
