---
title: "ROS 2 与 App 通讯 03：发布 BNO086 IMU 数据"
description: "由 VENTUNO Q MCU 采集 BNO086，经 RouterBridge、Arduino App 和 WebSocket 发布标准 sensor_msgs/msg/Imu，并保留完整诊断信息。"
section: "ros2-app"
appId: "bno086-ros-live"
order: 3
status: "in-progress"
pubDate: "2026-09-05"
updatedDate: "2026-09-05"
environment:
  - "Arduino VENTUNO Q"
  - "ROS 2 Jazzy"
  - "BNO086"
  - "Arduino RouterBridge"
capabilities:
  - "sensor_msgs/Imu"
  - "WebSocket"
  - "I²C"
  - "数据质量门禁"
sourceDir: "ros2-app-imu-demo"
---

这个示例把 BNO086 的真实采样转换成 ROS 2 标准 `sensor_msgs/msg/Imu`。MCU 负责稳定读取
I²C 和缓存报告，Arduino App 只读取完整快照、执行质量检查并通过 WebSocket 上传，原生
`ros_ws_bridge` 最终创建 ROS 2 话题。

## 通信链路

```text
BNO086
   ↓ I²C
Bno086Imu MCU 库
   ↓ imu_get_sample / imu_get_status
RouterBridge
   ↓
bno086_imu Brick + App 质量门禁
   ↓ WebSocket JSON
ros_ws_bridge
   ↓
/imu/data + /imu/status
```

这是单向上传示例。App 没有注册 WebSocket `on_message` 回调，因此网络输入不会意外变成
硬件写入或控制命令。

## 硬件连接

| 项目 | 当前配置 |
| --- | --- |
| 总线 | `Wire / I2C4` |
| 首选地址 | `0x4B` |
| 回退地址 | `0x4A` |
| INT | `D2`，低有效 |
| RST | `D3`，低有效 |
| I²C 时钟 | 400 kHz |

实际 App 使用本地 `Adafruit_BNO08x_Ventuno` 1.2.5 适配库，并把该库的完整源码、示例、
许可证和 NOTICE 一并保存在配套源码中。

## ROS 2 接口

| 名称 | 消息类型 | 频率 | 用途 |
| --- | --- | --- | --- |
| `/imu/data` | `sensor_msgs/msg/Imu` | 目标约 50 Hz | 姿态、角速度、去重力线加速度 |
| `/imu/status` | `std_msgs/msg/String` | 1 Hz | RPC、采样、复位、时间戳和网络诊断 JSON |

这里没有 Service、Parameter 或 Action。IMU 是连续数据源，使用 Topic 最合适。

## MCU 提供的 RouterBridge API

| RPC | 方向 | 返回内容 |
| --- | --- | --- |
| `imu_get_sample` | App 读取 MCU | 四路传感器完整快照 |
| `imu_get_status` | App 读取 MCU | 初始化、报告频率、计数、复位和错误状态 |

两个 RPC 都是只读接口。`bno086_imu` Brick 也不初始化 I²C、不控制引脚、不修改传感器，
它只负责调用 RPC 并验证返回对象结构。

## MCU 采集的四路数据

| 报告 | 频率 | 单位 | ROS 2 用途 |
| --- | --- | --- | --- |
| `accelerometer` | 50 Hz | m/s² | 保留含重力原始值，用于诊断 |
| `linear_acceleration` | 100 Hz | m/s² | 去重力后写入 `Imu.linear_acceleration` |
| `gyroscope` | 100 Hz | rad/s | 写入 `Imu.angular_velocity` |
| `orientation` | 100 Hz | 四元数 | Game Rotation Vector 姿态 |

不要把 `accelerometer.raw` 直接写入 ROS 2 的线加速度字段。当前实现明确使用去除重力后的
`linear_acceleration.raw`。

## 完整源码目录

左侧源码树包含完整 Arduino App、两个 Brick、MCU 库、第三方驱动和 ROS 2 桥接器：

```text
ros2-app-imu-demo/
├── app/
│   ├── app.yaml
│   ├── python/main.py
│   ├── bricks/
│   │   ├── bno086_imu/
│   │   └── websocket_server/
│   └── sketch/
│       ├── sketch.ino
│       ├── sketch.yaml
│       └── lib/
│           ├── Bno086Imu/
│           └── Adafruit_BNO08x_Ventuno/
└── ros2/
    ├── ros_ws_bridge/
    └── imu_live/
        ├── imu.yaml
        └── imu_subscriber.py
```

`Adafruit_BNO08x_Ventuno` 中的 `.c`、`.cpp`、`.h`、示例、许可证和配置文件都可以从左侧
打开。源码目录不包含 App 缓存、虚拟环境和 ROS 2 构建产物。

## 最小 Sketch

顶层 Sketch 只负责编排，不包含大量传感器协议代码：

```cpp
void setup() {
  const bool bridgeReady = Bridge.begin();
  Bno086Imu::provideRpc(bridgeReady);
  Bno086Imu::begin();
}

void loop() {
  Bno086Imu::update();
  delay(1);
}
```

`Bno086Imu::update()` 每次最多处理 32 个 FIFO 事件，避免持续读取 IMU 时饿死 RouterBridge
RPC。任一路超过 200 ms 没有更新，MCU 会把该报告标记为 `stale=true`。

## App 怎样生成 ROS 2 消息

App 的 `python/main.py` 每 0.019 秒尝试读取一次快照。只有下面条件全部满足时，才发布新的
`/imu/data`：

1. 四路报告都存在；
2. `valid=true` 且 `stale=false`；
3. 精度值在 1～3；
4. 向量和四元数都是有限数值；
5. 四元数范数接近 1；
6. `sample_seq`、`count` 和 `sensor_time_us` 没有倒退；
7. 去重力线加速度产生了新样本；
8. 传感器时间间隔没有超过 250 ms。

