# Teslemetry

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

![Project Maintenance][maintenance-shield]

[![Discord][discord-shield]][discord]

_Integration to integrate with [Teslemetry]("https://teslemetry.com")._

**This integration requires a subscription and access token from Teslemetry.com**

## HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Teslemetry&repository=hass-teslemetry&category=integration)

1. Install and setup HACS. https://hacs.xyz/docs/user
2. Add https://github.com/Teslemetry/hass-teslemetry as a repo (or click the link above).
3. Search for Teslemetry and install.
4. Restart Home Assistant

## Manual Installation

1. Using the tool of choice open the directory (folder) for your HA configuration (where you find `configuration.yaml`).
1. If you do not have a `custom_components` directory (folder) there, you need to create it.
1. In the `custom_components` directory (folder) create a new folder called `hacs-teslemetry`.
1. Download _all_ the files from the `custom_components/hacs-teslemetry/` directory (folder) in this repository.
1. Place the files you downloaded in the new directory (folder) you created.
1. Restart Home Assistant
1. In the HA UI go to "Configuration" -> "Integrations" click "+" and search for "Integration blueprint"

## Configuration is done in the UI

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
