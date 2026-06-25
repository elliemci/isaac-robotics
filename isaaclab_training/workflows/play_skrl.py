"""Script to play/evaluate a trained RL agent with skrl inside the workspace."""

import os
import sys
import glob
import argparse

from isaaclab.app import AppLauncher

# 1. Setup the command line arguments

parser = argparse.ArgumentParser(description="Evaluate a trained skrl agent.")
parser.add_argument("--task", type=str, default=None, help="Name of the task.")
parser.add_argument("--checkpoint", type=str, default=None, help="Path to the trained model checkpoint .pt file.")
parser.add_argument("--num_envs", type=int, default=16, help="Number of environments to simulate during playback.")
parser.add_argument("--ml_framework", type=str, default="torch", choices=["torch", "jax"], help="The ML framework used.")
parser.add_argument("--agent", type=str, default=None, help="Agent configuration entry point override.")
parser.add_argument("--algorithm", type=str, default="PPO", help="Name of the RL algorithm used.")

# append standard AppLauncher command line arguments
AppLauncher.add_app_launcher_args(parser)
args_cli, hydra_args = parser.parse_known_args()

# clear out sys.argv to keep Hydra happy
sys.argv = [sys.argv[0]] + hydra_args

# launch the full Omniverse Sim Application window
app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

# 2. Import custom local workspace libraries AFTER simulator is live

import isaaclab_training
import isaaclab_tasks 
import gymnasium as gym

from skrl.utils.runner.torch import Runner
from isaaclab.envs import ManagerBasedRLEnvCfg, DirectRLEnvCfg, DirectMARLEnvCfg
from isaaclab.utils.assets import retrieve_file_path
from isaaclab_tasks.utils.hydra import hydra_task_config
from isaaclab_rl.skrl import SkrlVecEnvWrapper

def find_latest_best_checkpoint() -> str:
    """Scans the local logs directory and returns the absolute path to the newest best_agent.pt file."""
    # look inside the logs/skrl/ directory tree for best_agent.pt files
    search_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "logs", "skrl", "**", "best_agent.pt"))
    checkpoint_files = glob.glob(search_path, recursive=True)
    
    if not checkpoint_files:
        raise FileNotFoundError(
            "No 'best_agent.pt' files found automatically in logs directory. Please provide an explicit path using --checkpoint."
        )
    
    # Sort files by their modification time to pick the newest one
    latest_file = max(checkpoint_files, key=os.path.getmtime)
    return latest_file

# define the orchestration logic targeting agent entry points
if args_cli.agent is None:
    algorithm = args_cli.algorithm.lower()
    agent_cfg_entry_point = "skrl_cfg_entry_point" if algorithm in ["ppo"] else f"skrl_{algorithm}_cfg_entry_point"
else:
    agent_cfg_entry_point = args_cli.agent
    algorithm = agent_cfg_entry_point.split("_cfg")[0].split("skrl_")[-1].lower()

@hydra_task_config(args_cli.task, agent_cfg_entry_point)
def main(env_cfg: ManagerBasedRLEnvCfg | DirectRLEnvCfg | DirectMARLEnvCfg, agent_cfg: dict):
    """Load agent weights and evaluate."""
    # Force single-node playback properties
    env_cfg.scene.num_envs = args_cli.num_envs
    env_cfg.sim.device = args_cli.device if args_cli.device is not None else env_cfg.sim.device
    
    # Configure the skrl evaluation parameters
    eval_steps = 1000
    agent_cfg["trainer"]["timesteps"] = eval_steps  
    agent_cfg["trainer"]["close_environment_at_exit"] = True
    
    # Specify the target log folder for reference data mapping
    log_root_path = os.path.join("logs", "skrl", "evaluation")
    env_cfg.log_dir = os.path.abspath(log_root_path)

    # Initialize the Gymnasium task environment wrapper layout
    env = gym.make(args_cli.task, cfg=env_cfg, render_mode="rgb_array")
    
    # Wrap the simulation environment matrix for skrl tracking execution
    env = SkrlVecEnvWrapper(env, ml_framework=args_cli.ml_framework)
    
    # Instantiate the agent model architecture
    runner = Runner(env, agent_cfg)
    
    # Resolve the checkpoint path logic
    if args_cli.checkpoint is not None:
        checkpoint_path = args_cli.checkpoint
    else:
        checkpoint_path = find_latest_best_checkpoint()
        print(f"[INFO] No checkpoint specified. Auto-detected newest model: {checkpoint_path}")
        
    resume_path = retrieve_file_path(checkpoint_path)
    print(f"[INFO] Loading model checkpoint weights from: {resume_path}")
    runner.agent.load(resume_path)
    
    # -------------------------------------------------------------
    # RELIABLE EVALUATION METRICS ENGINE
    # -------------------------------------------------------------
    print("[INFO] Starting visual policy evaluation rollouts...")
    
    import torch


    import inspect
    print(f"--- SKRL AGENT.ACT SIGNATURE: {inspect.signature(runner.agent.act)}")

    total_accumulated_reward = 0.0
    steps_executed = 0
    
    # Reset environment to get initial observation
    obs, _ = env.reset()
    
    # Manually step through the policy to capture raw streaming reward numbers
    for _ in range(eval_steps):
        # Let the trained neural network brain choose the next action step
        with torch.no_grad():
            # provide all 4 required positional arguments: observations, states, timestep, timesteps
            # catch the 2 outputs returned by skrl: actions, outputs_dict
            actions, _ = runner.agent.act(obs, None, timestep=steps_executed, timesteps=eval_steps)

        
        # Pass action directly to the physics engine
        obs, rewards, terminated, truncated, infos = env.step(actions)
        
        # Accumulate the raw rewards sent from Isaac Lab to skrl
        total_accumulated_reward += rewards.mean().item()
        steps_executed += 1

    # Print out the absolute mathematical average 
    print('\n' + '='*65)
    print('                EVALUATION PERFORMANCE SUMMARY                 ')
    print('='*65)
    mean_step_reward = total_accumulated_reward / steps_executed
    print(f" -> Total Steps Evaluated       : {steps_executed}")
    print(f" -> Mean Step Reward (Overall)  : {mean_step_reward:>10.4f}")
    
    # Simple qualitative scoring tier based on your reward redesign
    if mean_step_reward > 1.5:
        print(" -> Policy Performance Rating   : EXCELLENT (Tracking Target)")
    elif mean_step_reward > 0.0:
        print(" -> Policy Performance Rating   : GOOD (Hovering Near Target)")
    else:
        print(" -> Policy Performance Rating   : POOR (Penalties Overpowering Success)")
        
    print('='*65 + '\n')
    
    # Clean up environment bindings at close out
    env.close()


if __name__ == "__main__":
    main()
    simulation_app.close()