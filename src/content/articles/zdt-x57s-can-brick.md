---
title: "zdt_x57s_can Brick：把一台 ZDT X57S 封装成可复用对象"
description: "使用单电机代理 Brick 连接 VENTUNO Q 原生 SocketCAN 网关，并按需创建一个或多个独立电机对象。"
section: "bricks"
order: 2
pubDate: "2026-08-30"
updatedDate: "2026-08-30"
environment:
  - "Arduino VENTUNO Q"
  - "Arduino App Lab"
  - "ZDT X57S 第二代 / FW_Emm"
  - "经典 CAN 500 kbit/s"
capabilities:
  - "Custom Brick"
  - "单电机对象"
  - "SocketCAN 代理"
  - "安全看门狗"
sourceDir: "zdt-x57s-can-test"
---

`zdt_x57s_can` 把一台 ZDT X57S 第二代 `FW_Emm` 电机表示为一个
`ZdtX57SCan` 对象。地址在构造时绑定，因此同一个组件既能控制一台电机，也能由 App
创建多个对象组合控制多台电机。

这个 Brick 不直接打开 `can0`。它是 Linux 原生 CAN 网关的客户端，负责稳定的单电机
Python API、请求鉴权、响应匹配和错误转换；原生网关负责 SocketCAN 与电机协议。

## 组件在系统中的位置

```text
App 的 python/main.py
  ↓ 单电机对象方法
zdt_x57s_can Brick
  ↓ JSON/TCP + 随机令牌
/home/arduino/work/zdt_x57s_can_gateway
  ↓ SocketCAN can0
CANnectivity / gs_usb / FDCAN1
  ↓ 经典 CAN 500 kbit/s
ZDT X57S 第二代 FW_Emm
```

这种分层是当前 VENTUNO Q 固件链路决定的：`can0` 位于宿主网络命名空间，App 容器中
看不到它；Sketch 再调用 `CAN.begin()` 还会和系统 CANnectivity 争用同一个 FDCAN1。

## 源码目录

本文左侧“配套源码”包含 Brick、最小测试 App 和原生网关：

```text
app/
├── app.yaml
├── python/main.py
├── python/manual_test.py
└── bricks/zdt_x57s_can/
    ├── __init__.py
    ├── client.py
    ├── brick_config.yaml
    ├── requirements.txt
    └── README.md
can-gateway/
├── gateway.py
├── socketcan_transport.py
├── zdt_x57s_driver.py
├── zdt_x57s_protocol.py
└── tests/
```

只复制 Brick 还不能访问电机；原生网关是必要的运行依赖。

## 配置 App

将完整 `zdt_x57s_can` 目录放到新 App 的 `bricks/` 下，并在 `app.yaml` 引用：

```yaml
bricks:
  - zdt_x57s_can:
      variables:
        ZDT_CAN_GATEWAY_HOST: "msgpack-rpc-router"
        ZDT_CAN_GATEWAY_PORT: "8766"
        ZDT_CAN_GATEWAY_TOKEN: "<随机令牌>"
        ZDT_CAN_REQUEST_TIMEOUT_S: "1.5"
```

令牌需要同时写入 App 配置与原生网关的 `.gateway-token`，真实值不能提交到博客或公开
仓库。网关只监听 Docker 内部主机地址 `172.17.0.1:8766`，不应向局域网开放。

## 创建一个或多个对象

单电机：

```python
from zdt_x57s_can import ZdtX57SCan


motor = ZdtX57SCan(motor_id=1)
print(motor.probe())
```

四个独立对象：

```python
motors = tuple(ZdtX57SCan(motor_id) for motor_id in (1, 2, 3, 4))
speeds = {motor.motor_id: motor.read_speed() for motor in motors}
```

每个方法只操作对象绑定的地址。Brick 支持协议地址 `1～255`，但不提供 `stop_all` 或
批量同步接口；这些属于上层 App 的组合与安全策略。

## API 的准确含义

