import math
import time
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import Bool, Int32MultiArray
from std_srvs.srv import SetBool, Trigger

from .can_backend import CanMotorBackend
from .fake_backend import FakeMotorBackend


class ZdtMotorDriverNode(Node):
    """把四轮 ROS RPM 命令交给可替换的电机后端。"""

    def __init__(self):
        super().__init__("zdt_motor_driver")

        # fake 是默认值，避免 ros2 run 后意外访问或使能真实电机。
        self.declare_parameter("backend", "fake")
        self.declare_parameter("motor_ids", [1, 2, 3, 4])
        self.declare_parameter("direction_signs", [1, 1, 1, 1])
        self.declare_parameter("maximum_rpm", 60)
        self.declare_parameter("command_timeout_s", 0.5)
        self.declare_parameter("acceleration", 10)

        backend_name = str(
            self.get_parameter("backend").value
        ).strip().lower()
        motor_ids = [
            int(value)
            for value in self.get_parameter("motor_ids").value
        ]
        direction_signs = [
            int(value)
            for value in self.get_parameter("direction_signs").value
        ]
        self.maximum_rpm = int(
            self.get_parameter("maximum_rpm").value
        )
        self.command_timeout_s = float(
            self.get_parameter("command_timeout_s").value
        )
        if self.maximum_rpm <= 0:
            raise ValueError("maximum_rpm must be positive")
        if (
            not math.isfinite(self.command_timeout_s)
            or self.command_timeout_s <= 0
        ):
            raise ValueError("command_timeout_s must be finite and positive")

        self.last_command_time = None
        self.watchdog_stopped = True
        self.watchdog_warning_sent = False
        self.faulted = False
        self.backend = None

        if backend_name == "fake":
            self.backend = FakeMotorBackend()
        elif backend_name == "can":
            self.backend = CanMotorBackend(
                motor_ids=motor_ids,
                direction_signs=direction_signs,
                acceleration=int(
                    self.get_parameter("acceleration").value
                ),
            )
        else:
            raise ValueError("backend must be 'fake' or 'can'")

        self.target_subscription = self.create_subscription(
            Int32MultiArray,
            "/zdt_motors/target_rpm",
            self.handle_target_rpm,
            1,
        )

        self.actual_publisher = self.create_publisher(
            Int32MultiArray,
            "/zdt_motors/actual_rpm",
            10,
        )

        self.enabled_publisher = self.create_publisher(
            Bool,
            "/zdt_motors/enabled",
            10,
        )

        self.connected_publisher = self.create_publisher(
            Bool,
            "/zdt_motors/connected",
            10,
        )

        self.simulated_publisher = self.create_publisher(
            Bool,
            "/zdt_motors/simulated",
            10,
        )

        self.enable_service = self.create_service(
            SetBool,
            "/zdt_motors/enable",
            self.handle_enable,
        )

        self.stop_service = self.create_service(
            Trigger,
            "/zdt_motors/stop",
            self.handle_stop,
        )

        self.state_timer = self.create_timer(
            1.0,
            self.publish_state,
        )

        self.watchdog_timer = self.create_timer(
            0.05,
            self.check_watchdog,
        )

        self.get_logger().warning(
            f"zdt motor backend={backend_name}; "
            f"motor_ids={motor_ids}"
        )

    def handle_target_rpm(self, message):
        values = [int(value) for value in message.data]

        if len(values) != 4:
            self.get_logger().warning(
                "Rejected RPM command: expected "
                "[FL, FR, RL, RR]"
            )
            return

        if any(abs(rpm) > self.maximum_rpm for rpm in values):
            self.get_logger().warning(
                f"Rejected RPM command: limit is "
                f"±{self.maximum_rpm} RPM"
            )
            return

        if any(values) and (self.faulted or not self.backend.enabled):
            self.get_logger().warning(
                "Rejected RPM command: call enable successfully first"
            )
            return

        try:
            self.backend.set_target_rpm(values)
        except Exception as error:
            self.enter_fault(
                f"RPM command failed: {type(error).__name__}: {error}"
            )
            return

        self.last_command_time = time.monotonic()

        if all(rpm == 0 for rpm in values):
            self.watchdog_stopped = True
        else:
            self.watchdog_stopped = False
        self.watchdog_warning_sent = False

        self.get_logger().info(
            f"Accepted RPM: {values}"
        )

    def handle_enable(self, request, response):
        was_enabled = self.backend.enabled and not self.faulted
        try:
            self.backend.set_enabled(request.data)
        except Exception as error:
            self.enter_fault(
                f"enable request failed: "
                f"{type(error).__name__}: {error}"
            )
            response.success = False
            response.message = str(error)
            return response

        if request.data:
            self.faulted = False
        if not request.data or not was_enabled:
            self.watchdog_stopped = True
            self.last_command_time = None

        response.success = True
        response.message = (
            "motors enabled"
            if request.data
            else "motors stopped and disabled"
        )

        return response

    def handle_stop(self, request, response):
        del request

        try:
            self.backend.stop()
        except Exception as error:
            self.enter_fault(
                f"stop request failed: "
                f"{type(error).__name__}: {error}"
            )
            response.success = False
            response.message = str(error)
            return response

        self.watchdog_stopped = True
        self.last_command_time = None

        response.success = True
        response.message = "motors stopped"

        return response

    def check_watchdog(self):
        if (
            self.last_command_time is None
            or self.watchdog_stopped
        ):
            return

        age = time.monotonic() - self.last_command_time

        if age <= self.command_timeout_s:
            return

        try:
            # Watchdog 超时只发送停止；通信异常再进入 stop+disable。
            self.backend.stop()
            self.watchdog_stopped = True
        except Exception as error:
            self.enter_fault(
                f"watchdog stop failed: "
                f"{type(error).__name__}: {error}"
            )
            return

        if not self.watchdog_warning_sent:
            self.get_logger().warning(
                f"RPM command timeout after {age:.3f}s; motors stopped"
            )
            self.watchdog_warning_sent = True

    def enter_fault(self, reason):
        """硬件或通信异常时停车、失能并锁定节点。"""
        if self.faulted:
            return

        self.faulted = True
        self.watchdog_stopped = True
        self.last_command_time = None
        self.get_logger().error(reason)
        try:
            self.backend.safe_stop_and_disable()
        except Exception as error:
            self.get_logger().error(
                f"fault safe stop/disable failed: {error}"
            )

    def publish_state(self):
        # 读失败时不发布伪造的零转速，故障通过 connected=false 表达。
        if not self.faulted:
            try:
                actual = Int32MultiArray()
                actual.data = self.backend.get_actual_rpm()
                self.actual_publisher.publish(actual)
            except Exception as error:
                self.enter_fault(f"RPM feedback failed: {error}")

        enabled = Bool()
        enabled.data = self.backend.enabled
        self.enabled_publisher.publish(enabled)

        connected = Bool()
        connected.data = bool(
            self.backend.hardware_connected and not self.faulted
        )
        self.connected_publisher.publish(connected)

        simulated = Bool()
        simulated.data = bool(self.backend.simulated)
        self.simulated_publisher.publish(simulated)

    def destroy_node(self):
        try:
            self.backend.safe_stop_and_disable()
        except Exception as error:
            self.get_logger().error(
                f"shutdown safe stop/disable failed: {error}"
            )
        finally:
            self.backend.close()
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = None

    try:
        node = ZdtMotorDriverNode()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
