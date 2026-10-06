#pragma once

#include <string>

// Connects to the WiFi network from menuconfig. Blocks until an IP is assigned.
void wifi_connect();

// Starts the MQTT client if a broker URI is configured. Uses "meter-<mac>" as the client ID,
// publishes a retained {"online":true,"ip":...} to <prefix>/<id>/status on every connect, and
// registers {"online":false} on the same topic as the last will.
void mqtt_start();

// Publishes a reading JSON to <prefix>/<id>/reading.
void mqtt_publish_reading(const std::string &payload);
