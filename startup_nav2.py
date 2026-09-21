import asyncio

import omni.usd
import omni.timeline
from omni.isaac.core.utils.stage import open_stage

USD_STAGE = "/home/$USER/Documents/isaac-robotics/assets/robots/mobile_robot/Collected_warehouse_test_scene/warehouse_test_scene.usd"

# Replace $USER manually if desired.
# or pass via environment variable.

USD_STAGE = USD_STAGE.replace("$USER", __import__("os").getenv("USER"))


async def startup():

    print(f"Opening stage:\n{USD_STAGE}")

    open_stage(USD_STAGE)

    ctx = omni.usd.get_context()

    while ctx.get_stage() is None:
        await asyncio.sleep(0.5)

    await asyncio.sleep(5)

    timeline = omni.timeline.get_timeline_interface()
    timeline.play()

    print("Simulation started.")


asyncio.ensure_future(startup())