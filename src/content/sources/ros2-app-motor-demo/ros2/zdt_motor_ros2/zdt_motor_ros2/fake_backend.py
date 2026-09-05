class FakeMotorBackend:
    """不访问硬件的四电机模拟后端。"""

    simulated = True

    def __init__(self):
        self._enabled = False
        self._rpm = [0, 0, 0, 0]

    @property
    def enabled(self):
        return self._enabled

    @property
    def hardware_connected(self):
        # 明确表示当前不是硬件状态。
        return False

    def set_enabled(self, enabled):
        self._enabled = bool(enabled)

        if not self._enabled:
            self.stop()

    def set_target_rpm(self, values):
        rpms = [int(value) for value in values]

        if len(rpms) != 4:
            raise ValueError("RPM command must contain four values")

        if not self._enabled and any(rpm != 0 for rpm in rpms):
            raise RuntimeError("motors are not enabled")

        # FakeBackend 直接把目标值当作模拟反馈。
        self._rpm = rpms

    def get_actual_rpm(self):
        return list(self._rpm)

    def stop(self):
        self._rpm = [0, 0, 0, 0]

    def safe_stop_and_disable(self):
        self.stop()
        self.set_enabled(False)

    def close(self):
        pass
