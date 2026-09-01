# 离线 Python 依赖

普通用户不需要操作这个文件夹。

`zdt_motor` 需要 `python-can 4.6.1` 才能访问 Linux 的 `can0`。由于开发板
不一定能稳定连接 PyPI，App 已经把需要的安装包放在这里。启动 App 时会自动
安装它们，不需要手动运行 `pip install`。

这些安装包适用于当前 App Lab 环境：

- Linux aarch64；
- CPython 3.13；
- 兼容 manylinux2014 的系统环境。

具体版本记录在 Brick 的 `requirements.txt` 中。只有 App Lab 的 Python 版本、
处理器架构或依赖版本发生变化时，维护者才需要更新这里的 wheel 文件。
