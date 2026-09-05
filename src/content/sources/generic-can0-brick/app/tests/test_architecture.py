"""V1架构边界和统一函数注释格式测试。"""

import ast
from pathlib import Path
import unittest

import generic_can


APP_ROOT = Path(__file__).resolve().parents[1]
BRICK_ROOT = APP_ROOT / "bricks" / "generic_can"
EXPECTED_PUBLIC_API = {
    "CanBus",
    "CanFrame",
    "MessageDefinition",
    "CANError",
    "CANConfigurationError",
    "CANBackendError",
    "CANTimeoutError",
    "CANMessageError",
    "CANUnsupportedFeatureError",
}


class ArchitectureTests(unittest.TestCase):
    """防止协议代码和python-can依赖越过既定边界。"""

    def test_python_can_is_only_imported_by_socketcan_backend(self):
        """
        @description         : 验证python-can只在SocketCAN后端模块中动态导入
        @param self          : 当前测试用例
        @return              : 无
        """
        offenders = []
        for path in BRICK_ROOT.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if path.name != "socketcan.py" and (
                "import can" in source or 'import_module("can")' in source
            ):
                offenders.append(str(path.relative_to(APP_ROOT)))
        self.assertEqual(offenders, [])

    def test_brick_contains_no_device_protocol_names(self):
        """
        @description         : 验证通用Brick没有混入特定电机或高层协议名称
        @param self          : 当前测试用例
        @return              : 无
        """
        forbidden = ("zdt", "canopen", "j1939", "isotp", "isotp", "uds")
        offenders = []
        for path in BRICK_ROOT.rglob("*.py"):
            source = path.read_text(encoding="utf-8").lower()
            if any(term in source for term in forbidden):
                offenders.append(str(path.relative_to(APP_ROOT)))
        self.assertEqual(offenders, [])

    def test_every_brick_function_uses_project_comment_format(self):
        """
        @description         : 验证Brick内每个手写函数都有统一中文项目注释字段
        @param self          : 当前测试用例
        @return              : 无
        """
        missing = []
        for path in BRICK_ROOT.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    docstring = ast.get_docstring(node) or ""
                    if (
                        "@description" not in docstring
                        or "@return" not in docstring
                    ):
                        missing.append(
                            f"{path.relative_to(APP_ROOT)}:{node.lineno}:"
                            f"{node.name}"
                        )
        self.assertEqual(missing, [])

    def test_public_api_exactly_matches_v1_contract(self):
        """
        @description         : 锁定Generic CAN V1根包的稳定公开名称集合
        @param self          : 当前测试用例
        @return              : 无
        """
        self.assertEqual(set(generic_can.__all__), EXPECTED_PUBLIC_API)


if __name__ == "__main__":
    unittest.main()
