from glob import glob
import os

from setuptools import find_packages, setup


package_name = "ventuno_app_bridge"


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
    install_requires=["setuptools"],
    tests_require=["pytest"],
    zip_safe=True,
    maintainer="Arduino User",
    maintainer_email="arduino@example.com",
    description="Native ROS 2 client for the App Lab ROS Gateway WebSocket protocol.",
    license="MIT",
    entry_points={
        "console_scripts": [
            "ventuno_app_bridge_node = ventuno_app_bridge.node:main",
        ],
    },
)
