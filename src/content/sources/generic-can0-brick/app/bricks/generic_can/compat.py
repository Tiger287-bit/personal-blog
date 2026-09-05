# SPDX-License-Identifier: MIT
"""Arduino App Lab compatibility with a no-op host-test fallback."""

try:
    from arduino.app_utils import brick
except ImportError:

    def brick(component):
        """
        @description         : 在普通主机测试环境中提供无操作的brick装饰器
        @param component     : 需要装饰的类
        @return              : 未经修改的原始类
        """
        return component
