# SPDX-License-Identifier: MIT

import argparse
from contextlib import contextmanager
import json
import time

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect


def send_json(websocket, message):
    """
    @description         : 向服务端发送紧凑 JSON 文本
    @param websocket     : 已建立的 WebSocket 客户端连接
    @param message       : 待发送消息字典
    @return              : 无返回值
    """
    websocket.send(json.dumps(message, separators=(",", ":")))


def receive_json(websocket, timeout=3.0):
    """
    @description         : 接收并解析一条服务端 JSON 消息
    @param websocket     : 已建立的 WebSocket 客户端连接
    @param timeout       : 接收超时秒数
    @return              : 解析后的消息字典
    """
    return json.loads(websocket.recv(timeout=timeout))


@contextmanager
def open_owner(url, node):
    """
    @description         : 建立连接并完成 ROS 2 客户端握手
    @param url           : WebSocket 服务地址
    @param node          : 测试客户端节点名称
    @return              : 产生已完成握手连接的上下文管理器
    """
    with connect(url, open_timeout=3.0, close_timeout=2.0) as websocket:
        send_json(
            websocket,
            {
                "version": 1,
                "type": "hello",
                "role": "ros2",
                "node": node,
            },
        )
        hello = receive_json(websocket)
        if hello.get("type") != "hello" or hello.get("role") != "app":
            raise RuntimeError("server hello was not received")
        yield websocket


def test_wrong_path(base_url):
    """
    @description         : 验证非 /ros 路径会被策略关闭
    @param base_url      : 正确 WebSocket 服务地址
    @return              : 关闭码为 1008 时返回 True
    """
    wrong_url = base_url.rsplit("/", 1)[0] + "/wrong"
    try:
        with connect(wrong_url, open_timeout=3.0, close_timeout=2.0) as websocket:
            websocket.recv(timeout=2.0)
    except ConnectionClosed as exc:
        return exc.code == 1008
    return False


def test_protocol_errors(url):
    """
    @description         : 验证非法 JSON 与非递增序号返回结构化错误
    @param url           : WebSocket 服务地址
    @return              : 两个错误路径均正确时返回 True
    """
    with open_owner(url, "edge_case_protocol") as websocket:
        websocket.send("{")
        invalid_json = receive_json(websocket)

        send_json(
            websocket,
            {
                "version": 1,
                "type": "heartbeat",
                "seq": 10,
                "timestamp_ms": time.time_ns() // 1_000_000,
            },
        )
        send_json(
            websocket,
            {
                "version": 1,
                "type": "heartbeat",
                "seq": 10,
                "timestamp_ms": time.time_ns() // 1_000_000,
            },
        )

        deadline = time.monotonic() + 3.0
        sequence_error = None
        while time.monotonic() < deadline:
            message = receive_json(websocket, max(0.01, deadline - time.monotonic()))
            if message.get("type") == "error" and message.get("code") == "non_monotonic_seq":
                sequence_error = message
                break

        return (
            invalid_json.get("type") == "error"
            and invalid_json.get("code") == "invalid_json"
            and sequence_error is not None
        )


def test_single_owner(url):
    """
    @description         : 验证第二个客户端不能抢占已握手客户端
    @param url           : WebSocket 服务地址
    @return              : 第二连接收到 1013 关闭码时返回 True
    """
    with open_owner(url, "edge_case_owner"):
        try:
            with connect(url, open_timeout=3.0, close_timeout=2.0) as contender:
                contender.recv(timeout=2.0)
        except ConnectionClosed as exc:
            return exc.code == 1013
    return False


def test_heartbeat_timeout_and_reconnect(url):
    """
    @description         : 验证无应用层心跳会断开，且随后能够重新握手
    @param url           : WebSocket 服务地址
    @return              : 超时关闭和再次握手均成功时返回 True
    """
    timeout_closed = False
    with open_owner(url, "edge_case_timeout") as websocket:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                websocket.recv(timeout=max(0.01, deadline - time.monotonic()))
            except ConnectionClosed as exc:
                timeout_closed = exc.code == 1008
                break

    with open_owner(url, "edge_case_reconnect"):
        reconnected = True
    return timeout_closed and reconnected


def run(url):
    """
    @description         : 顺序执行 WebSocket 运行时边界测试
    @param url           : WebSocket 服务地址
    @return              : 测试名称到布尔结果的字典
    """
    return {
        "wrong_path_rejected": test_wrong_path(url),
        "protocol_errors": test_protocol_errors(url),
        "single_owner": test_single_owner(url),
        "heartbeat_timeout_and_reconnect": test_heartbeat_timeout_and_reconnect(url),
    }


def main():
    """
    @description         : 解析命令行参数并根据边界测试结果设置退出码
    @param               : 无参数
    @return              : 无返回值
    """
    parser = argparse.ArgumentParser(description="Test ROS Gateway runtime edge cases")
    parser.add_argument("--url", default="ws://127.0.0.1:8765/ros")
    arguments = parser.parse_args()
    results = run(arguments.url)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    if not all(results.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
