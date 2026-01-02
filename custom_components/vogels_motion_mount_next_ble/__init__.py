"""Integration for a Vogels Motion Mount via BLE."""

from __future__ import annotations

from datetime import timedelta
import logging

from packaging import version

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, __version__ as ha_version
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
    IntegrationError,
)
from homeassistant.util import dt as dt_util

from .const import BLE_CALLBACK, CONF_MAC, DOMAIN, MIN_HA_VERSION
from .coordinator import VogelsMotionMountNextBleCoordinator
from .data import VogelsMotionMountAuthenticationType
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
]

type VogelsMotionMountNextBleConfigEntry = ConfigEntry[VogelsMotionMountNextBleCoordinator]


async def async_setup(
    hass: HomeAssistant, entry: VogelsMotionMountNextBleConfigEntry
) -> bool:
    """Set up Vogels Motion Mount integration services."""
    _LOGGER.debug("async_setup called with config_entry: %s", entry)
    if version.parse(ha_version) < version.parse(MIN_HA_VERSION):
        raise IntegrationError(
            translation_key="invalid_ha_version",
            translation_placeholders={"version": MIN_HA_VERSION},
        )
    async_setup_services(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant, config_entry: VogelsMotionMountNextBleConfigEntry
) -> bool:
    """Set up Vogels Motion Mount Integration from a config entry."""
    _LOGGER.debug("async_setup_entry called with config_entry: %s", config_entry)

    hass.data.setdefault(DOMAIN, {})
    entry_data = hass.data[DOMAIN].setdefault(config_entry.entry_id, {})
    
    # If coordinator already exists (e.g., from a previous attempt), unsubscribe first
    if isinstance(entry_data, VogelsMotionMountNextBleCoordinator):
        return False

    # Initialise the coordinator that manages data updates from your api.
    device = bluetooth.async_ble_device_from_address(
        hass=hass,
        address=config_entry.data[CONF_MAC],
        connectable=True,
    )

    if device is None:
        _LOGGER.debug("async_setup_entry device not found")

        if entry_data.get(BLE_CALLBACK) is None:
            # Register a callback to retry setup when the device appears
            def _available_callback(
                info: BluetoothServiceInfoBleak, change: BluetoothChange
            ):
                if info.address == config_entry.data[CONF_MAC]:
                    _LOGGER.debug("%s is discovered again", info.address)
                    # Schedule a reload of the config entry immediately
                    hass.async_create_task(
                        hass.config_entries.async_reload(config_entry.entry_id)
                    )

            _LOGGER.debug("async_setup_entry async_register_callback")
            unregister_ble_callback = bluetooth.async_register_callback(
                hass,
                _available_callback,
                {"address": config_entry.data[CONF_MAC], "connectable": True},
                BluetoothScanningMode.ACTIVE,
            )
            entry_data[BLE_CALLBACK] = (
                unregister_ble_callback
            )
        raise ConfigEntryNotReady(
            translation_key="error_device_not_found",
        )

    # Registers update listener to update config entry when options are updated.
    unsub_update_listener = config_entry.add_update_listener(async_reload_entry)

    coordinator = VogelsMotionMountNextBleCoordinator(
        hass=hass,
        config_entry=config_entry,
        device=device,
        unsub_options_update_listener=unsub_update_listener,
    )
    config_entry.runtime_data = coordinator

    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = coordinator

    # Wait for the first data refresh to complete before setting up platforms
    # This ensures entities have data available when they're created
    # However, if the device is not immediately available, we still proceed
    # and let the coordinator retry on its scheduled update
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed as err:
        _LOGGER.debug("async_setup_entry ConfigEntryAuthFailed %s", str(err))
        unsub_update_listener()
        raise err from err

    # Set up platforms now that coordinator is initialized
    # Data may not be available yet if device is not immediately reachable
    try:
        await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
        return True
    except Exception as err:
        _LOGGER.debug("async_setup_entry Exception during platform setup %s", str(err))
        unsub_update_listener()
        raise ConfigEntryNotReady(
            translation_key="error_unknown",
            translation_placeholders={"error": repr(err)},
        ) from err


async def async_reload_entry(
    hass: HomeAssistant, config_entry: VogelsMotionMountNextBleConfigEntry
) -> None:
    """Reload config entry."""
    _LOGGER.debug(
        "async_reload_entry async_reload with pin %s", config_entry.data.get("conf_pin", "Not set")
    )
    await async_unload_entry(hass, config_entry)
    await async_setup_entry(hass, config_entry)


async def async_unload_entry(
    hass: HomeAssistant, config_entry: VogelsMotionMountNextBleConfigEntry
) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("async_unload_entry")

    # Try to get the BLE callback from stored data (if it was registered during setup failure)
    entry_data = hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
    if isinstance(entry_data, dict):
        unregister_ble_callback = entry_data.get(BLE_CALLBACK)
        if unregister_ble_callback:
            _LOGGER.debug("unregister_ble_callback")
            unregister_ble_callback()

    # Only unload platforms if the entry was actually loaded
    # Check if runtime_data is set, which indicates successful setup
    if config_entry.runtime_data is not None:
        unload_ok = await hass.config_entries.async_unload_platforms(
            config_entry, PLATFORMS
        )
        if unload_ok:
            coordinator: VogelsMotionMountNextBleCoordinator = config_entry.runtime_data
            await coordinator.unload()
            bluetooth.async_rediscover_address(hass, config_entry.data[CONF_MAC])
        # Clean up entry data
        hass.data.get(DOMAIN, {}).pop(config_entry.entry_id, None)
        return unload_ok
    
    # If runtime_data is None, the entry was never fully loaded, so just return True
    return True

