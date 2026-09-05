"""不依赖真实硬件和python-can的内存CAN后端。"""

import queue
import threading

from generic_can.backends import CanBackend
from generic_can.errors import CANBackendError
from generic_can.frame import CanFrame


class FakeBackend(CanBackend):
    """用线程安全队列模拟最小CanBackend契约。"""

    def __init__(self):
        """
        @description         : 创建一个尚未打开的内存测试后端
        @param self          : 当前FakeBackend对象
        @return              : 无
        """
        self.open_count = 0
        self.close_count = 0
        self.sent_frames = []
        self._receive_queue = queue.Queue()
        self._lock = threading.Lock()
        self._is_open = False

    def open(self):
        """
        @description         : 标记后端已打开并记录调用次数
        @param self          : 当前FakeBackend对象
        @return              : 无
        """
        with self._lock:
            self.open_count += 1
            self._is_open = True

    def send(self, frame):
        """
        @description         : 保存一帧发送记录但不访问真实CAN设备
        @param self          : 当前FakeBackend对象
        @param frame         : 需要记录的CanFrame
        @return              : 无
        """
        with self._lock:
            if not self._is_open:
                raise CANBackendError("fake backend is not open")
            self.sent_frames.append(frame)

    def receive(self, timeout_s):
        """
        @description         : 从测试注入队列等待一帧或异常
        @param self          : 当前FakeBackend对象
        @param timeout_s     : 最长等待秒数
        @return              : CanFrame或超时None
        """
        if not self._is_open:
            raise CANBackendError("fake backend is not open")
        try:
            value = self._receive_queue.get(timeout=timeout_s)
        except queue.Empty:
            return None
        if isinstance(value, BaseException):
            raise value
        return value

    def close(self):
        """
        @description         : 标记后端关闭并记录调用次数
        @param self          : 当前FakeBackend对象
        @return              : 无
        """
        with self._lock:
            self.close_count += 1
            self._is_open = False

    def inject(self, frame):
        """
        @description         : 向接收线程注入一帧CanFrame
        @param self          : 当前FakeBackend对象
        @param frame         : 待注入的CanFrame
        @return              : 无
        """
        self._receive_queue.put(frame)

    def inject_error(self, error):
        """
        @description         : 向接收线程注入一个待抛出的异常
        @param self          : 当前FakeBackend对象
        @param error         : 待抛出的异常对象
        @return              : 无
        """
        self._receive_queue.put(error)

