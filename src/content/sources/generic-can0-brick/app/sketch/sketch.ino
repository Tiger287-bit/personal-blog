#include <Arduino_RouterBridge.h>

/*
 * @description         : 启动RouterBridge并让系统CANnectivity向Linux提供FDCAN1
 * @param               : 无
 * @return              : 无
 */
void setup() {
  const bool bridgeReady = Bridge.begin();
  (void)bridgeReady;
}

/*
 * @description         : 保持MCU任务调度运行且不通过Arduino CAN库占用FDCAN1
 * @param               : 无
 * @return              : 无
 */
void loop() {
  delay(10);
}
