# top-level project registration file 

import gymnasium as gym

from .cartpole import CustomCartpoleEnvCfg

# for the UR10 registration import the specific local package blocks
from .reach import reach_env_cfg
from .reach import agents



# use Gymnasium's registration function to register training tasks
gym.register(
    id="Template-Cartpole-v0",
    entry_point="isaaclab.envs:ManagerBasedRLEnv", #"isaaclab_tasks.manager_based.classic.cartpole.cartpole_env:CartpoleEnv", 
    # or custom class
    kwargs={"env_cfg_entry_point": CustomCartpoleEnvCfg,
            # point exactly to Isaac Lab's pre-defined skrl agent configuration profile!
            "skrl_cfg_entry_point": "isaaclab_tasks.manager_based.classic.cartpole.agents:skrl_ppo_cfg.yaml",
    },
)

gym.register(
    id="Template-UR10-Reach-v0",
    entry_point="isaaclab.envs:ManagerBasedRLEnv",
    disable_env_checker=True,
    kwargs={
        # use the absolute string name pointing to custom class layout
        "env_cfg_entry_point": "isaaclab_training.reach.reach_env_cfg:UR10ReachEnvCfg", 
        
        # use the absolute string name pointing directly to local agents folder
        "skrl_cfg_entry_point": "isaaclab_training.reach.agents:skrl_ppo_cfg.yaml",
    },
)

# adding training tasks
# gym.register(id="Template-Humanoid-v0", ...)
