"""ZDT Motor Brick 的结构化异常。"""


class ZDTError(Exception):
    """所有 ZDT Brick 异常的基类。"""


class ZDTConfigurationError(ZDTError, ValueError):
    """配置、参数或工程单位取值不合法。"""


class ZDTBackendError(ZDTError, OSError):
    """Backend 打开、发送或接收失败。"""


class ZDTTimeoutError(ZDTError, TimeoutError):
    """等待指定电机和功能码的应答超时。"""


class ZDTCommandError(ZDTError):
    """电机返回了非成功命令状态。"""

    def __init__(self, message, *, status=None, function_code=None):
        """
        @description         : 保存电机命令失败的状态码和功能码
        @param message       : 便于用户理解的错误说明
        @param status        : 电机返回状态码，可为None
        @param function_code : 对应功能码，可为None
        @return              : 无返回值
        """
        super().__init__(message)
        self.status = status
        self.function_code = function_code


class ZDTParameterError(ZDTCommandError):
    """电机返回 0xE2，参数范围或当前状态不满足。"""


class ZDTFormatError(ZDTCommandError):
    """电机返回 0xEE，命令格式错误。"""


class ZDTUnsupportedFeatureError(ZDTError, NotImplementedError):
    """当前型号、固件或 Backend 不支持所请求功能。"""


class ZDTProtocolError(ZDTError):
    """CAN ID、分包、功能码、长度或校验码不符合手册。"""


class ZDTBusBusyError(ZDTError):
    """同一电机同一功能码已有未完成请求。"""
