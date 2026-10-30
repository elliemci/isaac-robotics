#!/usr/bin/env bash
# Stops headless Isaac Sim and the Nav2 stack started by run_nav2_lesson.sh.
# (Bracketed patterns keep pkill from matching this script's own command line.)
pkill -INT -f "[r]os2 launch carter_navigation" 2>/dev/null
sleep 4
for pat in "[i]saacsim/kit/kit" "[c]omponent_container_isolated" "[p]ointcloud_to_laserscan" "[r]obot_state_publisher" "[s]tatic_transform_publisher" "[w]orkshop_learning_script"; do
  pkill -9 -f "$pat" 2>/dev/null
done
for pat in "[l]ifecycle_manager" "[a]mcl" "[m]ap_server"; do pkill -9 -f "$pat" 2>/dev/null; done
sleep 2
exit 0
