"""不依赖真实 CAN 的测试 Backend。"""

import queue

from zdt_motor.backends import CanBackend


class FakeBackend(CanBackend):
    """记录发送帧并从内存队列返回接收帧。"""

    def __init__(self, on_send=None):
        """
        @description         : 初始化发送记录和接收队列
        @param on_send       : 可选发送回调
        @return              : 无返回值
        """
        self.on_send = on_send
        self.sent_frames = []
        self.receive_queue = queue.Queue()
        self.opened = False

    def open(self):
        """
        @description         : 标记FakeBackend已打开
        @param               : 无参数
        @return              : 当前FakeBackend
        """
        self.opened = True
        return self

    def send(self, frame):
        """
        @description         : 记录发送帧并调用可选回调
        @param frame         : CanFrame
        @return              : 无返回值
        """
        if not self.opened:
            raise RuntimeError("FakeBackend is not open")
        self.sent_frames.append(frame)
        if self.on_send is not None:
            self.on_send(frame, self)

    def receive(self, timeout_s):
        """
        @description         : 从内存队列等待一帧
        @param timeout_s     : 最大等待秒数
        @return              : CanFrame或None
        """
        try:
            return self.receive_queue.get(timeout=timeout_s)
        except queue.Empty:
            return None

    def close(self):
        """
        @description         : 标记FakeBackend已关闭
        @param               : 无参数
        @return              : 无返回值
        """
        self.opened = False

    def queue_frame(self, frame):
        """
        @description         : 向接收队列注入测试帧
        @param frame         : CanFrame
        @return              : 无返回值
        """
        self.receive_queue.put_nowait(frame)
