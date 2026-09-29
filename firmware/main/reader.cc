#include "reader.h"

#include <algorithm>
#include <atomic>
#include <climits>
#include <cmath>
#include <cstdlib>
#include <cstring>

#include "camera.h"
#include "cJSON.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "mbedtls/base64.h"
#include "model_data.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"

static const char *TAG = "reader";

constexpr int kFrames = 3;           // frames voted per reading
constexpr int kFrameGapMs = 200;     // spreads frames over LCD refresh / multiplexing
constexpr int kAlignRadius = 16;     // max anchor drift searched, pixels
constexpr int kConfirmCount = 5;     // repeats needed to accept an implausible value
constexpr int kArenaSize = 64 * 1024;

static uint8_t *s_arena;
static tflite::MicroInterpreter *s_interp;

// Plausibility state.
static bool s_have_last;
static int64_t s_last_raw;
static int64_t s_last_time_us;  // 0 = unknown (e.g. value restored after reboot)
static int64_t s_candidate_raw = -1;
static int s_candidate_count;
static std::atomic<bool> s_reset_requested;

void reader_reset_history() { s_reset_requested = true; }

bool reader_init() {
  const tflite::Model *model = tflite::GetModel(g_model_data);
  if (model->version() != TFLITE_SCHEMA_VERSION) {
    ESP_LOGE(TAG, "model schema %lu != %d", (unsigned long)model->version(), TFLITE_SCHEMA_VERSION);
    return false;
  }
  static tflite::MicroMutableOpResolver<5> resolver;
  resolver.AddConv2D();
  resolver.AddMaxPool2D();
  resolver.AddReshape();
  resolver.AddFullyConnected();
  resolver.AddSoftmax();

  // Internal RAM is much faster than PSRAM for the tensor arena.
  s_arena = (uint8_t *)heap_caps_aligned_alloc(16, kArenaSize, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
  if (!s_arena) return false;
  s_interp = new tflite::MicroInterpreter(model, resolver, s_arena, kArenaSize);
  if (s_interp->AllocateTensors() != kTfLiteOk) {
    ESP_LOGE(TAG, "AllocateTensors failed");
    return false;
  }
  ESP_LOGI(TAG, "model %u bytes, arena used %u", g_model_data_len, (unsigned)s_interp->arena_used_bytes());

  s_have_last = state_load_last(s_last_raw);
  return true;
}

// Best offset of the stored anchor patch within +-kAlignRadius, by sum of absolute differences.
static void align(const camera_fb_t *fb, const MeterConfig &cfg, int &dx, int &dy) {
  dx = dy = 0;
  const Rect &a = cfg.anchor;
  if (a.w == 0 || cfg.anchor_pixels.size() != (size_t)(a.w * a.h)) return;
  uint32_t best = UINT32_MAX;
  for (int oy = -kAlignRadius; oy <= kAlignRadius; oy++) {
    for (int ox = -kAlignRadius; ox <= kAlignRadius; ox++) {
      int x0 = a.x + ox, y0 = a.y + oy;
      if (x0 < 0 || y0 < 0 || x0 + a.w > (int)fb->width || y0 + a.h > (int)fb->height) continue;
      uint32_t sad = 0;
      // Every second row and column is enough and 4x cheaper.
      for (int y = 0; y < a.h && sad < best; y += 2) {
        const uint8_t *src = fb->buf + (y0 + y) * fb->width + x0;
        const uint8_t *ref = cfg.anchor_pixels.data() + y * a.w;
        for (int x = 0; x < a.w; x += 2) sad += abs(src[x] - ref[x]);
      }
      if (sad < best) {
        best = sad;
        dx = ox;
        dy = oy;
      }
    }
  }
}

// Area-average resize to kImgW x kImgH, then the contrast stretch from training/common.py.
static void crop_normalize(const camera_fb_t *fb, Rect r, int dx, int dy, uint8_t *out) {
  const int fw = fb->width, fh = fb->height;
  r.x = std::clamp(r.x + dx, 0, fw - 1);
  r.y = std::clamp(r.y + dy, 0, fh - 1);
  r.w = std::clamp(r.w, 1, fw - r.x);
  r.h = std::clamp(r.h, 1, fh - r.y);

  for (int oy = 0; oy < kImgH; oy++) {
    int y0 = r.y + oy * r.h / kImgH;
    int y1 = std::max(y0 + 1, r.y + (oy + 1) * r.h / kImgH);
    for (int ox = 0; ox < kImgW; ox++) {
      int x0 = r.x + ox * r.w / kImgW;
      int x1 = std::max(x0 + 1, r.x + (ox + 1) * r.w / kImgW);
      uint32_t sum = 0;
      for (int y = y0; y < y1; y++) {
        const uint8_t *row = fb->buf + y * fw;
        for (int x = x0; x < x1; x++) sum += row[x];
      }
      out[oy * kImgW + ox] = sum / ((y1 - y0) * (x1 - x0));
    }
  }

  int lo = 255, hi = 0;
  for (int i = 0; i < kImgW * kImgH; i++) {
    lo = std::min<int>(lo, out[i]);
    hi = std::max<int>(hi, out[i]);
  }
  int range = std::max(hi - lo, kMinRange);
  for (int i = 0; i < kImgW * kImgH; i++) out[i] = std::min(255, (out[i] - lo) * 255 / range);
}

static void classify(const uint8_t *pixels, float *probs) {
  TfLiteTensor *in = s_interp->input(0);
  const float in_scale = in->params.scale;
  const int in_zp = in->params.zero_point;
  for (int i = 0; i < kImgW * kImgH; i++) {
    int q = (int)lroundf(pixels[i] / 255.0f / in_scale) + in_zp;
    in->data.int8[i] = (int8_t)std::clamp(q, -128, 127);
  }
  if (s_interp->Invoke() != kTfLiteOk) {
    std::fill(probs, probs + kNumClasses, 0.0f);
    return;
  }
  TfLiteTensor *out = s_interp->output(0);
  for (int c = 0; c < kNumClasses; c++) {
    probs[c] = (out->data.int8[c] - out->params.zero_point) * out->params.scale;
  }
}

// Returns false (and sets status) if the digit sequence is not a valid number.
static bool parse(Reading &r, const MeterConfig &cfg, int64_t &raw_value) {
  raw_value = 0;
  bool seen_digit = false;
  for (const DigitResult &d : r.digits) {
    if (d.cls == kUnsure || d.conf < cfg.min_confidence) {
      r.status = "low_confidence";
      return false;
    }
    if (d.cls == kBlank) {
      // Blanks are only valid as leading digits.
      if (seen_digit) {
        r.status = "invalid";
        return false;
      }
      continue;
    }
    seen_digit = true;
    raw_value = raw_value * 10 + d.cls;
  }
  if (!seen_digit) {
    r.status = "invalid";
    return false;
  }
  return true;
}

static bool plausible(Reading &r, const MeterConfig &cfg, int64_t raw_value) {
  if (!s_have_last) return true;
  if (raw_value < s_last_raw) {
    r.status = "went_backwards";
    return false;
  }
  if (cfg.max_rate_per_hour > 0 && s_last_time_us > 0) {
    double hours = (r.time_us - s_last_time_us) / 3.6e9;
    double delta = (raw_value - s_last_raw) / std::pow(10.0, cfg.decimals);
    // Allow at least one least-significant step so tiny intervals do not reject everything.
    double allowed = std::max(cfg.max_rate_per_hour * hours, 1.0 / std::pow(10.0, cfg.decimals));
    if (delta > allowed) {
      r.status = "rate_exceeded";
      return false;
    }
  }
  return true;
}

Reading reader_read(const MeterConfig &cfg) {
  Reading r;
  r.time_us = esp_timer_get_time();
  if (s_reset_requested.exchange(false)) {
    s_have_last = false;
    s_last_time_us = 0;
    s_candidate_raw = -1;
    s_candidate_count = 0;
  }
  if (cfg.digits.empty() || !s_interp) return r;

  const size_t n = cfg.digits.size();
  r.digits.resize(n);
  std::vector<float> sums(n * kNumClasses, 0.0f);
  float probs[kNumClasses];
  int frames = 0;

  for (int f = 0; f < kFrames; f++) {
    if (f > 0) vTaskDelay(pdMS_TO_TICKS(kFrameGapMs));
    camera_fb_t *fb = camera_capture(!cfg.led_display);
    if (!fb) continue;
    align(fb, cfg, r.dx, r.dy);
    for (size_t i = 0; i < n; i++) {
      crop_normalize(fb, cfg.digits[i], r.dx, r.dy, r.digits[i].pixels);
      classify(r.digits[i].pixels, probs);
      for (int c = 0; c < kNumClasses; c++) sums[i * kNumClasses + c] += probs[c];
    }
    camera_release(fb);
    frames++;
  }
  if (frames == 0) {
    r.status = "capture_failed";
    return r;
  }

  r.min_conf = 1.0f;
  for (size_t i = 0; i < n; i++) {
    const float *s = &sums[i * kNumClasses];
    int best = std::max_element(s, s + kNumClasses) - s;
    r.digits[i].cls = best;
    r.digits[i].conf = s[best] / frames;
    r.min_conf = std::min(r.min_conf, r.digits[i].conf);
    r.raw += best < 10 ? char('0' + best) : (best == kBlank ? '_' : '?');
  }

  int64_t raw_value;
  if (!parse(r, cfg, raw_value)) return r;
  r.value = raw_value / std::pow(10.0, cfg.decimals);

  if (plausible(r, cfg, raw_value)) {
    r.status = "ok";
  } else {
    // A value that keeps coming back is probably real (meter swapped, or a bad earlier
    // reading was accepted). Accept it after kConfirmCount identical readings.
    s_candidate_count = raw_value == s_candidate_raw ? s_candidate_count + 1 : 1;
    s_candidate_raw = raw_value;
    if (s_candidate_count < kConfirmCount) return r;
    r.status = "reset";
  }

  r.ok = true;
  s_candidate_raw = -1;
  s_candidate_count = 0;
  if (!s_have_last || raw_value != s_last_raw) state_save_last(raw_value);
  s_have_last = true;
  s_last_raw = raw_value;
  s_last_time_us = r.time_us;
  return r;
}

bool reader_capture_anchor(MeterConfig &cfg) {
  const Rect &a = cfg.anchor;
  cfg.anchor_pixels.clear();
  if (a.w == 0) return true;
  camera_fb_t *fb = camera_capture(!cfg.led_display);
  if (!fb) return false;
  bool ok = a.x + a.w <= (int)fb->width && a.y + a.h <= (int)fb->height;
  if (ok) {
    cfg.anchor_pixels.resize(a.w * a.h);
    for (int y = 0; y < a.h; y++) {
      memcpy(cfg.anchor_pixels.data() + y * a.w, fb->buf + (a.y + y) * fb->width + a.x, a.w);
    }
  }
  camera_release(fb);
  return ok;
}

std::string reading_to_json(const Reading &r, bool with_crops) {
  cJSON *root = cJSON_CreateObject();
  cJSON_AddBoolToObject(root, "ok", r.ok);
  cJSON_AddStringToObject(root, "status", r.status.c_str());
  cJSON_AddStringToObject(root, "raw", r.raw.c_str());
  if (r.ok) cJSON_AddNumberToObject(root, "value", r.value);
  cJSON_AddNumberToObject(root, "min_conf", r.min_conf);
  cJSON_AddNumberToObject(root, "dx", r.dx);
  cJSON_AddNumberToObject(root, "dy", r.dy);
  cJSON_AddNumberToObject(root, "uptime_s", r.time_us / 1000000);
  if (with_crops) {
    cJSON *digits = cJSON_AddArrayToObject(root, "digits");
    unsigned char b64[((kImgW * kImgH + 2) / 3) * 4 + 1];
    for (const DigitResult &d : r.digits) {
      size_t len = 0;
      mbedtls_base64_encode(b64, sizeof(b64), &len, d.pixels, sizeof(d.pixels));
      b64[len] = 0;
      cJSON *o = cJSON_CreateObject();
      cJSON_AddNumberToObject(o, "cls", d.cls);
      cJSON_AddNumberToObject(o, "conf", d.conf);
      cJSON_AddStringToObject(o, "pixels", (const char *)b64);
      cJSON_AddItemToArray(digits, o);
    }
    cJSON_AddNumberToObject(root, "width", kImgW);
    cJSON_AddNumberToObject(root, "height", kImgH);
  }
  char *s = cJSON_PrintUnformatted(root);
  std::string out(s);
  cJSON_free(s);
  cJSON_Delete(root);
  return out;
}
