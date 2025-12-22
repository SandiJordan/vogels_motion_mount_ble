"""Defines the bluetooth client to control the Vogels Motion Mount."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional
import logging
import struct

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from .const import (
    #CHAR_AUTHENTICATE_UUID,
    CHAR_AUTOMOVE_UUID,
    CHAR_CALIBRATE_UUID,
    #CHAR_CHANGE_PIN_UUID,
    CHAR_DISABLE_CHANNEL,
    CHAR_DISTANCE_UUID,
    CHAR_FREEZE_UUID,
    #CHAR_MULTI_PIN_FEATURES_UUID,
    #CHAR_NAME_UUID,
    #CHAR_PIN_CHECK_UUID,
    #CHAR_PIN_SETTINGS_UUID,
    CHAR_PRESET_NAMES_UUIDS,
    CHAR_PRESET_UUID,
    CHAR_PRESET_UUIDS,
    CHAR_ROTATION_UUID,
    CHAR_VERSIONS_CEB_UUID,
    CHAR_VERSIONS_MCP_UUID,
)
from .data import (
    #VogelsMotionMountAuthenticationStatus,
    #VogelsMotionMountAuthenticationType,
    VogelsMotionMountAutoMoveType,
    VogelsMotionMountPreset,
    VogelsMotionMountPresetData,
    VogelsMotionMountVersions,
    VogelsMotionMountPermissions,
)

_LOGGER = logging.getLogger(__name__)

# -------------------------------
# region Exceptions
# -------------------------------


class VogelsMotionMountClientAuthenticationError(Exception):
    """Exception class if user is not authorized to do this action."""

    def __init__(self, cooldown: int, message: str = "Unauthorized") -> None:
        """Initialize APIAuthenticationError with cooldown and optional message."""
        super().__init__(message)
        self.cooldown = cooldown

    # -------------------------------
    # region Setup
    # -------------------------------


class VogelsMotionMountBluetoothClient:
    """Bluetooth client for controlling the Vogels Motion Mount.

    Handles connection, authentication, reading and writing characteristics,
    and permission management for the Vogels Motion Mount BLE device.
    """

    def __init__(
        self,
        pin: int | None = None,
        device: BLEDevice = None,
        permission_callback: Callable[[Optional[VogelsMotionMountPermissions]], None] = None,
        connection_callback: Callable[[bool], None] = None,
        distance_callback: Callable[[int], None] = None,
        rotation_callback: Callable[[int], None] = None,
    ) -> None:
        """Initialize the Vogels Motion Mount Bluetooth client.

        Args:
            pin: The PIN code for authentication, or None.
            device: The BLEDevice instance representing the mount.
            permission_callback: Callback for permission updates.
            connection_callback: Callback for connection state changes.
            distance_callback: Callback for distance updates.
            rotation_callback: Callback for rotation updates.
        """
        # keep the pin around for compatibility/future use
        self._pin = pin
        self._device = device
        if self._device is None:
            raise ValueError("device must be provided to VogelsMotionMountBluetoothClient")
        self._connection_callback = connection_callback
        self._permission_callback = permission_callback
        self._distance_callback = distance_callback
        self._rotation_callback = rotation_callback
        self._session_data: _VogelsMotionMountSessionData | None = None
        self._connect_lock = asyncio.Lock()

    # -------------------------------
    # region Read
    # -------------------------------

    async def read_permissions(self) -> VogelsMotionMountPermissions:
        """Read and return the current permissions for the connected Vogels Motion Mount.
        If no explicit permissions object is present, return a permissive default."""
        session = await self._connect()
        return session.permissions or _make_full_permissions()

    async def read_automove(self) -> VogelsMotionMountAutoMoveType:
        """Read and return the current automove type for the Vogels Motion Mount."""
        try:
            data = await self._read(CHAR_AUTOMOVE_UUID)
            if not data:
                raise RuntimeError("Empty automove characteristic")
            return VogelsMotionMountAutoMoveType(int.from_bytes(data, "big"))
        except Exception as err:
            _LOGGER.exception("Failed to read automove: %s", err)
            raise RuntimeError(f"Failed to read automove: {err}") from err

    async def read_distance(self) -> int:
        """Read and return the current distance value from the Vogels Motion Mount."""
        try:
            data = await self._read(CHAR_DISTANCE_UUID)
            if not data:
                raise RuntimeError("Empty distance characteristic")
            return int.from_bytes(data, "big")
        except Exception as err:
            _LOGGER.exception("Failed to read distance: %s", err)
            raise RuntimeError(f"Failed to read distance: {err}") from err

    async def read_freeze_preset_index(self) -> int:
        """Read and return the index of the current freeze preset from the Vogels Motion Mount."""
        try:
            data = await self._read(CHAR_FREEZE_UUID)
            if not data:
                raise RuntimeError("Empty freeze preset characteristic")
            return data[0]
        except Exception as err:
            _LOGGER.exception("Failed to read freeze preset index: %s", err)
            raise RuntimeError(f"Failed to read freeze preset index: {err}") from err

    """
    async def read_multi_pin_features(self) -> VogelsMotionMountMultiPinFeatures:
        #Read and return the current multi-pin feature flags from the Vogels Motion Mount.
        data = (await self._read(CHAR_MULTI_PIN_FEATURES_UUID))[0]
        return VogelsMotionMountMultiPinFeatures(
            change_presets=bool(data & (1 << 0)),
            change_name=bool(data & (1 << 1)),
            disable_channel=bool(data & (1 << 2)),
            change_tv_on_off_detection=bool(data & (1 << 3)),
            change_default_position=bool(data & (1 << 4)),
            start_calibration=bool(data & (1 << 7)),
        )
    """
    async def read_presets(self) -> list[VogelsMotionMountPreset]:
        """Read and return a list of all preset configurations from the Vogels Motion Mount."""
        return [
            await self.read_preset(index) for index in range(len(CHAR_PRESET_UUIDS))
        ]

    async def read_preset(self, index: int) -> VogelsMotionMountPreset:
        """Read and return the preset configuration at the specified index."""
        try:
            data = await self._read(CHAR_PRESET_UUIDS[index]) + await self._read(
                CHAR_PRESET_NAMES_UUIDS[index]
            )
            if data[0] != 0:
                data = VogelsMotionMountPresetData(
                    distance=max(0, min(int.from_bytes(data[1:3], "big"), 100)),
                    name=data[5:].decode("utf-8").rstrip("\x00"),
                    rotation=max(
                        -100, min(int.from_bytes(data[3:5], "big", signed=True), 100)
                    ),
                )
            else:
                data = None

            return VogelsMotionMountPreset(
                index=index,
                data=data,
            )
        except Exception as err:
            _LOGGER.exception("Failed to read preset %d: %s", index, err)
            raise RuntimeError(f"Failed to read preset {index}: {err}") from err

    async def read_rotation(self) -> int:
        """Read and return the current rotation value from the Vogels Motion Mount."""
        try:
            data = await self._read(CHAR_ROTATION_UUID)
            if not data:
                raise RuntimeError("Empty rotation characteristic")
            # Rotation is signed on the device
            return int.from_bytes(data, "big", signed=True)
        except Exception as err:
            _LOGGER.exception("Failed to read rotation: %s", err)
            raise RuntimeError(f"Failed to read rotation: {err}") from err

    async def read_versions(self) -> VogelsMotionMountVersions:
        """Read and return the firmware and hardware version information from the Vogels Motion Mount."""
        try:
            try:
                data_ceb = await self._read(CHAR_VERSIONS_CEB_UUID)
            except Exception as err:
                _LOGGER.debug("Failed to read CEB versions (characteristic may not be supported): %s", err)
                data_ceb = None
            
            try:
                data_mcp = await self._read(CHAR_VERSIONS_MCP_UUID)
            except Exception as err:
                _LOGGER.debug("Failed to read MCP versions (characteristic may not be supported): %s", err)
                data_mcp = None
            
            return VogelsMotionMountVersions(
                ceb_bl_version=".".join(str(b) for b in data_ceb) if data_ceb else "Unknown",
                mcp_hw_version=".".join(str(b) for b in data_mcp[:3]) if data_mcp else "Unknown",
                mcp_bl_version=".".join(str(b) for b in data_mcp[3:5]) if data_mcp else "Unknown",
                mcp_fw_version=".".join(str(b) for b in data_mcp[5:7]) if data_mcp else "Unknown",
            )
        except Exception as err:
            _LOGGER.debug("Failed to read versions: %s", err)
            return VogelsMotionMountVersions(
                ceb_bl_version="Unknown",
                mcp_hw_version="Unknown",
                mcp_bl_version="Unknown",
                mcp_fw_version="Unknown",
            )

    # -------------------------------
    # region Control
    # -------------------------------

    async def disconnect(self):
        """Disconnect from the Vogels Motion Mount BLE device if connected."""
        if self._session_data:
            try:
                await self._session_data.client.disconnect()
            except Exception as err:
                _LOGGER.debug("Error while disconnecting: %s", err)
            finally:
                self._session_data = None
                if self._connection_callback:
                    self._connection_callback(False)

    async def select_preset(self, preset_index: int):
        """Select the preset at the given index on the Vogels Motion Mount."""
        # Only allow indexes that match the available preset characteristic lists
        assert preset_index in range(len(CHAR_PRESET_UUIDS))
        await self._write(CHAR_PRESET_UUID, bytes([preset_index]))

    async def start_calibration(self):
        """Start the calibration process on the Vogels Motion Mount."""
        await self._write(CHAR_CALIBRATE_UUID, bytes([1]))

    # -------------------------------
    # region Write
    # -------------------------------

    async def request_distance(self, distance: int):
        """Set the distance value on the Vogels Motion Mount."""
        assert distance in range(101)
        await self._write(
            char_uuid=CHAR_DISTANCE_UUID,
            data=int(distance).to_bytes(2, byteorder="big"),
        )

    async def request_rotation(self, rotation: int):
        """Set the rotation value on the Vogels Motion Mount."""
        assert rotation in range(-100, 101)
        await self._write(
            char_uuid=CHAR_ROTATION_UUID,
            data=int(rotation).to_bytes(2, byteorder="big", signed=True),
        )
    """
    async def set_authorised_user_pin(self, pin: str):
        #Set the authorised user PIN on the Vogels Motion Mount.
        assert pin.isdigit()
        assert len(pin) == 4
        await self._write(
            char_uuid=CHAR_CHANGE_PIN_UUID,
            data=int(pin).to_bytes(2, byteorder="little"),
        )
    """
    async def set_automove(self, automove: VogelsMotionMountAutoMoveType):
        """Set the automove type on the Vogels Motion Mount."""
        await self._write(
            char_uuid=CHAR_AUTOMOVE_UUID,
            data=int(automove.value).to_bytes(2, byteorder="big"),
        )

    async def set_freeze_preset(self, preset_index: int):
        """Set the freeze preset index on the Vogels Motion Mount."""
        assert preset_index in range(8)
        await self._write(
            char_uuid=CHAR_FREEZE_UUID,
            data=bytes([preset_index]),
        )
    """
    async def set_multi_pin_features(self, features: VogelsMotionMountMultiPinFeatures):
        #Set the multi-pin features on the Vogels Motion Mount.
        value = 0
        value |= int(features.change_presets) << 0
        value |= int(features.change_name) << 1
        value |= int(features.disable_channel) << 2
        value |= int(features.change_tv_on_off_detection) << 3
        value |= int(features.change_default_position) << 4
        value |= int(features.start_calibration) << 7
        await self._write(
            char_uuid=CHAR_MULTI_PIN_FEATURES_UUID,
            data=bytes([value]),
        )
    """
    async def set_preset(self, preset: VogelsMotionMountPreset):
        """Set the data of a preset on the Vogels Motion Mount."""
        assert preset.index in range(len(CHAR_PRESET_UUIDS))
        if preset.data:
            assert preset.data.distance in range(101)
            assert preset.data.rotation in range(-100, 101)
            assert len(preset.data.name) in range(1, 33)
            data = (
                b"\x01"
                + int(preset.data.distance).to_bytes(2, byteorder="big")
                + int(preset.data.rotation).to_bytes(2, byteorder="big", signed=True)
                + preset.data.name.encode("utf-8")
            )
        else:
            data = b"\x00"

        await self._write(
            char_uuid=CHAR_PRESET_UUIDS[preset.index],
            data=data[:20].ljust(20, b"\x00"),
        )
        await self._write(
            char_uuid=CHAR_PRESET_NAMES_UUIDS[preset.index],
            data=data[20:].ljust(17, b"\x00"),
        )
    """
    async def set_supervisior_pin(self, pin: str):
        #Set the supervisior PIN on the Vogels Motion Mount.
        assert len(pin) == 4
        assert pin.isdigit()
        await self._write(
            char_uuid=CHAR_CHANGE_PIN_UUID, data=_encode_supervisior_pin(int(pin))
        )
    """

    # -------------------------------
    # region Connection
    # -------------------------------

    async def _connect(self) -> _VogelsMotionMountSessionData:
        """Connect to the device if not already connected. Read auth status and store it in session data."""
        async with self._connect_lock:
            _LOGGER.debug("Connecting to device %s", self._device.address)
            if self._session_data:
                _LOGGER.debug("Already connected")
                return self._session_data

            try:
                client = await establish_connection(
                    client_class=BleakClientWithServiceCache,
                    device=self._device,
                    name=self._device.name or "Unknown Device",
                    disconnected_callback=self._handle_disconnect,
                )
            except Exception as err:
                _LOGGER.exception("Failed to connect to %s: %s", self._device.address, err)
                raise ConnectionError(f"Failed to connect to {self._device.address}: {err}") from err

            # Device doesn't support PIN/auth — give full permissive permissions so writes work
            self._session_data = _VogelsMotionMountSessionData(
                client=client,
                permissions=_make_full_permissions(),
            )
            # Try to setup notifications but don't fail the entire connect on notification errors.
            try:
                await self._setup_notifications(client)
            except Exception as err:  # pragma: no cover - runtime BLE issues
                _LOGGER.warning("Failed to setup notifications: %s", err)
            if self._permission_callback:
                self._permission_callback(self._session_data.permissions)
            if self._connection_callback:
                self._connection_callback(self._session_data.client.is_connected)
            return self._session_data

    def _handle_disconnect(self, _: BleakClient):
        """Reset session and call connection callback."""
        self._session_data = None
        if self._connection_callback:
            self._connection_callback(False)

    async def _read(self, char_uuid: str) -> bytes:
        """Read data by first connecting and then returning the read data."""
        session_data = await self._connect()
        try:
            data = await session_data.client.read_gatt_char(char_uuid)
            _LOGGER.debug("Read data %s | %s", char_uuid, data)
            return data
        except Exception as err:
            _LOGGER.exception("Failed to read characteristic %s: %s", char_uuid, err)
            raise RuntimeError(f"Failed to read characteristic {char_uuid}: {err}") from err

    async def _write(self, char_uuid: str, data: bytes):
        """Writes data by first connecting, checking permission status and then writing data. Also reads updated data that is then returned to be verified."""
        session_data = await self._connect()
        if not self._has_write_permission(char_uuid, session_data.permissions):
            # Provide a clearer message to make debugging easier
            raise VogelsMotionMountClientAuthenticationError(
                cooldown=0, message=f"Write denied for char {char_uuid}"
            )
        try:
            await session_data.client.write_gatt_char(char_uuid, data)
            _LOGGER.debug("Wrote data %s | %s", char_uuid, data)
        except Exception as err:
            _LOGGER.exception("Failed to write characteristic %s: %s", char_uuid, err)
            raise RuntimeError(f"Failed to write characteristic {char_uuid}: {err}") from err

    def _has_write_permission(
        self, char_uuid: str, permissions: Optional[VogelsMotionMountPermissions]
    ) -> bool:
        # If no permissions object is provided assume device is permissive (no auth)
        if permissions is None:
            return True

        # Evaluate allowed writes: presets (single or list), names, disable channel, freeze,
        # calibrate or global change_settings permission.
        return bool(
            (
                (char_uuid in CHAR_PRESET_UUIDS)
                or (char_uuid in CHAR_PRESET_NAMES_UUIDS)
                or (char_uuid == CHAR_PRESET_UUID)
            )
            and permissions.change_presets
            or (char_uuid == CHAR_DISABLE_CHANNEL and permissions.disable_channel)
            or (char_uuid == CHAR_FREEZE_UUID and permissions.change_tv_on_off_detection)
            or (char_uuid == CHAR_CALIBRATE_UUID and permissions.start_calibration)
            or permissions.change_settings
        )

    # -------------------------------
    # region Notifications
    # -------------------------------

    async def _setup_notifications(self, client: BleakClient):
        """Setup notifications for distance and rotation changes."""
        # Start notifications individually and log but do not raise on failure
        try:
            await client.start_notify(
                char_specifier=CHAR_DISTANCE_UUID,
                callback=self._handle_distance_change,
            )
        except Exception as err:
            _LOGGER.warning("Failed to start distance notifications: %s", err)
        try:
            await client.start_notify(
                char_specifier=CHAR_ROTATION_UUID,
                callback=self._handle_rotation_change,
            )
        except Exception as err:
            _LOGGER.warning("Failed to start rotation notifications: %s", err)

    def _handle_distance_change(
        self, _: BleakGATTCharacteristic | None, data: bytearray
    ):
        if self._distance_callback:
            self._distance_callback(int.from_bytes(data, "big"))

    def _handle_rotation_change(
        self, _: BleakGATTCharacteristic | None, data: bytearray
    ):
        if self._rotation_callback:
            self._rotation_callback(int.from_bytes(data, "big", signed=True))

    # -------------------------------
    # region Permission
    # -------------------------------


def _make_full_permissions():
    """Return a permissive permissions object for devices without auth.
    Try constructing the real VogelsMotionMountPermissions if signature allows,
    otherwise fall back to a SimpleNamespace with the expected attributes.
    """
    try:
        # Best-effort: try to construct with named booleans (common signature)
        return VogelsMotionMountPermissions(
            auth_status=None,
            change_settings=True,
            change_default_position=True,
            change_name=True,
            change_presets=True,
            change_tv_on_off_detection=True,
            disable_channel=True,
            start_calibration=True,
        )
    except Exception:
        from types import SimpleNamespace

        return SimpleNamespace(
            change_settings=True,
            change_default_position=True,
            change_name=True,
            change_presets=True,
            change_tv_on_off_detection=True,
            disable_channel=True,
            start_calibration=True,
        )


@dataclass
class _VogelsMotionMountSessionData:
    client: BleakClient
    permissions: Optional[VogelsMotionMountPermissions] = None
