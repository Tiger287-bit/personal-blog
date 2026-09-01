# SPDX-License-Identifier: MIT

import os
import threading
import time
import uuid

from arduino.app_utils import brick
from websockets.exceptions import ConnectionClosed
from websockets.sync.server import serve


@brick
class WebSocketServer:
    """与上层消息格式无关的 WebSocket 服务端 Brick。"""

    def __init__(
        self,
        host=None,
        port=None,
        path=None,
        max_message_bytes=None,
        max_clients=None,
        ping_interval_s=None,
        ping_timeout_s=None,
    ):
        """
        @description         : 创建 WebSocket 服务并读取 App Lab 注入的配置变量
        @param host          : 容器内监听地址，None 时读取环境变量
        @param port          : WebSocket 监听端口，None 时读取环境变量
        @param path          : 接受的 WebSocket 请求路径，None 时读取环境变量
        @param max_message_bytes : 单条文本或二进制消息的最大字节数
        @param max_clients   : 允许同时连接的最大客户端数
        @param ping_interval_s : WebSocket 协议 ping 帧发送间隔秒数
        @param ping_timeout_s : WebSocket 协议 pong 帧等待秒数
        @return              : 无返回值
        """
        self._host = host if host is not None else os.getenv(
            "WEBSOCKET_SERVER_HOST",
            "0.0.0.0",
        )
        self._port = self._read_int(
            port,
            "WEBSOCKET_SERVER_PORT",
            8765,
            1,
            65535,
        )
        self._path = path if path is not None else os.getenv(
            "WEBSOCKET_SERVER_PATH",
            "/ws",
        )
        self._max_message_bytes = self._read_int(
            max_message_bytes,
            "WEBSOCKET_SERVER_MAX_MESSAGE_BYTES",
            16 * 1024,
            1,
            16 * 1024 * 1024,
        )
        self._max_clients = self._read_int(
            max_clients,
            "WEBSOCKET_SERVER_MAX_CLIENTS",
            4,
            1,
            1024,
        )
        self._ping_interval_s = self._read_float(
            ping_interval_s,
            "WEBSOCKET_SERVER_PING_INTERVAL_S",
            10.0,
            0.1,
            3600.0,
        )
        self._ping_timeout_s = self._read_float(
            ping_timeout_s,
            "WEBSOCKET_SERVER_PING_TIMEOUT_S",
            10.0,
            0.1,
            3600.0,
        )

        if not isinstance(self._host, str) or not self._host.strip():
            raise ValueError("WEBSOCKET_SERVER_HOST must be a non-empty string")
        if (
            not isinstance(self._path, str)
            or not self._path.startswith("/")
            or "?" in self._path
            or "#" in self._path
        ):
            raise ValueError(
                "WEBSOCKET_SERVER_PATH must start with '/' and contain no query or fragment"
            )

        self._state_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._startup_event = threading.Event()
        self._server = None
        self._server_thread = None
        self._server_error = None
        self._clients = {}
        self._connect_callback = None
        self._message_callback = None
        self._disconnect_callback = None

    def start(self):
        """
        @description         : 在后台线程中启动 WebSocket 服务且不阻塞 App 主循环
        @param               : 无参数
        @return              : 服务进入启动流程后返回 True
        """
        with self._state_lock:
            if self._server_thread and self._server_thread.is_alive():
                return True
            self._server_error = None
            self._stop_event.clear()
            self._startup_event.clear()
            self._server_thread = threading.Thread(
                target=self._run_server,
                name="websocket-server-brick",
                daemon=True,
            )
            self._server_thread.start()

        if not self._startup_event.wait(timeout=5.0):
            print("[websocket_server] startup timed out after 5 seconds", flush=True)
            return False
        return self.get_status()["listening"]

    def stop(self):
        """
        @description         : 关闭所有客户端、释放监听端口并等待后台线程退出
        @param               : 无参数
        @return              : 无返回值
        """
        self._stop_event.set()
        with self._state_lock:
            server = self._server
            sockets = [session["socket"] for session in self._clients.values()]
            server_thread = self._server_thread

        for websocket in sockets:
            try:
                websocket.close(1001, "App Lab application is stopping")
            except Exception as exc:
                print(
                    f"[websocket_server] client close failed: {type(exc).__name__}: {exc}",
                    flush=True,
                )

        if server is not None:
            server.shutdown(reason="App Lab application is stopping")
        if server_thread and server_thread is not threading.current_thread():
            server_thread.join(timeout=5.0)

    def on_connect(self, callback):
        """
        @description         : 注册客户端成功接入后的回调函数
        @param callback      : 接收 client_info 字典的可调用对象，None 表示取消回调
        @return              : 当前 WebSocketServer 实例
        """
        if callback is not None and not callable(callback):
            raise TypeError("connect callback must be callable or None")
        with self._state_lock:
            self._connect_callback = callback
        return self

    def on_message(self, callback):
        """
        @description         : 注册收到未解析文本帧或二进制帧时的回调函数
        @param callback      : 接收 client_id 和 str 或 bytes payload 的可调用对象
        @return              : 当前 WebSocketServer 实例
        """
        if callback is not None and not callable(callback):
            raise TypeError("message callback must be callable or None")
        with self._state_lock:
            self._message_callback = callback
        return self

    def on_disconnect(self, callback):
        """
        @description         : 注册客户端断开后的回调函数
        @param callback      : 接收 client_info、关闭状态码和原因的可调用对象
        @return              : 当前 WebSocketServer 实例
        """
        if callback is not None and not callable(callback):
            raise TypeError("disconnect callback must be callable or None")
        with self._state_lock:
            self._disconnect_callback = callback
        return self

    def send(self, client_id, payload):
        """
        @description         : 向指定客户端发送一条未解析文本帧或二进制帧
        @param client_id     : 连接建立时由 Brick 分配的客户端标识
        @param payload       : str 文本消息或 bytes 二进制消息
        @return              : 发送成功返回 True，客户端不存在或已断开返回 False
        """
        self._validate_payload(payload)
        with self._state_lock:
            session = self._clients.get(client_id)
        if session is None:
            return False

        try:
            with session["send_lock"]:
                session["socket"].send(payload)
            return True
        except (ConnectionClosed, OSError, RuntimeError):
            return False

    def broadcast(self, payload):
        """
        @description         : 将同一条未解析消息发送给当前所有客户端
        @param payload       : str 文本消息或 bytes 二进制消息
        @return              : 成功发送的客户端数量
        """
        self._validate_payload(payload)
        with self._state_lock:
            client_ids = list(self._clients)
        return sum(1 for client_id in client_ids if self.send(client_id, payload))

    def disconnect(self, client_id, code=1000, reason=""):
        """
        @description         : 主动关闭指定客户端的 WebSocket 连接
        @param client_id     : 连接建立时由 Brick 分配的客户端标识
        @param code          : 合法的 WebSocket 关闭状态码
        @param reason        : UTF-8 关闭原因字符串
        @return              : 找到客户端并发起关闭返回 True，否则返回 False
        """
        with self._state_lock:
            session = self._clients.get(client_id)
        if session is None:
            return False
        session["socket"].close(code, reason)
        return True

    def get_clients(self):
        """
        @description         : 获取不包含底层 socket 的客户端信息快照
        @param               : 无参数
        @return              : 按 client_id 排序的客户端信息字典列表
        """
        with self._state_lock:
            clients = [self._client_info(session) for session in self._clients.values()]
        return sorted(clients, key=lambda client: client["client_id"])

    def get_status(self):
        """
        @description         : 获取监听配置、当前连接数和最近服务错误的状态快照
        @param               : 无参数
        @return              : 服务状态字典
        """
        with self._state_lock:
            server_thread = self._server_thread
            return {
                "host": self._host,
                "port": self._port,
                "path": self._path,
                "running": bool(server_thread and server_thread.is_alive()),
                "listening": self._server is not None,
                "client_count": len(self._clients),
                "max_clients": self._max_clients,
                "max_message_bytes": self._max_message_bytes,
                "server_error": self._server_error,
            }

    @staticmethod
    def _read_int(explicit_value, environment_name, default_value, minimum, maximum):
        """
        @description         : 从显式参数或环境变量读取受范围约束的整数
        @param explicit_value : 调用方显式提供的值
        @param environment_name : 环境变量名称
        @param default_value : 默认值
        @param minimum       : 最小允许值
        @param maximum       : 最大允许值
        @return              : 校验后的整数
        """
        value = explicit_value
        if value is None:
            value = os.getenv(environment_name, str(default_value))
        parsed = int(value)
        if parsed < minimum or parsed > maximum:
            raise ValueError(
                f"{environment_name} must be between {minimum} and {maximum}"
            )
        return parsed

    @staticmethod
    def _read_float(explicit_value, environment_name, default_value, minimum, maximum):
        """
        @description         : 从显式参数或环境变量读取受范围约束的浮点数
        @param explicit_value : 调用方显式提供的值
        @param environment_name : 环境变量名称
        @param default_value : 默认值
        @param minimum       : 最小允许值
        @param maximum       : 最大允许值
        @return              : 校验后的浮点数
        """
        value = explicit_value
        if value is None:
            value = os.getenv(environment_name, str(default_value))
        parsed = float(value)
        if parsed < minimum or parsed > maximum:
            raise ValueError(
                f"{environment_name} must be between {minimum} and {maximum}"
            )
        return parsed

    def _run_server(self):
        """
        @description         : 绑定端口并在专用线程中运行 WebSocket 服务
        @param               : 无参数
        @return              : 无返回值
        """
        try:
            with serve(
                self._handle_connection,
                self._host,
                self._port,
                compression=None,
                ping_interval=self._ping_interval_s,
                ping_timeout=self._ping_timeout_s,
                close_timeout=2.0,
                max_size=self._max_message_bytes,
                max_queue=16,
            ) as server:
                with self._state_lock:
                    self._server = server
                    self._server_error = None
                self._startup_event.set()
                print(
                    f"[websocket_server] listening on "
                    f"ws://{self._host}:{self._port}{self._path}",
                    flush=True,
                )
                server.serve_forever()
        except Exception as exc:
            with self._state_lock:
                self._server_error = f"{type(exc).__name__}: {exc}"
            self._startup_event.set()
            print(
                f"[websocket_server] server failed: {type(exc).__name__}: {exc}",
                flush=True,
            )
        finally:
            with self._state_lock:
                self._server = None

    def _handle_connection(self, websocket):
        """
        @description         : 校验路径、登记客户端并转交原始 WebSocket 消息
        @param websocket     : websockets 同步服务端连接对象
        @return              : 无返回值
        """
        request_path = websocket.request.path.split("?", 1)[0]
        if request_path != self._path:
            websocket.close(1008, f"expected path {self._path}")
            return

        client_id = uuid.uuid4().hex
        session = {
            "client_id": client_id,
            "remote_address": self._format_remote_address(websocket.remote_address),
            "path": request_path,
            "connected_monotonic_s": time.monotonic(),
            "socket": websocket,
            "send_lock": threading.Lock(),
        }

        with self._state_lock:
            if len(self._clients) >= self._max_clients:
                accepted = False
            else:
                self._clients[client_id] = session
                connect_callback = self._connect_callback
                accepted = True

        if not accepted:
            websocket.close(1013, "maximum client count reached")
            return

        client_info = self._client_info(session)
        try:
            if not self._invoke_callback(
                "connect",
                connect_callback,
                client_info,
            ):
                websocket.close(1011, "connect callback failed")
                return

            for payload in websocket:
                with self._state_lock:
                    message_callback = self._message_callback
                if not self._invoke_callback(
                    "message",
                    message_callback,
                    client_id,
                    payload,
                ):
                    websocket.close(1011, "message callback failed")
                    break
        except ConnectionClosed:
            pass
        except Exception as exc:
            print(
                f"[websocket_server] client {client_id} failed: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            try:
                websocket.close(1011, "WebSocket handler failed")
            except Exception:
                pass
        finally:
            with self._state_lock:
                current = self._clients.get(client_id)
                if current is session:
                    self._clients.pop(client_id, None)
                disconnect_callback = self._disconnect_callback
            close_code = getattr(websocket, "close_code", None)
            close_reason = getattr(websocket, "close_reason", "") or ""
            self._invoke_callback(
                "disconnect",
                disconnect_callback,
                client_info,
                close_code,
                close_reason,
            )

    def _validate_payload(self, payload):
        """
        @description         : 校验待发送消息类型和 UTF-8 编码后的实际字节数
        @param payload       : str 文本消息或 bytes 二进制消息
        @return              : 消息字节数
        """
        if isinstance(payload, str):
            payload_size = len(payload.encode("utf-8"))
        elif isinstance(payload, bytes):
            payload_size = len(payload)
        else:
            raise TypeError("payload must be str or bytes")
        if payload_size > self._max_message_bytes:
            raise ValueError(
                f"payload exceeds {self._max_message_bytes} configured bytes"
            )
        return payload_size

    @staticmethod
    def _format_remote_address(remote_address):
        """
        @description         : 将 websockets 返回的远端地址转换成稳定的日志字符串
        @param remote_address : 远端地址元组、字符串或 None
        @return              : 远端地址字符串
        """
        if isinstance(remote_address, tuple):
            return ":".join(str(item) for item in remote_address)
        return str(remote_address) if remote_address is not None else "unknown"

    @staticmethod
    def _client_info(session):
        """
        @description         : 从内部会话生成不暴露 socket 和锁的客户端信息
        @param session       : 内部客户端会话字典
        @return              : 可安全交给上层使用的客户端信息字典
        """
        return {
            "client_id": session["client_id"],
            "remote_address": session["remote_address"],
            "path": session["path"],
            "connected_monotonic_s": session["connected_monotonic_s"],
        }

    @staticmethod
    def _invoke_callback(callback_name, callback, *arguments):
        """
        @description         : 隔离上层回调异常，避免单个回调破坏服务线程
        @param callback_name : 用于日志定位的回调名称
        @param callback      : 待调用函数，None 表示无需处理
        @param arguments     : 传递给回调的位置参数
        @return              : 回调成功或不存在返回 True，抛出异常返回 False
        """
        if callback is None:
            return True
        try:
            callback(*arguments)
            return True
        except Exception as exc:
            print(
                f"[websocket_server] {callback_name} callback failed: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            return False