重复读取到同一快照时不会重复发布。BNO086 复位后，MCU 重新启用报告，App 建立新的
传感器时间周期，并在 `/imu/status` 中保留新的 `reset_count`。

## 时间戳

BNO086 的 `sensor_time_us` 是传感器启动后的相对微秒计数，不是 Unix 时间。当前 App 的
处理方式是：

1. 第一帧有效线加速度到达时，用 Linux 墙上时间建立锚点；
2. 后续时间戳只按照 BNO086 相对时间的增量推进；
3. 最终转换成 ROS 2 `header.stamp`。

这样即使 WebSocket 或 RPC 偶尔成批到达，连续 IMU 样本的时间间隔仍来自传感器时钟，
不会简单地全部变成 Linux 收包时间。

报文外层的 `timestamp` 仍是 Unix Epoch 毫秒时间戳，用于通用桥接信封；真正的 ROS 2
IMU 时间在 `data.header.stamp` 中。

## 坐标系和协方差

- `frame_id` 固定为 `imu_link`；
- 当前 App 不伪造 `imu_link → base_link` TF；
- Game Rotation Vector 不依赖磁北，不能当作绝对航向；
- 三组 covariance 全部为 0，表示当前未知，并不表示测量误差为零；
- 安装方向、静态偏置、Tare 和协方差应在底盘集成阶段单独标定。

## 准备源码

把配套源码保存到：

```text
/home/arduino/ArduinoApps/bno086-ros-live
/home/arduino/ros2_ws/codex/src/ros_ws_bridge
/home/arduino/ros2_ws/codex/imu_live
```

构建桥接包：

```bash
cd /home/arduino/ros2_ws/codex
source /opt/ros/jazzy/setup.bash
colcon build --packages-select ros_ws_bridge --symlink-install
source install/setup.bash
```

## 启动 IMU App

先确认没有其他 App 占用 8765 端口：

```bash
arduino-app-cli app list
ss -ltnH | awk '$4 ~ /:8765$/ {print}'
```

然后启动：

```bash
arduino-app-cli app start /home/arduino/ArduinoApps/bno086-ros-live
```

App 启动会编译或刷写 MCU Sketch。正常运行时，App 日志会周期输出类似信息：

```text
[BNO086 ROS] clients=0 rpc_ok=True fault=none
```

这只证明 MCU RPC 最近一次读取成功；`clients=0` 表示 ROS 2 桥接器尚未连接。

## 启动 ROS 2 桥接器

```bash
export ROS_DOMAIN_ID=46
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
source /opt/ros/jazzy/setup.bash
source /home/arduino/ros2_ws/codex/install/setup.bash

ros2 run ros_ws_bridge bridge_node \
  --ros-args \
  -p config_file:=/home/arduino/ros2_ws/codex/imu_live/imu.yaml
```

桥接器只接受 `imu.yaml` 中声明的两条 `ws_to_ros` 路由，不会创建控制方向的话题。

## 查看标准 IMU 消息

另开终端：

```bash
export ROS_DOMAIN_ID=46
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
source /opt/ros/jazzy/setup.bash
source /home/arduino/ros2_ws/codex/install/setup.bash
ros2 topic echo /imu/data --once --full-length
```

正常消息应包含：

```yaml
header:
  frame_id: imu_link
orientation:
  x: 0.0
  y: 0.0
  z: 0.0
  w: 1.0
angular_velocity:
  x: 0.0
  y: 0.0
  z: 0.0
linear_acceleration:
  x: 0.0
  y: 0.0
  z: 0.0
```

具体数值会随安装姿态和运动变化，上面只展示字段结构。

检查发布频率：

```bash
ros2 topic hz /imu/data
```

目标约为 50 Hz。频率短时波动不能单独证明数据质量，还需要同时检查 `/imu/status`。

## 查看诊断

```bash
ros2 topic echo /imu/status --once --full-length
```

重点检查：

| 字段 | 正常含义 |
| --- | --- |
| `last_rpc_ok` | 最近一次 RouterBridge RPC 成功 |
| `last_fault` | 最近质量门禁结果，正常为 `none` |
| `report.*.valid` | 对应报告通过 MCU 有效性检查 |
| `report.*.stale` | 对应报告没有过期 |
| `report.*.accuracy` | 质量值在 1～3 |
| `report.*.count` | MCU 接收计数持续增加 |
| `report.reset_count` | BNO086 复位次数 |
| `timestamp_mapping.mapping_state` | 传感器时间映射状态 |
| `websocket.client_count` | 桥接器连接后应至少为 1 |

也可以运行配套观察器：

```bash
export ROS_DOMAIN_ID=46
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
source /opt/ros/jazzy/setup.bash
python3 /home/arduino/ros2_ws/codex/imu_live/imu_subscriber.py
```

观察器每秒打印最新姿态、角速度、线加速度和诊断摘要；超过一秒没有新 `/imu/data` 时会明确
显示 `STALE`，不会把旧缓存伪装成实时数据。

## 当前验证边界

当前参考 App 的 BNO086 实际采集链路已经确认可用，但下列内容仍属于机器人综合集成阶段：

- 长时间频率和丢帧统计；
- 安装方向与 `base_link` 的静态 TF；
- Tare、偏置和温漂标定；
- covariance 实测；
- 与轮速里程计的时钟和坐标系统一；
- VIO、LIO 或 `robot_localization` 融合。

因此本教程只证明“有效 IMU 快照能够安全转换并进入 ROS 2”，不把它扩大解释为已经完成
整车定位标定。
