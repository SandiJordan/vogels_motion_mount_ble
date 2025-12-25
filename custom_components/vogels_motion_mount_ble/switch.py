"""Button entities to define actions for Vogels Motion Mount BLE entities."""

from dataclasses import replace
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import async_get

from . import VogelsMotionMountBleConfigEntry
from .base import VogelsMotionMountBleBaseEntity, VogelsMotionMountBlePresetBaseEntity
from .coordinator import VogelsMotionMountBleCoordinator
from .data import VogelsMotionMountPresetData


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: VogelsMotionMountBleConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up the RefreshData and SelectPreset buttons."""
    coordinator: VogelsMotionMountBleCoordinator = config_entry.runtime_data

    switches = [ConnectionSwitch(coordinator)]
    
    # Add preset switches for all 7 preset slots
    switches.extend([PresetSwitch(coordinator, preset_index) for preset_index in range(7)])
    
    async_add_entities(switches)
    
    # Clean up old preset switch entities with old unique_id format
    entity_registry = async_get(hass)
    domain = "switch"
    platform = "vogels_motion_mount_ble"
    for entity in list(entity_registry.entities.values()):
        if entity.platform == platform and entity.domain == domain:
            if "preset_" in entity.unique_id and "_switch" in entity.unique_id:
                # Check if it's old format (count underscores = 2, not 3)
                if entity.unique_id.count("_") == 2:
                    entity_registry.async_remove(entity.entity_id)


class ConnectionSwitch(VogelsMotionMountBleBaseEntity, SwitchEntity):
    """Switch to control BLE device connection."""

    _attr_unique_id = "connection"
    _attr_translation_key = "connection"
    _attr_icon = "mdi:power-plug"

    @property
    def is_on(self) -> bool:
        """Return True if device is connected."""
        return self.coordinator.data.connected

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on (connect) the device."""
        await self.coordinator.connect()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off (disconnect) the device."""
        await self.coordinator.disconnect()


class PresetSwitch(VogelsMotionMountBlePresetBaseEntity, SwitchEntity):
    """Switch to manage preset existence - ON=exists, OFF=doesn't exist."""

    _attr_translation_key = "preset_config"
    _attr_icon = "mdi:bookmark"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: VogelsMotionMountBleCoordinator,
        preset_index: int,
    ) -> None:
        """Initialize unique_id because it's derived from preset_index."""
        super().__init__(
            coordinator=coordinator,
            preset_index=preset_index,
        )
        self._attr_unique_id = f"preset_{preset_index}_0_switch"
        self._attr_name = f"{preset_index + 1}. Preset {preset_index + 1}"

    @property
    def available(self) -> bool:
        """Always available to toggle presets on/off, regardless of data state."""
        return (
            self.coordinator.data is not None
            and self.coordinator.data.available
            and self.coordinator.data.permissions.change_presets
        )

    @property
    def is_on(self) -> bool:
        """Return True if preset has data."""
        return self._preset.data is not None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on (create) the preset with default values."""
        await self.coordinator.set_preset(
            replace(
                self._preset,
                data=VogelsMotionMountPresetData(
                    name=str(self._preset_index),
                    distance=0,
                    rotation=0,
                ),
            )
        )
        # Refresh the coordinator to update all entities
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off (delete) the preset."""
        await self.coordinator.set_preset(replace(self._preset, data=None))
        # Refresh the coordinator to update all entities
        await self.coordinator.async_request_refresh()


class MultiPinFeatureChangePresetsSwitch(VogelsMotionMountBleBaseEntity, SwitchEntity):
    """Set up the Switch to change multi pin feature change presets."""

    _attr_unique_id = "change_presets"
    _attr_translation_key = _attr_unique_id
    _attr_icon = "mdi:security"
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self) -> bool:
        """Set availability of multi pin features."""
        return (
            super().available
            and self.coordinator.data is not None
            and self.coordinator.data.permissions.change_settings
        )

    @property
    def is_on(self) -> bool:
        """Returns on if change_presets is enabled."""
        if self.coordinator.data is None or self.coordinator.data.multi_pin_features is None:
            return False
        return self.coordinator.data.multi_pin_features.change_presets

    async def async_turn_on(self, **_: Any):
        """Turn the entity on."""
        await self.async_toggle()

    async def async_turn_off(self, **_: Any):
        """Turn the entity off."""
        await self.async_toggle()

    async def async_toggle(self, **_: Any):
        """Toggle if change presets is on or off."""
        await self.coordinator.set_multi_pin_features(
            replace(
                self.coordinator.data.multi_pin_features, change_presets=not self.is_on
            )
        )


class MultiPinFeatureChangeNameSwitch(VogelsMotionMountBleBaseEntity, SwitchEntity):
    """Set up the Switch to change multi pin feature change name."""

    _attr_unique_id = "change_name"
    _attr_translation_key = _attr_unique_id
    _attr_icon = "mdi:security"
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self) -> bool:
        """Set availability of multi pin features."""
        return (
            super().available
            and self.coordinator.data is not None
            and self.coordinator.data.permissions.change_settings
        )

    @property
    def is_on(self) -> bool:
        """Returns on if change presets is enabled."""
        if self.coordinator.data is None or self.coordinator.data.multi_pin_features is None:
            return False
        return self.coordinator.data.multi_pin_features.change_name

    async def async_turn_on(self, **_: Any):
        """Turn the entity on."""
        await self.async_toggle()

    async def async_turn_off(self, **_: Any):
        """Turn the entity off."""
        await self.async_toggle()

    async def async_toggle(self, **_: Any):
        """Toggle if change name is on or off."""
        await self.coordinator.set_multi_pin_features(
            replace(
                self.coordinator.data.multi_pin_features, change_name=not self.is_on
            )
        )


