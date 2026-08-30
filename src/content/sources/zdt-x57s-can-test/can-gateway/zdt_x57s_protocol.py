"""
@description         : 封装ZDT X57S第二代闭环电机FW_Emm固定CAN协议
@param               : 无
@return              : 无
"""

CHECKSUM = 0x6B
ACK_SUCCESS = 0x02
ACK_REJECTED = 0xE2


class ZdtProtocolError(RuntimeError):
    """
    @description         : 表示ZDT应答格式错误或电机拒绝命令
    @param message       : 错误说明
    @return              : ZdtProtocolError实例
    """

    def __init__(self, message):
        """
        @description         : 初始化ZDT协议异常
        @param message       : 错误说明
        @return              : 无
        """
        super().__init__(message)


def validate_motor_id(motor_id, allow_broadcast=False):
    """
    @description         : 检查ZDT电机地址是否合法
    @param motor_id      : 电机地址
    @param allow_broadcast: true允许广播地址0; false仅允许1至255
    @return              : 合法时返回规范化整数地址
    """
    normalized_id = int(motor_id)
    minimum_id = 0 if allow_broadcast else 1
    if normalized_id < minimum_id or normalized_id > 255:
        raise ValueError("motor_id must be in the valid address range")
    return normalized_id


def arbitration_id(motor_id, packet_index=0):
    """
    @description         : 生成ZDT CAN扩展帧标识符Addr左移8位或分包序号
    @param motor_id      : 电机地址，范围0至255
    @param packet_index  : 分包序号，范围0至255
    @return              : 29位CAN扩展帧标识符
    """
    normalized_id = validate_motor_id(motor_id, allow_broadcast=True)
    normalized_packet = int(packet_index)
    if normalized_packet < 0 or normalized_packet > 255:
        raise ValueError("packet_index must be in range 0-255")
    return (normalized_id << 8) | normalized_packet


def build_speed_query():
    """
    @description         : 构造读取电机实时转速命令
    @param               : 无
    @return              : 数据35 6B
    """
    return bytes((0x35, CHECKSUM))


def build_enable_command(enabled, synchronized=False):
    """
    @description         : 构造电机使能或失能命令
    @param enabled       : true使能; false失能
    @param synchronized  : true等待同步启动; false立即执行
    @return              : F3功能码命令数据
    """
    return bytes(
        (
            0xF3,
            0xAB,
            0x01 if enabled else 0x00,
            0x01 if synchronized else 0x00,
            CHECKSUM,
        )
    )


def build_speed_command(rpm, acceleration_level, synchronized=False):
    """
    @description         : 构造FW_Emm速度模式F6命令
    @param rpm           : 带符号目标转速，单位整数RPM，范围负3000至3000
    @param acceleration_level: 加减速档位，范围0至255，0表示直接启动
    @param synchronized  : true等待同步启动; false立即执行
    @return              : 7字节F6命令数据
    """
    normalized_rpm = int(rpm)
    normalized_acceleration = int(acceleration_level)
    if normalized_rpm < -3000 or normalized_rpm > 3000:
        raise ValueError("rpm must be in range -3000 to 3000")
    if normalized_acceleration < 0 or normalized_acceleration > 255:
        raise ValueError("acceleration_level must be in range 0-255")

    speed = abs(normalized_rpm)
    return bytes(
        (
            0xF6,
            0x01 if normalized_rpm < 0 else 0x00,
            (speed >> 8) & 0xFF,
            speed & 0xFF,
            normalized_acceleration,
            0x01 if synchronized else 0x00,
            CHECKSUM,
        )
    )


def build_stop_command(synchronized=False):
    """
    @description         : 构造立即停止命令
    @param synchronized  : true等待同步启动; false立即执行
    @return              : FE功能码命令数据
    """
    return bytes(
        (0xFE, 0x98, 0x01 if synchronized else 0x00, CHECKSUM)
    )


def parse_ack(data, expected_function):
    """
    @description         : 校验ZDT控制命令确认应答
    @param data          : 电机返回的数据字节
    @param expected_function: 期望的功能码
    @return              : 校验成功返回True
    """
    payload = bytes(data)
    if len(payload) < 3:
        raise ZdtProtocolError("acknowledgement is too short")
    if payload[-1] != CHECKSUM:
        raise ZdtProtocolError("acknowledgement checksum is invalid")
    if payload[0] != expected_function:
        raise ZdtProtocolError("unexpected acknowledgement function code")
    if payload[1] == ACK_REJECTED:
        raise ZdtProtocolError("motor rejected the command")
    if payload[1] != ACK_SUCCESS:
        raise ZdtProtocolError("unexpected acknowledgement status")
    return True


def parse_speed_reply(data):
    """
    @description         : 解析FW_Emm实时转速应答
    @param data          : 期望格式35 方向 转速高字节 转速低字节 6B
    @return              : 带符号实时转速，单位整数RPM
    """
    payload = bytes(data)
    if len(payload) != 5:
        raise ZdtProtocolError("speed reply length must be 5 bytes")
    if payload[0] != 0x35 or payload[-1] != CHECKSUM:
        raise ZdtProtocolError("speed reply function or checksum is invalid")
    if payload[1] not in (0x00, 0x01):
        raise ZdtProtocolError("speed reply direction is invalid")

    magnitude = (payload[2] << 8) | payload[3]
    return -magnitude if payload[1] == 0x01 else magnitude
