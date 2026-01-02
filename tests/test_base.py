"""Tests for base entities."""

from unittest.mock import MagicMock

import pytest

from custom_components.vogels_motion_mount_next_ble.base import (
    VogelsMotionMountNextBleBaseEntity,
)
from custom_components.vogels_motion_mount_next_ble.coordinator import (
    VogelsMotionMountNextBleCoordinator,
)
from homeassistant.core import HomeAssistant


@pytest.mark.asyncio
async def test_handle_coordinator_update_triggers_state_write(
    hass: HomeAssistant,
    mock_coord: VogelsMotionMountNextBleCoordinator,
):
    """Test that _handle_coordinator_update calls async_write_ha_state."""

    # Create entity with coordinator
    entity = VogelsMotionMountNextBleBaseEntity(mock_coord)

    # Patch async_write_ha_state
    entity.async_write_ha_state = MagicMock()

    hass.async_add_job(entity._handle_coordinator_update)  # noqa: SLF001
    await hass.async_block_till_done()

    # Verify async_write_ha_state was called
    entity.async_write_ha_state.assert_called_once()

