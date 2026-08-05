# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import isaac_ros_launch_utils as lu
from isaac_ros_launch_utils.all_types import *
from launch.actions import DeclareLaunchArgument
from launch import LaunchDescription
from launch.substitutions import LaunchConfiguration, TextSubstitution
from launch_ros.actions import Node, SetRemap

def generate_launch_description() -> LaunchDescription:
    args = lu.ArgumentContainer()
    args.add_arg('calibrated_urdf_file', default='/etc/nova/calibration/isaac_calibration.urdf')

    robot_name = LaunchConfiguration('robot_name')
    declare_robot_name_cmd = DeclareLaunchArgument('robot_name', default_value='', description='Robot namespace')

    return LaunchDescription([

        # Declare robot_name argument
        declare_robot_name_cmd,

        # PushRosNamespace(robot_name),
        
        # Remap TF topics into robot namespace without pushing full ROS namespace
        SetRemap(src='/tf', dst=[TextSubstitution(text='/'), robot_name, TextSubstitution(text='/tf')]),
        SetRemap(src='/tf_static', dst=[TextSubstitution(text='/'), robot_name, TextSubstitution(text='/tf_static')]),
        SetRemap(src='/joint_states', dst=[TextSubstitution(text='/'), robot_name, TextSubstitution(text='/joint_states')]),
        SetRemap(src='/robot_description', dst=[TextSubstitution(text='/'), robot_name, TextSubstitution(text='/robot_description')]),
        

        # Add robot description
        lu.add_robot_description(
            nominals_package='nova_carter_description',
            nominals_file='urdf/nova_carter.urdf.xacro',
            robot_calibration_path=args.calibrated_urdf_file,
        ),
        

    ])
