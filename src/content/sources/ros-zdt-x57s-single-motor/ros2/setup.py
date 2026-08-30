from glob import glob
import os

from setuptools import find_packages, setup


package_name = "ventuno_zdt_motor_bridge"


setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml", "README.md"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.launch.py")),
        (os.path.join("share", package_name, "config"), glob("config/*.yaml")),
    ],
    install_requires=["setuptools", "websockets==17.1"],
    tests_require=["pytest"],
    zip_safe=True,
    maintainer="Arduino User",
    maintainer_email="arduino@example.com",
    description="Native ROS 2 WebSocket bridge for one App Lab ZDT X57S motor object.",
    license="MIT",
    entry_points={
        "console_scripts": [
            "ventuno_zdt_motor_bridge_node = ventuno_zdt_motor_bridge.node:main",
        ],
    },
)
