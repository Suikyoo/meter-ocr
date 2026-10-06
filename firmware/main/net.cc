#include "net.h"

#include <cstdio>
#include <cstring>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "mqtt_client.h"

static const char *TAG = "net";
static EventGroupHandle_t s_events;
static constexpr EventBits_t kGotIp = BIT0;
static esp_mqtt_client_handle_t s_mqtt;
static char s_ip[16];
static std::string s_device_id;
static std::string s_status_topic;
static std::string s_reading_topic;
static const char kOfflineStatus[] = "{\"online\":false}";

static void on_wifi_event(void *, esp_event_base_t base, int32_t id, void *data) {
  if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
    esp_wifi_connect();
  } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
    ESP_LOGW(TAG, "disconnected, retrying");
    xEventGroupClearBits(s_events, kGotIp);
    esp_wifi_connect();
  } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
    auto *event = (ip_event_got_ip_t *)data;
    snprintf(s_ip, sizeof(s_ip), IPSTR, IP2STR(&event->ip_info.ip));
    ESP_LOGI(TAG, "setup page: http://%s/", s_ip);
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

static void on_mqtt_event(void *, esp_event_base_t, int32_t id, void *) {
  if (id == MQTT_EVENT_CONNECTED) {
    char status[64];
    snprintf(status, sizeof(status), "{\"online\":true,\"ip\":\"%s\"}", s_ip);
    esp_mqtt_client_publish(s_mqtt, s_status_topic.c_str(), status, 0, 1, 1);
    ESP_LOGI(TAG, "mqtt connected as %s", s_device_id.c_str());
  } else if (id == MQTT_EVENT_DISCONNECTED) {
    ESP_LOGW(TAG, "mqtt disconnected");
  }
}

void mqtt_start() {
  if (strlen(CONFIG_METER_MQTT_URI) == 0) return;

  uint8_t mac[6];
  esp_read_mac(mac, ESP_MAC_WIFI_STA);
  char id[20];
  snprintf(id, sizeof(id), "meter-%02x%02x%02x%02x%02x%02x", mac[0], mac[1], mac[2], mac[3],
           mac[4], mac[5]);
  s_device_id = id;
  std::string base = std::string(CONFIG_METER_MQTT_PREFIX) + "/" + s_device_id;
  s_status_topic = base + "/status";
  s_reading_topic = base + "/reading";

  esp_mqtt_client_config_t cfg = {};
  cfg.broker.address.uri = CONFIG_METER_MQTT_URI;
  cfg.credentials.client_id = s_device_id.c_str();
  cfg.session.keepalive = 30;
  cfg.session.last_will.topic = s_status_topic.c_str();
  cfg.session.last_will.msg = kOfflineStatus;
  cfg.session.last_will.msg_len = sizeof(kOfflineStatus) - 1;
  cfg.session.last_will.qos = 1;
  cfg.session.last_will.retain = 1;
  s_mqtt = esp_mqtt_client_init(&cfg);
  esp_mqtt_client_register_event(s_mqtt, (esp_mqtt_event_id_t)ESP_EVENT_ANY_ID, on_mqtt_event,
                                 nullptr);
  esp_mqtt_client_start(s_mqtt);
}

void mqtt_publish_reading(const std::string &payload) {
  if (!s_mqtt) return;
  esp_mqtt_client_publish(s_mqtt, s_reading_topic.c_str(), payload.c_str(), payload.size(), 1, 0);
}
