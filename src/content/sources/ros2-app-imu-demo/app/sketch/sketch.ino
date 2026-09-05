#include <Arduino.h>
#include <Arduino_RouterBridge.h>
#include <Bno086Imu.h>

void setup() {
  // The app owns Bridge startup; the reusable library owns IMU acquisition
  // and the two read-only RPC callbacks.
  const bool bridgeReady = Bridge.begin();
  Bno086Imu::provideRpc(bridgeReady);
  Bno086Imu::begin();
}

void loop() {
  Bno086Imu::update();
  delay(1);
}
