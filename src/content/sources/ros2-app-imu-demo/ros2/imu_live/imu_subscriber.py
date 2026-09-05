"""Minimal ROS 2 observer for /imu/data and /imu/status."""

import json
import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Imu
from std_msgs.msg import String


class ImuObserver(Node):
    def __init__(self):
        super().__init__("bno086_imu_observer")
        self.last_imu = None
        self.last_status = None
        self.last_imu_monotonic = None
        self.last_status_monotonic = None
        self.create_subscription(Imu, "/imu/data", self.on_imu, qos_profile_sensor_data)
        self.create_subscription(String, "/imu/status", self.on_status, 10)
        self.create_timer(1.0, self.report)

    def on_imu(self, message):
        self.last_imu = message
        self.last_imu_monotonic = time.monotonic()

    def on_status(self, message):
        self.last_status = message.data
        self.last_status_monotonic = time.monotonic()

    def report(self):
        status_age = (
            None
            if self.last_status_monotonic is None
            else time.monotonic() - self.last_status_monotonic
        )
        if self.last_imu is None:
            self.get_logger().warning(
                "STALE /imu/data age=unknown status_age=%s (no sample yet)"
                % ("unknown" if status_age is None else "%.1fs" % status_age)
            )
        else:
            imu_age = (
                float("inf")
                if self.last_imu_monotonic is None
                else time.monotonic() - self.last_imu_monotonic
            )
            if imu_age > 1.0:
                self.get_logger().warning(
                    "STALE /imu/data age=%.1fs status_age=%s "
                    "(cached sample not shown as fresh)"
                    % (
                        imu_age,
                        "unknown" if status_age is None else "%.1fs" % status_age,
                    )
                )
            else:
                self._report_imu()
        if self.last_status:
            try:
                status = json.loads(self.last_status)
                self.get_logger().info(
                    "status rpc_ok=%s fault=%s reset=%s"
                    % (
                        status.get("last_rpc_ok"),
                        status.get("last_fault"),
                        status.get("report", {}).get("reset_count"),
                    )
                )
            except (TypeError, ValueError):
                self.get_logger().warning("/imu/status is not JSON")

    def _report_imu(self):
        imu = self.last_imu
        self.get_logger().info(
            "imu frame=%s q=(%.3f, %.3f, %.3f, %.3f) "
            "gyro=(%.4f, %.4f, %.4f) accel=(%.3f, %.3f, %.3f)"
            % (
                imu.header.frame_id,
                imu.orientation.x,
                imu.orientation.y,
                imu.orientation.z,
                imu.orientation.w,
                imu.angular_velocity.x,
                imu.angular_velocity.y,
                imu.angular_velocity.z,
                imu.linear_acceleration.x,
                imu.linear_acceleration.y,
                imu.linear_acceleration.z,
            )
        )


def main(args=None):
    rclpy.init(args=args)
    node = ImuObserver()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
