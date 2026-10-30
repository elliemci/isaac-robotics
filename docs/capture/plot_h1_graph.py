"""Diagram of the three ROS 2 OmniGraphs in h1_ros_locomotion_wearhouse.usd.

Node types and topic names were read (read-only) from the USD:
  /World/h1_ROS/Graph/ROS_JointStates, /World/h1_ROS/Graph/ROS_Imu, /World/Graph/ROS_Clock.
IMU and clock topic names are unset in the USD, so the node defaults are shown.
Run: isaaclab.sh -p docs/capture/plot_h1_graph.py <out.png>
"""
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

rows = [
    ("ROS_JointStates", [("OnPhysicsStep", "#8c8c8c"), ("ROS2PublishJointState", "#4c78a8"), ("ROS2SubscribeJointState", "#f58518"), ("IsaacArticulationController", "#54a24b")],
     ["", "publishes /joint_states", "subscribes /joint_command", "drives /World/h1_ROS joints"]),
    ("ROS_Imu", [("OnPhysicsStep", "#8c8c8c"), ("IsaacReadIMU", "#54a24b"), ("ROS2PublishImu", "#4c78a8")],
     ["", "reads pelvis/Imu_Sensor", "publishes /imu (node default)"]),
    ("ROS_Clock", [("OnPhysicsStep", "#8c8c8c"), ("IsaacReadSimulationTime", "#54a24b"), ("ROS2PublishClock", "#4c78a8")],
     ["", "reads sim time", "publishes /clock (node default)"]),
]
fig, ax = plt.subplots(figsize=(11, 4.6), dpi=110)
ax.set_xlim(0, 11); ax.set_ylim(0, 4.6); ax.axis("off")
for r, (title, nodes, notes) in enumerate(rows):
    y = 3.5 - r * 1.5
    ax.text(0.05, y + 0.95, title, fontsize=11, fontweight="bold")
    for i, ((name, col), note) in enumerate(zip(nodes, notes)):
        x = 0.1 + i * 2.7
        ax.add_patch(FancyBboxPatch((x, y), 2.35, 0.65, boxstyle="round,pad=0.02,rounding_size=0.08", fc=col, ec="none", alpha=0.9))
        ax.text(x + 1.175, y + 0.325, name, ha="center", va="center", fontsize=8.5, color="white", fontweight="bold")
        if note:
            ax.text(x + 1.175, y - 0.18, note, ha="center", va="top", fontsize=8, color="#444")
        if i:
            ax.annotate("", xy=(x - 0.02, y + 0.325), xytext=(x - 0.33, y + 0.325), arrowprops=dict(arrowstyle="->", color="#666"))
ax.text(0.05, 0.02, "Unitree H1 (/World/h1_ROS) - h1_ros_locomotion_wearhouse.usd", fontsize=8, color="#666")
fig.tight_layout(); fig.savefig(sys.argv[1])
