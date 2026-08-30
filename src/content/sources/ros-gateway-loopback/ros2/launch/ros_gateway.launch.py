# SPDX-License-Identifier: MIT

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    """
    @description         : 创建加载默认参数文件的 ROS 2 启动描述
    @param               : 无参数
    @return              : LaunchDescription 实例
    """
    package_share = Path(get_package_share_directory("ventuno_app_bridge"))
    parameters_file = package_share / "config" / "bridge_params.yaml"
    return LaunchDescription(
        [
            Node(
                package="ventuno_app_bridge",
                executable="ventuno_app_bridge_node",
                name="ventuno_app_bridge_node",
                output="screen",
                parameters=[str(parameters_file)],
            )
        ]
    )
