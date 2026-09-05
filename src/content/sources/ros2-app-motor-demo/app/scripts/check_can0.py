#!/usr/bin/env python3
"""只读检查 SocketCAN 接口，不修改系统状态。"""

import argparse
from pathlib import Path
import socket
import subprocess


def parse_args():
    """
    @description         : 解析待检查SocketCAN接口名
    @param               : 无参数
    @return              : argparse.Namespace
    """
    parser = argparse.ArgumentParser(
        description="Read-only SocketCAN interface check."
    )
    parser.add_argument("--device", default="can0")
    return parser.parse_args()


def read_text(path):
    """
    @description         : 安全读取sysfs单行文本
    @param path          : pathlib.Path
    @return              : 文本或unknown
    """
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def check_interface(device):
    """
    @description         : 检查接口存在性、状态、类型和SocketCAN绑定能力
    @param device        : 接口名称
    @return              : 成功返回True
    """
    sysfs = Path("/sys/class/net") / device
    if not sysfs.exists():
        print(f"FAIL: interface {device!r} does not exist")
        return False
    print(f"PASS: interface exists: {device}")
    print(f"state: {read_text(sysfs / 'operstate')}")
    print(f"mtu: {read_text(sysfs / 'mtu')}")
    try:
        details = subprocess.run(
            ["ip", "-details", "-statistics", "link", "show", "dev", device],
            check=True,
            capture_output=True,
            text=True,
        )
        print(details.stdout.rstrip())
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"FAIL: cannot inspect interface with ip: {error}")
        return False
    can_socket = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    try:
        can_socket.bind((device,))
        print("PASS: raw SocketCAN socket opened and bound")
    except OSError as error:
        print(f"FAIL: SocketCAN bind failed: {error}")
        return False
    finally:
        can_socket.close()
    state = read_text(sysfs / "operstate")
    if state not in ("up", "unknown"):
        print("FAIL: interface is not UP; this script does not change it")
        return False
    return True


def main():
    """
    @description         : 执行只读can0检查并设置进程退出码
    @param               : 无参数
    @return              : 成功0，失败1
    """
    args = parse_args()
    return 0 if check_interface(args.device) else 1


if __name__ == "__main__":
    raise SystemExit(main())
