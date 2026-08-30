---
title: "zdt-x57s-can-test：封装单电机 Brick 并组合验证四台电机"
description: "把一台 ZDT X57S 第二代电机封装为独立 Custom Brick 对象，再由 Arduino App Lab 创建任意数量对象并通过 Linux SocketCAN 网关通信。"
section: "app-lab"
appId: "zdt-x57s-can-test"
order: 2
status: "verified"
pubDate: "2026-08-30"
updatedDate: "2026-08-30"
verifiedDate: "2026-08-30"
environment:
  - "Arduino VENTUNO Q"
  - "Arduino App CLI 0.12.1"
  - "App runtime 0.11.0"
  - "ArduinoCore-zephyr 0.90.90-0.head.monza-1.0.1.66+b22aeca1"
  - "ZDT X57S 第二代 × 4 / FW_Emm"
  - "经典 CAN 500 kbit/s"
capabilities:
  - "Custom Brick"
  - "单电机对象"
  - "SocketCAN"
  - "多对象组合"
  - "通信自检"
  - "命令看门狗"
sourceDir: "zdt-x57s-can-test"
---

本教程实现一个名为 `zdt-x57s-can-test` 的 Arduino App Lab 小 App。它把一台
ZDT X57S 第二代闭环步进电机整理为一个可复用的 `ZdtX57SCan` 对象。电机地址在
构造对象时绑定，Brick 本身不知道底盘有几台电机。测试 App 创建四个对象，并在
Ventuno Q 上实际读取地址 `1`、`2`、`3`、`4` 的实时速度。

这里的 `V1.0` 指本项目 Brick/接口的第一个稳定版本。电机协议依据第二代
XS 系列 `FW_Emm` 固定 CAN 协议，不使用旧版 X57 V2 协议。

## 实测结果

四台电机上电、`can0` 配置为 500 kbit/s 后，App 自动探测和手动网关探测均成功：

```text
[zdt-x57s] 四电机CAN通信正常: id1=0RPM, id2=0RPM, id3=0RPM, id4=0RPM
```

手动探测每次只返回一个对象对应的电机：

```json
{
  "version": 1,
  "ok": true,
  "result": {
    "motor_id": 1,
    "speed_rpm": 0
  }
}
```

连续执行三轮四地址探测后，SocketCAN 状态仍为：

```text
can state ERROR-ACTIVE (berr-counter tx 0 rx 0)
bus-errors 0
arbit-lost 0
error-warn 0
error-pass 0
bus-off 0
RX errors 0, dropped 0
TX errors 0, dropped 0
```

接口带有 `ECHO` 标志，因此 RX 统计同时包括本机发送帧的回显。判断通信成功不能只看
RX 包数，必须确认四个地址各自返回的 `35 ... 6B` 应答均通过解析。

## 为什么 Brick 不直接打开 can0

当前 Ventuno Q 固件中的链路为：

```text
FDCAN1
  ↓
系统 CANnectivity
  ↓
gs_usb
  ↓
Linux 主机 can0
```

App Lab Python 主程序运行在 Docker 容器中。容器使用独立网络命名空间，只能看到
`lo` 和 `eth0`，看不到主机的 `can0`。把 `/dev` 挂载进容器也不会把主机网络接口
带进容器。

Sketch 端也不能再次调用 `CAN.begin()`。当前 ArduinoCore-zephyr/loader 组合已经由
CANnectivity 使用同一个 FDCAN1；实测电机应答会进入 Linux `can0`，但不会进入
Sketch 的 Arduino CAN 轮询接收队列。

因此采用两层结构：

```text
App Lab python/main.py
  ↓ Python API
一个或多个 zdt_x57s_can 单电机对象
  ↓ 带随机令牌的 JSON/TCP
Linux 原生 zdt_x57s_can_gateway
  ↓ SocketCAN can0
CANnectivity / gs_usb
  ↓ 经典 CAN 500 kbit/s
一台或多台 ZDT X57S
```

