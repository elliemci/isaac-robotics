# to expose the custom ur10 reach environment point to the reach_env_cfg.py instead of Isaac Lab's internal source files
from .reach_env_cfg import UR10ReachEnvCfg

# expose the configuration class to the rest of the project package namespace
__all__ = ["UR10ReachEnvCfg"]