from __future__ import annotations

import torch
from typing import TYPE_CHECKING

from isaaclab.managers import SceneEntityCfg
from isaaclab.utils.math import combine_frame_transforms

from isaaclab.assets import RigidObject
from isaaclab.managers import SceneEntityCfg
from isaaclab.utils.math import combine_frame_transforms, quat_error_magnitude, quat_mul

if TYPE_CHECKING:
    from isaaclab.envs import ManagerBasedRLEnv

def position_command_error(env: ManagerBasedRLEnv, command_name: str, asset_cfg: SceneEntityCfg) -> torch.Tensor:
    """Penalize tracking of the position error using L2-norm.

    The function computes the position error between the desired position (from the command) and the
    current position of the asset's body (in world frame). The position error is computed as the L2-norm
    of the difference between the desired and current positions.
    """
    # extract the asset (to enable type hinting)
    asset: RigidObject = env.scene[asset_cfg.name]
    command = env.command_manager.get_command(command_name)
    # obtain the desired and current positions
    des_pos_b = command[:, :3]
    # use the command manager's raw world frame coordinates directly!
    des_pos_w, _ = combine_frame_transforms(asset.data.root_state_w[:, :3], asset.data.root_state_w[:, 3:7], des_pos_b) #des_pos_w = command[:, :3] 
    curr_pos_w = asset.data.body_state_w[:, asset_cfg.body_ids[0], :3]  # type: ignore

    distance = torch.norm(curr_pos_w - des_pos_w, dim=1)

    if env.common_step_counter % 1000 == 0: 
        if env.common_step_counter ==0:
            print("\n===== SCENE OBJECTS =====")
            for key in env.scene.keys():
                print("Scene key:", key)
                print("========================\n")
        
        robot = env.scene["robot"]
        joint_pos = robot.data.joint_pos

        print(f"Position error mean: {distance.mean().item():.4f}")
        
        print(f"Joint position std = "
              f"{joint_pos.std(dim=0).mean().item():.4f}")
        # print the actual joint position of environment 0:
        print( "Joint positions in env 0:", robot.data.joint_pos[0].cpu().numpy())

        print("Command sample:", command[0, :3])
        print("Root position:", asset.data.root_state_w[0, :3])
        print("Current wrist:", curr_pos_w[0])

    return distance

def position_command_error_tanh(
    env: ManagerBasedRLEnv, std: float, command_name: str, asset_cfg: SceneEntityCfg
) -> torch.Tensor:
    """Reward tracking of the position using the tanh kernel.

    The function computes the position error between the desired position (from the command) and the
    current position of the asset's body (in world frame) and maps it with a tanh kernel.
    """
    # extract the asset (to enable type hinting)
    asset: RigidObject = env.scene[asset_cfg.name]
    command = env.command_manager.get_command(command_name)
    # obtain the desired and current positions
    #des_pos_b = command[:, :3]
    #des_pos_w, _ = combine_frame_transforms(asset.data.root_state_w[:, :3], asset.data.root_state_w[:, 3:7], des_pos_b)
    # FIX: Trust the command manager's raw world frame coordinates directly!
    des_pos_w = command[:, :3]

    curr_pos_w = asset.data.body_state_w[:, asset_cfg.body_ids[0], :3]  # type: ignore
    distance = torch.norm(curr_pos_w - des_pos_w, dim=1)
    return 1 - torch.tanh(distance / std)


def orientation_command_error(env: ManagerBasedRLEnv, command_name: str, asset_cfg: SceneEntityCfg) -> torch.Tensor:
    """Penalize tracking orientation error using shortest path.

    The function computes the orientation error between the desired orientation (from the command) and the
    current orientation of the asset's body (in world frame). The orientation error is computed as the shortest
    path between the desired and current orientations.
    """
    # extract the asset (to enable type hinting)
    asset: RigidObject = env.scene[asset_cfg.name]
    command = env.command_manager.get_command(command_name)
    # obtain the desired and current orientations
    des_quat_b = command[:, 3:7]
    des_quat_w = quat_mul(asset.data.root_state_w[:, 3:7], des_quat_b)
    curr_quat_w = asset.data.body_state_w[:, asset_cfg.body_ids[0], 3:7]  # type: ignore

    return quat_error_magnitude(curr_quat_w, des_quat_w) # returns a value between 0.0 and 3.14 radiants, i.e. max of 180 degrees

# adding distance reward term temporarily for debugging
def debug_distance(
    env,
    command_name,
    asset_cfg,
):
    asset = env.scene[asset_cfg.name]

    command = env.command_manager.get_command(command_name)

    des_pos_b = command[:, :3]

    des_pos_w, _ = combine_frame_transforms(
        asset.data.root_state_w[:, :3],
        asset.data.root_state_w[:, 3:7],
        des_pos_b,
    )

    curr_pos_w = asset.data.body_state_w[
        :, asset_cfg.body_ids[0], :3
    ]

    distance = torch.norm(curr_pos_w - des_pos_w, dim=1)
    if env.common_step_counter % 1000 == 0:
        print(f"DEBUG distance mean = {distance.mean().item():.4f}")

    return distance