Custom Brick 的目录、ID、配置变量和 App 引用方式遵循
[Arduino Custom Bricks](https://docs.arduino.cc/software/app-lab/bricks/custom-bricks/)
约定；博客文章则继续使用 Astro Content Collections 的统一文章集合。

## 文件目录

App Lab App：

```text
/home/arduino/ArduinoApps/zdt-x57s-can-test/
├── app.yaml
├── README.md
├── python/
│   ├── main.py
│   └── manual_test.py
├── sketch/
│   ├── sketch.ino
│   └── sketch.yaml
└── bricks/
    └── zdt_x57s_can/
        ├── __init__.py
        ├── client.py
        ├── brick_config.yaml
        ├── requirements.txt
        └── README.md
```

Linux 原生网关：

```text
/home/arduino/work/zdt_x57s_can_gateway/
├── gateway.py
├── gateway_client.py
├── socketcan_transport.py
├── zdt_x57s_driver.py
├── zdt_x57s_protocol.py
├── README.md
└── tests/
    ├── test_gateway.py
    └── test_protocol.py
```

App 和网关分别承担“可复用 API”与“主机硬件所有权”。不要复制一套 SocketCAN
驱动到 App 容器里，也不要让两个进程同时拥有 `can0`。

## CAN 报文协议

虽然 Ventuno Q 的物理控制器支持 CAN-FD，本项目的 ZDT 电机通信使用的是经典 CAN
帧，不发送 CAN-FD 或 BRS 帧。

| 项目 | 当前约定 |
| --- | --- |
| 位速率 | `500000 bit/s` |
| 帧格式 | 29 位扩展帧 |
| CAN-ID | `(motor_id << 8) \| packet_index` |
| 单包序号 | `packet_index = 0` |
| 地址 1～4 CAN-ID | `0x100`、`0x200`、`0x300`、`0x400` |
| 数据校验字节 | `0x6B` |
| 成功状态 | `0x02` |
| 拒绝状态 | `0xE2` |

当前 Brick 使用的命令如下：

| 功能 | 数据字节 |
| --- | --- |
| 读取实时速度 | `35 6B` |
| 使能/失能 | `F3 AB EN SYNC 6B` |
| 速度模式 | `F6 DIR SPEED_H SPEED_L ACC SYNC 6B` |
| 立即停止 | `FE 98 SYNC 6B` |
| 速度应答 | `35 DIR SPEED_H SPEED_L 6B` |
| 控制成功应答 | `FUNC 02 6B` |
| 控制拒绝应答 | `FUNC E2 6B` |

例如读取地址 1 的实时速度时，发送一帧 29 位扩展帧：

```text
CAN-ID: 00000100
DATA:   35 6B
```

电机停止时的合法速度应答为：

```text
CAN-ID: 00000100
DATA:   35 00 00 00 6B
```

### 协议编码代码

`zdt_x57s_protocol.py` 的核心编码如下：

```python
CHECKSUM = 0x6B


def arbitration_id(motor_id, packet_index=0):
    """
    @description         : 生成ZDT CAN扩展帧标识符Addr左移8位或分包序号
    @param motor_id      : 电机地址，范围0至255
    @param packet_index  : 分包序号，范围0至255
    @return              : 29位CAN扩展帧标识符
    """
    return (int(motor_id) << 8) | int(packet_index)


def build_speed_query():
    """
    @description         : 构造读取电机实时转速命令
    @param               : 无
    @return              : 数据35 6B
    """
    return bytes((0x35, CHECKSUM))


def parse_speed_reply(data):
    """
    @description         : 解析FW_Emm实时转速应答
    @param data          : 期望格式35 方向 转速高字节 转速低字节 6B
    @return              : 带符号实时转速，单位整数RPM
    """
    payload = bytes(data)
    if len(payload) != 5:
        raise ZdtProtocolError("speed reply length must be 5 bytes")
    if payload[0] != 0x35 or payload[-1] != CHECKSUM:
        raise ZdtProtocolError("speed reply function or checksum is invalid")
    if payload[1] not in (0x00, 0x01):
        raise ZdtProtocolError("speed reply direction is invalid")

    magnitude = (payload[2] << 8) | payload[3]
    return -magnitude if payload[1] == 0x01 else magnitude
```

## Custom Brick 配置

`bricks/zdt_x57s_can/brick_config.yaml`：

```yaml
id: zdt_x57s_can
name: ZDT X57S CAN
description: A reusable single-motor Brick for one ZDT X57S second-generation FW_Emm motor.
category: miscellaneous
supported_boards:
  - ventunoq
ports: []
variables:
  - name: ZDT_CAN_GATEWAY_HOST
    default_value: "msgpack-rpc-router"
    hidden: true
  - name: ZDT_CAN_GATEWAY_PORT
    default_value: "8766"
    hidden: true
  - name: ZDT_CAN_GATEWAY_TOKEN
    default_value: "replace-me"
    hidden: true
  - name: ZDT_CAN_REQUEST_TIMEOUT_S
    default_value: "1.5"
    hidden: true
```

实际部署时应生成 256 位随机令牌，同时写入 `app.yaml` 和权限为 `0600` 的
`.gateway-token`，不要把真实令牌放进教程或公开仓库。

`client.py` 使用官方 `@brick` 装饰器声明可复用类：

```python
from arduino.app_utils import brick


@brick
class ZdtX57SCan:
    """
    @description         : 表示一台使用第二代FW_Emm固定CAN协议的ZDT X57S电机
    @param motor_id      : 当前对象绑定的电机地址，范围1至255
    @param host          : Linux原生CAN网关地址; 默认读取环境变量
    @param port          : Linux原生CAN网关端口; 默认读取环境变量
    @param token         : 网关鉴权令牌; 默认读取环境变量
    @param timeout_s     : 单次请求超时时间; 默认读取环境变量
    @return              : 单台ZdtX57SCan电机对象
    """

    def __init__(self, motor_id, host=None, port=None, token=None, timeout_s=None):
        """
        @description         : 绑定一台电机地址并初始化网关连接参数
        @param motor_id      : 当前对象绑定的电机地址，范围1至255
        @param host          : Linux原生CAN网关地址
        @param port          : Linux原生CAN网关端口
        @param token         : 网关鉴权令牌
        @param timeout_s     : 单次请求超时时间
        @return              : 无
        """
        self._motor_id = validate_motor_id(motor_id)
        # 其余连接配置从App Lab环境变量读取。

    def read_speed(self):
        """
        @description         : 读取当前对象绑定电机的实时转速
        @param               : 无参数
        @return              : 带符号实时转速，单位整数RPM
        """
        result = self._call("read_speed", {"motor_id": self._motor_id})
        if result.get("motor_id") != self._motor_id:
            raise ZdtX57SCanError("CAN gateway returned a different motor_id")
        return result["speed_rpm"]
```

使用一台电机时只创建一个对象；使用四台时由 App 组合四个相同类型的对象：

```python
from zdt_x57s_can import ZdtX57SCan

single_motor = ZdtX57SCan(motor_id=7)
print(single_motor.read_speed())

motors = tuple(ZdtX57SCan(motor_id) for motor_id in (1, 2, 3, 4))
speeds = {
    motor.motor_id: motor.read_speed()
    for motor in motors
}
```

`enable()`、`disable()`、`set_speed()`、`stop()` 和 `timed_speed_test()` 都只操作
当前对象绑定的地址，调用时不再接收 `motor_id`，从接口上避免误操作另一台电机。

`app.yaml` 引用本地 Brick。下面只展示占位令牌：

```yaml
name: ZDT X57S CAN Test
description: Safely verify ZDT X57S second-generation FW_Emm motors.
ports: []
bricks:
  - zdt_x57s_can:
      variables:
        ZDT_CAN_GATEWAY_HOST: "msgpack-rpc-router"
        ZDT_CAN_GATEWAY_PORT: "8766"
        ZDT_CAN_GATEWAY_TOKEN: "<随机令牌>"
        ZDT_CAN_REQUEST_TIMEOUT_S: "1.5"
icon: ⚙️
```

## Brick 与原生网关协议

Brick 和 Linux 原生网关使用换行分隔的 UTF-8 JSON，每个 TCP 连接处理一个请求和
一个响应。网关只监听 Docker 内部主机地址 `172.17.0.1:8766`，不会在 Ventuno Q
的局域网地址上开放端口。

请求必须携带协议版本、唯一请求 ID、随机令牌、方法名和参数：

```json
{
  "version": 1,
  "request_id": "d0c1",
  "token": "<随机令牌>",
  "method": "read_speed",
  "params": {
    "motor_id": 1
  }
}
```

成功响应：

```json
{
  "version": 1,
  "request_id": "d0c1",
  "ok": true,
  "result": {
    "motor_id": 1,
    "speed_rpm": 0
  }
}
```

失败响应使用稳定错误码，程序不应根据英文错误文本分支：

```json
{
  "version": 1,
  "request_id": "d0c1",
  "ok": false,
  "error": {
    "code": "can_error",
    "message": "motor 1 speed reply timed out"
  }
}
```

网关只允许以下方法：

| 方法 | 是否可能运动 | 安全约束 |
| --- | --- | --- |
| `status` | 否 | 不发送 CAN 帧 |
| `read_speed` | 否 | 每次只接收一个地址并读取该电机速度 |
| `enable` | 否 | 必须携带运动确认口令 |
| `disable` | 否 | 每次只操作一个地址 |
| `set_speed` | 是 | 最大绝对值 60 RPM，500 ms 看门狗 |
| `stop` | 否 | 依次尝试零速、停止和失能 |
| `timed_speed_test` | 是 | 最长 5 秒，`finally` 中强制停车 |

网关接受的 `motor_id` 范围为 `1～255`。它不提供批量 `probe` 或 `stop_all`；多个
电机的循环、聚合和底盘安全策略必须由更上层的 App 明确组织。

非零 `set_speed` 必须在 500 ms 内持续刷新。调用方断线或停止刷新后，网关会自动发送
F6 零速，再继续尝试 FE 停止和 F3 失能。

## 最小 Sketch

Sketch 的任务只是启动 RouterBridge/CANnectivity，不能调用 `CAN.begin()`：

```cpp
#include <Arduino_RouterBridge.h>

/*
 * @description         : 初始化RouterBridge并让系统CANnectivity向Linux提供FDCAN1
 * @param               : 无
 * @return              : 无
 */
void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH);

  const bool bridgeReady = Bridge.begin();

  // FDCAN1由系统CANnectivity提供给Linux can0，Sketch不得调用CAN.begin()。
  digitalWrite(LED_BUILTIN, bridgeReady ? LOW : HIGH);
}

/*
 * @description         : 保持MCU任务调度运行且不占用FDCAN1
 * @param               : 无
 * @return              : 无
 */
void loop() {
  delay(10);
}
```

## 启动 App

Ventuno Q 当前 App CLI 一次只能运行一个 App。先查看并停止正在运行的其他 App，再启动
本 App：

```bash
arduino-app-cli app list
arduino-app-cli app stop /home/arduino/ArduinoApps/<当前运行的App>
arduino-app-cli app start /home/arduino/ArduinoApps/zdt-x57s-can-test
```

首次启动会编译并刷写 Sketch。本次实测的编译结果为：

```text
Sketch uses 23468 bytes (2%) of program storage space.
Global variables use 5676 bytes (4%) of dynamic memory.
App "ZDT X57S CAN Test" started successfully
```

App 启动后 `can0` 会重新出现，但接口初始为 `DOWN`。不要配置 `restart-ms`，当前
`gs_usb` 驱动会返回 `Device doesn't support restart from Bus Off`。

## 配置 can0

电机上电且 CAN-H、CAN-L、信号地和终端电阻检查完成后执行：

```bash
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 500000
sudo ip link set can0 up
ip -details -statistics link show can0
```

正常状态应包含：

```text
<NOARP,UP,LOWER_UP,ECHO>
can state ERROR-ACTIVE
bitrate 500000
berr-counter tx 0 rx 0
```

`ERROR-ACTIVE` 是 CAN 控制器的正常工作状态，不代表当前发生了错误。需要关注的是
错误计数是否增长，以及是否进入 `ERROR-PASSIVE` 或 `BUS-OFF`。

## 启动 Linux 原生网关

另开一个 SSH 终端，前台启动网关：

```bash
cd /home/arduino/work/zdt_x57s_can_gateway
python3 -B gateway.py
```

正常输出：

```text
ZDT X57S CAN gateway listening on 172.17.0.1:8766; interface=can0; max_rpm=60
```

网关不执行需要 `sudo` 的网络配置；接口不存在或未启动时，它只返回结构化错误。

## 用四个单电机对象验证通信

App 在顶层创建四个 `ZdtX57SCan` 对象，再依次调用每个对象的 `read_speed()`。它默认
每 3 秒重试一次，直到四个对象全部成功，然后停止自动探测。查看 App 日志：

```bash
arduino-app-cli app logs /home/arduino/ArduinoApps/zdt-x57s-can-test
```

也可以直接从 Linux 主机调用网关：

```bash
cd /home/arduino/work/zdt_x57s_can_gateway
python3 -B gateway_client.py --status
python3 -B gateway_client.py --probe --motor-id 1
python3 -B gateway_client.py --probe --motor-id 2
python3 -B gateway_client.py --probe --motor-id 3
python3 -B gateway_client.py --probe --motor-id 4
```

若要从 App 容器调用 Brick，必须显式提供官方启动脚本使用的 Brick 路径：

```bash
docker exec \
  -e PYTHONPATH=/app/bricks \
  zdt-x57s-can-test-main-1 \
  python3 -B /app/python/manual_test.py --probe --motor-id 1
```

省略 `PYTHONPATH=/app/bricks` 会出现：

```text
ModuleNotFoundError: No module named 'zdt_x57s_can'
```

正常 App 启动不需要手动设置该变量，官方 `/run.sh` 会自动注入。

## 运行协议测试

```bash
cd /home/arduino/work/zdt_x57s_can_gateway
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

当前网关与 CAN 协议测试为 `11/11`，单电机 Brick 对象测试为 `4/4`：

| 测试范围 | 覆盖内容 |
| --- | --- |
| 协议编码 | CAN-ID、速度查询、使能、速度、停止字节 |
| 应答解析 | 正反方向速度、`0x6B` 校验、`0xE2` 拒绝 |
| 网关鉴权 | 错误令牌拒绝 |
| 方法白名单 | 原始 CAN 发送等未公开方法拒绝 |
| 单电机边界 | 地址 1～255；拒绝批量 `probe` 和 `stop_all` |
| 多实例 | 四个对象分别保存地址 1、2、3、4 |
| 地址绑定 | 方法自动使用构造地址，调用方不能覆盖 |
| 运动确认 | 缺少固定确认口令时不访问 CAN |
| 参数限制 | 地址、60 RPM 上限、最长运行时间 |
| 看门狗配置 | 禁止配置超过安全范围的超时 |

## 单电机限时运行测试

这一节会让真实电机转动，不属于前面的无运动通信验证。必须先做到：

1. 只测试一台电机；
2. 轮子和底盘架空；
3. 周围没有人员、线缆或工具；
4. 能立即切断电机动力电源；
5. 当前对象的 `--probe --motor-id 1` 已成功且 CAN 错误计数为 0。

然后在 App 容器中执行：

```bash
docker exec \
  -e PYTHONPATH=/app/bricks \
  zdt-x57s-can-test-main-1 \
  python3 -B /app/python/manual_test.py \
  --motor-test \
  --motor-id 1 \
  --rpm 20 \
  --acceleration-level 10 \
  --duration 3 \
  --confirm RUN_ZDT_X57S_V1_0
```

没有 `--confirm RUN_ZDT_X57S_V1_0` 时，脚本会在访问 CAN 前退出。测试期间发生任何
异常，网关都会在 `finally` 中发送零速，并继续尝试停止和失能。

本教程的“已实测”范围是 App 构建、四个独立 Brick 对象、网关鉴权、四地址单独实时
速度读取和 CAN 错误计数；真实旋转与机械转速测量应在单独完成现场安全测试后再记录结果。

## 当前边界

- 速度值来自驱动器内部闭环反馈，不等同于独立机械转速测量。
- 原生网关当前需要手动启动，尚未安装为 systemd 服务。
- Brick 只表示一台电机；四轮同步、停止全部电机和底盘运动学必须由综合 App 组合对象实现。
- FE 停止和 F3 失能是否被具体电机参数接受，必须在真实运动测试中单独记录；F6 零速是
  当前安全停车的第一条命令。
- 综合机器人 App 仍应统一持有电机、IMU 和 ROS 2 控制状态，不能让多个 App 同时操作
  同一套电机硬件。
