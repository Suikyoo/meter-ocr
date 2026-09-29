#pragma once

#include "esp_camera.h"

bool camera_init();

// Captures a fresh grayscale frame and holds the camera lock until camera_release().
// flash: turn on the flash LED for the capture (ignored if no flash GPIO is configured).
camera_fb_t *camera_capture(bool flash);
void camera_release(camera_fb_t *fb);
