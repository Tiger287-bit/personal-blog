import argparse
import os
from contextlib import ExitStack
from urllib.parse import urlsplit, urlunsplit

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect


DEFAULT_PORT = os.getenv("WEBSOCKET_SERVER_PORT", "8765")
DEFAULT_PATH = os.getenv("WEBSOCKET_SERVER_PATH", "/ws")
DEFAULT_URL = os.getenv(
    "WEBSOCKET_TEST_URL",
    f"ws://127.0.0.1:{DEFAULT_PORT}{DEFAULT_PATH}",
)
DEFAULT_MAX_CLIENTS = os.getenv(
    "WEBSOCKET_TEST_MAX_CLIENTS",
    os.getenv("WEBSOCKET_SERVER_MAX_CLIENTS", "4"),
)


def parse_arguments():
    """
    @description         : 读取测试地址和服务端最大客户端数并检查基础格式
    @param               : 无参数
    @return              : 已校验的命令行参数
    """
    parser = argparse.ArgumentParser(
        description="Test the protocol-neutral websocket_server Brick.",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"WebSocket endpoint (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--max-clients",
        type=int,
        default=DEFAULT_MAX_CLIENTS,
        help=f"configured simultaneous client limit (default: {DEFAULT_MAX_CLIENTS})",
    )
    arguments = parser.parse_args()

    parsed_url = urlsplit(arguments.url)
    if parsed_url.scheme not in ("ws", "wss") or not parsed_url.netloc:
        parser.error("--url must be a complete ws:// or wss:// URL")
    if not 1 <= arguments.max_clients <= 64:
        parser.error("--max-clients must be between 1 and 64")
    return arguments


def build_wrong_path_url(url):
    """
    @description         : 根据目标服务地址生成必定不同的错误路径测试地址
    @param url           : 正常 WebSocket 服务地址
    @return              : 使用同一主机和端口的错误路径地址
    """
    parsed_url = urlsplit(url)
    return urlunsplit(
        (
            parsed_url.scheme,
            parsed_url.netloc,
            "/__websocket_brick_wrong_path__",
            "",
            "",
        )
    )


def require_equal(actual, expected, test_name):
    """
    @description         : 比较测试结果，不一致时立即抛出断言错误
    @param actual        : 实际结果
    @param expected      : 期望结果
    @param test_name     : 测试名称
    @return              : 无返回值
    """
    if actual != expected:
        raise AssertionError(f"{test_name}: expected {expected!r}, got {actual!r}")


def test_text_and_binary(url):
    """
    @description         : 验证文本帧与二进制帧能够保持类型和内容原样回环
    @param url           : 正常 WebSocket 服务地址
    @return              : 无返回值
    """
    with connect(url, open_timeout=3, close_timeout=1) as client:
        client.send("hello websocket")
        require_equal(client.recv(timeout=3), "hello websocket", "text echo")

        payload = bytes([0x00, 0x01, 0x7F, 0x80, 0xFF])
        client.send(payload)
        require_equal(client.recv(timeout=3), payload, "binary echo")
    print("PASS text and binary echo")


def test_two_clients(url):
    """
    @description         : 验证两个客户端同时连接时消息不会互相串线
    @param url           : 正常 WebSocket 服务地址
    @return              : 无返回值
    """
    with connect(url, open_timeout=3, close_timeout=1) as first:
        with connect(url, open_timeout=3, close_timeout=1) as second:
            first.send("from-client-1")
            second.send("from-client-2")
            require_equal(first.recv(timeout=3), "from-client-1", "client 1 echo")
            require_equal(second.recv(timeout=3), "from-client-2", "client 2 echo")
    print("PASS two independent clients")


def test_wrong_path(url):
    """
    @description         : 验证服务端以策略错误关闭不匹配的 WebSocket 路径
    @param url           : 正常 WebSocket 服务地址
    @return              : 无返回值
    """
    try:
        with connect(build_wrong_path_url(url), open_timeout=3, close_timeout=1) as client:
            client.recv(timeout=3)
    except ConnectionClosed as exc:
        require_equal(exc.code, 1008, "wrong path close code")
        print("PASS wrong path rejected")
        return
    raise AssertionError("wrong path: server did not close the connection")


def test_client_limit(url, max_clients):
    """
    @description         : 验证达到配置上限后新增客户端会被临时拒绝
    @param url           : 正常 WebSocket 服务地址
    @param max_clients   : 服务端配置的最大同时连接数
    @return              : 无返回值
    """
    with ExitStack() as stack:
        clients = [
            stack.enter_context(connect(url, open_timeout=3, close_timeout=1))
            for _ in range(max_clients)
        ]
        for index, client in enumerate(clients, start=1):
            message = f"client-{index}"
            client.send(message)
            require_equal(client.recv(timeout=3), message, f"client {index} active")

        try:
            with connect(url, open_timeout=3, close_timeout=1) as extra:
                extra.recv(timeout=3)
        except ConnectionClosed as exc:
            require_equal(exc.code, 1013, "client limit close code")
            print("PASS maximum client limit")
            return
    raise AssertionError("client limit: fifth client was not rejected")


def main():
    """
    @description         : 读取参数并顺序执行通用 WebSocket Brick 端到端测试
    @param               : 无参数
    @return              : 无返回值
    """
    arguments = parse_arguments()
    print(f"Testing {arguments.url} (max_clients={arguments.max_clients})")
    test_text_and_binary(arguments.url)
    if arguments.max_clients >= 2:
        test_two_clients(arguments.url)
    else:
        print("SKIP two independent clients (max_clients is 1)")
    test_wrong_path(arguments.url)
    test_client_limit(arguments.url, arguments.max_clients)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
