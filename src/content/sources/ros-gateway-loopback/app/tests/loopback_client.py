# SPDX-License-Identifier: MIT

import argparse
import json
import time

from websockets.sync.client import connect


def now_ms():
    """
    @description         : 获取当前 Unix 毫秒时间戳
    @param               : 无参数
    @return              : 当前 Unix 毫秒时间戳
    """
    return time.time_ns() // 1_000_000


def send_message(websocket, message):
    """
    @description         : 发送紧凑 JSON 文本消息
    @param websocket     : 已建立的 WebSocket 客户端连接
    @param message       : 待发送消息字典
    @return              : 无返回值
    """
    websocket.send(json.dumps(message, separators=(",", ":")))


def receive_json(websocket, timeout=3.0):
    """
    @description         : 接收并解析一条 JSON 文本消息
    @param websocket     : 已建立的 WebSocket 客户端连接
    @param timeout       : 接收超时秒数
    @return              : 解析后的消息字典
    """
    return json.loads(websocket.recv(timeout=timeout))


def receive_until(websocket, predicate, timeout=4.0):
    """
    @description         : 在限定时间内接收消息直到满足断言函数
    @param websocket     : 已建立的 WebSocket 客户端连接
    @param predicate     : 判断目标消息的函数
    @param timeout       : 总超时秒数
    @return              : 首条满足条件的消息
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = max(0.01, deadline - time.monotonic())
        message = receive_json(websocket, timeout=remaining)
        if predicate(message):
            return message
    raise TimeoutError("expected WebSocket message was not received")


def run_test(url):
    """
    @description         : 执行端口、握手、心跳、状态和错误路径的回环测试
    @param url           : WebSocket 服务地址
    @return              : 测试结果字典
    """
    results = {
        "url": url,
        "hello": False,
        "mode_change": False,
        "base_state": False,
        "heartbeat": False,
        "overspeed_rejected": False,
        "stale_rejected": False,
        "invalid_field_rejected": False,
    }

    with connect(url, open_timeout=3.0, close_timeout=2.0) as websocket:
        send_message(
            websocket,
            {
                "version": 1,
                "type": "hello",
                "role": "ros2",
                "node": "loopback_client",
            },
        )
        hello = receive_until(websocket, lambda item: item.get("type") == "hello")
        results["hello"] = hello.get("role") == "app"

        send_message(
            websocket,
            {
                "version": 1,
                "type": "mode_change",
                "seq": 1,
                "timestamp_ms": now_ms(),
                "mode": "ROS_TELEOP",
            },
        )
        acknowledgement = receive_until(
            websocket,
            lambda item: item.get("type") == "ack" and item.get("seq") == 1,
        )
        results["mode_change"] = acknowledgement.get("accepted") is True

        send_message(
            websocket,
            {
                "version": 1,
                "type": "heartbeat",
                "seq": 2,
                "timestamp_ms": now_ms(),
            },
        )
        send_message(
            websocket,
            {
                "version": 1,
                "type": "cmd_vel",
                "seq": 3,
                "timestamp_ms": now_ms(),
                "vx": 0.2,
                "vy": -0.1,
                "wz": 0.3,
            },
        )

        deadline = time.monotonic() + 2.2
        while time.monotonic() < deadline:
            message = receive_json(websocket, timeout=max(0.01, deadline - time.monotonic()))
            results["base_state"] |= message.get("type") == "base_state"
            results["heartbeat"] |= message.get("type") == "heartbeat"
            if results["base_state"] and results["heartbeat"]:
                break

        send_message(
            websocket,
            {
                "version": 1,
                "type": "cmd_vel",
                "seq": 4,
                "timestamp_ms": now_ms(),
                "vx": 99.0,
                "vy": 0.0,
                "wz": 0.0,
            },
        )
        overspeed = receive_until(
            websocket,
            lambda item: item.get("type") == "error" and item.get("seq") == 4,
        )
        results["overspeed_rejected"] = overspeed.get("code") == "out_of_range"

        send_message(
            websocket,
            {
                "version": 1,
                "type": "cmd_vel",
                "seq": 5,
                "timestamp_ms": now_ms() - 1000,
                "vx": 0.1,
                "vy": 0.0,
                "wz": 0.0,
            },
        )
        stale = receive_until(
            websocket,
            lambda item: item.get("type") == "error" and item.get("seq") == 5,
        )
        results["stale_rejected"] = stale.get("code") == "stale_command"

        send_message(
            websocket,
            {
                "version": 1,
                "type": "cmd_vel",
                "seq": 6,
                "timestamp_ms": now_ms(),
                "vx": "fast",
                "vy": 0.0,
                "wz": 0.0,
            },
        )
        invalid_field = receive_until(
            websocket,
            lambda item: item.get("type") == "error" and item.get("seq") == 6,
        )
        results["invalid_field_rejected"] = invalid_field.get("code") == "invalid_field"

    return results


def main():
    """
    @description         : 解析命令行参数、执行测试并设置进程退出码
    @param               : 无参数
    @return              : 无返回值
    """
    parser = argparse.ArgumentParser(description="Test the ROS Gateway WebSocket endpoint")
    parser.add_argument("--url", default="ws://127.0.0.1:8765/ros")
    arguments = parser.parse_args()
    results = run_test(arguments.url)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    if not all(value for key, value in results.items() if key != "url"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
