#include "camera.h"

#include "driver/gpio.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

static const char *TAG = "camera";
static SemaphoreHandle_t s_lock;

// Pinout of the ESP32-S3-EYE and the Freenove ESP32-S3-WROOM CAM board.
// Check your board's schematic and change these if it differs.
static camera_config_t camera_config() {
  camera_config_t c = {};
  c.pin_pwdn = -1;
  c.pin_reset = -1;
  c.pin_xclk = 15;
  c.pin_sccb_sda = 4;
  c.pin_sccb_scl = 5;
  c.pin_d7 = 16;
  c.pin_d6 = 17;
  c.pin_d5 = 18;
  c.pin_d4 = 12;
  c.pin_d3 = 10;
  c.pin_d2 = 8;
  c.pin_d1 = 9;
  c.pin_d0 = 11;
  c.pin_vsync = 6;
  c.pin_href = 7;
  c.pin_pclk = 13;
  c.xclk_freq_hz = 20000000;
  c.ledc_timer = LEDC_TIMER_0;
  c.ledc_channel = LEDC_CHANNEL_0;
  // Raw grayscale avoids JPEG decoding. SVGA gives digits enough pixels in most mounts.
  c.pixel_format = PIXFORMAT_GRAYSCALE;
  c.frame_size = FRAMESIZE_SVGA;
  c.fb_count = 2;
  c.fb_location = CAMERA_FB_IN_PSRAM;
  c.grab_mode = CAMERA_GRAB_LATEST;
  return c;
}

bool camera_init() {
  s_lock = xSemaphoreCreateMutex();
  if (CONFIG_METER_FLASH_GPIO >= 0) {
    gpio_reset_pin((gpio_num_t)CONFIG_METER_FLASH_GPIO);
    gpio_set_direction((gpio_num_t)CONFIG_METER_FLASH_GPIO, GPIO_MODE_OUTPUT);
    gpio_set_level((gpio_num_t)CONFIG_METER_FLASH_GPIO, 0);
  }
  camera_config_t cfg = camera_config();
  esp_err_t err = esp_camera_init(&cfg);
  if (err != ESP_OK) {
    ESP_LOGE(TAG, "init failed: %s", esp_err_to_name(err));
    return false;
  }
  return true;
}

camera_fb_t *camera_capture(bool flash) {
  xSemaphoreTake(s_lock, portMAX_DELAY);
  bool use_flash = flash && CONFIG_METER_FLASH_GPIO >= 0;
  if (use_flash) {
    gpio_set_level((gpio_num_t)CONFIG_METER_FLASH_GPIO, 1);
    vTaskDelay(pdMS_TO_TICKS(150));
  }
  // The buffered frame may predate the flash; drop it and take the next one.
  camera_fb_t *fb = esp_camera_fb_get();
  if (fb) esp_camera_fb_return(fb);
  fb = esp_camera_fb_get();
  if (use_flash) gpio_set_level((gpio_num_t)CONFIG_METER_FLASH_GPIO, 0);
  if (!fb) {
    ESP_LOGE(TAG, "capture failed");
    xSemaphoreGive(s_lock);
  }
  return fb;
}

void camera_release(camera_fb_t *fb) {
  esp_camera_fb_return(fb);
  xSemaphoreGive(s_lock);
}
