#pragma once

#include "config.h"
#include "reader.h"

// State shared between the reading task and the web server. All functions are thread-safe.
MeterConfig app_config();
void app_set_config(const MeterConfig &cfg);
Reading app_last_reading();
