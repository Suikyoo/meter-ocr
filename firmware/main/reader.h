#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "config.h"

// Must match training/common.py.
constexpr int kImgW = 20;
constexpr int kImgH = 32;
constexpr int kMinRange = 80;
constexpr int kNumClasses = 12;
constexpr int kBlank = 10;
constexpr int kUnsure = 11;

struct DigitResult {
  int cls = kUnsure;
  float conf = 0;
  uint8_t pixels[kImgW * kImgH];  // normalized crop from the last frame, for data collection
};

struct Reading {
  bool ok = false;
  // ok, reset (implausible value confirmed repeatedly), capture_failed, not_configured,
  // low_confidence, invalid, went_backwards, rate_exceeded
  std::string status = "not_configured";
  std::string raw;  // one char per digit: 0-9, '_' blank, '?' unsure
  double value = 0;
  float min_conf = 0;
  int dx = 0, dy = 0;  // alignment offset applied
  int64_t time_us = 0;
  std::vector<DigitResult> digits;
};

bool reader_init();
Reading reader_read(const MeterConfig &cfg);

// Forget the last accepted value, e.g. after the digit layout changed. Thread-safe.
void reader_reset_history();

// Copies a w x h patch from the current frame into cfg.anchor_pixels.
bool reader_capture_anchor(MeterConfig &cfg);

std::string reading_to_json(const Reading &r, bool with_crops);