class MultiPinFeatureDisableChannelSwitch(VogelsMotionMountBleBaseEntity, SwitchEntity):
    """Set up the Switch to change multi pin feature disable channel."""

    _attr_unique_id = "disable_channel"
    _attr_translation_key = _attr_unique_id
    _attr_icon = "mdi:security"
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self) -> bool:
        """Set availability of multi pin features."""
        return (
            super().available
            and self.coordinator.data is not None
            and self.coordinator.data.permissions.change_settings
        )

    @property
    def is_on(self) -> bool:
        """Returns on if disable channel is enabled."""
        if self.coordinator.data is None or self.coordinator.data.multi_pin_features is None:
            return False
        return self.coordinator.data.multi_pin_features.disable_channel

    async def async_turn_on(self, **_: Any):
        """Turn the entity on."""
        await self.async_toggle()

    async def async_turn_off(self, **_: Any):
        """Turn the entity off."""
        await self.async_toggle()

    async def async_toggle(self, **_: Any):
        """Toggle if disable channeld is on or off."""
        await self.coordinator.set_multi_pin_features(
            replace(
                self.coordinator.data.multi_pin_features, disable_channel=not self.is_on
            )
        )


class MultiPinFeatureChangeTvOnOffDetectionSwitch(
    VogelsMotionMountBleBaseEntity, SwitchEntity
):
    """Set up the Switch to change multi pin feature change tv on off detection."""

    _attr_unique_id = "change_tv_on_off_detection"
    _attr_translation_key = _attr_unique_id
    _attr_icon = "mdi:security"
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self) -> bool:
        """Set availability of multi pin features."""
        return (
            super().available
            and self.coordinator.data is not None
            and self.coordinator.data.permissions.change_settings
        )

    @property
    def is_on(self) -> bool:
        """Returns on if change tv on off detection is enabled."""
        if self.coordinator.data is None or self.coordinator.data.multi_pin_features is None:
            return False
        return self.coordinator.data.multi_pin_features.change_tv_on_off_detection

    async def async_turn_on(self, **_: Any):
        """Turn the entity on."""
        await self.async_toggle()

    async def async_turn_off(self, **_: Any):
        """Turn the entity off."""
        await self.async_toggle()

    async def async_toggle(self, **_: Any):
        """Toggle if change tv on off detection is on or off."""
        await self.coordinator.set_multi_pin_features(
            replace(
                self.coordinator.data.multi_pin_features,
                change_tv_on_off_detection=not self.is_on,
            )
        )


class MultiPinFeatureChangeDefaultPositionSwitch(
    VogelsMotionMountBleBaseEntity, SwitchEntity
):
    """Set up the Switch to change multi pin feature change default position."""

    _attr_unique_id = "change_default_position"
    _attr_translation_key = _attr_unique_id
    _attr_icon = "mdi:security"
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self) -> bool:
        """Set availability of multi pin features."""
        return (
            super().available
            and self.coordinator.data is not None
            and self.coordinator.data.permissions.change_settings
        )

    @property
    def is_on(self) -> bool:
        """Returns on if change default position is enabled."""
        if self.coordinator.data is None or self.coordinator.data.multi_pin_features is None:
            return False
        return self.coordinator.data.multi_pin_features.change_default_position

    async def async_turn_on(self, **_: Any):
        """Turn the entity on."""
        await self.async_toggle()

    async def async_turn_off(self, **_: Any):
        """Turn the entity off."""
        await self.async_toggle()

    async def async_toggle(self, **_: Any):
        """Toggle if change default position is on or off."""
        await self.coordinator.set_multi_pin_features(
            replace(
                self.coordinator.data.multi_pin_features,
                change_default_position=not self.is_on,
            )
        )


class MultiPinFeatureStartCalibrationSwitch(
    VogelsMotionMountBleBaseEntity, SwitchEntity
):
    """Set up the Switch to change multi pin feature start calibration."""

    _attr_unique_id = "start_calibration"
    _attr_translation_key = _attr_unique_id
    _attr_icon = "mdi:security"
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self) -> bool:
        """Set availability of multi pin features."""
        return (
            super().available
            and self.coordinator.data is not None
            and self.coordinator.data.permissions.change_settings
        )

    @property
    def is_on(self) -> bool:
        """Returns on if change start calibration is enabled."""
        if self.coordinator.data is None or self.coordinator.data.multi_pin_features is None:
            return False
        return self.coordinator.data.multi_pin_features.start_calibration

    async def async_turn_on(self, **_: Any):
        """Turn the entity on."""
        await self.async_toggle()

    async def async_turn_off(self, **_: Any):
        """Turn the entity off."""
        await self.async_toggle()

    async def async_toggle(self, **_: Any):
        """Toggle if start calibration is on or off."""
        await self.coordinator.set_multi_pin_features(
            replace(
                self.coordinator.data.multi_pin_features,
                start_calibration=not self.is_on,
            )
        )
