"""Number entities to define properties that can be changed for Vogels Motion Mount BLE entities."""

from dataclasses import replace

from homeassistant.components.number import NumberEntity, NumberMode  # type: ignore[import-untyped]
from homeassistant.const import EntityCategory  # type: ignore[import-untyped]
from homeassistant.core import HomeAssistant  # type: ignore[import-untyped]
from homeassistant.helpers.entity_platform import AddEntitiesCallback  # type: ignore[import-untyped]
from homeassistant.helpers.entity_registry import async_get  # type: ignore[import-untyped]

from . import VogelsMotionMountNextBleConfigEntry
from .base import VogelsMotionMountNextBleBaseEntity, VogelsMotionMountNextBlePresetBaseEntity
from .coordinator import VogelsMotionMountNextBleCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: VogelsMotionMountNextBleConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up the Numbers for distance, rotation and preset positions."""
    coordinator: VogelsMotionMountNextBleCoordinator = config_entry.runtime_data

    numbers = [
        DistanceNumber(coordinator),
        RotationNumber(coordinator),
    ]

    # Create preset distance/rotation numbers for all 7 presets
    # Availability will be controlled by the entities themselves
    for preset_index in range(7):
        numbers.append(PresetDistanceNumber(coordinator, preset_index))
        numbers.append(PresetRotationNumber(coordinator, preset_index))
    
    # Add BLE disconnect timeout to configuration section
    numbers.append(BleDisconnectTimeoutNumber(coordinator, config_entry))

    async_add_entities(numbers)

    # Clean up old preset number entities that no longer have data
    entity_registry = async_get(hass)
    domain = "number"
    platform = "vogels_motion_mount_next_ble"
    
    # Create a list copy to avoid "dictionary changed size during iteration" error
    for entity in list(entity_registry.entities.values()):
        if entity.platform == platform and entity.domain == domain:
            # Check if it's a preset number and if the preset no longer has data
            if "preset_" in entity.unique_id and ("_distance" in entity.unique_id or "_rotation" in entity.unique_id) and coordinator.data:
                try:
                    preset_index = int(entity.unique_id.split("_")[1])
                    if preset_index >= 0 and preset_index < 7:
                        if coordinator.data.presets[preset_index].data is None:
                            entity_registry.async_remove(entity.entity_id)
                except (ValueError, IndexError):
                    pass
    
    # Also clean up old-format preset entities (without the ordering number: preset_X_distance/rotation format)
    for entity in list(entity_registry.entities.values()):
        if entity.platform == platform and entity.domain == domain:
            if "preset_" in entity.unique_id and ("_distance" in entity.unique_id or "_rotation" in entity.unique_id):
                # Check if it's old format (count underscores = 2, not 3)
                if entity.unique_id.count("_") == 2:
                    entity_registry.async_remove(entity.entity_id)


class DistanceNumber(VogelsMotionMountNextBleBaseEntity, NumberEntity):
    """NumberEntity to set the distance."""

    _attr_unique_id = "distance"
    _attr_translation_key = _attr_unique_id
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_icon = "mdi:ruler"

    @property
    def native_value(self):
        """Return the state of the entity."""
        if not self.coordinator.data:
            return None
        if self.coordinator.data.requested_distance is not None:
            return self.coordinator.data.requested_distance
        return self.coordinator.data.distance

    @property
    def available(self) -> bool:
        """Only available when connected."""
        return self.coordinator.data is not None and self.coordinator.data.connected

    async def async_set_native_value(self, value: float) -> None:
        """Set the value from the UI."""
        await self.coordinator.request_distance(int(value))


class RotationNumber(VogelsMotionMountNextBleBaseEntity, NumberEntity):
    """NumberEntity to set the rotation."""

    _attr_unique_id = "rotation"
    _attr_translation_key = _attr_unique_id
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = -100
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_icon = "mdi:angle-obtuse"

    @property
    def native_value(self):  # pyright: ignore[reportIncompatibleVariableOverride]
        """Return the state of the entity."""
        if not self.coordinator.data:
            return None
        if self.coordinator.data.requested_rotation is not None:
            return self.coordinator.data.requested_rotation
        return self.coordinator.data.rotation

    @property
    def available(self) -> bool:
        """Only available when connected."""
        return self.coordinator.data is not None and self.coordinator.data.connected

    async def async_set_native_value(self, value: float) -> None:
        """Set the value from the UI."""
        await self.coordinator.request_rotation(int(value))


class PresetDistanceNumber(VogelsMotionMountNextBlePresetBaseEntity, NumberEntity):
    """NumberEntity to set distance of a preset."""

    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_icon = "mdi:ruler"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: VogelsMotionMountNextBleCoordinator, preset_index: int
    ) -> None:
        """Initialize unique_id because it's derived from preset_index."""
        super().__init__(coordinator, preset_index)
        self._attr_unique_id = f"preset_{preset_index}_2_distance"
        self._attr_name = f"{preset_index + 1}.2 Preset {preset_index + 1} - Distance"
        self._attr_translation_key = "preset_distance_custom"

    @property
    def available(self) -> bool:
        """Set availability if connected, preset exists and user has permission."""
        return (
            self.coordinator.data is not None 
            and self.coordinator.data.connected
            and self.coordinator.data.permissions.change_presets
            and self._preset is not None 
            and self._preset.data is not None
        )

    @property
    def native_value(self):
        """Return the current value."""
        if self._preset is None or not self._preset.data:
            return 0  # Return 0 instead of None so entity stays available
        return self._preset.data.distance

    async def async_set_native_value(self, value: float) -> None:
        """Set the value from the UI."""
        if self._preset is None:
            return
        if self._preset.data is None:
            # Create a new preset with default values if it doesn't exist
            from .data import VogelsMotionMountPresetData
            data = VogelsMotionMountPresetData(
                name=str(self._preset_index),
                distance=int(value),
                rotation=0,
            )
        else:
            data = replace(self._preset.data, distance=(int(value)))
        
        await self.coordinator.set_preset(
            replace(
                self._preset,
                data=data,
            )
        )


