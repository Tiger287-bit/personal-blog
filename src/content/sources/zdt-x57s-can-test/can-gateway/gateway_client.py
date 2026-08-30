#!/usr/bin/env python3
"""
@description         : 从Linux主机手动调用ZDT X57S CAN网关用于诊断
@param               : 无
@return              : 无
"""

import argparse
import json
import os
import socket
import uuid


MOTION_CONFIRMATION = "RUN_ZDT_X57S_V1_0"


def parse_args():
    """
    @description         : 解析网关状态、探测或单电机限时测试参数
    @param               : 无
    @return              : argparse.Namespace参数对象
    """
    parser = argparse.ArgumentParser(description="Call the local CAN gateway.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--status", action="store_true")
    action.add_argument("--probe", action="store_true")
    action.add_argument("--motor-test", action="store_true")
    parser.add_argument("--host", default="172.17.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--motor-id", type=int, default=1)
    parser.add_argument("--rpm", type=int, default=20)
    parser.add_argument("--acceleration-level", type=int, default=10)
    parser.add_argument("--duration", type=float, default=3.0)
    parser.add_argument("--confirm", default="")
    parser.add_argument(
        "--token-file",
        default=os.path.join(os.path.dirname(__file__), ".gateway-token"),
    )
    return parser.parse_args()


def load_token(path):
    """
    @description         : 读取Linux网关共享鉴权令牌
    @param path          : 令牌文件路径
    @return              : 非空令牌字符串
    """
    with open(path, "r", encoding="utf-8") as token_stream:
        token = token_stream.read().strip()
    if not token:
        raise RuntimeError("gateway token file is empty")
    return token


def call_gateway(host, port, token, method, params, timeout_s):
    """
    @description         : 发送一条换行分隔JSON请求并读取响应
    @param host          : 网关地址
    @param port          : 网关端口
    @param token         : 共享鉴权令牌
    @param method        : 网关方法名称
    @param params        : 方法参数字典
    @param timeout_s     : 连接和响应超时时间
    @return              : 解码后的响应字典
    """
    request = {
        "version": 1,
        "request_id": uuid.uuid4().hex,
        "token": token,
        "method": method,
        "params": params,
    }
    with socket.create_connection((host, port), timeout=timeout_s) as connection:
        connection.settimeout(timeout_s)
        connection.sendall((json.dumps(request) + "\n").encode("utf-8"))
        with connection.makefile("rb") as response_stream:
            response_line = response_stream.readline(65537)
    if not response_line:
        raise RuntimeError("gateway closed without a response")
    return json.loads(response_line.decode("utf-8"))


def main():
    """
    @description         : 根据命令行参数调用网关并打印格式化JSON结果
    @param               : 无
    @return              : 网关成功返回0; 网关失败返回1; 确认失败返回2
    """
    args = parse_args()
    token = load_token(args.token_file)
    if args.status:
        method = "status"
        params = {}
        timeout_s = 2.0
    elif args.probe:
        method = "read_speed"
        params = {"motor_id": args.motor_id}
        timeout_s = 2.0
    else:
        if args.confirm != MOTION_CONFIRMATION:
            print(
                "拒绝运行：请确认电机已架空并添加 "
                f"--confirm {MOTION_CONFIRMATION}"
            )
            return 2
        method = "timed_speed_test"
        params = {
            "motor_id": args.motor_id,
            "rpm": args.rpm,
            "acceleration_level": args.acceleration_level,
            "duration_s": args.duration,
            "confirmation": args.confirm,
        }
        timeout_s = args.duration + 5.0

    response = call_gateway(
        args.host, args.port, token, method, params, timeout_s
    )
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0 if response.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
