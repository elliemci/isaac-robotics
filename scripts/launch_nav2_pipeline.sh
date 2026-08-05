#!/bin/bash

set -e

############################################################
# Environment
############################################################

export WORKSPACE_DIR="$HOME/Documents/sim_interfaces_example/sim_control_script_and_carter_ws"

export FASTRTPS_DEFAULT_PROFILES_FILE="$HOME/Documents/isaac-robotics/ros_ws/fastdds.xml"

export ISAACSIM_ROS_WS="$WORKSPACE_DIR/ros_ws"

USD_STAGE_PATH="$HOME/Documents/isaac-robotics/assets/robots/mobile_robot/Collected_warehouse_test_scene/warehouse_test_scene.usd"

ISAACSIM="$HOME/Documents/isaacsim/isaac-sim.sh"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

############################################################
# Terminal 1
############################################################

gnome-terminal \
--title="Isaac Sim" \
-- bash -c "

export WORKSPACE_DIR='$WORKSPACE_DIR'
export FASTRTPS_DEFAULT_PROFILES_FILE='$FASTRTPS_DEFAULT_PROFILES_FILE'
export ISAACSIM_ROS_WS='$ISAACSIM_ROS_WS'

$ISAACSIM \
    --/isaac/startup/ros_sim_control_extension=True \
    --exec $SCRIPT_DIR/startup_nav2.py

exec bash
"

############################################################
# Wait for Isaac Sim
############################################################

echo "Waiting for Isaac Sim to load..."

sleep 45

# or wait till Isaac Sim is publishing ROS messages
#until ros2 topic echo /clock --once >/dev/null 2>&1
#do
    #echo "Waiting for /clock..."
    #sleep 2
#done

############################################################
# Terminal 2
############################################################

gnome-terminal \
--title="Nav2" \
-- bash -c "

source /opt/ros/humble/setup.bash

source ~/Documents/isaac-robotics/ros_ws/install/setup.bash

cd ~/Documents/isaac-robotics/ros_ws

source install/setup.bash

ros2 launch carter_navigation \
multiple_robot_carter_navigation_warehouse.launch.py \
use_sim_time:=True

exec bash
"