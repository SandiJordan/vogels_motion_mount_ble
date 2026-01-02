"""Coordinator for Vogels Motion Mount BLE integration in order to communicate with client."""

from collections.abc import Callable
import asyncio
from dataclasses import replace
from datetime import timedelta
import logging

from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakConnectionError, BleakNotFoundError, BleakOutOfConnectionSlotsError

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ServiceValidationError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import (
    VogelsMotionMountBluetoothClient,
    VogelsMotionMountClientAuthenticationError,
)
from .const import CONF_MAC, CONF_PIN, CONF_BLE_DISCONNECT_TIMEOUT, DEFAULT_BLE_DISCONNECT_TIMEOUT, DOMAIN
from .data import (
    VogelsMotionMountAuthenticationType,
    VogelsMotionMountAutoMoveType,
    VogelsMotionMountData,
    VogelsMotionMountMultiPinFeatures,
    VogelsMotionMountPermissions,
    VogelsMotionMountPinSettings,
    VogelsMotionMountPreset,
)

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


class VogelsMotionMountNextBleCoordinator(DataUpdateCoordinator[VogelsMotionMountData]):
    """Vogels Motion Mount NEXT BLE coordinator."""

    # -------------------------------
    # region Setup
    # -------------------------------

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        device: BLEDevice,
        unsub_options_update_listener: Callable[[], None],
    ) -> None:
        """Initialize coordinator and setup client."""
        _LOGGER.debug("Startup coordinator with %s", config_entry.data)

        # Store setup data
        self.address = device.address
        self._reconnect_attempts = 0
        self._last_disconnect_time = None
        self._load_ble_disconnect_timeout(config_entry)
        self._last_activity_time = dt_util.utcnow()
        self._disconnect_timer_handle = None

        # Create client
        self._client = VogelsMotionMountBluetoothClient(
            pin=config_entry.data.get(CONF_PIN),
            device=device,
            permission_callback=self._permissions_changed,
            connection_callback=self._connection_changed,
            distance_callback=self._distance_changed,
            rotation_callback=self._rotation_changed,
        )

        # Initialise DataUpdateCoordinator
        super().__init__(
            hass,
            _LOGGER,
            name=config_entry.title,
            config_entry=config_entry,
            update_interval=timedelta(minutes=5),
        )

        # Setup listeners
        self._unsub_options_update_listener = unsub_options_update_listener
        self._unsub_unavailable_update_listener = bluetooth.async_track_unavailable(
            hass, self._unavailable_callback, self.address, connectable=True
        )
        self._unsub_available_update_listener = bluetooth.async_register_callback(
            hass,
            self._available_callback,
            {"address": self.address, "connectable": True},
            BluetoothScanningMode.ACTIVE,
        )

        _LOGGER.debug("Coordinator startup finished")

    def _load_ble_disconnect_timeout(self, config_entry: ConfigEntry) -> None:
        """Load BLE disconnect timeout from config."""
        timeout_minutes = (
            config_entry.data.get(CONF_BLE_DISCONNECT_TIMEOUT)
            or DEFAULT_BLE_DISCONNECT_TIMEOUT
        )
        self._ble_disconnect_timeout = timedelta(minutes=timeout_minutes)
        _LOGGER.debug(
            "BLE disconnect timeout set to %d minutes", timeout_minutes
        )

    async def async_config_entry_first_refresh(self) -> None:
        """Perform the first refresh with a timeout to avoid blocking bootstrap.
        
        If the device is not immediately available, we still allow setup to proceed
        so platforms can be created. The coordinator will continue to retry on the
        periodic update schedule.
        """
        try:
            await asyncio.wait_for(
                self.async_refresh(),
                timeout=60.0
            )
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "First data refresh for %s timed out. Device may not be available yet. "
                "Setup will continue and coordinator will retry on scheduled updates.",
                self.address,
            )
        except UpdateFailed as err:
            _LOGGER.warning(
                "First data refresh for %s failed: %s. "
                "Setup will continue and coordinator will retry on scheduled updates.",
                self.address,
                str(err),
            )

    def _available_callback(
        self, info: BluetoothServiceInfoBleak, change: BluetoothChange
    ) -> None:
        _LOGGER.debug("%s is discovered again", info.address)
        self._reconnect_attempts = 0  # Reset retry counter
        self._update_activity_timer()
        # Only request refresh if we haven't recently tried and failed
        # This prevents rapid retry loops when device is unreachable
        if self._last_disconnect_time is None or (
            dt_util.utcnow() - self._last_disconnect_time
        ).total_seconds() > 30:
            self._last_disconnect_time = None  # Clear the disconnect time on successful discovery
            self.hass.async_create_task(self.async_request_refresh())  # load the data
        else:
            _LOGGER.debug(
                "Skipping refresh for %s - recently disconnected, will wait for scheduled update",
                self.address,
            )

    def _cancel_disconnect_timer(self) -> None:
        """Cancel the disconnect timer if active."""
        if self._disconnect_timer_handle is not None:
            self._disconnect_timer_handle.cancel()
            self._disconnect_timer_handle = None

    def _update_activity_timer(self) -> None:
        """Update activity timer - resets the disconnect timeout."""
        self._last_activity_time = dt_util.utcnow()
        self._cancel_disconnect_timer()
        
        if self._client.is_connected:
            # Schedule disconnect after timeout period
            self._disconnect_timer_handle = self.hass.loop.call_later(
                self._ble_disconnect_timeout.total_seconds(),
                self._async_disconnect_timeout,
            )
            _LOGGER.debug(
                "BLE disconnect timer set for %s minutes",
                self._ble_disconnect_timeout.total_seconds() / 60,
            )

    def _async_disconnect_timeout(self) -> None:
        """Called when disconnect timeout is reached."""
        _LOGGER.info(
            "BLE idle timeout reached for %s. Disconnecting.", self.address
        )
        self._disconnect_timer_handle = None
        self.hass.async_create_task(self._client.disconnect())

    def _unavailable_callback(self, info: BluetoothServiceInfoBleak) -> None:
        _LOGGER.debug("%s is no longer seen", info.address)
        self._set_unavailable()

    async def unload(self):
        """Disconnect and unload."""
        _LOGGER.debug("unload coordinator")
        self._cancel_disconnect_timer()
        self._unsub_options_update_listener()
        self._unsub_unavailable_update_listener()
        self._unsub_available_update_listener()
        await self._client.disconnect()

    async def refresh_data(self):
        """Load data form client."""
        self.hass.async_create_task(self.async_request_refresh())

    # -------------------------------
    # region Control
    # -------------------------------

    async def disconnect(self):
        """Disconnect form client."""
        await self._call(self._client.disconnect)

    async def connect(self):
        """Connect to device."""
        _LOGGER.info("Manually connecting to %s", self.address)
        try:
            await self._client._connect()
            _LOGGER.info("Successfully connected to %s", self.address)
            await self.async_request_refresh()
        except Exception as err:
            _LOGGER.error("Failed to manually connect to %s: %s", self.address, err)
            raise ServiceValidationError(
                translation_key="error_device_not_found",
                translation_placeholders={"error": str(err)},
            ) from err

    async def select_preset(self, preset_index: int):
        """Select a preset to move to."""
        # Verify preset has data before attempting to select
        if self.data and preset_index < len(self.data.presets):
            preset = self.data.presets[preset_index]
            if preset.data is None:
                raise ServiceValidationError(
                    translation_key="error_preset_no_data",
                    translation_placeholders={"preset": str(preset_index)},
                )
        await self._call(self._client.select_preset, preset_index)

    async def start_calibration(self):
        """Start calibration process."""
        await self._call(self._client.start_calibration)

    # -------------------------------
    # region Config
    # -------------------------------

    async def request_distance(self, distance: int):
        """Request a distance to move to."""
        await self._call(self._client.request_distance, distance)
        self.async_set_updated_data(replace(self.data, requested_distance=distance))

    async def request_rotation(self, rotation: int):
        """Request a rotation to move to."""
        await self._call(self._client.request_rotation, rotation)
        self.async_set_updated_data(replace(self.data, requested_rotation=rotation))

    """
    async def set_authorised_user_pin(self, pin: str):
        #Set or remove pin for authorised user.
        await self._call(self._client.set_authorised_user_pin, pin)
        remove = pin == "0000"
        pin_setting = await self._call(self._client.read_pin_settings)
        if remove and pin_setting != VogelsMotionMountPinSettings.Deactivated:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_saved_remove_authorised_user_pin",
                translation_placeholders={
                    "actual": str(pin_setting),
                    "expected": str(VogelsMotionMountPinSettings.Deactivated),
                },
            )
        if not remove and pin_setting == VogelsMotionMountPinSettings.Deactivated:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_saved_authorised_user_pin",
                translation_placeholders={
                    "actual": str(pin_setting),
                    "expected": str(VogelsMotionMountPinSettings.Deactivated),
                },
            )
        await self._call(self.disconnect)
        self.async_set_updated_data(await self._async_update_data())
    """

    async def set_automove(self, automove: VogelsMotionMountAutoMoveType):
        """Set type of automove."""
        await self._call(self._client.set_automove, automove)
        actual = await self._call(self._client.read_automove)
        self.async_set_updated_data(replace(self.data, automove=actual))
        if actual != automove:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_saved_automove",
                translation_placeholders={
                    "expected": str(automove),
                    "actual": str(actual),
                },
            )

    async def set_freeze_preset(self, preset_index: int):
        """Set a preset to move to when automove is executed."""
        await self._call(self._client.set_freeze_preset, preset_index)
        actual = await self._call(self._client.read_freeze_preset_index)
        self.async_set_updated_data(replace(self.data, freeze_preset_index=actual))
        if actual != preset_index:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_saved_freeze_preset_index",
                translation_placeholders={
                    "expected": str(preset_index),
                    "actual": str(actual),
                },
            )

    """
    async def set_multi_pin_features(self, features: VogelsMotionMountMultiPinFeatures):
        #Set features the authorised user is eligible to change.
        await self._call(self._client.set_multi_pin_features, features)
        actual = await self._call(self._client.read_multi_pin_features)
        self.async_set_updated_data(replace(self.data, multi_pin_features=actual))
        if actual != features:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_saved_multi_pin_features",
                translation_placeholders={
                    "expected": str(features),
                    "actual": str(actual),
                },
            )
    """

    async def set_preset(self, preset: VogelsMotionMountPreset):
        """Set the data of a preset."""
        await self._call(self._client.set_preset, preset)
        actual = await self._call(self._client.read_preset, preset.index)
        presets = self.data.presets.copy()
        presets[preset.index] = actual
        self.async_set_updated_data(replace(self.data, presets=presets))
        if actual != preset:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_saved_preset",
                translation_placeholders={
                    "expected": str(preset),
                    "actual": str(actual),
                },
            )

    """
    async def set_supervisior_pin(self, pin: str):
        #Set or remove pin for a supervisior.
        await self._call(self._client.set_supervisior_pin, pin)
        remove = pin == "0000"
        pin_setting = await self._call(self._client.read_pin_settings)
        if remove and pin_setting != VogelsMotionMountPinSettings.Single:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_saved_remove_supervisior_pin",
                translation_placeholders={
                    "actual": str(pin_setting),
                    "expected": str(VogelsMotionMountPinSettings.Single),
                },
            )
        if not remove and pin_setting != VogelsMotionMountPinSettings.Multi:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_saved_supervisior_pin",
                translation_placeholders={
                    "actual": str(pin_setting),
                    "expected": str(VogelsMotionMountPinSettings.Multi),
                },
            )
        await self.disconnect()
        self.async_set_updated_data(await self._async_update_data())
    """

    """
    async def set_tv_width(self, width: int):
        #Set the width of the tv.
        await self._call(self._client.set_tv_width, width)
        actual = await self._call(self._client.read_tv_width)
        self.async_set_updated_data(replace(self.data, tv_width=actual))
        if actual != width:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_saved_tv_width",
                translation_placeholders={
                    "expected": str(width),
                    "actual": str(actual),
                },
            )
    """

    # -------------------------------
    # region Notifications
    # -------------------------------

    def _permissions_changed(self, permissions: VogelsMotionMountPermissions):
        if self.data is not None:
            _LOGGER.debug("_permissions_changed %s", permissions)
            self.async_set_updated_data(replace(self.data, permissions=permissions))
        self._check_permission_status(permissions)

    def _connection_changed(self, connected: bool):
        if self.data is not None:
            self.async_set_updated_data(replace(self.data, connected=connected))
        
        # Manage disconnect timeout based on connection state
        if connected:
            self._update_activity_timer()
        else:
            self._cancel_disconnect_timer()

    def _distance_changed(self, distance: int):
        _LOGGER.debug("_distance_changed %s", distance)
        if self.data is not None:
            self.async_set_updated_data(replace(self.data, distance=distance))

    def _rotation_changed(self, rotation: int):
        _LOGGER.debug("_rotation_changed %s", rotation)
        if self.data is not None:
            self.async_set_updated_data(replace(self.data, rotation=rotation))

    # -------------------------------
    # region internal
    # -------------------------------

    async def _async_update_data(self) -> VogelsMotionMountData:
        """Fetch data from device."""
        # Retry once on transient connection errors (e.g., device not immediately ready after disconnect)
        max_retries = 2
        last_error = None
        
        for attempt in range(max_retries):
            try:
                permissions = await self._client.read_permissions()
                self._check_permission_status(permissions)

                result = VogelsMotionMountData(
                    automove=await self._client.read_automove(),
                    available=True,
                    connected=self._client.is_connected,
                    distance=await self._client.read_distance(),
                    freeze_preset_index=await self._client.read_freeze_preset_index(),
                    multi_pin_features=None,
                    name=None,
                    pin_setting=None,
                    presets=await self._client.read_presets(),
                    rotation=await self._client.read_rotation(),
                    tv_width=65,
                    versions=await self._client.read_versions(),
                    permissions=permissions,
                )
                
                # Reset activity timer on successful update
                self._update_activity_timer()
                return result
            except VogelsMotionMountClientAuthenticationError as err:
                self._set_unavailable()
                # reraise auth issues immediately
                _LOGGER.debug("_async_update_data ConfigEntryAuthFailed %s", str(err))
                raise ConfigEntryAuthFailed from err
            except ConnectionError as err:
                # Transient connection error - retry once
                last_error = err
                if attempt < max_retries - 1:
                    _LOGGER.debug(
                        "Transient connection error for %s (attempt %d/%d), retrying: %s",
                        self.address,
                        attempt + 1,
                        max_retries,
                        err,
                    )
                    await asyncio.sleep(0.5)  # Brief delay before retry
                    continue
                else:
                    _LOGGER.debug(
                        "Connection lost for %s after %d attempts: %s",
                        self.address,
                        max_retries,
                        err,
                    )
                    self._handle_connection_error()
                    raise UpdateFailed(translation_key="error_device_not_found") from err
            except BleakOutOfConnectionSlotsError as err:
                # BLE adapter is out of connection slots - force disconnect and wait before retry
                _LOGGER.debug(
                    "BLE adapter out of connection slots for %s. Forcing disconnect and will retry on next update.",
                    self.address,
                )
                self._handle_connection_error()
                raise UpdateFailed(
                    translation_key="error_unknown",
                    translation_placeholders={
                        "error": "Bluetooth adapter out of connection slots. Try restarting your Bluetooth adapter or removing stale connections."
                    },
                ) from err
            except BleakConnectionError as err:
                # Handle connection errors with smart retry strategy
                self._handle_connection_error()
                # treat BleakConnectionErrors as device not found
                raise UpdateFailed(translation_key="error_device_not_found") from err
            except BleakNotFoundError as err:
                self._set_unavailable()
                _LOGGER.debug("_async_update_data BleakNotFoundError %s", str(err))
                # treat BleakNotFoundError as device not found
                raise UpdateFailed(translation_key="error_device_not_found") from err
            except Exception as err:
                self._set_unavailable()
                # Device unreachable → tell HA gracefully
                _LOGGER.debug("_async_update_data Exception %s", repr(err))
                raise UpdateFailed(
                    translation_key="error_unknown",
                    translation_placeholders={"error": repr(err)},
                ) from err
        
        # Should not reach here, but just in case
        raise UpdateFailed(translation_key="error_device_not_found") from last_error

    def _check_permission_status(self, permissions: VogelsMotionMountPermissions):
        if (
            permissions.auth_status is not None
            and permissions.auth_status.auth_type
            == VogelsMotionMountAuthenticationType.Wrong
        ):
            _LOGGER.debug(
                "Authentication failed with auth status %s", permissions.auth_status
            )
            raise ConfigEntryAuthFailed(translation_key="error_invalid_authentication")

    async def _call(self, func, *args, **kwargs):
        """Execute a BLE client call safely."""
        try:
            return await func(*args, **kwargs)
        except VogelsMotionMountClientAuthenticationError as err:
            # reraise auth issues
            _LOGGER.debug("_async_update_data ConfigEntryAuthFailed %s", str(err))
            raise ConfigEntryAuthFailed from err
        except BleakConnectionError as err:
            self._set_unavailable()
            # treat BleakConnectionError as device not found
            raise ServiceValidationError(
                translation_key="error_device_not_found"
            ) from err
        except BleakNotFoundError as err:
            self._set_unavailable()
            _LOGGER.debug("_async_update_data BleakNotFoundError %s", str(err))
            # treat BleakNotFoundError as device not found
            raise ServiceValidationError(
                translation_key="error_device_not_found"
            ) from err
        except Exception as err:
            self._set_unavailable()
            # Device unreachable → tell HA gracefully
            _LOGGER.debug("_async_update_data Exception %s", repr(err))
            raise ServiceValidationError(
                translation_key="error_unknown",
                translation_placeholders={"error": repr(err)},
            ) from err

    def _set_unavailable(self):
        _LOGGER.debug("_set_unavailable width data %s", str(self.data))
        # trigger rediscovery for the device
        bluetooth.async_rediscover_address(self.hass, self.config_entry.data[CONF_MAC])
        if self.data is None:  # may be called before data is available
            return
        # tell HA to refresh all entities
        self.async_set_updated_data(replace(self.data, available=False))

    def _handle_connection_error(self):
        """Handle BLE connection errors with logging and disconnect."""
        self._reconnect_attempts += 1
        self._last_disconnect_time = dt_util.utcnow()
        _LOGGER.warning(
            "BLE connection error for %s. Attempt %d. Forcing disconnect to reset connection.",
            self.address,
            self._reconnect_attempts,
        )
        # Force disconnect to reset the BLE connection
        self.hass.async_create_task(self._client.disconnect())

