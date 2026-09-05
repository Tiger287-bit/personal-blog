"""Connect the protocol-neutral WebSocket Brick to the MCU LED RPC."""

import json
import queue
import time

from arduino.app_utils import App, Bridge
from websocket_server import WebSocketServer


LED_COMMAND_TOPIC = "/my_ros2_02/led_command"
LED_STATE_TOPIC = "/my_ros2_02/led_state"
LED_MESSAGE_TYPE = "std_msgs/msg/UInt8MultiArray"
STRING_MESSAGE_TYPE = "std_msgs/msg/String"
ALL_OFF = (0, 0, 0, 0)

server = WebSocketServer()
events = queue.Queue(maxsize=32)
current_leds = ALL_OFF
mcu_ready = False
last_server_status = None


def make_envelope(direction, topic, ros_type, sequence, data):
    """Build one JSON-safe ROS WebSocket envelope."""
    return {
        "direction": direction,
        "topic": topic,
        "ros_type": ros_type,
        "seq": int(sequence),
        "timestamp": int(time.time() * 1000),
        "data": data,
    }


def send_envelope(client_id, message):
    """Encode and send one text-frame envelope."""
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    return server.send(client_id, payload)


def send_error(client_id, sequence, error_text):
    """Return an error as a normal ROS String envelope."""
    message = make_envelope(
        "ws_to_ros",
        "/my_ros2_02/error",
        STRING_MESSAGE_TYPE,
        sequence,
        {"data": str(error_text)},
    )
    send_envelope(client_id, message)


def mask_to_leds(mask):
    """Convert the MCU bit mask into four LED values."""
    if not isinstance(mask, int) or isinstance(mask, bool):
        raise ValueError("get_leds must return an integer")
    if mask < 0 or mask > 15:
        raise ValueError("get_leds returned a value outside 0..15")
    return tuple((mask >> index) & 1 for index in range(4))


def set_leds_on_mcu(leds):
    """Send four LED values to the MCU and read back the result."""
    values = tuple(int(value) for value in leds)
    if len(values) != 4 or any(value not in (0, 1) for value in values):
        raise ValueError("LED command must contain four 0/1 values")

    accepted = Bridge.call(
        "set_leds",
        bool(values[0]),
        bool(values[1]),
        bool(values[2]),
        bool(values[3]),
        timeout=3,
    )
    if accepted is False:
        raise RuntimeError("MCU rejected set_leds")
    return mask_to_leds(Bridge.call("get_leds", timeout=3))


def validate_envelope(message):
    """Validate the common fields and return the sequence number."""
    if not isinstance(message, dict):
        raise ValueError("message must be a JSON object")

    if message.get("direction") != "ros_to_ws":
        raise ValueError("direction must be ros_to_ws")

    if not isinstance(message.get("topic"), str):
        raise ValueError("topic must be a string")

    if not isinstance(message.get("ros_type"), str):
        raise ValueError("ros_type must be a string")

    sequence = message.get("seq")
    if (
        type(sequence) is not int
        or sequence < 0
    ):
        raise ValueError("seq must be a non-negative integer")

    timestamp = message.get("timestamp")
    if (
        type(timestamp) is not int
        or timestamp <= 0
    ):
        raise ValueError(
            "timestamp must be a positive Unix millisecond integer"
        )

    if not isinstance(message.get("data"), dict):
        raise ValueError(
            "data must contain the serialized ROS message object"
        )

    return sequence


def process_text_message(client_id, payload):
    """Decode one text frame and dispatch the ROS message by topic and type."""
    global current_leds

    message = json.loads(payload)
    sequence = validate_envelope(message)
    print(
        f"Received topic={message['topic']} ros_type={message['ros_type']} "
        f"seq={sequence}",
        flush=True,
    )

    if (
        message["topic"] != LED_COMMAND_TOPIC
        or message["ros_type"] != LED_MESSAGE_TYPE
    ):
        raise ValueError(
            f"unsupported route: {message['topic']} ({message['ros_type']})"
        )

    current_leds = set_leds_on_mcu(message["data"].get("data"))
    response = make_envelope(
        "ws_to_ros",
        LED_STATE_TOPIC,
        LED_MESSAGE_TYPE,
        sequence,
        {
            "layout": {"dim": [], "data_offset": 0},
            "data": list(current_leds),
        },
    )
    send_envelope(client_id, response)
    print(f"LED state: {list(current_leds)}", flush=True)


def enqueue_event(event):
    """Move a short Brick callback event into the App main loop."""
    try:
        events.put_nowait(event)
    except queue.Full:
        print("WebSocket event queue is full; event dropped", flush=True)


def handle_connect(client_info):
    """Queue a client connection event."""
    enqueue_event(("connect", client_info))


def handle_message(client_id, payload):
    """Queue raw text or binary payload without blocking the Brick thread."""
    enqueue_event(("message", client_id, payload))


def handle_disconnect(client_info, code, reason):
    """Queue a client disconnection event."""
    enqueue_event(("disconnect", client_info, code, reason))


def process_event(event):
    """Process one queued Brick event in the App main loop."""
    event_type = event[0]
    if event_type == "connect":
        client_info = event[1]
        print(f"WebSocket connected: {client_info['client_id']}", flush=True)
        return

    if event_type == "disconnect":
        global current_leds
        client_info, code, reason = event[1:]
        print(
            f"WebSocket disconnected: {client_info['client_id']} "
            f"code={code} reason={reason}",
            flush=True,
        )
        try:
            current_leds = set_leds_on_mcu(ALL_OFF)
        except Exception as error:
            print(f"Could not turn LEDs off: {error}", flush=True)
        return

    client_id, payload = event[1:]
    if not isinstance(payload, str):
        send_error(client_id, 0, "binary frames are not used by this ROS lesson")
        return

    sequence = 0
    try:
        decoded = json.loads(payload)
        if isinstance(decoded, dict) and isinstance(decoded.get("seq"), int):
            sequence = decoded["seq"]
        process_text_message(client_id, payload)
    except Exception as error:
        print(f"Message rejected: {error}", flush=True)
        send_error(client_id, sequence, error)


server.on_connect(handle_connect)
server.on_message(handle_message)
server.on_disconnect(handle_disconnect)


def loop():
    """Initialize the MCU, process WebSocket events, and report server state."""
    global current_leds
    global last_server_status
    global mcu_ready

    if not mcu_ready:
        try:
            current_leds = set_leds_on_mcu(ALL_OFF)
            mcu_ready = True
            print(f"MCU ready: {list(current_leds)}", flush=True)
        except Exception as error:
            print(f"MCU is not ready: {error}", flush=True)
            time.sleep(1)
            return

    for _ in range(8):
        try:
            event = events.get_nowait()
        except queue.Empty:
            break
        process_event(event)

    status = server.get_status()
    status_snapshot = (
        status["listening"],
        status["client_count"],
        status["server_error"],
    )
    if status_snapshot != last_server_status:
        print(
            f"WebSocket listening={status['listening']} "
            f"clients={status['client_count']} error={status['server_error']}",
            flush=True,
        )
        last_server_status = status_snapshot

    time.sleep(0.05)


App.run(user_loop=loop)
