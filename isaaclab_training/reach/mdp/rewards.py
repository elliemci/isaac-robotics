from __future__ import annotations

import pprint as pprint

import torch
from typing import TYPE_CHECKING

from isaaclab.managers import SceneEntityCfg

from isaaclab.assets import RigidObject
from isaaclab.managers import SceneEntityCfg
from isaaclab.utils.math import combine_frame_transforms, quat_error_magnitude, quat_mul, euler_xyz_from_quat, matrix_from_quat, quat_inv


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

    ####################### debugging code ############################
    # to figure out if whether command[:, :3] is stored in the robot frame or in the world frame
    root_pos_w = asset.data.root_state_w[:, :3]

    des_pos_b = command[:, :3]

    des_pos_w, _ = combine_frame_transforms(
        root_pos_w,
        asset.data.root_state_w[:, 3:7],
        des_pos_b,
    )

    curr_pos_w = asset.data.body_state_w[:, asset_cfg.body_ids[0], :3]
    curr_pos_b = curr_pos_w - root_pos_w

    distance = torch.norm(curr_pos_w - des_pos_w, dim=1)

    if env.common_step_counter % 1000 == 0: 
        #if env.common_step_counter ==0:
            #print("\n===== SCENE OBJECTS =====")
            #for key in env.scene.keys():
                #print("Scene key:", key)
                #print("========================\n")
        
        robot = env.scene["robot"]
        joint_pos = robot.data.joint_pos

        #print(f"Position error mean: {distance.mean().item():.4f}")
        
        #print(f"Joint position std = "
              #f"{joint_pos.std(dim=0).mean().item():.4f}")
        # print the actual joint position of environment 0:
        #print( "Joint positions in env 0:", robot.data.joint_pos[0].cpu().numpy())

        #print("Command sample:", command[0, :3])
        #print("Root position:", asset.data.root_state_w[0, :3])
        #print("Current wrist:", curr_pos_w[0])

        #print("\n==============================")
        #print("Root world      :", root_pos_w[0])
        #print("Desired (cmd)   :", des_pos_b[0])
        #print("Desired world   :", des_pos_w[0])
        #print("Current world   :", curr_pos_w[0])
        #print("Current relative:", curr_pos_b[0])

        #print("World distance  :", torch.norm(curr_pos_w-des_pos_w,dim=1)[0])
        #print("Relative dist   :", torch.norm(curr_pos_b-des_pos_b,dim=1)[0])
        #print("==============================")
        

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
    des_pos_b = command[:, :3]
    # combine_frame_transform to convert base frame into a world frame before comparing against body_state_w
    des_pos_w, _ = combine_frame_transforms(asset.data.root_state_w[:, :3], asset.data.root_state_w[:, 3:7], des_pos_b)

    ########## FIX: Trust the command manager's raw world frame coordinates directly ########
    #des_pos_w = command[:, :3]
    # In Isaac Lab, UnivormPoseCommand stores the command relative to the robot base, NOT in world coordinates!!!!

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

    #if env.common_step_counter % 1000 == 0:
        #print("Body names:", asset.data.body_names)
        #print("Body id:", asset_cfg.body_ids[0])
        #print("Body being evaluated:", asset.data.body_names[asset_cfg.body_ids[0]])
        #print("body quat:", asset.data.body_state_w[0, asset_cfg.body_ids[0], 3:7])
        #print("link quat:", asset.data.body_link_state_w[0, asset_cfg.body_ids[0], 3:7])
        #print()
        # check if the output of get_command return in robot frame or world coordinats
        #print("\nCommand tensor:", command[0])
        #print("Command shape :", command.shape)
        #print("Desired position:", command[0, :3])

        

    # obtain the desired and current orientations
    des_quat_b = command[:, 3:7]
    des_quat_w = quat_mul(asset.data.root_state_w[:, 3:7], des_quat_b)

    curr_quat_w = asset.data.body_state_w[:, asset_cfg.body_ids[0], 3:7]
    error = quat_error_magnitude(curr_quat_w, des_quat_w)

    # Note: If the robot base isn't the identity orientation, then the world-frame target would be different!!!

    # inspect if the robot base is rotated, is the expected command quaternion, does converting it
    # to world coordinates change it, and if the write is being compared in the same frame
    #if env.common_step_counter == 1:
        #print("\n========== FRAME DEBUG ==========")

        #print("Robot root quaternion:")
        #print(asset.data.root_state_w[0, 3:7])

        #print("Desired body quaternion:")
        #print(des_quat_b[0])

        #print("Desired world quaternion:")
        #print(des_quat_w[0])

        #print("Current wrist quaternion:")
        #print(curr_quat_w[0])
        #print()

    roll_c, pitch_c, yaw_c = euler_xyz_from_quat(curr_quat_w)
    roll_d, pitch_d, yaw_d = euler_xyz_from_quat(des_quat_w)

    if env.common_step_counter % 1000 == 0:

        curr_quat = curr_quat_w[0]
        des_quat = des_quat_w[0]
        q_rel = quat_mul(des_quat.unsqueeze(0), quat_inv(curr_quat.unsqueeze(0)))

        print("Current quaternion:", curr_quat)
        print("Desired quaternion:", des_quat)
        print("Relative quaternion:", q_rel[0])

        print("Orientation error:",
            quat_error_magnitude(
                curr_quat.unsqueeze(0),
                des_quat.unsqueeze(0)
            ))

        print(f"Orientation error mean = "
              f"{error.mean().item():.4f} rad "
              f"({error.mean().item() * 57.3:.1f} deg)"
        )

        Rc = matrix_from_quat(curr_quat)
        Rd = matrix_from_quat(des_quat)

        print("Current Z axis :", Rc[:,2])
        print("Desired Z axis :", Rd[:,2])

        print("Current X axis :", Rc[:,0])
        print("Desired X axis :", Rd[:,0])


        # to check if 
        #print(
            #f"Current RPY : "
            #f"{roll_c[0].item():.2f}, "
            #f"{pitch_c[0].item():.2f}, "
            #f"{yaw_c[0].item():.2f}"
        #)

        #print(
            #f"Desired RPY : "
            #f"{roll_d[0].item():.2f}, "
            #f"{pitch_d[0].item():.2f}, "
            #f"{yaw_d[0].item():.2f}"
        #)


    #if env.common_step_counter == 1:

        #for key in sorted(env.__dict__.keys()):
            #print(key)

        #print("\n========== ENV ==========")
        #for name in vars(env):
            #print(name)

        #print("\n========== SCENE ==========")
        #for name in env.scene.keys():
            #print(name)

        #asset = env.scene["robot"]

        #print("\n========== ROBOT.DATA ==========")
        #for name in vars(asset.data):
            #print(name)

        #print("\n========== COMMAND MANAGER ==========")
        # show registered command terms
        #for name, term in env.command_manager._terms.items():
            #print(f"{name}: {type(term).__name__}")

        # show the command configuration
        #cfg = env.command_manager.cfg.ee_pose

        #print("\n========== EE POSE CONFIG ==========")
        #print("asset_name :", cfg.asset_name)
        #print("body_name  :", cfg.body_name)
        #print("resample   :", cfg.resampling_time_range)

        #print("Position ranges:")
        #print(" x:", cfg.ranges.pos_x)
        #print(" y:", cfg.ranges.pos_y)
        #print(" z:", cfg.ranges.pos_z)

        #print("Orientation ranges:")
        #print(" roll :", cfg.ranges.roll)
        #print(" pitch:", cfg.ranges.pitch)
        #print(" yaw  :", cfg.ranges.yaw)


    return error # returns a value between 0.0 and 3.14 radiants, i.e. max of 180 degrees

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