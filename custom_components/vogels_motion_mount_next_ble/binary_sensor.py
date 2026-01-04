"""Binary sensor entities to define properties for Vogels Motion Mount BLE entities."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import VogelsMotionMountNextBleConfigEntry
from .base import VogelsMotionMountNextBleBaseEntity
from .coordinator import VogelsMotionMountNextBleCoordinator


async def async_setup_entry(
    _: HomeAssistant,
    config_entry: VogelsMotionMountNextBleConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up the connection Sensors."""
    coordinator: VogelsMotionMountNextBleCoordinator = config_entry.runtime_data
    async_add_entities([
        DiscoveredBinarySensor(coordinator),
        ConnectionBinarySensor(coordinator),
    ])


class DiscoveredBinarySensor(VogelsMotionMountNextBleBaseEntity, BinarySensorEntity):
    """Sensor to indicate if the Vogels Motion Mount has been discovered via Bluetooth."""

    _attr_unique_id = "discovered"
    _attr_translation_key = _attr_unique_id
    _attr_device_class = BinarySensorDeviceClass.PRESENCE

    @property
    def is_on(self):
        """Return if the MotionMount is discovered."""
        # Device is discovered if we have any data or if it's available
        return self.coordinator.data is not None and self.coordinator.data.available

    @property
    def icon(self):
        """Return icon."""
        return "mdi:bluetooth" if self.is_on else "mdi:bluetooth-off"


class ConnectionBinarySensor(VogelsMotionMountNextBleBaseEntity, BinarySensorEntity):
    """Sensor to indicate if the Vogels Motion Mount is connected."""

    _attr_unique_id = "connection"
    _attr_translation_key = _attr_unique_id
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self):
        """Return if the MotionMount is currently connected."""
        if self.coordinator.data is None:
            return False
        return self.coordinator.data.connected

    @property
    def icon(self):
        """Return icon."""
        return "mdi:wifi" if self.is_on else "mdi:wifi-off"

