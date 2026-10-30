#!/usr/bin/env bash
# Records NVIDIA's "Simulation Interfaces" lesson scenario (unmodified
# workshop_learning_script_final.py) in headless Isaac Sim, with Nav2 (no RViz).
# Usage: run_nav2_lesson.sh <work_dir>   (frames land in <work_dir>/frames)
set -o pipefail
W="${1:?work dir}"; mkdir -p "$W"
R="$HOME/Documents/isaac-robotics"
LESSON="$HOME/Documents/sim_interfaces_example/sim_control_script_and_carter_ws"
cat > "$W/ros_env.sh" <<ENV
export ROS_DOMAIN_ID=42 RMW_IMPLEMENTATION=rmw_fastrtps_cpp FASTRTPS_DEFAULT_PROFILES_FILE=$R/ros_ws/fastdds.xml
source /opt/ros/humble/setup.bash
source $R/ros_ws/install/setup.bash
ENV
HERE="$(cd "$(dirname "$0")" && pwd)"
"$HERE/stop_nav2_lesson.sh"; trap '"$HERE/stop_nav2_lesson.sh"' EXIT
rm -rf "$W/frames" "$W/cap.flag"

( export ROS_DOMAIN_ID=42 RMW_IMPLEMENTATION=rmw_fastrtps_cpp FASTRTPS_DEFAULT_PROFILES_FILE=$R/ros_ws/fastdds.xml \
    ISAACSIM_ROS_WS=$LESSON/ros_ws CAP_OUT="$W/frames" CAP_FLAG="$W/cap.flag" \
    CAP_EYE="${CAP_EYE:--0.5 -6.5 4.0}" CAP_LOOKAT="${CAP_LOOKAT:--4.7 -0.5 0.8}" CAP_FPS="${CAP_FPS:-10}"
  nohup "$HOME/Documents/isaacsim/isaac-sim.sh" --no-window --/isaac/startup/ros_sim_control_extension=True \
    --exec "$R/docs/capture/isaacsim_recorder.py" > "$W/isaacsim.log" 2>&1 & )
until grep -aq "\[recorder\] camera set up" "$W/isaacsim.log" 2>/dev/null; do sleep 3; done
echo "Isaac Sim up"

( source "$W/ros_env.sh"; cd "$R/ros_ws"
  nohup ros2 launch carter_navigation multiple_robot_carter_navigation_warehouse.launch.py use_sim_time:=True use_rviz:=False > "$W/nav2.log" 2>&1 & )
sleep 25

touch "$W/cap.flag"
( source "$W/ros_env.sh"; export ROSCON25_ASSET_PATH="$HOME/Documents/sim_interfaces_assets"
  cd "$LESSON/learning_simulation_control"
  python3 workshop_learning_script_final.py > "$W/script.log" 2>&1; echo "lesson script exit=$?" >> "$W/script.log" )
rm -f "$W/cap.flag"
echo "done"
