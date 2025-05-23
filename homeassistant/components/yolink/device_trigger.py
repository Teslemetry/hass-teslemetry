"""Provides device triggers for YoLink."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from yolink.const import ATTR_DEVICE_SMART_REMOTER, ATTR_DEVICE_SWITCH

from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from . import DOMAIN, YOLINK_EVENT
from .const import (
    DEV_MODEL_FLEX_FOB_YS3604_EC,
    DEV_MODEL_FLEX_FOB_YS3604_UC,
    DEV_MODEL_FLEX_FOB_YS3614_EC,
    DEV_MODEL_FLEX_FOB_YS3614_UC,
    DEV_MODEL_SWITCH_YS5708_EC,
    DEV_MODEL_SWITCH_YS5708_UC,
    DEV_MODEL_SWITCH_YS5709_EC,
    DEV_MODEL_SWITCH_YS5709_UC,
)

CONF_BUTTON_1 = "button_1"
CONF_BUTTON_2 = "button_2"
CONF_BUTTON_3 = "button_3"
CONF_BUTTON_4 = "button_4"
CONF_SHORT_PRESS = "short_press"
CONF_LONG_PRESS = "long_press"

FLEX_BUTTONS_4 = {
    f"{CONF_BUTTON_1}_{CONF_SHORT_PRESS}",
    f"{CONF_BUTTON_1}_{CONF_LONG_PRESS}",
    f"{CONF_BUTTON_2}_{CONF_SHORT_PRESS}",
    f"{CONF_BUTTON_2}_{CONF_LONG_PRESS}",
    f"{CONF_BUTTON_3}_{CONF_SHORT_PRESS}",
    f"{CONF_BUTTON_3}_{CONF_LONG_PRESS}",
    f"{CONF_BUTTON_4}_{CONF_SHORT_PRESS}",
    f"{CONF_BUTTON_4}_{CONF_LONG_PRESS}",
}

FLEX_BUTTONS_2 = {
    f"{CONF_BUTTON_1}_{CONF_SHORT_PRESS}",
    f"{CONF_BUTTON_1}_{CONF_LONG_PRESS}",
    f"{CONF_BUTTON_2}_{CONF_SHORT_PRESS}",
    f"{CONF_BUTTON_2}_{CONF_LONG_PRESS}",
}

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {vol.Required(CONF_TYPE): vol.In(FLEX_BUTTONS_4)}
)

# YoLink Remotes YS3604/YS3614, Switch YS5708/YS5709
TRIGGER_MAPPINGS: dict[str, set[str]] = {
    DEV_MODEL_FLEX_FOB_YS3604_EC: FLEX_BUTTONS_4,
    DEV_MODEL_FLEX_FOB_YS3604_UC: FLEX_BUTTONS_4,
    DEV_MODEL_FLEX_FOB_YS3614_UC: FLEX_BUTTONS_2,
    DEV_MODEL_FLEX_FOB_YS3614_EC: FLEX_BUTTONS_2,
    DEV_MODEL_SWITCH_YS5708_EC: FLEX_BUTTONS_2,
    DEV_MODEL_SWITCH_YS5708_UC: FLEX_BUTTONS_2,
    DEV_MODEL_SWITCH_YS5709_EC: FLEX_BUTTONS_2,
    DEV_MODEL_SWITCH_YS5709_UC: FLEX_BUTTONS_2,
}


async def async_get_triggers(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, Any]]:
    """List device triggers for YoLink devices."""
    device_registry = dr.async_get(hass)
    registry_device = device_registry.async_get(device_id)
    if not registry_device or registry_device.model not in [
        ATTR_DEVICE_SMART_REMOTER,
        ATTR_DEVICE_SWITCH,
    ]:
        return []
    if registry_device.model_id not in list(TRIGGER_MAPPINGS.keys()):
        return []
    return [
        {
            CONF_DEVICE_ID: device_id,
            CONF_DOMAIN: DOMAIN,
            CONF_PLATFORM: "device",
            CONF_TYPE: trigger,
        }
        for trigger in TRIGGER_MAPPINGS[registry_device.model_id]
    ]


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Listen for state changes based on configuration."""
    event_config = {
        event_trigger.CONF_PLATFORM: "event",
        event_trigger.CONF_EVENT_TYPE: YOLINK_EVENT,
        event_trigger.CONF_EVENT_DATA: {
            CONF_DEVICE_ID: config[CONF_DEVICE_ID],
            CONF_TYPE: config[CONF_TYPE],
        },
    }
    event_config = event_trigger.TRIGGER_SCHEMA(event_config)
    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info, platform_type="device"
    )
