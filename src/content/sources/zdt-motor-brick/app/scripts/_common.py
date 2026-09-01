"""ZDT 宿主机测试脚本的公共参数和输出工具。"""

from pathlib import Path
import sys


APP_ROOT = Path(__file__).resolve().parents[1]
BRICKS_ROOT = APP_ROOT / "bricks"
if str(BRICKS_ROOT) not in sys.path:
    sys.path.insert(0, str(BRICKS_ROOT))

from zdt_motor import ZDTBus, ZDTMotor  # noqa: E402
from zdt_motor.protocols import parse_arbitration_id  # noqa: E402


def add_motor_arguments(parser):
    """
    @description         : 为测试脚本添加可复用电机和接口参数
    @param parser        : argparse.ArgumentParser
    @return              : 无返回值
    """
    parser.add_argument("--device", default="can0")
    parser.add_argument("--id", type=int, default=1, dest="motor_id")
    parser.add_argument("--firmware", choices=("emm", "x"), default="emm")
    parser.add_argument("--model", default="X57S")
    parser.add_argument(
        "--checksum",
        choices=("fixed_6b", "xor", "crc8"),
        default="fixed_6b",
    )
    parser.add_argument("--timeout", type=float, default=0.5)


def create_bus_and_motor(args, *, trace=False):
    """
    @description         : 根据命令行参数创建共享Bus和单电机对象
    @param args          : argparse解析结果
    @param trace         : 是否打印原始CAN帧
    @return              : ZDTBus和ZDTMotor二元组
    """
    callback = print_trace if trace else None
    bus = ZDTBus(
        interface="can",
        device=args.device,
        checksum=args.checksum,
        default_timeout_s=args.timeout,
        trace_callback=callback,
    )
    motor = ZDTMotor(
        bus=bus,
        motor_id=args.motor_id,
        model=args.model,
        firmware=args.firmware,
        timeout_s=args.timeout,
    )
    return bus, motor


def format_frame(frame):
    """
    @description         : 将ZDT CAN帧格式化为可复制的诊断文本
    @param frame         : CanFrame
    @return              : 格式化字符串
    """
    try:
        motor_id, packet = parse_arbitration_id(frame.arbitration_id)
        address_text = f"motor={motor_id} packet={packet}"
    except Exception:
        address_text = "motor=? packet=?"
    return (
        f"{frame.timestamp:.6f} ID=0x{frame.arbitration_id:08X} "
        f"{address_text} data={frame.data.hex(' ').upper()}"
    )


def print_trace(trace):
    """
    @description         : 打印一条带收发方向的原始CAN记录
    @param trace         : BusTrace
    @return              : 无返回值
    """
    print(f"RAW {trace.direction.upper()} {format_frame(trace.frame)}", flush=True)


def parse_hex_bytes(text):
    """
    @description         : 把空格或冒号分隔HEX字符串转换为字节
    @param text          : HEX字符串
    @return              : bytes
    """
    normalized = str(text).replace(":", " ").replace(",", " ").strip()
    return bytes.fromhex(normalized) if normalized else b""
