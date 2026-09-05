#include <Bno086Imu.h>

#include <Arduino_RouterBridge.h>
#include <Adafruit_BNO08x.h>
#include <Wire.h>
#include <math.h>

namespace {

// 自制Shield已经确认的连接。
constexpr uint8_t kInterruptPin = 2;  // D2，BNO086 INT，低有效
constexpr uint8_t kResetPin = 3;      // D3，BNO086 RST，低有效

// 实测首先在0x4B发现设备；仍保留0x4A作为ADR改变后的回退地址。
constexpr uint8_t kPrimaryAddress = 0x4B;
constexpr uint8_t kAlternateAddress = 0x4A;

// BNO08X I2C上限为400 kHz；Ventuno当前Wire对象已有setClock(uint32_t)
// 接口，沿用现有调用方式提升传输余量。
constexpr uint32_t kI2cClockHz = 400000;

// MCU内部采样率：兼容加速度50 Hz、去重力线加速度100 Hz、角速度100 Hz、姿态100 Hz。
// ROS2-05只发布50 Hz快照；100 Hz报告用于在MCU FIFO中保留更细的真实更新。
constexpr uint32_t kAccelerometerIntervalUs = 20000;
constexpr uint32_t kLinearAccelerationIntervalUs = 10000;
constexpr uint32_t kGyroscopeIntervalUs = 10000;
constexpr uint32_t kOrientationIntervalUs = 10000;

// 每次loop最多从FIFO取出有限数量的事件，避免高负载时饿死RouterBridge RPC。
constexpr uint8_t kMaxEventsPerUpdate = 32;

// 任一类数据超过200 ms没有更新，就在RPC结果中标记stale。
constexpr uint32_t kStaleTimeoutMs = 200;

// 仅用于App终端显示的指数低通滤波。
// raw始终保留，不会被滤波值替代。
constexpr float kDisplayFilterAlpha = 0.20F;

struct VectorSample {
  float rawX = 0.0F;
  float rawY = 0.0F;
  float rawZ = 0.0F;

  float filteredX = 0.0F;
  float filteredY = 0.0F;
  float filteredZ = 0.0F;

  uint8_t accuracy = 0;
  uint8_t sourceSequence = 0;
  uint8_t previousSourceSequence = 0;

  uint32_t sampleSequence = 0;
  uint32_t count = 0;
  uint32_t sequenceGapCount = 0;
  uint32_t lastSampleMillis = 0;
  uint64_t timestampUs = 0;

  bool haveSample = false;
  bool haveSourceSequence = false;
  bool finite = false;
};

struct QuaternionSample {
  float x = 0.0F;
  float y = 0.0F;
  float z = 0.0F;
  float w = 1.0F;
  float normBeforeNormalize = 1.0F;

  uint8_t accuracy = 0;
  uint8_t sourceSequence = 0;
  uint8_t previousSourceSequence = 0;

  uint32_t sampleSequence = 0;
  uint32_t count = 0;
  uint32_t sequenceGapCount = 0;
  uint32_t lastSampleMillis = 0;
  uint64_t timestampUs = 0;

