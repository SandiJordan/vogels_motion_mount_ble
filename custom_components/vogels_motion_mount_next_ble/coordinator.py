"""Coordinator for Vogels Motion Mount BLE integration in order to communicate with client."""

from collections.abc import Callable
import asyncio
from dataclasses import replace
from datetime import timedelta
import logging

from bleak.backends.device import BLEDevice  # type: ignore[import-untyped]
from bleak_retry_connector import BleakConnectionError, BleakNotFoundError, BleakOutOfConnectionSlotsError  # type: ignore[import-untyped]

from homeassistant.components import bluetooth  # type: ignore[import-untyped]
from homeassistant.components.bluetooth import (  # type: ignore[import-untyped]
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.config_entries import ConfigEntry  # type: ignore[import-untyped]
from homeassistant.core import HomeAssistant  # type: ignore[import-untyped]
from homeassistant.exceptions import ConfigEntryAuthFailed, ServiceValidationError  # type: ignore[import-untyped]
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed  # type: ignore[import-untyped]
from homeassistant.util import dt as dt_util  # type: ignore[import-untyped]

from .client import (
    VogelsMotionMountBluetoothClient,
    VogelsMotionMountClientAuthenticationError,
)
from .const import CONF_MAC, CONF_PIN, CONF_BLE_DISCONNECT_TIMEOUT, CONF_BLE_DISCOVERY_TIMEOUT, DEFAULT_BLE_DISCONNECT_TIMEOUT, DEFAULT_BLE_DISCOVERY_TIMEOUT, DOMAIN
from .data import (
    VogelsMotionMountAuthenticationType,
    VogelsMotionMountAutoMoveType,
    VogelsMotionMountData,
    VogelsMotionMountMultiPinFeatures,
    VogelsMotionMountPermissions,
    VogelsMotionMountPinSettings,
    VogelsMotionMountPreset,
    VogelsMotionMountPresetData,
    VogelsMotionMountVersions,
)

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1

# Minimum cooldown period after disconnect before attempting to reconnect.
# The Vogels Motion Mount device has DDoS prevention that triggers if reconnection
# attempts are too frequent. This cooldown prevents that protection from activating
# during development/testing with repeated restarts.
DISCONNECT_COOLDOWN_SECONDS = 30

# Maximum number of consecutive reconnection attempts before requiring a longer cooldown
MAX_RECONNECT_ATTEMPTS = 20


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
        self._last_connection_attempt_time = None
        self._load_ble_disconnect_timeout(config_entry)
        self._load_ble_discovery_timeout(config_entry)
        self._last_activity_time = dt_util.utcnow()
        self._disconnect_timer_handle = None
        self._is_discovered = False  # Track if device is discovered (seen via BLE scan)
        self._last_discovery_time = None  # Track timestamp of last discovery
        self._rediscovery_timer_handle = None  # Timer for triggering rediscovery scans
        self._last_scan_request_time = None  # Track when we last requested a scan

        # Create client
        self._client = VogelsMotionMountBluetoothClient(
            hass=hass,
            address=device.address,
            pin=config_entry.data.get(CONF_PIN),
            permission_callback=self._permissions_changed,  # type: ignore[arg-type]
            connection_callback=self._connection_changed,
            distance_callback=self._distance_changed,
            rotation_callback=self._rotation_changed,
        )

        # Initialise DataUpdateCoordinator
        # NOTE: update_interval is intentionally not set here (None).
        # We only fetch device data when explicitly requested via connect() or on manual refresh.
        # BLE discovery status is maintained through BLE callbacks, not periodic polling.
        # This prevents continuous connection attempts when the device is disconnected.
        super().__init__(
            hass,
            _LOGGER,
            name=config_entry.title,
            config_entry=config_entry,
        )
        
        # Initialize with minimal disconnected data so entities show up with default values
        # instead of being unavailable until first connection
        empty_presets = [
            VogelsMotionMountPreset(index=i, data=VogelsMotionMountPresetData(
                name=f"Preset {i+1}",
                distance=0,
                rotation=0,
            )) for i in range(7)
        ]
        disconnected_permissions = VogelsMotionMountPermissions(
            auth_status=None,  # type: ignore[arg-type]
            change_settings=True,
            change_default_position=True,
            change_name=True,
            change_presets=True,
            change_tv_on_off_detection=True,
            disable_channel=True,
            start_calibration=True,
        )
        initial_data = VogelsMotionMountData(
            automove=None,
            available=False,  # Will be set to True when discovered
            connected=False,
            distance=0,
            freeze_preset_index=0,
            multi_pin_features=VogelsMotionMountMultiPinFeatures(
                change_default_position=True,
                change_name=True,
                change_presets=True,
                change_tv_on_off_detection=True,
                disable_channel=True,
                start_calibration=True,
            ),
            name=None,  # type: ignore[arg-type]
            pin_setting=None,  # type: ignore[arg-type]
            presets=empty_presets,
            rotation=0,
            tv_width=65,
            versions=VogelsMotionMountVersions(
                ceb_bl_version="",
                mcp_bl_version="",
                mcp_fw_version="",
                mcp_hw_version="",
            ),
            permissions=disconnected_permissions,
        )
        self.async_set_updated_data(initial_data)

        # Setup listeners
        self._unsub_options_update_listener = unsub_options_update_listener
        self._unsub_unavailable_update_listener = bluetooth.async_track_unavailable(
            hass, self._unavailable_callback, self.address
        )
        _LOGGER.info("Registered unavailable callback for device %s", self.address)
        
        # Register for ALL advertisements of our device (connectable or not)
        # We check connectable status in the callback itself
        self._unsub_available_update_listener = bluetooth.async_register_callback(
            hass,
            self._available_callback,
            {"address": self.address},
            BluetoothScanningMode.ACTIVE,
        )
        _LOGGER.info("Registered available callback for device %s with active scanning", self.address)

        # Home Assistant bluetooth integration will handle scanning automatically
        # Just log that we're ready to receive advertisements
        _LOGGER.info("Coordinator initialized for device %s, waiting for BLE advertisements", self.address)

        # Start the rediscovery scan timer
        self._schedule_rediscovery_scan()

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

    def _load_ble_discovery_timeout(self, config_entry: ConfigEntry) -> None:
        """Load BLE discovery timeout from config."""
        timeout_seconds = (
            config_entry.options.get(CONF_BLE_DISCOVERY_TIMEOUT)
            or config_entry.data.get(CONF_BLE_DISCOVERY_TIMEOUT)
            or DEFAULT_BLE_DISCOVERY_TIMEOUT
        )
        self._ble_discovery_timeout_seconds = timeout_seconds
        _LOGGER.debug(
            "BLE discovery timeout set to %d seconds", timeout_seconds
        )

    async def async_config_entry_first_refresh(self) -> None:
        """Perform the first refresh with a timeout to avoid blocking bootstrap.
        
        If the device is not immediately available, we still allow setup to proceed
        so platforms can be created. The coordinator will continue to retry when
        the user manually connects.
        
        NOTE: We skip the initial refresh because:
        1. We initialize with default disconnected data in __init__
        2. Entities are already available with default values
        3. We don't have periodic updates enabled
        4. Device will only connect when user clicks the Connect button
        """
        # Don't try to fetch data on startup - wait for manual connect
        pass

    def _available_callback(
        self, info: BluetoothServiceInfoBleak, change: BluetoothChange
    ) -> None:
        # Device is available (discovered via Bluetooth scan)
        # However, we don't auto-connect anymore. User must manually click the Connect button.
        _LOGGER.info(
            "%s advertisement received: connectable=%s, rssi=%s",
            info.address,
            info.connectable,
            info.rssi,
        )
        
        # Mark device as discovered when we see any advertisement from it
        if not self._is_discovered:
            _LOGGER.info("%s is now marked as discovered (connectable=%s)", info.address, info.connectable)
            self._is_discovered = True  # Mark device as discovered
            # Update data to mark as available
            if self.data is not None:
                self.async_set_updated_data(replace(self.data, available=True))
            self.async_update_listeners()  # Notify entities of discovery state change
        
        # Always update last discovery time when we see any advertisement
        self._last_discovery_time = dt_util.utcnow()
        self._reconnect_attempts = 0  # Reset retry counter

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

    def _cancel_rediscovery_timer(self) -> None:
        """Cancel the rediscovery timer if active."""
        if self._rediscovery_timer_handle is not None:
            self._rediscovery_timer_handle.cancel()
            self._rediscovery_timer_handle = None

    def _schedule_rediscovery_scan(self) -> None:
        """Schedule a rediscovery scan check in 30 seconds."""
        self._cancel_rediscovery_timer()
        self._rediscovery_timer_handle = self.hass.loop.call_later(
            30,  # Check every 30 seconds
            self._trigger_rediscovery_scan,
        )

    def _trigger_rediscovery_scan(self) -> None:
        """Periodic check of device discovery status (logging only)."""
        self._rediscovery_timer_handle = None
        
        # Just log current discovery status for debugging
        if self._is_discovered:
            _LOGGER.debug("Device %s is still discovered", self.address)
        else:
            _LOGGER.debug("Device %s is not discovered", self.address)
        
        # Reschedule the check
        self._schedule_rediscovery_scan()

    def _unavailable_callback(self, info: BluetoothServiceInfoBleak) -> None:
        _LOGGER.debug("%s is no longer seen", info.address)
        if self._is_discovered or self._last_discovery_time is not None:
            self._is_discovered = False  # Mark device as not discovered
            self._last_discovery_time = None  # Clear discovery timestamp
            # Update data to mark as unavailable
            if self.data is not None:
                self.async_set_updated_data(replace(self.data, available=False))
            self.async_update_listeners()  # Notify entities of discovery state change
        self._set_unavailable()

    async def unload(self):
        """Disconnect and unload."""
        _LOGGER.debug("unload coordinator")
        self._cancel_disconnect_timer()
        self._cancel_rediscovery_timer()
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
        self._last_connection_attempt_time = dt_util.utcnow()  # Track connection attempt
        try:
            await self._client._connect()
            _LOGGER.info("Successfully connected to %s", self.address)
            await self.async_request_refresh()
        except Exception as err:
            _LOGGER.error("Failed to manually connect to %s: %s", self.address, err)
            # Ensure the connection state is updated to False on failure
            # Create a minimal disconnected state if we don't have data yet
            if self.data is not None:
                self.async_set_updated_data(replace(self.data, connected=False))
            else:
                # Initialize with disconnected state if no data exists yet
                # Use permissive permissions for disconnected state
                disconnected_permissions = VogelsMotionMountPermissions(
                    auth_status=None,  # type: ignore[arg-type]
                    change_settings=True,
                    change_default_position=True,
                    change_name=True,
                    change_presets=True,
                    change_tv_on_off_detection=True,
                    disable_channel=True,
                    start_calibration=True,
                )
                # Initialize 7 empty presets (as per CHAR_PRESET_UUIDS)
                empty_presets = [
                    VogelsMotionMountPreset(index=i, data=VogelsMotionMountPresetData(
                        name=f"Preset {i+1}",
                        distance=0,
                        rotation=0,
                    )) for i in range(7)
                ]
                disconnected_data = VogelsMotionMountData(
                    automove=None,
                    available=True,
                    connected=False,
                    distance=0,
                    freeze_preset_index=0,
                    multi_pin_features=VogelsMotionMountMultiPinFeatures(
                        change_default_position=True,
                        change_name=True,
                        change_presets=True,
                        change_tv_on_off_detection=True,
                        disable_channel=True,
                        start_calibration=True,
                    ),
                    name=None,  # type: ignore[arg-type]
                    pin_setting=None,  # type: ignore[arg-type]
                    presets=empty_presets,
                    rotation=0,
                    tv_width=65,
                    versions=VogelsMotionMountVersions(
                        ceb_bl_version="",
                        mcp_bl_version="",
                        mcp_fw_version="",
                        mcp_hw_version="",
                    ),
                    permissions=disconnected_permissions,
                )
                self.async_set_updated_data(disconnected_data)
            # Force immediate entity update
            self.async_update_listeners()
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

    @property
    def is_discovered(self) -> bool:
        """Return whether the device has been discovered via Bluetooth scan.
        
        A device is considered discovered if:
        1. It's currently connected (we're actively using it), OR
        2. We've received an advertisement from it (doesn't timeout)
        
        The device is only marked as NOT discovered if we explicitly receive
        an unavailable callback (device removed from BLE).
        """
        # If currently connected, device is definitely discovered
        if self._client.is_connected:
            return True
        
        # Device is discovered if we've seen it via BLE at least once
        # (flag is only cleared by unavailable callback)
        return self._is_discovered

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
        # NEW BEHAVIOR: Only fetch data if already connected.
        # Do not attempt to auto-connect during periodic updates.
        if not self._client.is_connected:
            _LOGGER.debug(
                "Device %s not connected. Skipping update. Click the Connect button to establish connection.",
                self.address,
            )
            # Return None or raise UpdateFailed to keep the coordinator offline until user connects
            raise UpdateFailed(
                translation_key="error_device_not_found",
                translation_placeholders={
                    "error": "Device not connected. Click the 'Connect' button to establish connection."
                },
            )
        
        # Retry once on transient connection errors (e.g., device not immediately ready after disconnect)
        max_retries = 2
        last_error = None
        
        # Check if we've exceeded max reconnect attempts
        if self._reconnect_attempts >= MAX_RECONNECT_ATTEMPTS:
            _LOGGER.error(
                "Maximum reconnection attempts (%d) exceeded for %s. "
                "Device may have DDoS protection active or is offline. "
                "Please ensure your Bluetooth adapter is functioning and the device is powered on.",
                MAX_RECONNECT_ATTEMPTS,
                self.address,
            )
            await self._async_handle_connection_error()
            raise UpdateFailed(
                translation_key="error_unknown",
                translation_placeholders={
                    "error": f"Maximum reconnection attempts ({MAX_RECONNECT_ATTEMPTS}) exceeded. "
                             "Check device is powered on and Bluetooth is functioning."
                },
            )
        
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
                    multi_pin_features=None,  # type: ignore[arg-type]
                    name=None,  # type: ignore[arg-type]
                    pin_setting=None,  # type: ignore[arg-type]
                    presets=await self._client.read_presets(),
                    rotation=await self._client.read_rotation(),
                    tv_width=65,
                    versions=await self._client.read_versions(),
                    permissions=permissions,
                )
                
                # Reset activity timer on successful update
                self._update_activity_timer()
                # Reset reconnect attempts on successful update
                self._reconnect_attempts = 0
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
                    _LOGGER.error(
                        "Connection lost for %s after %d attempts: %s",
                        self.address,
                        max_retries,
                        err,
                    )
                    await self._async_handle_connection_error()
                    raise UpdateFailed(translation_key="error_device_not_found") from err
            except BleakOutOfConnectionSlotsError as err:
                # BLE adapter is out of connection slots - force disconnect and wait before retry
                _LOGGER.error(
                    "BLE adapter out of connection slots for %s. Forcing disconnect and will retry.",
                    self.address,
                )
                await self._async_handle_connection_error()
                raise UpdateFailed(
                    translation_key="error_unknown",
                    translation_placeholders={
                        "error": "Bluetooth adapter out of connection slots. Try restarting your Bluetooth adapter or removing stale connections."
                    },
                ) from err
            except BleakConnectionError as err:
                # Handle connection errors with smart retry strategy
                _LOGGER.error(
                    "BLE connection error for %s: %s",
                    self.address,
                    err,
                )
                await self._async_handle_connection_error()
                # treat BleakConnectionErrors as device not found
                raise UpdateFailed(translation_key="error_device_not_found") from err
            except BleakNotFoundError as err:
                self._set_unavailable()
                _LOGGER.error("Device not found for %s: %s", self.address, err)
                # treat BleakNotFoundError as device not found
                raise UpdateFailed(translation_key="error_device_not_found") from err
            except Exception as err:
                self._set_unavailable()
                # Device unreachable → tell HA gracefully
                _LOGGER.error("Unexpected error fetching data for %s: %s", self.address, repr(err))
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

    async def _async_handle_connection_error(self):
        """Async version of handle connection error with automatic retry scheduling.
        
        Enforces both exponential backoff (for adapter recovery) and disconnect cooldown
        (to respect device DDoS prevention). Also implements a maximum retry limit to
        prevent infinite reconnection loops when device is genuinely offline.
        """
        self._reconnect_attempts += 1
        self._last_disconnect_time = dt_util.utcnow()
        _LOGGER.warning(
            "BLE connection error for %s. Attempt %d. Forcing disconnect to reset connection.",
            self.address,
            self._reconnect_attempts,
        )
        # Force disconnect to reset the BLE connection
        try:
            await self._client.disconnect()
        except Exception as err:
            _LOGGER.debug("Error while disconnecting during error handling: %s", err)
        
        # Check if we've hit the max retry limit for aggressive backoff
        if self._reconnect_attempts > MAX_RECONNECT_ATTEMPTS:
            _LOGGER.critical(
                "Maximum reconnection attempts (%d) exceeded for %s. "
                "Giving up. The device is likely offline or has DDoS protection active.",
                MAX_RECONNECT_ATTEMPTS,
                self.address,
            )
            self._set_unavailable()
            return
        
        # Calculate retry delay using exponential backoff
        # For first few attempts: quick retry (30-60 seconds)
        # For later attempts: longer delays (up to 2+ minutes)
        # Always respect the minimum disconnect cooldown
        if self._reconnect_attempts <= 5:
            # First few attempts: 30-60 second backoff
            exponential_delay = DISCONNECT_COOLDOWN_SECONDS + (self._reconnect_attempts * 5)
        elif self._reconnect_attempts <= 10:
            # Middle attempts: 1-2 minute backoff
            exponential_delay = 60 + (self._reconnect_attempts * 10)
        else:
            # Late attempts: 2+ minute backoff
            exponential_delay = 120 + ((self._reconnect_attempts - 10) * 15)
        
        # Cap at 5 minutes to avoid excessively long waits
        retry_delay = min(exponential_delay, 300.0)
        retry_delay = max(retry_delay, DISCONNECT_COOLDOWN_SECONDS)
        
        _LOGGER.info(
            "Scheduling automatic reconnection for %s in %.1f seconds (attempt %d/%d). "
            "This delay respects both adapter recovery time and device DDoS protection.",
            self.address,
            retry_delay,
            self._reconnect_attempts,
            MAX_RECONNECT_ATTEMPTS,
        )
        self.hass.loop.call_later(retry_delay, lambda: self.hass.async_create_task(self.async_request_refresh()))

