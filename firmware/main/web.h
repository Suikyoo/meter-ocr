#pragma once

// Serves the setup page and the JSON API:
//   GET  /               setup page
//   GET  /snapshot.jpg   current camera frame
//   GET  /api/config     current config
//   POST /api/config     save config (also captures the anchor patch)
//   GET  /api/reading    last reading
//   GET  /api/crops      last reading with normalized digit crops (for training/collect.py)
void web_start();