| API | 是否发 CAN | 结果 |
| --- | --- | --- |
| `motor_id` | 否 | 当前对象地址 |
| `status()` | 否 | 网关进程与 `can0` 状态，不代表电机在线 |
| `read_speed()` | 是 | 当前电机返回的带符号整数 RPM |
| `probe()` | 是 | `{motor_id, speed_rpm}` |
| `enable(confirmation)` | 是 | 使能当前电机 |
| `disable()` | 是 | 失能当前电机 |
| `set_speed(rpm, acceleration_level, confirmation)` | 是 | 设置目标整数 RPM |
| `stop()` | 是 | 尝试零速、停止、失能 |
| `timed_speed_test(...)` | 是 | 限时运行并在 `finally` 中停车 |

因此检查顺序应是：先用 `status()` 检查网关，再用 `probe()` 检查指定地址的 CAN 应答。

## 启动硬件链路

电机上电、接线与终端电阻确认后，在 VENTUNO Q 宿主执行：

```bash
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 500000
sudo ip link set can0 up
ip -details -statistics link show can0
```

正常工作状态应包含 `UP`、`LOWER_UP`、`ERROR-ACTIVE` 和 `bitrate 500000`。这里的
`ERROR-ACTIVE` 是 CAN 控制器的正常主动错误状态；需要关注的是计数是否增长，或是否进入
`ERROR-PASSIVE`、`BUS-OFF`。当前 `gs_usb` 不支持 `restart-ms`，不要添加该参数。

另开终端启动原生网关：

```bash
cd /home/arduino/work/zdt_x57s_can_gateway
python3 -B gateway.py
```

## 先做无运动验证

在 App 容器中调用 Brick：

```bash
docker exec \
  -e PYTHONPATH=/app/bricks \
  zdt-x57s-can-test-main-1 \
  python3 -B /app/python/manual_test.py --probe --motor-id 1
```

正常结果示例：

```json
{
  "motor_id": 1,
  "speed_rpm": 0
}
```

这个结果说明地址 1 返回了能通过地址、命令字和 `0x6B` 校验的实时速度应答。它不会
使能电机，也不会让电机转动。

## 安全运行测试

会导致运动的方法需要精确确认口令 `RUN_ZDT_X57S_V1_0`。只有底盘架空、周围清空且
可以立即切断电机电源时才执行：

```python
result = motor.timed_speed_test(
    rpm=20,
    acceleration_level=10,
    duration_s=3.0,
    confirmation="RUN_ZDT_X57S_V1_0",
)
```

当前网关限制绝对速度不超过 60 RPM、限时测试不超过 5 秒。持续非零
`set_speed()` 必须在 500 ms 内刷新，否则网关看门狗会尝试零速、停止与失能。

## CAN 报文

虽然硬件控制器是 FDCAN，本电机协议使用经典 CAN，不发送 CAN-FD/BRS 帧。

| 项目 | 值 |
| --- | --- |
| 位速率 | `500000 bit/s` |
| 帧格式 | 29 位扩展帧 |
| CAN-ID | `(motor_id << 8) \| packet_index` |
| 当前单包序号 | `packet_index = 0` |
| 地址 1 CAN-ID | `0x00000100` |
| 校验字节 | `0x6B` |

| 操作 | 数据 |
| --- | --- |
| 读实时速度 | `35 6B` |
| 速度应答 | `35 DIR SPEED_H SPEED_L 6B` |
| 使能/失能 | `F3 AB EN SYNC 6B` |
| 设置速度 | `F6 DIR SPEED_H SPEED_L ACC SYNC 6B` |
| 立即停止 | `FE 98 SYNC 6B` |
| 成功/拒绝应答 | `FUNC 02 6B` / `FUNC E2 6B` |

这些字节只适用于本项目确认的第二代 XS/`FW_Emm` 固定 CAN 协议，不能用于旧版
X57 V2 协议。完整测试 App 见 [zdt-x57s-can-test 教程](/app-lab/zdt-x57s-can-test/)。

