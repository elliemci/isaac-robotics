"""Headless rollout capture for the Isaac Lab training sub-project (E).

Run with Isaac Lab's python, from a scratch directory (not the repo), e.g.:
  isaaclab.sh -p docs/capture/capture_isaaclab_rollout.py --headless --enable_cameras \
      --task Template-UR10-Reach-v0 --checkpoint logs/skrl/.../best_agent.pt \
      --name reach --out <frames_dir> --still <png>

play_skrl.py has no video option, so this loads the same registered task and
skrl checkpoint, steps the policy deterministically and saves env.render()
RGB frames. It builds the env cfg directly (no hydra) and turns off skrl's
logging/checkpointing, so nothing is written into the project.
"""
import argparse
from pathlib import Path

from isaaclab.app import AppLauncher

p = argparse.ArgumentParser()
p.add_argument("--task", required=True)
p.add_argument("--checkpoint", required=True)
p.add_argument("--out", required=True, help="directory for numbered PNG frames")
p.add_argument("--still", default=None, help="optional path to copy the mid-rollout frame to")
p.add_argument("--num_envs", type=int, default=4)
p.add_argument("--steps", type=int, default=360)
p.add_argument("--frame_skip", type=int, default=1)
p.add_argument("--eye", type=float, nargs=3, default=None)
p.add_argument("--lookat", type=float, nargs=3, default=None)
AppLauncher.add_app_launcher_args(p)
args = p.parse_args()
app = AppLauncher(args).app

import shutil
import gymnasium as gym
import numpy as np
import torch
from PIL import Image
from skrl.utils.runner.torch import Runner

import isaaclab_training  # noqa: F401  registers Template-* tasks
import isaaclab_tasks  # noqa: F401
from isaaclab_rl.skrl import SkrlVecEnvWrapper
from isaaclab_tasks.utils import load_cfg_from_registry, parse_env_cfg

env_cfg = parse_env_cfg(args.task, device="cuda:0", num_envs=args.num_envs)
if args.eye:
    env_cfg.viewer.eye = tuple(args.eye)
if args.lookat:
    env_cfg.viewer.lookat = tuple(args.lookat)
agent_cfg = load_cfg_from_registry(args.task, "skrl_cfg_entry_point")
exp = agent_cfg["agent"]["experiment"]
exp["write_interval"] = 0
exp["checkpoint_interval"] = 0

base = gym.make(args.task, cfg=env_cfg, render_mode="rgb_array")
env = SkrlVecEnvWrapper(base, ml_framework="torch")
runner = Runner(env, agent_cfg)
runner.agent.load(args.checkpoint)

out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
for f in out.glob("*.png"):
    f.unlink()

obs, _ = env.reset()
n = 0
for t in range(args.steps):
    with torch.no_grad():
        actions, outputs = runner.agent.act(obs, None, timestep=t, timesteps=args.steps)
        actions = outputs.get("mean_actions", actions)
    obs, *_ = env.step(actions)
    if t % args.frame_skip == 0:
        frame = base.render()
        Image.fromarray(np.asarray(frame)[..., :3]).save(out / f"{n:04d}.png")
        n += 1

step_dt = base.unwrapped.step_dt
(out / "fps.txt").write_text(f"{1.0 / (step_dt * args.frame_skip):.2f}\n")
print(f"[capture] {n} frames, step_dt={step_dt:.4f}, fps={1.0 / (step_dt * args.frame_skip):.2f}")
if args.still:
    shutil.copy(out / f"{n // 2:04d}.png", args.still)
env.close()
app.close()
