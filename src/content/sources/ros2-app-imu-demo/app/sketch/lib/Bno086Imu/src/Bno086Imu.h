#pragma once

#include <Arduino.h>

// Validated BNO086 acquisition for the Ventuno Q MCU.
//
// This is deliberately a namespace API: the underlying Adafruit/SH-2 driver
// state is global, so one process supports one BNO086 instance only.  Callers
// own RouterBridge startup and must pass its result to provideRpc().
namespace Bno086Imu {

// Initializes only the IMU bus, reset sequence, driver, and four reports.
// This function does not start RouterBridge, register RPCs, or control LEDs.
bool begin();

// Pass the result of the caller's Bridge.begin().  When true, registers the
// two read-only RPCs (imu_get_status and imu_get_sample).  Registration is
// idempotent: an already successful RPC is not registered a second time, and
// an unsuccessful one can be retried.  A false result means Bridge was not
// ready or at least one RPC could not be registered (for example, a name
// collision); no existing RPC is replaced.
bool provideRpc(bool bridgeStarted);

// Drains pending BNO086 events (up to the bounded per-call limit).  Call this
// frequently from loop() so the FIFO and read-only RPCs remain responsive.
void update();

// Returns the validated latest-data JSON used by imu_get_sample.
String sampleJson();

// Returns the diagnostic/status JSON used by imu_get_status.
String statusJson();

}  // namespace Bno086Imu
