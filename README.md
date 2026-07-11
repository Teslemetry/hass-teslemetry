# Teslemetry

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

![Project Maintenance][maintenance-shield]

[![Discord][discord-shield]][discord]

**This integration requires an account and subscription from Teslemetry.com**

## HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Teslemetry&repository=hass-teslemetry&category=integration)

1. Install and setup HACS. https://hacs.xyz/docs/user
2. Add https://github.com/Teslemetry/hass-teslemetry as a repo (or click the link above).
3. Search for Teslemetry and install.
4. Restart Home Assistant

**Checkout the full documentation at https://teslemetry.com/docs/home-assistant/features**

## Diagnostic log shipping (opt-in)

This HACS build can ship this integration's debug logs to Teslemetry's ClickStack so
command/connection issues can be diagnosed without you pasting log files.

- **Off by default.** It only ships while debug logging is enabled for the `teslemetry`
  integration (Settings -> Devices & services -> Teslemetry -> ... -> Enable debug logging).
  Turning debug logging off stops shipping immediately.
- **Only three loggers are shipped**: `homeassistant.components.teslemetry`,
  `tesla_fleet_api`, and `teslemetry_stream`. No other integration or HA system log is
  ever read.
- Shipping runs in the background, is capped in memory, and never blocks or breaks the
  integration if the network is unavailable.

<!---->

***

[commits-shield]: https://img.shields.io/github/commit-activity/y/Teslemetry/hacs-teslemetry.svg?style=for-the-badge
[commits]: https://github.com/teslemetry/hacs-teslemetry/commits/main
[discord]: https://discord.gg/7wZwHaZbWD
[discord-shield]: https://img.shields.io/discord/1197069901664358460.svg?style=for-the-badge
[license-shield]: https://img.shields.io/github/license/teslemetry/hacs-teslemetry.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-Brett%20Adams%20%40Bre77-blue.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/teslemetry/hacs-teslemetry.svg?style=for-the-badge
[releases]: https://github.com/teslemetry/hacs-teslemetry/releases
