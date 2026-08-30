---
title: "four-motor-can-probe：检查四台 ZDT 电机的 CAN 通信"
description: "通过 SocketCAN 依次读取地址 1、2、3、4 的电机速度，确认四台电机都能在 500 kbit/s 总线上应答。"
section: "app-lab"
appId: "four-motor-can-probe"
order: 2
status: "planned"
pubDate: "2026-08-30"
updatedDate: "2026-08-30"
environment:
  - "Arduino VENTUNO Q"
  - "ZDT X57S × 4"
  - "CAN 500 kbit/s"
capabilities:
  - "SocketCAN"
  - "四电机寻址"
  - "通信自检"
---

这篇示例教程用于展示 App Lab 板块中同时存在多篇文章时的排列效果。教程目标是把
四台电机的通信检查做成一个独立小 App，只验证 CAN 链路和地址应答，不执行旋转命令。

## 预期结果

四台电机的地址分别为 `1`、`2`、`3`、`4`。CAN 接口启动后，程序依次读取每台电机的
实时速度；四个地址全部返回有效应答，才判定通信检查通过。

```text
四电机通信正常: id1=0RPM, id2=0RPM, id3=0RPM, id4=0RPM
```

## 启动 CAN 接口

```bash
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 500000
sudo ip link set can0 up
ip -details -statistics link show can0
```

接口应该显示 `UP`、`LOWER_UP` 和 `ERROR-ACTIVE`。如果仍然是 `DOWN`，应先排查接口、
终端电阻和电机供电，不要继续发送运动命令。

## App 应实现的检查流程

1. 打开 `can0`，固定使用 500 kbit/s 普通 CAN 帧。
2. 按地址 `1 → 2 → 3 → 4` 逐台发送速度读取命令。
3. 校验应答地址、命令字、数据长度和校验字节。
4. 任意一台超时或返回非法应答时，输出对应地址并判定失败。
5. 四台全部应答后，只打印检测结果，不使能电机。

## 当前状态

这篇文章目前标记为“规划中”，用于预览 App Lab 的多文章布局。等独立 App 完成实机验证后，
再补充完整目录、源码和复现步骤，并将状态更新为“已实测”。
