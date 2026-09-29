#pragma once

#include <string>

// Connects to the WiFi network from menuconfig. Blocks until an IP is assigned.
void wifi_connect();

// Starts the MQTT client if a broker URI is configured.
void mqtt_start();
void mqtt_publish(const std::string &payload);
