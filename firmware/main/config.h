#pragma once

#include <cstdint>
#include <string>
#include <vector>

struct Rect {
  int x = 0, y = 0, w = 0, h = 0;
};

// Per-install settings, edited from the setup page and stored in NVS.
struct MeterConfig {
  bool led_display = false;           // self-lit LED/backlit display: no flash
  std::vector<Rect> digits;           // most significant digit first
  int decimals = 0;                   // digits after the decimal point
  Rect anchor;                        // w == 0 disables alignment
  std::vector<uint8_t> anchor_pixels; // anchor.w * anchor.h grayscale, captured on save
  float max_rate_per_hour = 0;        // 0 disables the rate check
  float min_confidence = 0.8f;
  int interval_s = 60;
};

bool config_load(MeterConfig &cfg);
bool config_save(const MeterConfig &cfg);

std::string config_to_json(const MeterConfig &cfg);
// Parses everything except anchor_pixels, which is left unchanged.
bool config_from_json(const char *json, MeterConfig &cfg);

// Last accepted raw reading, kept across reboots for the monotonic check.
bool state_load_last(int64_t &raw);
void state_save_last(int64_t raw);
