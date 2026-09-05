"""面向高级调试的 ZDT 原始逻辑命令接口。"""

from .commands.common import build_raw


class RawMotorAPI:
    """不要求用户手动计算 Extended CAN ID 或分包。"""

    def __init__(self, motor):
        """
        @description         : 绑定一个ZDTMotor对象
        @param motor         : ZDTMotor实例
        @return              : 无返回值
        """
        self._motor = motor

    def request(
        self,
        function_code,
        payload=b"",
        *,
        expected_response_length=3,
        timeout_s=None,
    ):
        """
        @description         : 发送原始逻辑命令并返回校验完成的响应
        @param function_code : 功能码
        @param payload       : 不含功能码和校验码的命令数据
        @param expected_response_length: 期望逻辑应答总长度
        @param timeout_s     : 可选超时秒数
        @return              : ZDTResponse
        """
        command = build_raw(
            function_code,
            payload,
            expected_response_length=expected_response_length,
        )
        return self._motor.bus.request(
            self._motor.motor_id,
            command,
            timeout_s=timeout_s,
        )
