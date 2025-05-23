"""Manifest validation."""

from __future__ import annotations

from enum import StrEnum, auto
import json
from pathlib import Path
import subprocess
from typing import Any
from urllib.parse import urlparse

from awesomeversion import (
    AwesomeVersion,
    AwesomeVersionException,
    AwesomeVersionStrategy,
)
import voluptuous as vol
from voluptuous.humanize import humanize_error

from homeassistant.const import Platform
from homeassistant.helpers import config_validation as cv
from script.util import sort_manifest as util_sort_manifest

from .model import Config, Integration, ScaledQualityScaleTiers

DOCUMENTATION_URL_SCHEMA = "https"
DOCUMENTATION_URL_HOST = "www.home-assistant.io"
DOCUMENTATION_URL_PATH_PREFIX = "/integrations/"
DOCUMENTATION_URL_EXCEPTIONS = {"https://www.home-assistant.io/hassio"}

_CORE_DOCUMENTATION_BASE = "https://www.home-assistant.io/integrations"


class NonScaledQualityScaleTiers(StrEnum):
    """Supported manifest quality scales."""

    CUSTOM = auto()
    NO_SCORE = auto()
    INTERNAL = auto()
    LEGACY = auto()


SUPPORTED_QUALITY_SCALES = [
    value.name.lower()
    for enum in [ScaledQualityScaleTiers, NonScaledQualityScaleTiers]
    for value in enum
]
SUPPORTED_IOT_CLASSES = [
    "assumed_state",
    "calculated",
    "cloud_polling",
    "cloud_push",
    "local_polling",
    "local_push",
]

# List of integrations that are supposed to have no IoT class
NO_IOT_CLASS = [
    *{platform.value for platform in Platform},
    "api",
    "application_credentials",
    "auth",
    "automation",
    "blueprint",
    "color_extractor",
    "config",
    "configurator",
    "counter",
    "default_config",
    "device_automation",
    "device_tracker",
    "diagnostics",
    "downloader",
    "ffmpeg",
    "file_upload",
    "frontend",
    "hardkernel",
    "hardware",
    "history",
    "homeassistant",
    "homeassistant_alerts",
    "homeassistant_green",
    "homeassistant_hardware",
    "homeassistant_sky_connect",
    "homeassistant_yellow",
    "image_upload",
    "input_boolean",
    "input_button",
    "input_datetime",
    "input_number",
    "input_select",
    "input_text",
    "intent_script",
    "intent",
    "logbook",
    "logger",
    "lovelace",
    "media_source",
    "my",
    "onboarding",
    "panel_custom",
    "plant",
    "profiler",
    "proxy",
    "python_script",
    "raspberry_pi",
    "recovery_mode",
    "repairs",
    "schedule",
    "script",
    "search",
    "system_health",
    "system_log",
    "tag",
    "timer",
    "trace",
    "webhook",
    "websocket_api",
    "zone",
]


def core_documentation_url(value: str) -> str:
    """Validate that a documentation url has the correct path and domain."""
    if value in DOCUMENTATION_URL_EXCEPTIONS:
        return value
    if not value.startswith(_CORE_DOCUMENTATION_BASE):
        raise vol.Invalid(
            f"Documentation URL does not begin with {_CORE_DOCUMENTATION_BASE}"
        )

    return value


def custom_documentation_url(value: str) -> str:
    """Validate that a custom integration documentation url is correct."""
    parsed_url = urlparse(value)
    if parsed_url.scheme != DOCUMENTATION_URL_SCHEMA:
        raise vol.Invalid("Documentation url is not prefixed with https")
    if value.startswith(_CORE_DOCUMENTATION_BASE):
        raise vol.Invalid(
            "Documentation URL should point to the custom integration documentation"
        )

    return value


def verify_lowercase(value: str) -> str:
    """Verify a value is lowercase."""
    if value.lower() != value:
        raise vol.Invalid("Value needs to be lowercase")

    return value


def verify_uppercase(value: str) -> str:
    """Verify a value is uppercase."""
    if value.upper() != value:
        raise vol.Invalid("Value needs to be uppercase")

    return value