class PresetRotationNumber(VogelsMotionMountNextBlePresetBaseEntity, NumberEntity):
    """NumberEntity to set rotation of a preset."""

    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = -100
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_icon = "mdi:angle-obtuse"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: VogelsMotionMountNextBleCoordinator, preset_index: int
    ) -> None:
        """Initialize unique_id because it's derived from preset_index."""
        super().__init__(coordinator, preset_index)
        self._attr_unique_id = f"preset_{preset_index}_3_rotation"
        self._attr_name = f"{preset_index + 1}.3 Preset {preset_index + 1} - Rotation"
        self._attr_translation_key = "preset_rotation_custom"

    @property
    def available(self) -> bool:
        """Set availability if connected, preset exists and user has permission."""
        return (
            self.coordinator.data is not None 
            and self.coordinator.data.connected
            and self.coordinator.data.permissions.change_presets
            and self._preset is not None 
            and self._preset.data is not None
        )

    @property
    def native_value(self):
        """Return the current value."""
        if self._preset is None or not self._preset.data:
            return 0  # Return 0 instead of None so entity stays available
        return self._preset.data.rotation

    async def async_set_native_value(self, value: float) -> None:
        """Set the value from the UI."""
        if self._preset is None:
            return
        if self._preset.data is None:
            # Create a new preset with default values if it doesn't exist
            from .data import VogelsMotionMountPresetData
            data = VogelsMotionMountPresetData(
                name=str(self._preset_index),
                distance=0,
                rotation=int(value),
            )
        else:
            data = replace(self._preset.data, rotation=(int(value)))
        
        await self.coordinator.set_preset(
            replace(
                self._preset,
                data=data,
            )
        )


class BleDisconnectTimeoutNumber(VogelsMotionMountNextBleBaseEntity, NumberEntity):
    """Number entity to configure BLE disconnect timeout."""

    _attr_unique_id = "ble_disconnect_timeout"
    _attr_translation_key = _attr_unique_id
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 1
    _attr_native_max_value = 1440
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "minutes"
    _attr_icon = "mdi:bluetooth"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: VogelsMotionMountNextBleCoordinator, config_entry
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._config_entry = config_entry

    @property
    def available(self) -> bool:
        """Always available - this is an app configuration setting, not device-dependent."""
        return True

    @property
    def native_value(self):
        """Return the current timeout value."""
        return self._config_entry.data.get("ble_disconnect_timeout", 30)

    async def async_set_native_value(self, value: float) -> None:
        """Update the timeout configuration."""
        from homeassistant.core import HomeAssistant
        from .const import CONF_BLE_DISCONNECT_TIMEOUT
        
        self.hass.config_entries.async_update_entry(
            self._config_entry,
            data={
                **self._config_entry.data,
                CONF_BLE_DISCONNECT_TIMEOUT: int(value),
            },
        )
        # Reload the coordinator with new timeout
        self.coordinator._load_ble_disconnect_timeout(self._config_entry)
        if self.coordinator._client.is_connected:
            self.coordinator._update_activity_timer()

