from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    """
    @description         : 使用包内默认参数启动单电机ROS 2桥接节点
    @param               : 无参数
    @return              : ROS 2 LaunchDescription对象
    """
    package_share = Path(get_package_share_directory("ventuno_zdt_motor_bridge"))
    parameters = package_share / "config" / "bridge_params.yaml"
    return LaunchDescription(
        [
            Node(
                package="ventuno_zdt_motor_bridge",
                executable="ventuno_zdt_motor_bridge_node",
                name="ventuno_zdt_motor_bridge",
                output="screen",
                parameters=[str(parameters)],
            )
        ]
    )
