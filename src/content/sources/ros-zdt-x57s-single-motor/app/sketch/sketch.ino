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
