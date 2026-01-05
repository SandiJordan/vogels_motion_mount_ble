# Vogel's MotionMount NEXT Bluetooth Home Assistant Integratioon

Home Assistant integration allows to control the Vogel's MotionMount NEXT over Bluetooth Low Energy (BLE). It has been tested with NEXT 7355 model, but probably works with all NEXT models that do not require any authentication via PIN.

## High-level description & use cases

This integration exposes the MotionMount as local devices and entities in Home Assistant so you can:

- Connect/disconnect from MotionMount
- Move the mount forward/backward and rotate left/right (percentage-based control).
- Call presets and enable/configure/disable presets.
- Monitor sensors (BLE discovered, BLE Connected, Distance and Rotation)
- Set a freeze preset and automove setting.
- Start the calibration process.

Use cases:

- Move to a preset when the TV turns on/off or based on another trigger.
- Automatically rotate or adjust distance based on other sensors or automations.
- Expose device status for monitoring.

## Supported device(s)

- [Vogel’s MotionMount NEXT 7355]([https://www.vogels.com/en-gb/c/motionmount-next-7355-gb-full-motion-motorised-tv-wall-mount])

## Requirements & prerequisites

- Home Assistant **2025.6.0 or newer**
- Bluetooth support on the host (integration depends on HA’s `bluetooth` integration)
- Python package: **`bleak>=0.21.1`**

## Installation

### Manual installation

1. Copy the `custom_components/vogels_motion_mount_next_ble` folder into `<config>/custom_components/`.
2. Restart Home Assistant.
3. Configure via **Settings → Devices & Services → Add integration → Vogels MotionMount NEXT (BLE)**.

## Setup

During setup, the integration asks for:

- **MAC** — the BLE MAC address of the device.
- **Device name** — a friendly name for the device.

> **Note**: Ensure your Bluetooth adapter is working and within range of the mount.

## Removing the integration

This integration follows standard integration removal, no extra steps are required.
