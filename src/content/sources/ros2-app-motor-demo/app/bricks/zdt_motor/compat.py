"""让同一 Brick 源码可在 App Lab 和宿主机测试脚本中导入。"""

try:
    from arduino.app_utils import brick
except ImportError:

    def brick(component):
        """
        @description         : 在非App Lab环境中保留被装饰类本身
        @param component     : Brick类
        @return              : 未修改的Brick类
        """
        return component


__all__ = ["brick"]
