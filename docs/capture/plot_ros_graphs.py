"""Static ROS 2 topic diagrams for sub-projects A and B.

Facts come from (read-only): ros_ws/src/carter_navigation/launch/multiple_robot_carter_navigation_warehouse.launch.py,
params/carter_navigation_params_{1,2}.yaml, and the OmniGraphs in assets/robots/mobile_robot/*.usd
(ROS2SubscribeTwist, ROS2PublishOdometry/TransformTree, ROS2CameraHelper, ROS2PublishImu,
ROS2PublishLaserScan, ROS2RtxLidarHelper). Topic names the USD leaves unset are the node defaults.
Run: isaaclab.sh -p docs/capture/plot_ros_graphs.py <out_dir>
"""
import sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = Path(sys.argv[1])
SIM, ROS, NAV = "#76b900", "#4c78a8", "#f58518"


def box(ax, x, y, w, h, text, col, fs=8.5):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08", fc=col, ec="none", alpha=0.92))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, color="white", fontweight="bold")


def arrow(ax, x0, y0, x1, y1, label="", dy=0.12):
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0), arrowprops=dict(arrowstyle="->", color="#555", lw=1.2))
    if label:
        ax.text((x0 + x1) / 2, (y0 + y1) / 2 + dy, label, ha="center", fontsize=7.5, color="#333")


def canvas(w, h, title):
    fig, ax = plt.subplots(figsize=(w, h), dpi=110)
    ax.set_xlim(0, w); ax.set_ylim(0, h); ax.axis("off")
    ax.text(0.1, h - 0.3, title, fontsize=11, fontweight="bold")
    return fig, ax


# ---- B: Nav2 two-Carter ----
fig, ax = canvas(11.5, 5.4, "Nav2 two-Carter warehouse: topics per robot (carter1 and carter2 are identical, namespaced)")
for i, ns in enumerate(("carter1", "carter2")):
    y = 2.6 - i * 2.3
    ax.text(0.1, y + 1.55, f"/{ns}", fontsize=9, fontweight="bold", color="#333")
    box(ax, 0.1, y + 0.2, 2.2, 1.1, "Isaac Sim\nNova Carter", SIM)
    box(ax, 3.6, y + 0.2, 2.6, 1.1, "pointcloud_to_laserscan\n(target_frame front_3d_lidar)", ROS, 7.5)
    box(ax, 7.0, y + 0.2, 2.2, 1.1, "Nav2 stack\nAMCL, planner, DWB,\ncostmaps (voxel layer on\nthe point cloud)", NAV, 7.5)
    arrow(ax, 2.3, y + 0.95, 3.6, y + 0.95, f"/{ns}/xt_32/point_cloud")
    arrow(ax, 6.2, y + 0.95, 7.0, y + 0.95, f"/{ns}/scan")
    arrow(ax, 2.3, y + 0.05, 7.0, y + 0.05, "/odom, /tf, /clock", dy=-0.3)
    arrow(ax, 9.2, y + 0.95, 10.0, y + 0.95)
    ax.text(10.05, y + 0.9, f"/{ns}/cmd_vel\nback to Isaac Sim", fontsize=7.5, va="center")
fig.savefig(OUT / "nav2-ros-graph.png", bbox_inches="tight")

# ---- A: mobile-robot ROS 2 graphs ----
fig, ax = canvas(11.5, 6.7, "Mobile-robot ROS 2 graphs in Isaac Sim (OmniGraph nodes -> ROS 2 topics)")
rows = [  # (name, nodes, notes, chained)
    ("Turtlebot3 / Jackal-style 4-wheel", [("ROS2SubscribeTwist", ROS), ("DifferentialController", SIM), ("IsaacArticulationController", SIM)],
     ["cmd_vel (Twist, node default)", "", "drives the wheel joints"], True),
    ("Turtlebot3 transform tree", [("IsaacComputeOdometry", SIM), ("ROS2PublishOdometry", ROS), ("ROS2PublishTransformTree", ROS)],
     ["", "/odom", "/tf"], True),
    ("Carter v1 sensors", [("ROS_Camera", ROS), ("ROS_IMU", ROS), ("ROS_Lidar2D", ROS), ("ROS_Lidar3D", ROS)],
     ["/rgb + camera_info", "imu (node default)", "scan (LaserScan, default)", "point_cloud (RTX lidar)"], False),
    ("Nova Carter warehouse", [("ROS_Clock", ROS)], ["clock (node default)"], False),
]
for r, (name, nodes, notes, chained) in enumerate(rows):
    y = 4.9 - r * 1.45
    ax.text(0.1, y + 0.8, name, fontsize=9, fontweight="bold")
    for i, ((n, col), note) in enumerate(zip(nodes, notes)):
        x = 0.1 + i * 2.8
        box(ax, x, y, 2.45, 0.6, n, col, 8)
        if note:
            ax.text(x + 1.22, y - 0.12, note, ha="center", va="top", fontsize=7.5, color="#444")
        if i and chained:
            arrow(ax, x - 0.33, y + 0.3, x - 0.02, y + 0.3)
fig.savefig(OUT / "ros2-graphs-overview.png", bbox_inches="tight")
