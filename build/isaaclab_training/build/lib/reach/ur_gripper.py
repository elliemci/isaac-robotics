
"""Configuration for the Universal Robots.
Reference: https://github.com/ros-industrial/universal_robot
"""

import isaaclab.sim as sim_utils
from isaaclab.actuators import ImplicitActuatorCfg
from isaaclab.assets.articulation import ArticulationCfg

UR_GRIPPER_CFG = ArticulationCfg(

# Where is the USD file for this robot?
spawn=sim_utils.UsdFileCfg( 
    # point to the exact GCP workspace directory      
    usd_path="/home/elliemcintosh/Documents/isaac-robotics/isaaclab_training/reach/UR-with-gripper.usd",
        activate_contact_sensors=False,
        rigid_props=sim_utils.RigidBodyPropertiesCfg(
            rigid_body_enabled=True,
            max_linear_velocity=1000.0,
            max_angular_velocity=1000.0,
            max_depenetration_velocity=5.0,
        ),
        articulation_props=sim_utils.ArticulationRootPropertiesCfg(
            enabled_self_collisions=True, 
            solver_position_iteration_count=8, 
            solver_velocity_iteration_count=0
        ),
    ),
# What is its initial position of the robot, and its joints?
    init_state=ArticulationCfg.InitialStateCfg(
        joint_pos={
            "shoulder_pan_joint": 0.0,
            "shoulder_lift_joint": -1.712,
            "elbow_joint": 1.712,
            "wrist_1_joint": 0.0,
            "wrist_2_joint": 0.0,
            "wrist_3_joint": 0.0,
        },
    ),
# what parts of the robot move, and how stiff / damped are they?
    actuators={
        "arm": ImplicitActuatorCfg(
            joint_names_expr=[".*"], # ".*" matches the available joints
            effort_limit=87.0,
            stiffness=800.0,
            damping=40.0,
        ),
    }
        # the simulator isolates mimic joints, having a separate "gripper" 
        # block here will cause the script to look for a joint it cannot see and crash
        #"gripper": ImplicitActuatorCfg(
            #joint_names_expr=["finger_joint"],
            #stiffness=280,
            #damping=28
        #),
    #}
)
