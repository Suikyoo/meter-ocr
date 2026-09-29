#include "net.h"

#include <cstring>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "mqtt_client.h"

static const char *TAG = "net";
static EventGroupHandle_t s_events;
static constexpr EventBits_t kGotIp = BIT0;
static esp_mqtt_client_handle_t s_mqtt;

static void on_wifi_event(void *, esp_event_base_t base, int32_t id, void *data) {
  if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
    esp_wifi_connect();
  } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
    ESP_LOGW(TAG, "disconnected, retrying");
    xEventGroupClearBits(s_events, kGotIp);
    esp_wifi_connect();
  } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
    auto *event = (ip_event_got_ip_t *)data;
    ESP_LOGI(TAG, "setup page: http://" IPSTR "/", IP2STR(&event->ip_info.ip));
    xEventGroupSetBits(s_events, kGotIp);
  }
}

void wifi_connect() {
  s_events = xEventGroupCreate();
  ESP_ERROR_CHECK(esp_netif_init());
  ESP_ERROR_CHECK(esp_event_loop_create_default());
  esp_netif_create_default_wifi_sta();

  wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
  ESP_ERROR_CHECK(esp_wifi_init(&init));
  ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_wifi_event, nullptr));
  ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_wifi_event, nullptr));

  wifi_config_t cfg = {};
  strncpy((char *)cfg.sta.ssid, CONFIG_METER_WIFI_SSID, sizeof(cfg.sta.ssid));
  strncpy((char *)cfg.sta.password, CONFIG_METER_WIFI_PASSWORD, sizeof(cfg.sta.password));
  ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
  ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &cfg));
  ESP_ERROR_CHECK(esp_wifi_start());

  xEventGroupWaitBits(s_events, kGotIp, pdFALSE, pdTRUE, portMAX_DELAY);
}

void mqtt_start() {
  if (strlen(CONFIG_METER_MQTT_URI) == 0) return;
  esp_mqtt_client_config_t cfg = {};
  cfg.broker.address.uri = CONFIG_METER_MQTT_URI;
  s_mqtt = esp_mqtt_client_init(&cfg);
  esp_mqtt_client_start(s_mqtt);
}

void mqtt_publish(const std::string &payload) {
  if (!s_mqtt) return;
  esp_mqtt_client_publish(s_mqtt, CONFIG_METER_MQTT_TOPIC, payload.c_str(), payload.size(), 1, 0);
}
