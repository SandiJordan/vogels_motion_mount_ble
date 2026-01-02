"""Button entities to define actions for Vogels Motion Mount BLE entities."""

from dataclasses import replace

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import async_get

from . import VogelsMotionMountNextBleConfigEntry
from .base import VogelsMotionMountNextBleBaseEntity, VogelsMotionMountNextBlePresetBaseEntity
from .coordinator import VogelsMotionMountNextBleCoordinator
from .data import VogelsMotionMountPresetData


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: VogelsMotionMountNextBleConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up the RefreshData and SelectPreset buttons."""
    coordinator: VogelsMotionMountNextBleCoordinator = config_entry.runtime_data

    buttons = [
        StartCalibrationButton(coordinator),
        RefreshDataButton(coordinator),
        SelectPresetDefaultButton(coordinator),
    ]

    # Only create select preset buttons for presets that have data
    if coordinator.data:
        for preset_index in range(7):
            if coordinator.data.presets[preset_index].data is not None:
                buttons.append(SelectPresetButton(coordinator, preset_index))

    async_add_entities(buttons)

    # Clean up old preset buttons that no longer have data
    entity_registry = async_get(hass)
    domain = "button"
    platform = "vogels_motion_mount_next_ble"
    
    # Create a list copy to avoid "dictionary changed size during iteration" error
    for entity in list(entity_registry.entities.values()):
        if entity.platform == platform and entity.domain == domain:
            # Check if it's a preset button and if the preset no longer has data
            if "select_preset_" in entity.unique_id and coordinator.data:
                try:
                    preset_index = int(entity.unique_id.split("_")[-1])
                    if preset_index >= 0 and preset_index < 7:
                        if coordinator.data.presets[preset_index].data is None:
                            entity_registry.async_remove(entity.entity_id)
                except (ValueError, IndexError):
                    pass


class StartCalibrationButton(VogelsMotionMountNextBleBaseEntity, ButtonEntity):
    """Set up the Button that provides an action to start the calibration."""

    _attr_unique_id = "start_calibration"
    _attr_translation_key = _attr_unique_id
    _attr_icon = "mdi:rotate-3d"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        """Set availability if user has permission."""
        return super().available and self.coordinator.data.permissions.start_calibration

    async def async_press(self):
        """Execute start calibration."""
        await self.coordinator.start_calibration()


class RefreshDataButton(VogelsMotionMountNextBleBaseEntity, ButtonEntity):
    """Set up the Button that provides an action to refresh data."""

    _attr_unique_id = "refresh_data"
    _attr_translation_key = _attr_unique_id
    _attr_icon = "mdi:refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        """Always available to try refresh data."""
        return True

    async def async_press(self):
        """Execute data refresh."""
        await self.coordinator.refresh_data()


class SelectPresetDefaultButton(VogelsMotionMountNextBleBaseEntity, ButtonEntity):
    """Set up the Buttons to select the default preset."""

    _attr_unique_id = "select_preset_default"
    _attr_translation_key = "select_preset_default"
    _attr_icon = "mdi:wall"

    async def async_press(self):
        """Return to home position (wall: distance=0, rotation=0)."""
        await self.coordinator._client.request_distance(0)
        await self.coordinator._client.request_rotation(0)


class SelectPresetButton(VogelsMotionMountNextBlePresetBaseEntity, ButtonEntity):
    """Set up the Buttons to select the custom presets."""

    _attr_translation_key = "select_preset_custom"
    _attr_icon = "mdi:rotate-3d"

    def __init__(
        self,
        coordinator: VogelsMotionMountNextBleCoordinator,
        preset_index: int,
    ) -> None:
        """Initialize unique_id because it's derived from preset_index."""
        super().__init__(
            coordinator=coordinator,
            preset_index=preset_index,
        )
        self._attr_unique_id = f"select_preset_{preset_index}"
        self._update_hidden_state()

    def _update_hidden_state(self) -> None:
        """Update hidden state based on whether preset has data."""
        if self._preset is None:
            self._attr_hidden = True
        else:
            self._attr_hidden = self._preset.data is None

    @property
    def name(self) -> str:
        """Return button name with current preset name."""
        if self._preset is None or not self._preset.data:
            return f"Preset {self._preset_index}"
        return self._preset.data.name

    @property
    def available(self) -> bool:
        """Only show button if preset has data."""
        if self._preset is None:
            return False
        return super().available and self._preset.data is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update button visibility when preset data changes."""
        self._update_hidden_state()
        self.async_write_ha_state()
        super()._handle_coordinator_update()

    async def async_press(self):
        """Select a custom preset by it's index."""
        await self.coordinator.select_preset(self._preset_index)


class DeletePresetButton(VogelsMotionMountNextBlePresetBaseEntity, ButtonEntity):
    """Set up the Buttons to delete the custom presets."""

    _attr_translation_key = "delete_preset_custom"
    _attr_icon = "mdi:delete"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: VogelsMotionMountNextBleCoordinator,
        preset_index: int,
    ) -> None:
        """Initialize unique_id because it's derived from preset_index."""
        super().__init__(coordinator, preset_index)
        self._attr_unique_id = f"delete_preset_{preset_index}"
        self._update_hidden_state()

    def _update_hidden_state(self) -> None:
        """Update hidden state based on whether preset has data."""
        if self._preset is None:
            self._attr_hidden = True
        else:
            self._attr_hidden = self._preset.data is None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update button visibility when preset data changes."""
        self._update_hidden_state()
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        """Set availability if preset exists and user has permission."""
        if self._preset is None:
            return False
        return (
            super().available
            and self.coordinator.data.permissions.change_presets
        )

    async def async_press(self):
        """Delete a custom preset by it's index."""
        if self._preset is None:
            return
        await self.coordinator.set_preset(replace(self._preset, data=None))


class AddPresetButton(VogelsMotionMountNextBlePresetBaseEntity, ButtonEntity):
    """Set up the Buttons to add the custom presets."""

    _attr_translation_key = "add_preset_custom"
    _attr_icon = "mdi:plus"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: VogelsMotionMountNextBleCoordinator,
        preset_index: int,
    ) -> None:
        """Initialize unique_id because it's derived from preset_index."""
        super().__init__(coordinator, preset_index)
        self._attr_unique_id = f"add_preset_{preset_index}"
        self._update_hidden_state()

    def _update_hidden_state(self) -> None:
        """Update hidden state based on whether preset has data."""
        if self._preset is None:
            self._attr_hidden = True
        else:
            self._attr_hidden = self._preset.data is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update button visibility when preset data changes."""
        self._update_hidden_state()
        super()._handle_coordinator_update()

    async def async_press(self):
        """Add a custom preset by it's index with empty data."""
        if self._preset is None:
            return
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

    @property
    def available(self) -> bool:
        """Set availability of this index of Preset entity based on the lengths of presets in the data."""
        return (
            self.coordinator.data
            and self.coordinator.data.available
            and (
                self.coordinator.data.presets[self._preset_index].data is None
                and self.coordinator.data.permissions.change_presets
            )
        )

