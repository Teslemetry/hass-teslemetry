# Teslemetry

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

![Project Maintenance][maintenance-shield]

[![Discord][discord-shield]][discord]

**This integration requires a subscription and access token from Teslemetry.com**

## HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Teslemetry&repository=hass-teslemetry&category=integration)

1. Install and setup HACS. https://hacs.xyz/docs/user
2. Add https://github.com/Teslemetry/hass-teslemetry as a repo (or click the link above).
3. Search for Teslemetry and install.
4. Restart Home Assistant

## Services

The services are all documented inside Home Assistant as well, so its recommended you start with the services developer tool (developer-tools/service) to correctly format your service calls.

### teslemetry.navigation_gps_request
| Field         | Description                | Example                          |
|---------------|----------------------------|----------------------------------|
| device_id     | The vehicles device_id     | 0d462c0c4c0b064b1a91cdbd1ffcbd31 |
| gps           | Dictionary of coordinates  |                                  |
| gps.latitude  | Latitude in degrees        | -27.9699373                      |
| gps.longitude | Longitude in degrees       | 153.4081865                      |
| order         | Order for this destination | 1                                |

### navigation_sc_request
| Field     | Description                | Example                          |
|-----------|----------------------------|----------------------------------|
| device_id | The vehicles device_id     | 0d462c0c4c0b064b1a91cdbd1ffcbd31 |
| id        | Supercharged ID            | Unknown                          |
| order     | Order for this destination | 1                                |

### teslemetry.navigation_request
| Field        | Description             | Example                          |
|--------------|-------------------------|----------------------------------|
| device_id    | The vehicles device_id  | 0d462c0c4c0b064b1a91cdbd1ffcbd31 |
| type         | Unknown                 | Unknown                          |
| value        | Location to navigate to | Unknown                          |
| locale       | ISO string              | en-au                            |
| timestamp_ms | Unknown                 | Unknown                          |

### teslemetry.set_scheduled_charging
| Field     | Description                           | Example                          |
|-----------|---------------------------------------|----------------------------------|
| device_id | The vehicles device_id                | 0d462c0c4c0b064b1a91cdbd1ffcbd31 |
| enable    | Enable or disable scheduled charging. | true                             |
| time      | Time to start charging in HH:MM       | 6:00                             |

### teslemetry.set_scheduled_departure
| Field                           | Description                               | Example                          |
|---------------------------------|-------------------------------------------|----------------------------------|
| device_id                       | The vehicles device_id                    | 0d462c0c4c0b064b1a91cdbd1ffcbd31 |
| enable                          | Enable or disable scheduled departure     | true                             |
| preconditioning_enabled         | Enable preconditioning                    | true                             |
| preconditioning_weekdays_only   | Enable preconditioning on weekdays only   | false                            |
| departure_time                  | Time to precondition by (HH:MM)           | 6:00                             |
| off_peak_charging_enabled       | Enable off peak charging                  | false                            |
| off_peak_charging_weekdays_only | Enable off peak charging on weekdays only | false                            |
| end_off_peak_time               | Time to complete charging by (HH:MM)      | 5:00                             |

### teslemetry.stream_fields
The stream fields service replaces the fields in your streaming configuration, and uses the same structure as the [Tesla Fleet API](https://developer.tesla.com/docs/fleet-api#fleet_telemetry_config-create) to ensure future compatibility.

```
service: teslemetry.stream_fields
data:
  device_id: 0d462c0c4c0b064b1a91cdbd1ffcbd31
  fields:
    BatteryLevel:
      interval_seconds: 60
```

## Events
When streaming is configured, alerts and errors reported by your vehicles will be sent on the event bus as `teslemetry_alert` and `teselemetry_error`.

```
event_type: teslemetry_alert
data:
  name: VCFRONT_a186_noDriveChgCableCon
  audiences:
    - Customer
  startedAt: "2024-04-07T02:03:17.775Z"
  endedAt: "2024-04-07T02:03:18.778Z"
  vin: "LRW3..."
origin: LOCAL
time_fired: "2024-04-07T02:03:28.612834+00:00"
context:
  id: 01HTV4QPZ42GFHET0JW9SK9RHY
  parent_id: null
  user_id: null
```



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
