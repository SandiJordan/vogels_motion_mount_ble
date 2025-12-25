"""Number entities to define properties that can be changed for Vogels Motion Mount BLE entities."""

from dataclasses import replace

from homeassistant.components.text import TextEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import async_get

from . import VogelsMotionMountBleConfigEntry
from .base import VogelsMotionMountBleBaseEntity, VogelsMotionMountBlePresetBaseEntity
from .coordinator import VogelsMotionMountBleCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: VogelsMotionMountBleConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up the TextEntities for name, preset names and pins."""
    coordinator: VogelsMotionMountBleCoordinator = config_entry.runtime_data

    async_add_entities(
        [
            NameText(coordinator),
        ]
    )

    # Clean up old preset name text entities that no longer have data
    entity_registry = async_get(hass)
    domain = "text"
    platform = "vogels_motion_mount_ble"
    
    # Create a list copy to avoid "dictionary changed size during iteration" error
    for entity in list(entity_registry.entities.values()):
        if entity.platform == platform and entity.domain == domain:
            # Check if it's a preset name and if the preset no longer has data
            if "preset_" in entity.unique_id and "_name" in entity.unique_id and coordinator.data:
                try:
                    preset_index = int(entity.unique_id.split("_")[1])
                    if preset_index >= 0 and preset_index < 7:
                        if coordinator.data.presets[preset_index].data is None:
                            entity_registry.async_remove(entity.entity_id)
                except (ValueError, IndexError):
                    pass
    
    # Also clean up old-format preset entities (without the ordering number: preset_X_name format)
    for entity in list(entity_registry.entities.values()):
        if entity.platform == platform and entity.domain == domain:
            if "preset_" in entity.unique_id and "_name" in entity.unique_id:
                # Check if it's old format (count underscores = 2, not 3)
                if entity.unique_id.count("_") == 2:
                    entity_registry.async_remove(entity.entity_id)


class NameText(VogelsMotionMountBleBaseEntity, TextEntity):
    """Implementation of a the Name Text."""

    _attr_unique_id = "name"
    _attr_translation_key = _attr_unique_id
    _attr_native_min = 1
    _attr_native_max = 20
    _attr_icon = "mdi:rename-box-outline"
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def native_value(self):
        """Return the state of the entity."""
        return self.coordinator.data.name

    @property
    def available(self) -> bool:
        """Set availability if user has permission."""
        return super().available and self.coordinator.data.permissions.change_name

    async def async_set_value(self, value: str) -> None:
        """Set the name value from the UI."""
        await self.coordinator.set_name(value)


class PresetNameText(VogelsMotionMountBlePresetBaseEntity, TextEntity):
    """Implementation of a the Preset Name text."""

    _attr_translation_key = "preset_name_custom"
    _attr_native_min = 1
    _attr_native_max = 32
    _attr_icon = "mdi:form-textbox"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: VogelsMotionMountBleCoordinator, preset_index: int
    ) -> None:
        """Initialize unique_id because it's derived from preset_index."""
        super().__init__(coordinator, preset_index)
        self._attr_unique_id = f"preset_{preset_index}_1_name"
        self._attr_name = f"{preset_index + 1}.1 Preset {preset_index + 1} - Name"

    @property
    def available(self) -> bool:
        """Set availability based on permissions, not preset data."""
        return (
            super().available
            and self.coordinator.data.permissions.change_presets
        )

    @property
    def native_value(self):
        """Return the current value."""
        if self._preset.data:
            return self._preset.data.name
        return ""  # Return empty string instead of None so entity stays available

    async def async_set_value(self, value: str) -> None:
        """Set the preset name value from the UI."""
        if self._preset.data is None:
            # Create a new preset with default values if it doesn't exist
            from .data import VogelsMotionMountPresetData
            data = VogelsMotionMountPresetData(
                name=value,
                distance=0,
                rotation=0,
            )
        else:
            data = replace(self._preset.data, name=value)
        
        await self.coordinator.set_preset(
            replace(self._preset, data=data)
        )
