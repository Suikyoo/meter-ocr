idf_component_register(
    SRCS "main.cc" "camera.cc" "config.cc" "reader.cc" "web.cc" "net.cc" "model_data.cc"
    INCLUDE_DIRS "."
    EMBED_FILES "setup.html"
    PRIV_REQUIRES esp_http_server esp_wifi esp_netif esp_event nvs_flash mqtt json mbedtls esp_timer esp_driver_gpio esp_hw_support)
