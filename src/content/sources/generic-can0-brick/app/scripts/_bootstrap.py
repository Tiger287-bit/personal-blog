"""让独立脚本直接使用当前App内的Brick和报文定义。"""

from pathlib import Path
import sys


APP_ROOT = Path(__file__).resolve().parents[1]
for source_directory in (APP_ROOT / "bricks", APP_ROOT / "python"):
    source_text = str(source_directory)
    if source_text not in sys.path:
        sys.path.insert(0, source_text)


def parse_can_id(text):
    """
    @description         : 解析0x123或十进制形式的CAN ID命令行参数
    @param text          : 用户输入的ID字符串
    @return              : 整数CAN ID
    """
    try:
        return int(text, 0)
    except (TypeError, ValueError) as error:
        raise ValueError("CAN ID must be an integer such as 0x123") from error


def parse_hex_data(values):
    """
    @description         : 把命令行中的十六进制字节列表转换成bytes
    @param values        : 例如01、A0、ff组成的字符串列表
    @return              : CAN DATA bytes
    """
    result = []
    for value in values:
        try:
            parsed = int(value, 16)
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid hex byte '{value}'") from error
        if not 0 <= parsed <= 0xFF or len(value) > 2:
            raise ValueError(f"hex byte '{value}' must be 00..FF")
        result.append(parsed)
    return bytes(result)


def format_frame(frame, direction="RX"):
    """
    @description         : 把CanFrame格式化成统一CAN Monitor文本
    @param frame         : 需要显示的CanFrame
    @param direction     : RX或TX方向标签
    @return              : 一行可读报文文本
    """
    identifier = (
        f"0x{frame.arbitration_id:08X}"
        if frame.is_extended
        else f"0x{frame.arbitration_id:03X}"
    )
    id_kind = "EXT" if frame.is_extended else "STD"
    frame_kind = "FD+BRS" if frame.bitrate_switch else (
        "FD" if frame.is_fd else "CAN"
    )
    data = " ".join(f"{byte:02X}" for byte in frame.data) or "--"
    return (
        f"{frame.timestamp:12.6f} {direction} {id_kind} {frame_kind} "
        f"{identifier} [{len(frame.data)}] {data}"
    )
