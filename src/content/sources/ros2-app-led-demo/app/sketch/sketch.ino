#include <Arduino.h>
#include <Arduino_RouterBridge.h>

// 每个 LED 都是一组 RGB，三个引脚同时控制。
const uint8_t kLedPins[4][3] = {
    {LED1_R, LED1_G, LED1_B},
    {LED2_R, LED2_G, LED2_B},
    {LED3_R, LED3_G, LED3_B},
    {LED4_R, LED4_G, LED4_B},
};

// 保存四组 LED 的逻辑状态。
bool led1On = false;
bool led2On = false;
bool led3On = false;
bool led4On = false;


void writeLedGroup(uint8_t index, bool on) {
  // ROS 和 App 使用 true=亮、false=灭。
  // Ventuno Q 的 LED 是 active-low，所以只在这里反转电平。
  const uint8_t level = on ? LOW : HIGH;

  for (uint8_t color = 0; color < 3; ++color) {
    digitalWrite(kLedPins[index][color], level);
  }
}


void applyLedStates(bool led1, bool led2, bool led3, bool led4) {
  writeLedGroup(0, led1);
  writeLedGroup(1, led2);
  writeLedGroup(2, led3);
  writeLedGroup(3, led4);

  led1On = led1;
  led2On = led2;
  led3On = led3;
  led4On = led4;
}


// 提供给 Linux/App 调用。
// 参数顺序是 LED1、LED2、LED3、LED4。
bool set_leds(bool led1, bool led2, bool led3, bool led4) {
  applyLedStates(led1, led2, led3, led4);
  return true;
}


// 返回四组 LED 当前状态。
// bit 0、1、2、3 分别表示 LED1、LED2、LED3、LED4。
uint8_t get_leds() {
  return (led1On ? 1U : 0U) |
         (led2On ? 2U : 0U) |
         (led3On ? 4U : 0U) |
         (led4On ? 8U : 0U);
}


void setup() {
  for (uint8_t index = 0; index < 4; ++index) {
    for (uint8_t color = 0; color < 3; ++color) {
      // 在设为输出前先写入熄灭电平，避免启动时短暂闪烁。
      digitalWrite(kLedPins[index][color], HIGH);
      pinMode(kLedPins[index][color], OUTPUT);
    }
  }

  // MCU 启动时默认四组全灭。
  applyLedStates(false, false, false, false);

  const bool bridgeReady = Bridge.begin();
  bool apiReady = false;

  if (bridgeReady) {
    const bool setApiReady =
        Bridge.provide("set_leds", set_leds);

    const bool getApiReady =
        Bridge.provide("get_leds", get_leds);

    apiReady = setApiReady && getApiReady;
  }

  // Bridge 初始化失败时保持全灭。
  if (!bridgeReady || !apiReady) {
    applyLedStates(false, false, false, false);
  }
}

int i = 0;


void loop() {
  // RouterBridge 在后台处理 RPC。
  delay(1);
}