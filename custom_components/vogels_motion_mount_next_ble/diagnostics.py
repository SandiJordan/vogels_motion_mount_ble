"""Diagnostics support for Vogels Motion Mount BLE."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data  # type: ignore[import-untyped]
from homeassistant.core import HomeAssistant  # type: ignore[import-untyped]

from . import VogelsMotionMountNextBleConfigEntry
from .const import CONF_MAC, CONF_PIN
from .coordinator import VogelsMotionMountNextBleCoordinator

TO_REDACT = {CONF_PIN, CONF_MAC}


async def async_get_config_entry_diagnostics(
    _: HomeAssistant, config_entry: VogelsMotionMountNextBleConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: VogelsMotionMountNextBleCoordinator = config_entry.runtime_data

    return {
        "config_entry_data": async_redact_data(dict(config_entry.data), TO_REDACT),
        "vogels_motion_mount_ble_data": coordinator.data,
    }

