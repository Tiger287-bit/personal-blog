from setuptools import find_packages, setup

package_name = 'my_ros2_02_led_bridge'

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
    description='TODO: Package description',
    license='Apache-2.0',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'led_command_publisher = my_ros2_02_led_bridge.led_command_publisher:main',
            'led_command_subscriber = my_ros2_02_led_bridge.led_command_subscriber:main',
        ],
    },
)
