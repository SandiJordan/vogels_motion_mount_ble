"""Sensor entities to define properties for Vogels Motion Mount BLE entities."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
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
    """Set up the Sensors for Distance and Rotation."""
    coordinator: VogelsMotionMountNextBleCoordinator = config_entry.runtime_data

    async_add_entities(
        [
            DiscoveryStatusSensor(coordinator),
            DistanceSensor(coordinator),
            RotationSensor(coordinator),
            CEBBLSensor(coordinator),
        ]
    )


class DistanceSensor(VogelsMotionMountNextBleBaseEntity, SensorEntity):
    """Sensor for current distance, may be different from requested distance."""

    _attr_unique_id = "current_distance"
    _attr_translation_key = "current_distance"
    _attr_icon = "mdi:ruler"

    @property
    def native_value(self):
        """Return the current value."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.distance


class DiscoveryStatusSensor(VogelsMotionMountNextBleBaseEntity, SensorEntity):
    """Sensor for BLE discovery status."""

    _attr_unique_id = "discovery_status"
    _attr_translation_key = "discovery_status"
    _attr_icon = "mdi:bluetooth"

    @property
    def native_value(self):
        """Return the discovery status."""
        return self.coordinator.is_discovered


class RotationSensor(VogelsMotionMountNextBleBaseEntity, SensorEntity):
    """Sensor for current rotation, may be different from requested rotation."""

    _attr_unique_id = "current_rotation"
    _attr_translation_key = "current_rotation"
    _attr_icon = "mdi:angle-obtuse"

    @property
    def native_value(self):
        """Return the state of the rotation or None."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.rotation


class CEBBLSensor(VogelsMotionMountNextBleBaseEntity, SensorEntity):
    """Sensor for CEB BL Version."""

    _attr_unique_id = "ceb_bl_version"
    _attr_translation_key = _attr_unique_id
    _attr_icon = "mdi:alpha-v"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        """Return the current value."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.versions.ceb_bl_version


class MCPHWSensor(VogelsMotionMountNextBleBaseEntity, SensorEntity):
    """Sensor for MCP HW Version."""

    _attr_unique_id = "mcp_hw_version"
    _attr_translation_key = _attr_unique_id
    _attr_icon = "mdi:alpha-v"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        """Return the current value."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.versions.mcp_hw_version


class MCPBLSensor(VogelsMotionMountNextBleBaseEntity, SensorEntity):
    """Sensor for MCP BL Version."""

    _attr_unique_id = "mcp_bl_version"
    _attr_translation_key = _attr_unique_id
    _attr_icon = "mdi:alpha-v"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        """Return the current value."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.versions.mcp_bl_version


class MCPFWSensor(VogelsMotionMountNextBleBaseEntity, SensorEntity):
    """Sensor for MCP FW Version."""

    _attr_unique_id = "mcp_fw_version"
    _attr_translation_key = _attr_unique_id
    _attr_icon = "mdi:alpha-v"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        """Return the current value."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.versions.mcp_fw_version


class PinSettingsSensor(VogelsMotionMountNextBleBaseEntity, SensorEntity):
    """Sensor for Pin Settings."""

    _attr_unique_id = "pin_settings"
    _attr_translation_key = _attr_unique_id
    _attr_icon = "mdi:cloud-key"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        """Return the current value."""
        if self.coordinator.data is None or self.coordinator.data.pin_setting is None:
            return None
        return self.coordinator.data.pin_setting.value


class AuthenticationSensor(VogelsMotionMountNextBleBaseEntity, SensorEntity):
    """Sensor for current Authentication level."""

    _attr_unique_id = "authentication"
    _attr_translation_key = _attr_unique_id
    _attr_icon = "mdi:server-security"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        """Return the current value."""
        if (
            self.coordinator.data is None
            or self.coordinator.data.permissions is None
            or self.coordinator.data.permissions.auth_status is None
        ):
            return None
        return self.coordinator.data.permissions.auth_status.auth_type.value

