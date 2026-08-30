# ZDT X57S CAN Custom Brick

`zdt_x57s_can` 为一台 ZDT X57S 第二代 `FW_Emm` 电机提供 Python 对象 API。每个
`ZdtX57SCan` 实例在构造时绑定一个 `motor_id`；使用一台电机就创建一个对象，使用四台
电机则由 App 创建四个对象。

这个 Brick 是 **Linux 原生 CAN 网关的客户端/代理**，不是直接 SocketCAN 驱动：它不
打开 `can0`，也不发送原始 CAN 帧。真正拥有 `can0` 的进程位于：

```text
/home/arduino/work/zdt_x57s_can_gateway
```

## 数据链路

```text
App 的 python/main.py
  ↓ 单电机 Python 方法
ZdtX57SCan 对象
  ↓ 带令牌的换行分隔 JSON/TCP
Linux 原生 zdt_x57s_can_gateway
  ↓ SocketCAN can0
CANnectivity / gs_usb / FDCAN1
  ↓ 经典 CAN 500 kbit/s，29 位扩展帧
ZDT X57S 第二代 FW_Emm
```

VENTUNO Q 的 FDCAN 控制器虽然支持 CAN-FD，本协议实际发送的是经典 CAN 帧，不使用
CAN-FD 数据阶段或 BRS。

## 运行前提

- `can0` 已设为 `500000 bit/s` 并处于 `UP`、`ERROR-ACTIVE`。
- 原生网关已启动，并只监听 Docker 主机内部地址 `172.17.0.1:8766`。
- App 与网关配置了同一个随机令牌；公开源码只保存 `<随机令牌>` 占位符。
- 电机协议为第二代 XS 系列 `FW_Emm`，不能套用旧版 X57 V2 报文。

`brick_config.yaml` 的默认容器访问主机名是 `msgpack-rpc-router`。原生网关是独立部署
依赖，安装 Brick 本身不会自动安装或启动网关，也不会自动配置 `can0`。

## 在 App 中引用

```yaml
bricks:
  - zdt_x57s_can:
      variables:
        ZDT_CAN_GATEWAY_HOST: "msgpack-rpc-router"
        ZDT_CAN_GATEWAY_PORT: "8766"
        ZDT_CAN_GATEWAY_TOKEN: "<随机令牌>"
        ZDT_CAN_REQUEST_TIMEOUT_S: "1.5"
```

创建对象时绑定地址：

```python
from zdt_x57s_can import ZdtX57SCan


motor_1 = ZdtX57SCan(motor_id=1)
print(motor_1.probe())

motors = tuple(ZdtX57SCan(motor_id) for motor_id in (1, 2, 3, 4))
speeds = {motor.motor_id: motor.read_speed() for motor in motors}
```

Brick 接受协议地址 `1～255`。对象方法不再接收 `motor_id`，从接口上避免一次调用意外
操作其他地址。多电机聚合、四轮同步、`stop_all` 和底盘运动学应由上层 App 实现。

## Python API

| API | 是否发送 CAN | 语义 |
| --- | --- | --- |
| `motor_id` | 否 | 返回对象绑定的电机地址 |
| `status()` | 否 | 查询原生网关进程和 `can0` 状态；不能证明电机有应答 |
| `read_speed()` | 是 | 查询当前地址的实时整数 RPM |
| `probe()` | 是 | 调用 `read_speed()` 并返回 `motor_id` 与 `speed_rpm` |
| `enable(confirmation)` | 是 | 发送当前电机使能命令 |
| `disable()` | 是 | 发送当前电机失能命令 |
| `set_speed(rpm, acceleration_level, confirmation)` | 是 | 设置当前电机速度 |
| `stop()` | 是 | 依次尝试零速、立即停止和失能，并汇总结果 |
| `timed_speed_test(...)` | 是 | 执行最长 5 秒的限时运行，`finally` 中停车 |

`status()` 只验证 App 到原生网关的控制链路。确认某个电机 CAN 通信必须调用
`probe()` 或 `read_speed()`，并成功解析该地址返回的 `35 ... 6B` 应答。

## 只读通信检查

```python
from zdt_x57s_can import ZdtX57SCan, ZdtX57SCanError


try:
    motor = ZdtX57SCan(motor_id=1)
    print(motor.status())  # 不发 CAN
    print(motor.probe())   # 发送实时速度查询，但不会使能电机
except ZdtX57SCanError as error:
    print(error)
```

从 App 容器手动执行测试脚本时，需要显式提供 Brick 搜索路径；正常 App 启动脚本会自动
设置该路径：

```bash
docker exec \
  -e PYTHONPATH=/app/bricks \
  zdt-x57s-can-test-main-1 \
  python3 -B /app/python/manual_test.py --probe --motor-id 1
```

## 运动方法与安全约束

`enable()`、`set_speed()` 和 `timed_speed_test()` 必须接收精确确认口令：

```text
RUN_ZDT_X57S_V1_0
```

```python
motor.timed_speed_test(
    rpm=20,
    acceleration_level=10,
    duration_s=3.0,
    confirmation="RUN_ZDT_X57S_V1_0",
)
```

当前原生网关限制目标速度绝对值不超过 60 RPM，限时测试不超过 5 秒。非零
`set_speed()` 必须在 500 ms 内持续刷新，否则网关看门狗会尝试零速、停止和失能。
固定确认口令只是防止误调用，不替代架空底盘、清空周围人员和准备硬件断电。

## Brick 与原生网关协议

每个 TCP 连接处理一个请求和一个响应，报文是以 `\n` 结束的 UTF-8 JSON。请求包含
协议版本、唯一请求 ID、随机令牌、方法和参数：

```json
{"version":1,"request_id":"d0c1","token":"<随机令牌>","method":"read_speed","params":{"motor_id":1}}
```

成功响应：

```json
{"version":1,"request_id":"d0c1","ok":true,"result":{"motor_id":1,"speed_rpm":0}}
```

失败响应中的程序分支应依据稳定的 `error.code`，不能依据英文 `message`：

```json
{"version":1,"request_id":"d0c1","ok":false,"error":{"code":"can_error","message":"motor 1 speed reply timed out"}}
```

客户端会检查响应协议版本和 `request_id`。任一连接、超时、JSON、版本、地址或网关错误
都会转换为 `ZdtX57SCanError`。

## 电机 CAN 协议

| 项目 | 当前实现 |
| --- | --- |
| 总线类型 | 经典 CAN，不使用 CAN-FD/BRS |
| 位速率 | `500000 bit/s` |
| 帧格式 | 29 位扩展帧 |
| CAN-ID | `(motor_id << 8) \| packet_index` |
| 当前 `packet_index` | `0` |
| 校验字节 | `0x6B` |
| 成功/拒绝状态 | `0x02` / `0xE2` |

| 功能 | 数据字段 |
| --- | --- |
| 读取实时速度 | `35 6B` |
| 速度应答 | `35 DIR SPEED_H SPEED_L 6B` |
| 使能/失能 | `F3 AB EN SYNC 6B` |
| 速度模式 | `F6 DIR SPEED_H SPEED_L ACC SYNC 6B` |
| 立即停止 | `FE 98 SYNC 6B` |
| 控制应答 | `FUNC 02 6B` 或 `FUNC E2 6B` |

驱动层只接受匹配当前对象地址、期望命令字和 `0x6B` 校验的应答。以上字节只适用于
本项目确认的第二代 XS/`FW_Emm` 固定 CAN 协议。

