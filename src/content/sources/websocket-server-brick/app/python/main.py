import time

from arduino.app_utils import App
from websocket_server import WebSocketServer


server = WebSocketServer()
_last_status = None


def handle_connect(client):
    """
    @description         : 记录新 WebSocket 客户端，回环 App 不发送应用层握手消息
    @param client        : Brick 提供的客户端信息字典
    @return              : 无返回值
    """
    print(
        f"[loopback] connected client={client['client_id']} "
        f"remote={client['remote_address']}",
        flush=True,
    )


def handle_message(client_id, payload):
    """
    @description         : 将收到的文本帧或二进制帧原样发回同一客户端
    @param client_id     : Brick 分配的客户端标识
    @param payload       : 未解析的 str 或 bytes 消息
    @return              : 无返回值
    """
    frame_type = "text" if isinstance(payload, str) else "binary"
    payload_size = len(payload.encode("utf-8")) if isinstance(payload, str) else len(payload)
    if not server.send(client_id, payload):
        print(f"[loopback] echo failed client={client_id}", flush=True)
        return
    print(
        f"[loopback] echoed client={client_id} type={frame_type} bytes={payload_size}",
        flush=True,
    )


def handle_disconnect(client, code, reason):
    """
    @description         : 记录 WebSocket 客户端断开事件
    @param client        : Brick 提供的客户端信息字典
    @param code          : WebSocket 关闭状态码，未知时为 None
    @param reason        : WebSocket 关闭原因字符串
    @return              : 无返回值
    """
    print(
        f"[loopback] disconnected client={client['client_id']} "
        f"code={code} reason={reason}",
        flush=True,
    )


def loop():
    """
    @description         : 输出服务状态变化并让出 CPU 给 App Lab 生命周期
    @param               : 无参数
    @return              : 无返回值
    """
    global _last_status

    status = server.get_status()
    status_snapshot = (
        status["listening"],
        status["client_count"],
        status["server_error"],
    )
    if status_snapshot != _last_status:
        print(
            f"[loopback] listening={status['listening']} "
            f"clients={status['client_count']} error={status['server_error']}",
            flush=True,
        )
        _last_status = status_snapshot
    time.sleep(0.05)


server.on_connect(handle_connect)
server.on_message(handle_message)
server.on_disconnect(handle_disconnect)
App.run(user_loop=loop)

