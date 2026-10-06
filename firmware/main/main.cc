#include <mutex>

#include "app.h"
#include "camera.h"
#include "esp_log.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "net.h"
#include "nvs_flash.h"
#include "web.h"

static const char *TAG = "main";

static std::mutex s_mutex;
static MeterConfig s_config;
static Reading s_last;

MeterConfig app_config() {
  std::lock_guard<std::mutex> lock(s_mutex);
  return s_config;
}

void app_set_config(const MeterConfig &cfg) {
  std::lock_guard<std::mutex> lock(s_mutex);
  s_config = cfg;
}

Reading app_last_reading() {
  std::lock_guard<std::mutex> lock(s_mutex);
  return s_last;
}

static void reading_task(void *) {
  while (true) {
    MeterConfig cfg = app_config();
    if (cfg.digits.empty()) {
      ESP_LOGI(TAG, "no digit boxes configured yet, open the setup page");
      vTaskDelay(pdMS_TO_TICKS(10000));
      continue;
    }
    Reading r = reader_read(cfg);
    ESP_LOGI(TAG, "%s raw=%s value=%.3f min_conf=%.2f offset=(%d,%d)", r.status.c_str(),
             r.raw.c_str(), r.value, r.min_conf, r.dx, r.dy);
    mqtt_publish_reading(reading_to_json(r, false));
    {
      std::lock_guard<std::mutex> lock(s_mutex);
      s_last = std::move(r);
    }
    vTaskDelay(pdMS_TO_TICKS(cfg.interval_s * 1000));
  }
}

extern "C" void app_main() {
  esp_err_t err = nvs_flash_init();
  if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
    ESP_ERROR_CHECK(nvs_flash_erase());
    err = nvs_flash_init();
  }
  ESP_ERROR_CHECK(err);

  config_load(s_config);
  if (!camera_init() || !reader_init()) {
    ESP_LOGE(TAG, "startup failed, restarting in 10 s");
    vTaskDelay(pdMS_TO_TICKS(10000));
    esp_restart();
  }

  wifi_connect();
  mqtt_start();
  web_start();

  xTaskCreatePinnedToCore(reading_task, "reading", 8192, nullptr, 5, nullptr, 1);
}
