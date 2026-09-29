#include "config.h"

#include <cstdlib>

#include "cJSON.h"
#include "esp_log.h"
#include "nvs.h"

static const char *TAG = "config";
static const char *NS = "meter";

static cJSON *rect_to_json(const Rect &r) {
  cJSON *o = cJSON_CreateObject();
  cJSON_AddNumberToObject(o, "x", r.x);
  cJSON_AddNumberToObject(o, "y", r.y);
  cJSON_AddNumberToObject(o, "w", r.w);
  cJSON_AddNumberToObject(o, "h", r.h);
  return o;
}

static bool rect_from_json(const cJSON *o, Rect &r) {
  if (!cJSON_IsObject(o)) return false;
  const char *keys[] = {"x", "y", "w", "h"};
  int *vals[] = {&r.x, &r.y, &r.w, &r.h};
  for (int i = 0; i < 4; i++) {
    const cJSON *v = cJSON_GetObjectItem(o, keys[i]);
    if (!cJSON_IsNumber(v) || v->valueint < 0) return false;
    *vals[i] = v->valueint;
  }
  return true;
}

std::string config_to_json(const MeterConfig &cfg) {
  cJSON *root = cJSON_CreateObject();
  cJSON_AddStringToObject(root, "display", cfg.led_display ? "led" : "lcd");
  cJSON *digits = cJSON_AddArrayToObject(root, "digits");
  for (const Rect &r : cfg.digits) cJSON_AddItemToArray(digits, rect_to_json(r));
  cJSON_AddNumberToObject(root, "decimals", cfg.decimals);
  if (cfg.anchor.w > 0) {
    cJSON_AddItemToObject(root, "anchor", rect_to_json(cfg.anchor));
  } else {
    cJSON_AddNullToObject(root, "anchor");
  }
  cJSON_AddNumberToObject(root, "max_rate_per_hour", cfg.max_rate_per_hour);
  cJSON_AddNumberToObject(root, "min_confidence", cfg.min_confidence);
  cJSON_AddNumberToObject(root, "interval_s", cfg.interval_s);
  char *s = cJSON_PrintUnformatted(root);
  std::string out(s);
  cJSON_free(s);
  cJSON_Delete(root);
  return out;
}

bool config_from_json(const char *json, MeterConfig &cfg) {
  cJSON *root = cJSON_Parse(json);
  if (!root) return false;
  MeterConfig next = cfg;
  bool ok = true;

  const cJSON *display = cJSON_GetObjectItem(root, "display");
  if (cJSON_IsString(display)) next.led_display = std::string(display->valuestring) == "led";

  const cJSON *digits = cJSON_GetObjectItem(root, "digits");
  if (cJSON_IsArray(digits)) {
    next.digits.clear();
    const cJSON *d;
    cJSON_ArrayForEach(d, digits) {
      Rect r;
      if (!rect_from_json(d, r) || r.w < 4 || r.h < 4) ok = false;
      next.digits.push_back(r);
    }
    // More than 18 digits would overflow the int64 reading.
    if (next.digits.size() > 18) ok = false;
  }

  const cJSON *anchor = cJSON_GetObjectItem(root, "anchor");
  if (cJSON_IsNull(anchor)) {
    next.anchor = Rect{};
  } else if (anchor && !rect_from_json(anchor, next.anchor)) {
    ok = false;
  }

  const cJSON *v;
  if (cJSON_IsNumber(v = cJSON_GetObjectItem(root, "decimals"))) next.decimals = v->valueint;
  if (cJSON_IsNumber(v = cJSON_GetObjectItem(root, "max_rate_per_hour"))) next.max_rate_per_hour = v->valuedouble;
  if (cJSON_IsNumber(v = cJSON_GetObjectItem(root, "min_confidence"))) next.min_confidence = v->valuedouble;
  if (cJSON_IsNumber(v = cJSON_GetObjectItem(root, "interval_s"))) next.interval_s = v->valueint;
  cJSON_Delete(root);

  if (next.decimals < 0 || next.decimals > (int)next.digits.size()) ok = false;
  if (next.interval_s < 5) ok = false;
  if (!ok) return false;
  cfg = next;
  return true;
}

bool config_load(MeterConfig &cfg) {
  nvs_handle_t h;
  if (nvs_open(NS, NVS_READONLY, &h) != ESP_OK) return false;
  size_t len = 0;
  bool ok = false;
  if (nvs_get_str(h, "cfg", nullptr, &len) == ESP_OK) {
    std::string json(len, '\0');
    nvs_get_str(h, "cfg", json.data(), &len);
    ok = config_from_json(json.c_str(), cfg);
  }
  len = 0;
  if (ok && nvs_get_blob(h, "anchor", nullptr, &len) == ESP_OK &&
      len == (size_t)(cfg.anchor.w * cfg.anchor.h)) {
    cfg.anchor_pixels.resize(len);
    nvs_get_blob(h, "anchor", cfg.anchor_pixels.data(), &len);
  } else {
    cfg.anchor_pixels.clear();
  }
  nvs_close(h);
  if (!ok) ESP_LOGW(TAG, "no stored config");
  return ok;
}

bool config_save(const MeterConfig &cfg) {
  nvs_handle_t h;
  if (nvs_open(NS, NVS_READWRITE, &h) != ESP_OK) return false;
  esp_err_t err = nvs_set_str(h, "cfg", config_to_json(cfg).c_str());
  if (err == ESP_OK) {
    if (cfg.anchor_pixels.empty()) {
      nvs_erase_key(h, "anchor");
    } else {
      err = nvs_set_blob(h, "anchor", cfg.anchor_pixels.data(), cfg.anchor_pixels.size());
    }
  }
  if (err == ESP_OK) err = nvs_commit(h);
  nvs_close(h);
  if (err != ESP_OK) ESP_LOGE(TAG, "save failed: %s", esp_err_to_name(err));
  return err == ESP_OK;
}

bool state_load_last(int64_t &raw) {
  nvs_handle_t h;
  if (nvs_open(NS, NVS_READONLY, &h) != ESP_OK) return false;
  bool ok = nvs_get_i64(h, "last", &raw) == ESP_OK;
  nvs_close(h);
  return ok;
}

void state_save_last(int64_t raw) {
  nvs_handle_t h;
  if (nvs_open(NS, NVS_READWRITE, &h) != ESP_OK) return;
  nvs_set_i64(h, "last", raw);
  nvs_commit(h);
  nvs_close(h);
}
