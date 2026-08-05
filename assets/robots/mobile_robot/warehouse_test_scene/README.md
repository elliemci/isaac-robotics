# Autonomous Navigation with Isaac Sim and ROS 2 Nav2

This project demonstrates autonomous navigation of multiple NVIDIA Nova Carter robots
in a warehouse environment using:

- NVIDIA Isaac Sim
- ROS 2 Humble
- Nav2
- Isaac Sim ROS 2 Simulation Interfaces


## Overview

The simulation contains:

- A warehouse environment
- Two Nova Carter mobile robots
- ROS 2 navigation stack
- SLAM/navigation maps
- Multi-robot Nav2 configuration


## Repository Structure

isaac-robotics/
|
├── assets/
│ └── robots/
│ └── mobile_robot/
│ └── warehouse_test_scene/
|
├── scripts/
│ ├── setup_assets.sh
│ └── launch_nav2_pipeline.sh
|
└── ros_ws/

## Requirements

### Software

- Ubuntu 22.04
- ROS 2 Humble
- NVIDIA Isaac Sim 5.x
- NVIDIA GPU with CUDA support


### ROS 2 Dependencies

Install ROS 2 Humble and source:

```bash
source /opt/ros/humble/setup.bash
```

### Download Simulation Assets

The USD stage references external Isaac Sim assets, which are not stored in Git because they exceed GitHub file limits.
Install them using:

`./scripts/setup_assets.sh`

The script downloads and installs:

Nova Carter robot assets
Warehouse environment
Materials and textures
Supporting USD assets

## Build ROS 2 Workspace

```bash
cd ros_ws

source /opt/ros/humble/setup.bash

colcon build

source install/setup.bash
```

## Launch Simulation
`./scripts/launch_nav2_pipeline.sh`

The script will:

1. Start Isaac Sim
2. Load warehouse_test_scene.usd
3. Enable ROS 2 simulation interfaces
4. Start simulation playback
5. Launch the Nav2 navigation stack