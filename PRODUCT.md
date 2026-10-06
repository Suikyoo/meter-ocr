# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Regular consumers who check their own meter's readings on a phone. They are not engineers. They open the app to see how much they have used, whether the meter is online, and how the usage compares across hours, days, weeks, months, and years.

## Product Purpose
Shows electricity meter readings captured by an ESP32-S3 camera device that reads the meter's LCD/LED display. The app shows the current reading, the consumption per period, and whether each device is online. Success means a person can answer "how much have I used, and is it working?" within a few seconds.

## Positioning
Reads the meter itself with a camera on the device. No smart-meter hardware or utility integration is needed, so any analog-era or 7-segment meter can be made readable.

## Operating Context
Used on a phone, usually on the go, in short glances. Data refreshes every 30 seconds while a screen is open. Devices connect over MQTT; the app reads from a FastAPI/SQLite service.

## Capabilities and Constraints
- Device list with online/offline state, last reading, and time since last seen.
- Device page: partition by hour, day, week, month, or year; window navigation; total consumption; bar chart; current meter value; link to the device's setup page.
- Meter reset notice when a reset is detected in the period.
- Phone-width layout first. No login.
- Stack is already set: Svelte 5 + Vite + Chart.js (in `server/frontend`).

## Brand Commitments
No existing name, logo, or brand color is binding. The visual identity may be replaced.

## Evidence on Hand
No testimonials, customer logos, or marketing claims exist. Do not invent any. Data shown is live device output only.

## Product Principles
- Numbers first. The kWh total is the hero of every screen.
- Readable at a glance, in daylight and at night, on a small screen.
- Friendly and light, with one confident accent that draws the eye without shouting.
- Status is never color-only; offline and online also use text and shape.

## Accessibility & Inclusion
Plain language for non-technical users. Tap targets of at least 44px. Respect reduced motion. Keep contrast at WCAG AA in light and dark themes.
