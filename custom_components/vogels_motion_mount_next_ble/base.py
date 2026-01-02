"""Base entity to define common properties and methods for Vogels Motion Mount BLE entities."""

from propcache.api import cached_property

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VogelsMotionMountNextBleCoordinator
from .data import VogelsMotionMountPreset


class VogelsMotionMountNextBleBaseEntity(
    CoordinatorEntity[VogelsMotionMountNextBleCoordinator]
):
    """Base Entity Class for all Entities."""

    _attr_has_entity_name: bool = True

    @cached_property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            name=self.coordinator.name,
            manufacturer="Vogel's",
            model="Motion Mount",
            identifiers={(DOMAIN, self.coordinator.address)},
        )

    @property
    def available(self) -> bool:
        """Set availability of the entities only when the ble device is available."""
        return self.coordinator.data and self.coordinator.data.available

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update sensor with latest data from coordinator."""
        self.async_write_ha_state()


class VogelsMotionMountNextBlePresetBaseEntity(VogelsMotionMountNextBleBaseEntity):
    """Base Entity Class For Preset Entities."""

    def __init__(
        self,
        coordinator: VogelsMotionMountNextBleCoordinator,
        preset_index: int,
    ) -> None:
        """Initialise entity."""
        super().__init__(coordinator=coordinator)
        self._preset_index = preset_index
        self._update_translation_placeholders()

    def _update_translation_placeholders(self) -> None:
        """Update translation placeholders with preset info."""
        if self.coordinator.data is None:
            self._attr_translation_placeholders = {
                "preset": str(self._preset_index),
                "preset_name": f"Preset {self._preset_index}",
            }
            return
        preset = self._preset
        preset_name = preset.data.name if preset.data else f"Preset {self._preset_index}"
        self._attr_translation_placeholders = {
            "preset": str(self._preset_index),
            "preset_name": preset_name,
        }

    @property
    def available(self) -> bool:
        """Set availability of this index of Preset entity based if there is dat astored in the preset."""
        if self._preset is None:
            return False
        return super().available and self._preset.data is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update sensor with latest data from coordinator and refresh preset name."""
        self._update_translation_placeholders()
        super()._handle_coordinator_update()

    @property
    def _preset(self) -> VogelsMotionMountPreset | None:
        """Preset."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.presets[self._preset_index]

