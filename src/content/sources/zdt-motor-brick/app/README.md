# ZDT Motor Demo

这个 Arduino App Lab App 演示如何复用 `zdt_motor` Brick，通过 VENTUNO Q 的 Linux `can0` 控制 ZDT 第二代闭环步进电机。

## 先认识两个对象

- `ZDTBus` 表示一条 CAN 总线。一个 App 通常只创建一个。
- `ZDTMotor` 表示一台电机。每台电机分别创建一个。

例如，地址为 `1` 的电机对应一个 `ZDTMotor(motor_id=1)` 对象。四台电机地址为 `1、2、3、4` 时，创建四个对象并共用同一个 `ZDTBus`。

## 项目目录

```text
zdt-motor-demo/
├── app.yaml
├── python/main.py                 # 最小使用示例
├── sketch/
│   ├── sketch.ino                 # 初始化 RouterBridge
│   └── sketch.yaml
├── bricks/zdt_motor/
│   ├── README.md                  # Brick 使用说明
│   ├── motor.py                   # 单电机 API
│   ├── bus.py                     # CAN 总线管理
│   ├── commands/                  # 命令参数编码
│   ├── protocols/                 # CAN 报文生成和解析
│   ├── backends/socketcan.py      # 打开 can0
│   └── vendor/                    # 离线 Python 依赖安装包
├── scripts/                       # 开发板宿主系统辅助工具
└── tests/                         # 开发阶段的自动检查
```

第一次阅读时，建议依次查看：

1. `python/main.py`
2. `bricks/zdt_motor/README.md`
3. `bricks/zdt_motor/motor.py`
4. `bricks/zdt_motor/bus.py`

## 启动 App

```bash
arduino-app-cli app start \
  /home/arduino/ArduinoApps/zdt-motor-demo \
  -v
```

查看日志：

```bash
arduino-app-cli app logs \
  /home/arduino/ArduinoApps/zdt-motor-demo \
  --tail 100
```

`app start` 会准备 App、安装随附的 Python 依赖并启动程序。

## 为什么不用联网安装 python-can

`zdt_motor` 使用 `python-can 4.6.1` 读写 Linux CAN 接口。

开发板有时无法稳定访问 PyPI，所以 App 已经带上适合当前 VENTUNO Q 环境的离线安装包。普通用户不需要下载依赖，也不需要手动运行 `pip install`。

只有更换 Python 版本或处理器架构时，维护者才需要更新 `vendor/` 中的安装包。

## 准备 can0

Brick 不会自动修改系统接口。需要在 VENTUNO Q 的 Linux 终端中执行：

```bash
cd /home/arduino/ArduinoApps/zdt-motor-demo
sudo scripts/configure_can0.sh can0 500000
```

查看接口状态：

```bash
ip -details -statistics link show can0
```

看到 `UP` 和 `ERROR-ACTIVE` 表示接口已经启动。

## 最小 Python 用法

```python
from zdt_motor import ZDTBus, ZDTMotor


with ZDTBus(device="can0") as bus:
    motor = ZDTMotor(
        bus=bus,
        model="X57S",
        motor_id=1,
        firmware="emm",
    )

    print(motor.get_speed())
    print(motor.get_position())
    print(motor.get_status())
```

`motor_id` 必须等于电机的实际地址。`firmware` 必须与电机菜单中的 `FWType` 一致。

## 四台电机的写法

```python
from zdt_motor import ZDTBus, ZDTMotor


with ZDTBus(device="can0") as bus:
    motors = {
        motor_id: ZDTMotor(
            bus=bus,
            model="X57S",
            motor_id=motor_id,
            firmware="emm",
        )
        for motor_id in (1, 2, 3, 4)
    }

    for motor_id, motor in motors.items():
        print(motor_id, motor.get_speed())
```

不要为每台电机分别打开一次 `can0`。所有电机对象应共用一个 `ZDTBus`。

## VENTUNO Q 上的运行边界

当前 CAN 路径是：

```text
FDCAN1 → CANnectivity → gs_usb → Linux SocketCAN → can0
```

因此 Sketch 只调用 `Bridge.begin()`，不再使用 Arduino CAN 库访问 FDCAN1。

当前 App Lab 的 `python/main.py` 在容器中运行，默认看不到宿主系统的 `can0`。需要访问真实 CAN 接口的代码，应通过 `scripts/run_host_python.sh` 在 VENTUNO Q 的 Linux 宿主系统中运行，同时复用 App 已安装的 Brick 和依赖。

## 安全提醒

读取状态不会主动要求电机运动。调用 `enable()`、`set_speed()`、`move_relative()`、`move_absolute()`、`home()` 或配置写入方法前，请先架空车轮、清理机械运动范围，并准备物理急停。
