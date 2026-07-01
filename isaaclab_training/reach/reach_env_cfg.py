
import math
import carb

NUCLEUS_ASSET_ROOT_DIR = carb.settings.get_settings().get("/persistent/isaac/asset_root/cloud")
"""Path to the root directory on the Nucleus Server."""

NVIDIA_NUCLEUS_DIR = f"{NUCLEUS_ASSET_ROOT_DIR}/NVIDIA"
"""Path to the root directory on the NVIDIA Nucleus Server."""

ISAAC_NUCLEUS_DIR = f"{NUCLEUS_ASSET_ROOT_DIR}/Isaac"
"""Path to the ``Isaac`` directory on the NVIDIA Nucleus Server."""

import isaaclab.sim as sim_utils

from isaaclab.assets import AssetBaseCfg
from isaaclab_assets import UR10_CFG
from isaaclab.envs import ManagerBasedRLEnvCfg
from isaaclab.managers import ActionTermCfg as ActionTerm
from isaaclab.managers import CurriculumTermCfg as CurrTerm
from isaaclab.managers import EventTermCfg as EventTerm
from isaaclab.managers import ObservationGroupCfg as ObsGroup
from isaaclab.managers import ObservationTermCfg as ObsTerm
from isaaclab.managers import RewardTermCfg as RewTerm
from isaaclab.managers import SceneEntityCfg
from isaaclab.managers import TerminationTermCfg as DoneTerm
from isaaclab.scene import InteractiveSceneCfg
from isaaclab.utils import configclass
from isaaclab.utils.noise import AdditiveUniformNoiseCfg as Unoise
from isaaclab.sim.spawners.from_files.from_files_cfg import GroundPlaneCfg

# pull the specialized robotic arm task functions for the correct manipulation tasks
#import isaaclab_tasks.manager_based.manipulation.reach.mdp as mdp

# import custom local mdp module
import isaaclab_training.reach.mdp as mdp

##
# Pre-defined configs
##

from .ur_gripper import UR_GRIPPER_CFG  # isort:skip

##
# Managers and Scenes are defined through classes which will be instantiated and set in a Manager Based Environmet Configuration
##

@configclass
class ReachSceneCfg(InteractiveSceneCfg):
    """Configuration for a scene."""

    # world
    ground = AssetBaseCfg(
        prim_path="/World/ground",
        spawn=sim_utils.GroundPlaneCfg(),
        init_state=AssetBaseCfg.InitialStateCfg(pos=(0.0, 0.0, -1.05)),
    )

    # robot
    robot = UR_GRIPPER_CFG.replace(prim_path="{ENV_REGEX_NS}/Robot")
    
    # lights
    dome_light = AssetBaseCfg(
        prim_path="/World/DomeLight",
        spawn=sim_utils.DomeLightCfg(color=(0.9, 0.9, 0.9), intensity=5000.0),
    )

    table = AssetBaseCfg(
        prim_path="{ENV_REGEX_NS}/Table",
        spawn=sim_utils.UsdFileCfg(
            usd_path=f"{ISAAC_NUCLEUS_DIR}/Props/Mounts/SeattleLabTable/table_instanceable.usd",
        ),
        init_state=AssetBaseCfg.InitialStateCfg(pos=(0.55, 0.0, 0.0), rot=(0.70711, 0.0, 0.0, 0.70711)),
    )

    # plane
    plane = AssetBaseCfg(
        prim_path="/World/GroundPlane",
        init_state=AssetBaseCfg.InitialStateCfg(pos=[0, 0, -1.05]),
        spawn=GroundPlaneCfg(),
    )

##
# MDP settings: ActionsCfg, CommandsCfg, ObservationCfg, TerminationsCfg, EventCfg
##

@configclass
class ActionsCfg:
    """Action specifications for the MDP, defines what the agent can do which is moving all 6 revolute joints of the robot."""

    arm_action: ActionTerm = mdp.JointPositionActionCfg(
        asset_name="robot", 
        joint_names=["shoulder_pan_joint", "shoulder_lift_joint", "elbow_joint", "wrist_1_joint", "wrist_2_joint", "wrist_3_joint"], # joint names in the robot.usd file
        scale=0.05, # 0.05 the naural network outputs its max action of 1, Isaac lab commands the joint to move 0.05 radiants in a single step
        use_default_offset=True, 
        debug_vis=True
    )

