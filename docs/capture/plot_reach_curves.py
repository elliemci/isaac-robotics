"""Training curves for the latest UR10 reach run (read-only on logs/skrl).
Run with Isaac Lab's python: isaaclab.sh -p docs/capture/plot_reach_curves.py <run_dir> <out.png>
"""
import glob, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from tensorboard.backend.event_processing import event_accumulator as E

run, out = sys.argv[1], sys.argv[2]
ea = E.EventAccumulator(glob.glob(f"{run}/events.out*")[0], size_guidance={E.SCALARS: 0})
ea.Reload()


def xy(tag):
    s = ea.Scalars(tag)
    return [e.step for e in s], [e.value for e in s]


fig, (a, b) = plt.subplots(1, 2, figsize=(11, 4), dpi=110)
x, lo = xy("Reward / Total reward (min)"); _, hi = xy("Reward / Total reward (max)"); _, mean = xy("Reward / Total reward (mean)")
a.fill_between(x, lo, hi, alpha=0.2, color="#4c78a8", label="min to max")
a.plot(x, mean, color="#4c78a8", lw=2, label="mean")
a.set(title="Total episode reward", xlabel="timestep", ylabel="reward"); a.legend(frameon=False)
for tag, c in [("end_effector_position_tracking", "#4c78a8"), ("end_effector_orientation_tracking", "#f58518"),
               ("action_rate", "#54a24b"), ("joint_vel", "#b279a2")]:
    x, y = xy(f"Episode_Reward/{tag}")
    b.plot(x, y, lw=2, color=c, label=tag.replace("end_effector_", "ee_"))
b.set(title="Weighted reward terms (per episode)", xlabel="timestep"); b.legend(frameon=False, fontsize=8)
for ax in (a, b):
    ax.spines[["top", "right"]].set_visible(False); ax.grid(alpha=0.25)
fig.suptitle("Template-UR10-Reach-v0, skrl PPO, run " + run.rstrip("/").split("/")[-1], fontsize=10)
fig.tight_layout(); fig.savefig(out)