def verify_version(value: str) -> str:
    """Verify the version."""
    try:
        AwesomeVersion(
            value,
            ensure_strategy=[
                AwesomeVersionStrategy.CALVER,
                AwesomeVersionStrategy.SEMVER,
                AwesomeVersionStrategy.SIMPLEVER,
                AwesomeVersionStrategy.BUILDVER,
                AwesomeVersionStrategy.PEP440,
            ],
        )
    except AwesomeVersionException as err:
        raise vol.Invalid(f"'{value}' is not a valid version.") from err
    return value


def verify_wildcard(value: str) -> str:
    """Verify the matcher contains a wildcard."""
    if "*" not in value:
        raise vol.Invalid(f"'{value}' needs to contain a wildcard matcher")
    return value


INTEGRATION_MANIFEST_SCHEMA = vol.Schema(
    {
        vol.Required("domain"): str,
        vol.Required("name"): str,
        vol.Optional("integration_type", default="hub"): vol.In(
            [
                "device",
                "entity",
                "hardware",
                "helper",
                "hub",
                "service",
                "system",
            ]
        ),
        vol.Optional("config_flow"): bool,
        vol.Optional("mqtt"): [str],
        vol.Optional("zeroconf"): [
            vol.Any(
                str,
                vol.All(
                    cv.deprecated("macaddress"),
                    cv.deprecated("model"),
                    cv.deprecated("manufacturer"),
                    vol.Schema(
                        {
                            vol.Required("type"): str,
                            vol.Optional("macaddress"): vol.All(
                                str, verify_uppercase, verify_wildcard
                            ),
                            vol.Optional("manufacturer"): vol.All(
                                str, verify_lowercase
                            ),
                            vol.Optional("model"): vol.All(str, verify_lowercase),
                            vol.Optional("name"): vol.All(str, verify_lowercase),
                            vol.Optional("properties"): vol.Schema(
                                {str: verify_lowercase}
                            ),
                        }
                    ),
                ),
            )
        ],
        vol.Optional("ssdp"): vol.Schema(
            vol.All([vol.All(vol.Schema({}, extra=vol.ALLOW_EXTRA), vol.Length(min=1))])
        ),
        vol.Optional("bluetooth"): [
            vol.Schema(
                {
                    vol.Optional("connectable"): bool,
                    vol.Optional("service_uuid"): vol.All(str, verify_lowercase),
                    vol.Optional("service_data_uuid"): vol.All(str, verify_lowercase),
                    vol.Optional("local_name"): vol.All(str),
                    vol.Optional("manufacturer_id"): int,
                    vol.Optional("manufacturer_data_start"): [int],
                }
            )
        ],
        vol.Optional("homekit"): vol.Schema({vol.Optional("models"): [str]}),
        vol.Optional("dhcp"): [
            vol.Schema(
                {
                    vol.Optional("macaddress"): vol.All(
                        str, verify_uppercase, verify_wildcard
                    ),
                    vol.Optional("hostname"): vol.All(str, verify_lowercase),
                    vol.Optional("registered_devices"): cv.boolean,
                }
            )
        ],
        vol.Optional("usb"): [
            vol.Schema(
                {
                    vol.Optional("vid"): vol.All(str, verify_uppercase),
                    vol.Optional("pid"): vol.All(str, verify_uppercase),
                    vol.Optional("serial_number"): vol.All(str, verify_lowercase),
                    vol.Optional("manufacturer"): vol.All(str, verify_lowercase),
                    vol.Optional("description"): vol.All(str, verify_lowercase),
                    vol.Optional("known_devices"): [str],
                }
            )
        ],
        vol.Required("documentation"): vol.All(vol.Url(), core_documentation_url),
        vol.Optional("quality_scale"): vol.In(SUPPORTED_QUALITY_SCALES),
        vol.Optional("requirements"): [str],
        vol.Optional("dependencies"): [str],
        vol.Optional("after_dependencies"): [str],
        vol.Required("codeowners"): [str],
        vol.Optional("loggers"): [str],
        vol.Optional("disabled"): str,
        vol.Optional("iot_class"): vol.In(SUPPORTED_IOT_CLASSES),
        vol.Optional("single_config_entry"): bool,
    }
)

VIRTUAL_INTEGRATION_MANIFEST_SCHEMA = vol.Schema(
    {
        vol.Required("domain"): str,
        vol.Required("name"): str,
        vol.Required("integration_type"): "virtual",
        vol.Exclusive("iot_standards", "virtual_integration"): [
            vol.Any("homekit", "zigbee", "zwave")
        ],
        vol.Exclusive("supported_by", "virtual_integration"): str,
    }
)