@configclass
class CommandsCfg:
    """Command terms for the MDP, what to achive rather than how to achive it"""

    ee_pose = mdp.UniformPoseCommandCfg(
        asset_name="robot",
        body_name="ee_link", # "wrist_3_link"
        resampling_time_range=(4.0, 4.0),
        debug_vis=True,
        # ranges of poses that can be commanded for the end of the robot during training; whring command range for debugging
        ranges=mdp.UniformPoseCommandCfg.Ranges(
            #pos_x=(0.45, 0.55),
            #pos_y=(-0.05, 0.05),
            #pos_z=(0.2, 0.35),
            # for debugging of orientation learning, fix the commanded possition not allowing the robot to move over a volume of space
            pos_x=(0.45, 0.45),
            pos_y=(0.05, 0.05),
            pos_z=(0.2, 0.2),

            # check if from the Euler angles of (0.2, 0.3, 0.4) the reconstructed quaternion matches the original or is different by a sign
            roll=(0.2, 0.2),
            pitch=(0.3, 0.3), # (math.pi / 2, math.pi / 2),
            yaw=(0.4, 0.4)   # to test with one orientation (-math.pi, math.pi)    # remove orientation for debugging; yaw=(-math.pi, math.pi)
        ),
    )

    print("\nCreating CommandsCfg")
    print("Pitch =", ee_pose.ranges.pitch)

@configclass
class ObservationsCfg:
    """Observation specifications for the MDP, taken from the environment that are needed to evaluate the talk:
       * End effector possition
       * Joint positions
       * joint velocities
    These observation can evaluate the smootheness of the motion and how closed the postion of the robot is to the goal position."""

    @configclass
    class PolicyCfg(ObsGroup):
        """Observations for policy group."""

        # observation terms (order preserved)
        joint_pos = ObsTerm(func=mdp.joint_pos_rel, noise=Unoise(n_min=-0.01, n_max=0.01))
        joint_vel = ObsTerm(func=mdp.joint_vel_rel, noise=Unoise(n_min=-0.01, n_max=0.01))
        pose_command = ObsTerm(func=mdp.generated_commands, params={"command_name": "ee_pose"})
        actions = ObsTerm(func=mdp.last_action)

        def __post_init__(self):
            # explicitly invoke the parent post-initialization method inside the configuration group so Isaac Lab register the dictionaly params correcly
            super().__post_init__()
            self.enable_corruption = True
            self.concatenate_terms = True

    # observation groups
    policy: PolicyCfg = PolicyCfg()

@configclass
class EventCfg:
    """Configuration for events. Only the reset event is handled, which happens when
        training ends, it resets the joint with a bit of rendomness, scaling the default position
        and velocity by the given range"""

    reset_robot_joints = EventTerm(
        func=mdp.reset_joints_by_scale,
        mode="reset",
        params={
            "position_range": (0.75, 1.25),
            "velocity_range": (0.0, 0.0),
        },
    )

# Isaac Lab's config manager treats built-in and custom function identically. 
# It automatically executes it every frame, passes the environment properties 
# it applies the weight, and combines it into the total score tracking system

@configclass
class RewardsCfg:
    """Reward terms for the MDP with structure balance, which reducaes themotion penalties
       to bare minimum and softens the orientation rules to encorage exploration"""


    # task terms: track the endo fo the robot, end fine-grained, penalize action rate and joint velocity
    end_effector_position_tracking = RewTerm(
        func=mdp.position_command_error,
        weight=-0.2,  # increase pulls the arm out of hanging position towards the goal
        params={"asset_cfg": SceneEntityCfg("robot", body_names=["ee_link"]), "command_name": "ee_pose"},
    )  # params={"asset_cfg": SceneEntityCfg("robot", body_names=["wrist_3_link"]), "command_name": "ee_pose"},

    
    # since Tanh is bounded (0 to 1), a positive weight here acts as an attractor bubble
    end_effector_position_tracking_fine_grained = RewTerm(
        func=mdp.position_command_error_tanh,
        weight=0.1, # 0.1, accuracy bonus
        params={"asset_cfg": SceneEntityCfg("robot", body_names=["ee_link"]), "std": 0.2, "command_name": "ee_pose"},
    )

    end_effector_orientation_tracking = RewTerm(
        func=mdp.orientation_command_error,
        weight=-0.002, # -0.2 Force the gripper to rotate, a 90 degree error triggers a noticble -3.14 penalty while stopu paralyzis of the arm from a distance
        params={"asset_cfg": SceneEntityCfg("robot", body_names=["ee_link"]), "command_name": "ee_pose"},
    )

    # the same tanh logic as position to give a +3.0 bonus when the angle is within ~15 degrees (0.25 rad)
    #end_effector_orientation_tracking_fine_grained = RewTerm(
        #func=mdp.position_command_error_tanh, # Re-uses the clean exponential decay wrapper
        #weight=0.03, # <--- Extra reward for locking in the rotation angle
        #params={"asset_cfg": SceneEntityCfg("robot", body_names=["ee_link"]), "std": 0.25, "command_name": "ee_pose"},
    #)
    
    # allow the arm to move forward without being paralaysed by penalties; 
    # ABSOLUTE MINIMUM MOTION COSTS, lowered significantly so the network doesn't fear the cost of moving
    action_rate = RewTerm(
        func=mdp.action_rate_l2, 
        weight=-0.002) # -0.0001 low penalty to prevent paralysis
    
    
    joint_vel = RewTerm(
        func=mdp.joint_vel_l2,
        weight=-0.005 
    )

    # temporarily add dstance reward
    debug_distance = RewTerm(
    func=mdp.debug_distance,
    weight=1e-6,
    params={
        "asset_cfg": SceneEntityCfg(
            "robot",
            body_names=["wrist_3_link"]
        ),
        "command_name": "ee_pose",
    },
)


