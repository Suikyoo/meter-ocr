#include "web.h"

#include <cstdlib>
#include <string>

#include "app.h"
#include "camera.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "img_converters.h"

static const char *TAG = "web";

extern const uint8_t setup_html_start[] asm("_binary_setup_html_start");
extern const uint8_t setup_html_end[] asm("_binary_setup_html_end");

constexpr int kMaxBody = 4096;
constexpr int kMaxAnchorSide = 96;

static esp_err_t send_json(httpd_req_t *req, const std::string &json) {
  httpd_resp_set_type(req, "application/json");
  return httpd_resp_send(req, json.c_str(), json.size());
}

static esp_err_t index_get(httpd_req_t *req) {
  httpd_resp_set_type(req, "text/html");
  return httpd_resp_send(req, (const char *)setup_html_start, setup_html_end - setup_html_start);
}

static esp_err_t snapshot_get(httpd_req_t *req) {
  camera_fb_t *fb = camera_capture(!app_config().led_display);
  if (!fb) return httpd_resp_send_500(req);
  uint8_t *jpg = nullptr;
  size_t len = 0;
  bool ok = frame2jpg(fb, 85, &jpg, &len);
  camera_release(fb);
  if (!ok) return httpd_resp_send_500(req);
  httpd_resp_set_type(req, "image/jpeg");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  esp_err_t err = httpd_resp_send(req, (const char *)jpg, len);
  free(jpg);
  return err;
}

static esp_err_t config_get(httpd_req_t *req) {
  return send_json(req, config_to_json(app_config()));
}

static esp_err_t config_post(httpd_req_t *req) {
  if (req->content_len <= 0 || req->content_len > kMaxBody) {
    return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "bad body size");
  }
  std::string body(req->content_len, '\0');
  for (size_t got = 0; got < body.size();) {
    int n = httpd_req_recv(req, body.data() + got, body.size() - got);
    if (n == HTTPD_SOCK_ERR_TIMEOUT) continue;
    if (n <= 0) return ESP_FAIL;
    got += n;
  }

  MeterConfig old_cfg = app_config();
  MeterConfig cfg = old_cfg;
  if (!config_from_json(body.c_str(), cfg)) {
    return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "invalid config");
  }
  if (cfg.anchor.w > kMaxAnchorSide || cfg.anchor.h > kMaxAnchorSide) {
    return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "anchor larger than 96x96");
  }
  if (!reader_capture_anchor(cfg)) {
    return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "anchor capture failed");
  }
  if (!config_save(cfg)) {
    return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "save failed");
  }
  if (cfg.digits.size() != old_cfg.digits.size() || cfg.decimals != old_cfg.decimals) {
    reader_reset_history();
  }
  app_set_config(cfg);
  ESP_LOGI(TAG, "config saved: %d digits", (int)cfg.digits.size());
  return send_json(req, config_to_json(cfg));
}

static esp_err_t reading_get(httpd_req_t *req) {
  return send_json(req, reading_to_json(app_last_reading(), false));
}

static esp_err_t crops_get(httpd_req_t *req) {
  return send_json(req, reading_to_json(app_last_reading(), true));
}

void web_start() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.stack_size = 8192;
  httpd_handle_t server;
  if (httpd_start(&server, &config) != ESP_OK) {
    ESP_LOGE(TAG, "failed to start server");
    return;
  }
  const httpd_uri_t routes[] = {
      {"/", HTTP_GET, index_get, nullptr},
      {"/snapshot.jpg", HTTP_GET, snapshot_get, nullptr},
      {"/api/config", HTTP_GET, config_get, nullptr},
      {"/api/config", HTTP_POST, config_post, nullptr},
      {"/api/reading", HTTP_GET, reading_get, nullptr},
      {"/api/crops", HTTP_GET, crops_get, nullptr},
  };
  for (const httpd_uri_t &r : routes) httpd_register_uri_handler(server, &r);
}
