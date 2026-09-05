from setuptools import find_packages, setup

package_name = 'zdt_motor_ros2'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='arduino',
    maintainer_email='arduino@todo.todo',
    description='ROS 2 driver for four ZDT X57S motors',
    license='MIT',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        "console_scripts": [
            "four_motor_driver = zdt_motor_ros2.driver_node:main",
        ],
    },
)