@configclass
class TerminationsCfg:
    """Termination terms for the MDP."""

    time_out = DoneTerm(func=mdp.time_out, time_out=True)

@configclass
class CurriculumCfg:
    """Curriculum terms for the MDP to further configure more detailed training instructions."""

    action_rate = CurrTerm(
        func=mdp.modify_reward_weight, params={"term_name": "action_rate", "weight": -0.005, "num_steps": 4500}
    )

    joint_vel = CurrTerm(
        func=mdp.modify_reward_weight, params={"term_name": "joint_vel", "weight": -0.001, "num_steps": 4500}
    )

##
# Environment configuration
##

@configclass
class ReachEnvCfg(ManagerBasedRLEnvCfg):
    """Configuration for the reach end-effector pose tracking environment."""

    # Scene settings - how many robots, how far apart?
    scene = ReachSceneCfg(num_envs=2000, env_spacing=2.5)
    # Basic settings
    observations = ObservationsCfg()
    actions = ActionsCfg()
    commands: CommandsCfg = CommandsCfg()
    # MDP settings
    rewards = RewardsCfg()
    terminations = TerminationsCfg()
    events = EventCfg()
    curriculum = CurriculumCfg()

    def __post_init__(self):
        """Post initialization."""
        # general settings
        self.decimation = 2
        self.sim.render_interval = self.decimation
        self.episode_length_s = 6.0  #6*60 Hz / 2 = 180 policy actions per episode which give PPO more time to move towards target
        self.viewer.eye = (3.5, 3.5, 3.5)
        # simulation settings
        self.sim.dt = 0.005 # 200 Hz

@configclass
class ReachEnvCfg_PLAY(ReachEnvCfg):
    def __post_init__(self):
        # post init of parent
        super().__post_init__()
        # make a smaller scene for play
        self.scene.num_envs = 50
        self.scene.env_spacing = 2.5
        # disable randomization for play
        self.observations.policy.enable_corruption = False


from isaaclab.envs import ManagerBasedRLEnvCfg


@configclass
class UR10ReachEnvCfg(ReachEnvCfg):
    """The final environment config wrapper class that Isaac Lab loads."""

    # set simulation parameters number of environments and physical spacing between those environments
    scene: ReachSceneCfg = ReachSceneCfg(num_envs=2000, env_spacing=3.0)
    
    # Instantiate the MDP configurations directly, create the instances of the managers defined above
    commands: CommandsCfg = CommandsCfg()
    actions: ActionsCfg = ActionsCfg()
    observations: ObservationsCfg = ObservationsCfg()
    rewards: RewardsCfg = RewardsCfg()
    terminations: TerminationsCfg = TerminationsCfg()

    def __post_init__(self):
        # post init of parent
        super().__post_init__()

        # switch robot to ur10
        self.scene.robot = UR10_CFG.replace(prim_path="{ENV_REGEX_NS}/Robot")
        # override events
        self.events.reset_robot_joints.params["position_range"] = (0.75, 1.25)
        
        # --- FIX THESE FOUR LINES TO USE WRIST_3_LINK ???---
        self.rewards.end_effector_position_tracking.params["asset_cfg"].body_names = ["ee_link"]
        self.rewards.end_effector_position_tracking_fine_grained.params["asset_cfg"].body_names = ["ee_link"]
        self.rewards.end_effector_orientation_tracking.params["asset_cfg"].body_names = ["ee_link"]
        
        # override actions
        self.actions.arm_action = mdp.JointPositionActionCfg(
            asset_name="robot",
            joint_names=[".*"],
            scale=0.05, # for smooth arm movement
            use_default_offset=True
        )
        
        # override command generator body
        self.commands.ee_pose.body_name = "wrist_3_link"
        self.commands.ee_pose.ranges.pitch = (math.pi / 2, math.pi / 2)


