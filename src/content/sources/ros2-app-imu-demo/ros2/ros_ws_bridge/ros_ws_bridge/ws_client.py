import threading

from websockets.sync.client import connect


class ReconnectingWebSocketClient:
    """WebSocket client running in a reconnecting background thread."""

    def __init__(
        self,
        uri,
        on_message=None,
        max_message_bytes=16 * 1024,
        reconnect_delay_s=1.0,
    ):
        if not isinstance(uri, str) or not uri.startswith(("ws://", "wss://")):
            raise ValueError("uri must start with ws:// or wss://")
        if on_message is not None and not callable(on_message):
            raise TypeError("on_message must be callable or None")

        self._uri = uri
        self._on_message = on_message
        self._reconnect_delay_s = float(reconnect_delay_s)

        self._state_lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._stop_event = threading.Event()

        self._thread = None
        self._websocket = None
        self._connected = False
        self._connection_attempts = 0
        self._last_error = None

        if type(max_message_bytes) is not int or max_message_bytes <= 0:
            raise ValueError("max_message_bytes must be a positive integer")

        self._max_message_bytes = max_message_bytes

    def start(self):
        """Start the background connection thread."""
        with self._state_lock:
            if self._thread and self._thread.is_alive():
                return

            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="ros-ws-bridge-client",
                daemon=True,
            )
            self._thread.start()

    def stop(self):
        """Stop reconnecting and close the current connection."""
        self._stop_event.set()

        with self._state_lock:
            websocket = self._websocket
            thread = self._thread

        if websocket is not None:
            try:
                websocket.close(1000, "ROS bridge stopping")
            except Exception:
                pass

        if thread and thread is not threading.current_thread():
            thread.join(timeout=3.0)

    def send(self, payload):
        """Send one text frame, or return False while disconnected."""
        if not isinstance(payload, str):
            raise TypeError("payload must be a string")

        with self._state_lock:
            websocket = self._websocket

        if websocket is None:
            return False

        try:
            with self._send_lock:
                websocket.send(payload)
            return True
        except Exception as exc:
            with self._state_lock:
                self._last_error = f"{type(exc).__name__}: {exc}"
            return False

    def get_status(self):
        """Return a thread-safe connection status snapshot."""
        with self._state_lock:
            thread = self._thread
            return {
                "uri": self._uri,
                "running": bool(thread and thread.is_alive()),
                "connected": self._connected,
                "connection_attempts": self._connection_attempts,
                "last_error": self._last_error,
            }

    def _run(self):
        """Connect, receive messages, and reconnect after failure."""
        while not self._stop_event.is_set():
            with self._state_lock:
                self._connection_attempts += 1

            try:
                with connect(
                    self._uri,
                    proxy = None,
                    open_timeout=2.0,
                    close_timeout=1.0,
                    ping_interval=10.0,
                    ping_timeout=10.0,
                    max_size=self._max_message_bytes,
                ) as websocket:
                    with self._state_lock:
                        self._websocket = websocket
                        self._connected = True
                        self._last_error = None

                    while not self._stop_event.is_set():
                        try:
                            payload = websocket.recv(timeout=0.2)
                        except TimeoutError:
                            continue

                        if self._on_message is not None:
                            try:
                                self._on_message(payload)
                            except Exception as exc:
                                with self._state_lock:
                                    self._last_error = (
                                        f"message callback failed: "
                                        f"{type(exc).__name__}: {exc}"
                                    )

            except Exception as exc:
                with self._state_lock:
                    self._last_error = f"{type(exc).__name__}: {exc}"
            finally:
                with self._state_lock:
                    self._websocket = None
                    self._connected = False

            self._stop_event.wait(self._reconnect_delay_s)