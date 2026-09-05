# 离线依赖

这里保存新 App 自己使用的 Python 安装包，因此不依赖 ZDT Motor App 的运行状态、虚拟环境或缓存。

| 文件 | 用途 |
| --- | --- |
| `python_can-4.6.1-py3-none-any.whl` | 访问 Linux SocketCAN |
| `packaging-26.3-py3-none-any.whl` | python-can依赖 |
| `typing_extensions-4.16.0-py3-none-any.whl` | python-can依赖 |
| `wrapt-1.17.3-...aarch64.whl` | python-can依赖，适用于CPython 3.13/aarch64 |

`.whl` 是 Python 的离线安装包，不是项目源码文件。Arduino App Lab 会按照上一级 `requirements.txt` 从本目录安装，不需要开发板访问 PyPI。第三方 wheel 保留各自上游包中的许可证和元数据。