def manifest_schema(value: dict[str, Any]) -> vol.Schema:
    """Validate integration manifest."""
    if value.get("integration_type") == "virtual":
        return VIRTUAL_INTEGRATION_MANIFEST_SCHEMA(value)
    return INTEGRATION_MANIFEST_SCHEMA(value)


CUSTOM_INTEGRATION_MANIFEST_SCHEMA = INTEGRATION_MANIFEST_SCHEMA.extend(
    {
        vol.Required("documentation"): vol.All(vol.Url(), custom_documentation_url),
        vol.Optional("version"): vol.All(str, verify_version),
        vol.Optional("issue_tracker"): vol.Url(),
        vol.Optional("import_executor"): bool,
    }
)


def validate_version(integration: Integration) -> None:
    """Validate the version of the integration.

    Will be removed when the version key is no longer optional for custom integrations.
    """
    if not integration.manifest.get("version"):
        integration.add_error("manifest", "No 'version' key in the manifest file.")
        return


def validate_manifest(integration: Integration, core_components_dir: Path) -> None:
    """Validate manifest."""
    try:
        if integration.core:
            manifest_schema(integration.manifest)
        else:
            CUSTOM_INTEGRATION_MANIFEST_SCHEMA(integration.manifest)
    except vol.Invalid as err:
        integration.add_error(
            "manifest", f"Invalid manifest: {humanize_error(integration.manifest, err)}"
        )

    if (domain := integration.manifest["domain"]) != integration.path.name:
        integration.add_error("manifest", "Domain does not match dir name")

    if not integration.core and (core_components_dir / domain).exists():
        integration.add_warning(
            "manifest", "Domain collides with built-in core integration"
        )

    if domain in NO_IOT_CLASS and "iot_class" in integration.manifest:
        integration.add_error("manifest", "Domain should not have an IoT Class")

    if (
        domain not in NO_IOT_CLASS
        and "iot_class" not in integration.manifest
        and integration.manifest.get("integration_type") != "virtual"
    ):
        integration.add_error("manifest", "Domain is missing an IoT Class")

    if (
        integration.manifest.get("integration_type") == "virtual"
        and (supported_by := integration.manifest.get("supported_by"))
        and not (core_components_dir / supported_by).exists()
    ):
        integration.add_error(
            "manifest",
            "Virtual integration points to non-existing supported_by integration",
        )

    if (
        (quality_scale := integration.manifest.get("quality_scale"))
        and quality_scale.upper() in ScaledQualityScaleTiers
        and ScaledQualityScaleTiers[quality_scale.upper()]
        >= ScaledQualityScaleTiers.SILVER
    ):
        if not integration.manifest.get("codeowners"):
            integration.add_error(
                "manifest",
                f"{quality_scale} integration does not have a code owner",
            )

    if not integration.core:
        validate_version(integration)


def sort_manifest(integration: Integration, config: Config) -> bool:
    """Sort manifest."""
    if integration.manifest_path is None:
        integration.add_error(
            "manifest",
            "Manifest path not set, unable to sort manifest keys",
        )
        return False

    if util_sort_manifest(integration.manifest):
        if config.action == "generate":
            integration.manifest_path.write_text(
                json.dumps(integration.manifest, indent=2) + "\n"
            )
            text = "have been sorted"
        else:
            text = "are not sorted correctly"
        integration.add_error(
            "manifest",
            f"Manifest keys {text}: domain, name, then alphabetical order",
        )
        return True
    return False


def validate(integrations: dict[str, Integration], config: Config) -> None:
    """Handle all integrations manifests."""
    core_components_dir = config.root / "homeassistant/components"
    manifests_resorted = []
    for integration in integrations.values():
        validate_manifest(integration, core_components_dir)
        if not integration.errors:
            if sort_manifest(integration, config):
                manifests_resorted.append(integration.manifest_path)
    if config.action == "generate" and manifests_resorted:
        subprocess.run(
            [
                "pre-commit",
                "run",
                "--hook-stage",
                "manual",
                "prettier",
                "--files",
                *manifests_resorted,
            ],
            stdout=subprocess.DEVNULL,
            check=True,
        )
