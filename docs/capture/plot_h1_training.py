"""Training curves for an Isaac Lab skrl run (read-only on the tfevents file).
Run: isaaclab.sh -p docs/capture/plot_h1_training.py <run_dir> <out.png>
"""
import glob, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from tensorboard.backend.event_processing import event_accumulator as E

run, out = sys.argv[1], sys.argv[2]
ea = E.EventAccumulator(glob.glob(f"{run}/events.out*")[0], size_guidance={E.SCALARS: 0})
ea.Reload()
xy = lambda t: ([e.step for e in ea.Scalars(t)], [e.value for e in ea.Scalars(t)])

fig, ax = plt.subplots(1, 3, figsize=(13, 3.9), dpi=110)
x, lo = xy("Reward / Total reward (min)"); _, hi = xy("Reward / Total reward (max)"); _, mean = xy("Reward / Total reward (mean)")
ax[0].fill_between(x, lo, hi, alpha=0.2, color="#4c78a8"); ax[0].plot(x, mean, lw=2, color="#4c78a8", label="mean (band: min to max)")
ax[0].set(title="Total episode reward", xlabel="timestep"); ax[0].legend(frameon=False, fontsize=8)
x, y = xy("Episode / Total timesteps (mean)")
ax[1].plot(x, y, lw=2, color="#54a24b"); ax[1].axhline(1000, ls="--", lw=1, color="#888")
ax[1].set(title="Mean episode length (steps; 1000 = max)", xlabel="timestep")
for tag, c in [("track_lin_vel_xy_exp", "#4c78a8"), ("track_ang_vel_z_exp", "#f58518")]:
    x, y = xy(f"Episode_Reward/{tag}"); ax[2].plot(x, y, lw=2, color=c, label=tag)
ax[2].set(title="Velocity-tracking reward terms", xlabel="timestep"); ax[2].legend(frameon=False, fontsize=8)
for a in ax:
    a.spines[["top", "right"]].set_visible(False); a.grid(alpha=0.25)
fig.suptitle("Isaac-Velocity-Flat-H1-v0, skrl PPO, 300 iterations, 2048 envs (" + run.rstrip("/").split("/")[-1] + ")", fontsize=10)
fig.tight_layout(); fig.savefig(out)