  bool haveSample = false;
  bool haveSourceSequence = false;
  bool finite = false;
};

Adafruit_BNO08x imu(kResetPin);
sh2_SensorValue_t sensorValue = {};

VectorSample accelerometer;
VectorSample linearAcceleration;
VectorSample gyroscope;
QuaternionSample orientation;

bool bridgeReady = false;
bool apiReady = false;
bool statusRpcReady = false;
bool sampleRpcReady = false;
bool imuReady = false;
bool accelerometerReportReady = false;
bool linearAccelerationReportReady = false;
bool gyroscopeReportReady = false;
bool orientationReportReady = false;
bool allReportsReady = false;

uint8_t detectedAddress = 0;
uint32_t resetCount = 0;
uint32_t unknownReportCount = 0;

uint8_t productEntries = 0;
uint8_t softwareMajor = 0;
uint8_t softwareMinor = 0;
uint16_t softwarePatch = 0;
uint32_t partNumber = 0;
uint32_t buildNumber = 0;

const char *lastError = "not_started";

void hardwareResetBno086() {
  pinMode(kInterruptPin, INPUT_PULLUP);

  pinMode(kResetPin, OUTPUT);
  digitalWrite(kResetPin, HIGH);
  delay(10);

  digitalWrite(kResetPin, LOW);
  delay(10);

  digitalWrite(kResetPin, HIGH);
  delay(300);
}

bool addressResponds(uint8_t address) {
  Wire.beginTransmission(address);
  return Wire.endTransmission() == 0;
}

uint8_t findBno086Address() {
  for (uint8_t attempt = 0; attempt < 20; ++attempt) {
    if (addressResponds(kPrimaryAddress)) {
      return kPrimaryAddress;
    }

    if (addressResponds(kAlternateAddress)) {
      return kAlternateAddress;
    }

    delay(25);
  }

  return 0;
}

void cacheProductInformation() {
  productEntries = imu.prodIds.numEntries;
  if (productEntries == 0) {
    return;
  }

  const sh2_ProductId_t &product = imu.prodIds.entry[0];
  softwareMajor = product.swVersionMajor;
  softwareMinor = product.swVersionMinor;
  softwarePatch = product.swVersionPatch;
  partNumber = product.swPartNumber;
  buildNumber = product.swBuildNumber;
}

void clearLiveSamplesAfterReset() {
  accelerometer.haveSample = false;
  accelerometer.finite = false;
  accelerometer.sourceSequence = 0;
  accelerometer.previousSourceSequence = 0;
  accelerometer.haveSourceSequence = false;
  accelerometer.sequenceGapCount = 0;

  linearAcceleration.haveSample = false;
  linearAcceleration.finite = false;
  linearAcceleration.sourceSequence = 0;
  linearAcceleration.previousSourceSequence = 0;
  linearAcceleration.haveSourceSequence = false;
  linearAcceleration.sequenceGapCount = 0;

  gyroscope.haveSample = false;
  gyroscope.finite = false;
  gyroscope.sourceSequence = 0;
  gyroscope.previousSourceSequence = 0;
  gyroscope.haveSourceSequence = false;
  gyroscope.sequenceGapCount = 0;

  orientation.haveSample = false;
  orientation.finite = false;
  orientation.sourceSequence = 0;
  orientation.previousSourceSequence = 0;
  orientation.haveSourceSequence = false;
  orientation.sequenceGapCount = 0;

  // SH-2序号在复位后重新开始；新的reset_count标记了一个新的序号epoch。
}

bool enableReports() {
  // 分开记录四项结果，便于定位具体是哪一种报告没有启用。
  accelerometerReportReady = imu.enableReport(
      SH2_ACCELEROMETER,
      kAccelerometerIntervalUs);

  linearAccelerationReportReady = imu.enableReport(
      SH2_LINEAR_ACCELERATION,
      kLinearAccelerationIntervalUs);

  gyroscopeReportReady = imu.enableReport(
      SH2_GYROSCOPE_CALIBRATED,
      kGyroscopeIntervalUs);

  orientationReportReady = imu.enableReport(
      SH2_GAME_ROTATION_VECTOR,
      kOrientationIntervalUs);

  allReportsReady =
      accelerometerReportReady &&
      linearAccelerationReportReady &&
      gyroscopeReportReady &&
      orientationReportReady;

  return allReportsReady;
}

bool initializeBno086() {
  imuReady = false;
  allReportsReady = false;
  clearLiveSamplesAfterReset();
  lastError = "initializing";

  // 当前Shield连接I2C4，在此Zephyr core中对应Wire。
  Wire.begin();
  Wire.setClock(kI2cClockHz);

  hardwareResetBno086();
  detectedAddress = findBno086Address();

  if (detectedAddress == 0) {
    lastError = "i2c_address_not_found";
    return false;
  }

  // 使用现有App中已经验证过的Ventuno适配库接口。
  // 参数：地址、Wire对象、sensor_id、INT引脚。
  if (!imu.begin_I2C(
          detectedAddress,
          &Wire,
          0,
          kInterruptPin)) {
    lastError = "driver_initialization_failed";
    return false;
  }

  Wire.setClock(kI2cClockHz);
  cacheProductInformation();

  if (!enableReports()) {
    lastError = "one_or_more_reports_failed";
    return false;
  }

  imuReady = true;
  lastError = "none";
  return true;
}

bool vectorIsFinite(float x, float y, float z) {
  return isfinite(x) && isfinite(y) && isfinite(z);
}

template <typename Sample>
void updateSourceSequence(Sample &destination, uint8_t newSequence) {
  // SH-2 raw sequence values are scoped by report stream in the adapter
  // contract.  Do not compare an accelerometer value with a linear-
  // acceleration/gyro/orientation value: the report IDs have independent
  // cadence and their raw bytes are not one shared +1 counter.
  if (destination.haveSourceSequence) {
    const uint8_t expected =
        static_cast<uint8_t>(destination.previousSourceSequence + 1);

    if (newSequence != expected) {
      ++destination.sequenceGapCount;
    }
  }

  destination.previousSourceSequence = newSequence;
  destination.haveSourceSequence = true;
}

uint32_t aggregateSequenceGapCount() {
  const uint64_t total =
      static_cast<uint64_t>(accelerometer.sequenceGapCount) +
      static_cast<uint64_t>(linearAcceleration.sequenceGapCount) +
      static_cast<uint64_t>(gyroscope.sequenceGapCount) +
      static_cast<uint64_t>(orientation.sequenceGapCount);

  // Keep the wire field a uint32 even if a very long run exhausts the
  // individual counters.  This value is diagnostic only; stream counters
  // remain the authoritative gate inputs on the Linux side.
  return total > 0xFFFFFFFFULL
             ? 0xFFFFFFFFUL
             : static_cast<uint32_t>(total);
}

void cacheVectorSample(
    VectorSample &destination,
    float x,
    float y,
    float z,
    const sh2_SensorValue_t &value) {
  const bool finite = vectorIsFinite(x, y, z);

  updateSourceSequence(destination, value.sequence);
  destination.accuracy = value.status & 0x03;
  destination.sourceSequence = value.sequence;
  destination.timestampUs = value.timestamp;
  destination.lastSampleMillis = millis();
  destination.finite = finite;
  ++destination.count;
  destination.sampleSequence = destination.count;

  if (!finite) {
    destination.haveSample = true;
    lastError = "vector_not_finite";
    return;
  }

  // 只有有限数值才覆盖缓存，确保RPC始终生成合法JSON；若本帧异常，
  // valid会变为false，但仍保留上一帧可供诊断的数值。
  destination.rawX = x;
  destination.rawY = y;
  destination.rawZ = z;

  if (!destination.haveSample) {
    // 第一帧直接作为滤波器初值，避免从0慢慢爬升。
    destination.filteredX = x;
    destination.filteredY = y;
    destination.filteredZ = z;
  } else {
    destination.filteredX +=
        kDisplayFilterAlpha * (x - destination.filteredX);
    destination.filteredY +=
        kDisplayFilterAlpha * (y - destination.filteredY);
    destination.filteredZ +=
        kDisplayFilterAlpha * (z - destination.filteredZ);
  }

  destination.haveSample = true;
  lastError = "none";
}

void cacheAccelerometer(const sh2_SensorValue_t &value) {
  const sh2_Accelerometer_t &data = value.un.accelerometer;
  cacheVectorSample(
      accelerometer,
      data.x,
      data.y,
      data.z,
      value);
}

void cacheLinearAcceleration(const sh2_SensorValue_t &value) {
  const sh2_Accelerometer_t &data = value.un.linearAcceleration;
  cacheVectorSample(
      linearAcceleration,
      data.x,
      data.y,
      data.z,
      value);
}

void cacheGyroscope(const sh2_SensorValue_t &value) {
  const sh2_Gyroscope_t &data = value.un.gyroscope;
  cacheVectorSample(
      gyroscope,
      data.x,
      data.y,
      data.z,
      value);
}

void cacheOrientation(const sh2_SensorValue_t &value) {
  const sh2_RotationVector_t &rotation =
      value.un.gameRotationVector;

  float x = rotation.i;
  float y = rotation.j;
  float z = rotation.k;
  float w = rotation.real;

  updateSourceSequence(orientation, value.sequence);
  orientation.accuracy = value.status & 0x03;
  orientation.sourceSequence = value.sequence;
  orientation.timestampUs = value.timestamp;
  orientation.lastSampleMillis = millis();
  ++orientation.count;
  orientation.sampleSequence = orientation.count;

  if (!isfinite(x) || !isfinite(y) ||
      !isfinite(z) || !isfinite(w)) {
    orientation.haveSample = true;
    orientation.finite = false;
    lastError = "quaternion_not_finite";
    return;
  }

  const float normSquared =
      x * x + y * y + z * z + w * w;

  if (!isfinite(normSquared) ||
      normSquared < 0.25F ||
      normSquared > 2.25F) {
    orientation.haveSample = true;
    orientation.finite = false;
    lastError = "quaternion_norm_invalid";
    return;
  }

  const float norm = sqrtf(normSquared);
  orientation.normBeforeNormalize = norm;

  x /= norm;
  y /= norm;
  z /= norm;
  w /= norm;

  // q与-q是同一个姿态。保持符号连续可以避免显示无意义地跳变。
  if (orientation.haveSample && orientation.finite) {
    const float dot =
        orientation.x * x +
        orientation.y * y +
        orientation.z * z +
        orientation.w * w;

    if (dot < 0.0F) {
      x = -x;
      y = -y;
      z = -z;
      w = -w;
    }
  }

  orientation.x = x;
  orientation.y = y;
  orientation.z = z;
  orientation.w = w;
  orientation.haveSample = true;
  orientation.finite = true;
  lastError = "none";
}

void serviceBno086() {
  if (!imuReady) {
    return;
  }

  // BNO086复位后，芯片会忘记已启用的报告，必须重新设置。
  if (imu.wasReset()) {
    ++resetCount;
    clearLiveSamplesAfterReset();

    if (!enableReports()) {
      imuReady = false;
      lastError = "report_reenable_failed";
    } else {
      lastError = "sensor_reset_recovered";
    }

    return;
  }

  // 只在进入drain前检查一次低有效INT，避免空FIFO时进入可能等待的读取。
  // 一旦进入，连续取事件直到驱动报告没有更多事件或达到上限；不在每个
  // 事件之间重新读取INT，以免在FIFO drain期间制造竞态。
  if (digitalRead(kInterruptPin) != LOW) {
    return;
  }

  for (uint8_t eventIndex = 0; eventIndex < kMaxEventsPerUpdate; ++eventIndex) {
    if (!imu.getSensorEvent(&sensorValue)) {
      break;
    }

    switch (sensorValue.sensorId) {
      case SH2_ACCELEROMETER:
        cacheAccelerometer(sensorValue);
        break;

      case SH2_LINEAR_ACCELERATION:
        cacheLinearAcceleration(sensorValue);
        break;

      case SH2_GYROSCOPE_CALIBRATED:
        cacheGyroscope(sensorValue);
        break;

      case SH2_GAME_ROTATION_VECTOR:
        cacheOrientation(sensorValue);
        break;

      default:
        ++unknownReportCount;
        break;
    }
  }
}

bool isStale(bool haveSample, uint32_t lastSampleMillis) {
  if (!haveSample) {
    return true;
  }

  return static_cast<uint32_t>(millis() - lastSampleMillis) >
         kStaleTimeoutMs;
}

bool vectorIsValid(const VectorSample &sample) {
  return sample.haveSample &&
         sample.finite &&
         sample.accuracy != 0 &&
         !isStale(sample.haveSample, sample.lastSampleMillis);
}

bool orientationIsValid() {
  return orientation.haveSample &&
         orientation.finite &&
         orientation.accuracy != 0 &&
         !isStale(
             orientation.haveSample,
             orientation.lastSampleMillis);
}

void appendBoolean(String &response, bool value) {
  response += value ? "true" : "false";
}

void appendTimestamp(String &response, uint64_t timestampUs) {
  char timestampText[24];
  snprintf(
      timestampText,
      sizeof(timestampText),
      "%llu",
      static_cast<unsigned long long>(timestampUs));
  response += timestampText;
}

void appendVectorJson(
    String &response,
    const VectorSample &sample,
    const char *unit) {
  const bool stale =
      isStale(sample.haveSample, sample.lastSampleMillis);

  response += "{\"valid\":";
  appendBoolean(response, vectorIsValid(sample));

  response += ",\"stale\":";
  appendBoolean(response, stale);

  response += ",\"accuracy\":";
  response += static_cast<unsigned int>(sample.accuracy);

  response += ",\"seq\":";
  response += static_cast<unsigned long>(sample.sampleSequence);

  response += ",\"sample_seq\":";
  response += static_cast<unsigned long>(sample.sampleSequence);

  response += ",\"sensor_seq\":";
  response += static_cast<unsigned int>(sample.sourceSequence);

  response += ",\"sensor_time_us\":";
  appendTimestamp(response, sample.timestampUs);

  response += ",\"unit\":\"";
  response += unit;
  response += "\"";

  response += ",\"raw\":{\"x\":";
  response += String(sample.rawX, 7);
  response += ",\"y\":";
  response += String(sample.rawY, 7);
  response += ",\"z\":";
  response += String(sample.rawZ, 7);
  response += "}";

  response += ",\"filtered\":{\"x\":";
  response += String(sample.filteredX, 7);
  response += ",\"y\":";
  response += String(sample.filteredY, 7);
  response += ",\"z\":";
  response += String(sample.filteredZ, 7);
  response += "}";

  response += ",\"count\":";
  response += static_cast<unsigned long>(sample.count);

  response += ",\"sequence_gap_count\":";
  response += static_cast<unsigned long>(sample.sequenceGapCount);
  response += "}";
}

String getImuStatusJson() {
  String response;
  response.reserve(1200);

  response += "{\"bridge_ready\":";
  appendBoolean(response, bridgeReady);

  response += ",\"api_ready\":";
  appendBoolean(response, apiReady);

  response += ",\"imu_ready\":";
  appendBoolean(response, imuReady);

  response += ",\"reports\":{\"all_ready\":";
  appendBoolean(response, allReportsReady);
  response += ",\"accelerometer_ready\":";
  appendBoolean(response, accelerometerReportReady);
  response += ",\"linear_acceleration_ready\":";
  appendBoolean(response, linearAccelerationReportReady);
  response += ",\"gyroscope_ready\":";
  appendBoolean(response, gyroscopeReportReady);
  response += ",\"orientation_ready\":";
  appendBoolean(response, orientationReportReady);
  response += "}";

  response += ",\"bus\":\"Wire/I2C4\"";
  response += ",\"address\":\"";
  if (detectedAddress == kPrimaryAddress) {
    response += "0x4B";
  } else if (detectedAddress == kAlternateAddress) {
    response += "0x4A";
  } else {
    response += "none";
  }
  response += "\"";

  response += ",\"i2c_clock_hz\":";
  response += static_cast<unsigned long>(kI2cClockHz);

  response += ",\"interval_us\":{\"accelerometer\":";
  response += static_cast<unsigned long>(kAccelerometerIntervalUs);
  response += ",\"linear_acceleration\":";
  response += static_cast<unsigned long>(kLinearAccelerationIntervalUs);
  response += ",\"gyroscope\":";
  response += static_cast<unsigned long>(kGyroscopeIntervalUs);
  response += ",\"orientation\":";
  response += static_cast<unsigned long>(kOrientationIntervalUs);
  response += "}";

  response += ",\"display_filter_alpha\":";
  response += String(kDisplayFilterAlpha, 2);

  response += ",\"pins\":{\"int\":2,\"int_level\":";
  response += digitalRead(kInterruptPin);
  response += ",\"reset\":3,\"reset_level\":";
  response += digitalRead(kResetPin);
  response += "}";

  response += ",\"product_entries\":";
  response += static_cast<unsigned int>(productEntries);

  response += ",\"software_version\":\"";
  response += static_cast<unsigned int>(softwareMajor);
  response += ".";
  response += static_cast<unsigned int>(softwareMinor);
  response += ".";
  response += static_cast<unsigned int>(softwarePatch);
  response += "\"";

  response += ",\"part_number\":";
  response += static_cast<unsigned long>(partNumber);
  response += ",\"build_number\":";
  response += static_cast<unsigned long>(buildNumber);

  response += ",\"counts\":{\"accelerometer\":";
  response += static_cast<unsigned long>(accelerometer.count);
  response += ",\"linear_acceleration\":";
  response += static_cast<unsigned long>(linearAcceleration.count);
  response += ",\"gyroscope\":";
  response += static_cast<unsigned long>(gyroscope.count);
  response += ",\"orientation\":";
  response += static_cast<unsigned long>(orientation.count);
  response += ",\"unknown\":";
  response += static_cast<unsigned long>(unknownReportCount);
  response += "}";

  response += ",\"sequence_gaps\":{\"accelerometer\":";
  response += static_cast<unsigned long>(accelerometer.sequenceGapCount);
  response += ",\"linear_acceleration\":";
  response += static_cast<unsigned long>(linearAcceleration.sequenceGapCount);
  response += ",\"gyroscope\":";
  response += static_cast<unsigned long>(gyroscope.sequenceGapCount);
  response += ",\"orientation\":";
  response += static_cast<unsigned long>(orientation.sequenceGapCount);
  response += "}";

  response += ",\"source_sequence_gap_count\":";
  response += static_cast<unsigned long>(aggregateSequenceGapCount());

  response += ",\"reset_count\":";
  response += static_cast<unsigned long>(resetCount);

  response += ",\"last_error\":\"";
  response += lastError;
  response += "\"}";

  return response;
}

String getImuSampleJson() {
  String response;
  response.reserve(1800);

  response += "{\"accelerometer\":";
  appendVectorJson(
      response,
      accelerometer,
      "m/s^2");

  response += ",\"linear_acceleration\":";
  appendVectorJson(
      response,
      linearAcceleration,
      "m/s^2");

  response += ",\"gyroscope\":";
  appendVectorJson(
      response,
      gyroscope,
      "rad/s");

  const bool orientationStale = isStale(
      orientation.haveSample,
      orientation.lastSampleMillis);

  response += ",\"orientation\":{\"valid\":";
  appendBoolean(response, orientationIsValid());

  response += ",\"stale\":";
  appendBoolean(response, orientationStale);

  response += ",\"mode\":\"game_rotation_vector\"";
  response += ",\"accuracy\":";
  response += static_cast<unsigned int>(orientation.accuracy);

  response += ",\"seq\":";
  response += static_cast<unsigned long>(orientation.sampleSequence);

  response += ",\"sample_seq\":";
  response += static_cast<unsigned long>(orientation.sampleSequence);

  response += ",\"sensor_seq\":";
  response += static_cast<unsigned int>(orientation.sourceSequence);

  response += ",\"sensor_time_us\":";
  appendTimestamp(response, orientation.timestampUs);

  response += ",\"quaternion\":{\"x\":";
  response += String(orientation.x, 7);
  response += ",\"y\":";
  response += String(orientation.y, 7);
  response += ",\"z\":";
  response += String(orientation.z, 7);
  response += ",\"w\":";
  response += String(orientation.w, 7);
  response += "}";

  response += ",\"norm_before_normalize\":";
  response += String(orientation.normBeforeNormalize, 7);

  response += ",\"count\":";
  response += static_cast<unsigned long>(orientation.count);

  response += ",\"sequence_gap_count\":";
  response += static_cast<unsigned long>(orientation.sequenceGapCount);

  response += "},\"reset_count\":";
  response += static_cast<unsigned long>(resetCount);
  response += ",\"source_sequence_gap_count\":";
  response += static_cast<unsigned long>(aggregateSequenceGapCount());
  response += "}";

  return response;
}

}  // namespace

namespace Bno086Imu {

bool begin() {
  return initializeBno086();
}

bool provideRpc(bool bridgeStarted) {
  bridgeReady = bridgeStarted;
  if (!bridgeStarted) {
    apiReady = false;
    return false;
  }

  // safe回调在Arduino主循环上下文执行，避免RPC线程与采样代码
  // 同时读写同一组数据。每个名称独立记录，失败的注册可重试。
  if (!statusRpcReady) {
    statusRpcReady = Bridge.provide_safe(
        "imu_get_status",
        getImuStatusJson);
  }

  if (!sampleRpcReady) {
    sampleRpcReady = Bridge.provide_safe(
        "imu_get_sample",
        getImuSampleJson);
  }

  apiReady = statusRpcReady && sampleRpcReady;
  return apiReady;
}

void update() {
  serviceBno086();
}

String sampleJson() {
  return getImuSampleJson();
}

String statusJson() {
  return getImuStatusJson();
}

}  // namespace Bno086Imu
