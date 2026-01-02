# Debugging BLE Connection Issue

## Current Problem
Device connects, services are resolved, then immediately disconnects.

Pattern:
```
[NEW] Device E4:15:F6:54:2D:AE Vogel's MotionMount
connected eir_len 30
[CHG] Device E4:15:F6:54:2D:AE Connected: yes
[CHG] Device E4:15:F6:54:2D:AE ServicesResolved: yes
[CHG] Device E4:15:F6:54:2D:AE ServicesResolved: no
[SIGNAL] org.bluez.Device1.Disconnected
[CHG] Device E4:15:F6:54:2D:AE Connected: no
```

## Things to Try

### 1. **Pair/Bond the Device** (Most Likely Fix)
Run these commands in `bluetoothctl`:
```bash
bluetoothctl
remove E4:15:F6:54:2D:AE
scan on
# Wait for device to appear
pair E4:15:F6:54:2D:AE
trust E4:15:F6:54:2D:AE
connect E4:15:F6:54:2D:AE
```

Then test Home Assistant integration again.

### 2. **Enable BlueZ Debug Logging**
Stop Bluetooth service and restart with debug:
```bash
sudo systemctl stop bluetooth
sudo bluetoothd -d -n
```

This will show detailed BlueZ logs. Watch for:
- MTU negotiation errors
- GATT protocol errors
- Device-side error codes
- Timeout messages

### 3. **Test Direct Connection with gatttool**
```bash
gatttool -b E4:15:F6:54:2D:AE -I
# Inside gatttool prompt:
connect
characteristics
# Watch to see if this also disconnects
```

### 4. **Check Device Logs**
Does the device (Vogel's Motion Mount) have its own logging/debug mode you can enable?

### 5. **Try Different Connection Approach**
If nothing else works, we could try:
- Reducing MTU size
- Disabling notifications entirely
- Using a very aggressive timeout for service discovery
- Direct BleakClient instead of BleakClientWithServiceCache

## Logs to Check

On the Linux machine:

```bash
# Check BlueZ journal logs
journalctl -u bluetooth -n 100 --no-pager

# Check if device is showing as trusted
bluetoothctl
info E4:15:F6:54:2D:AE

# Check for pairing info
ls -la /var/lib/bluetooth/$(hcitool dev | grep -o '[0-9A-Fa-f:]*' | tail -1)/E4\:15\:F6\:54\:2D\:AE/
```

## Home Assistant Logs

Check HA logs for:
- `DEBUG` level messages from custom_components.vogels_motion_mount_next_ble
- The coordinator retry logs should show what's happening

Add this to your `configuration.yaml` to enable debug logging:
```yaml
logger:
  logs:
    custom_components.vogels_motion_mount_next_ble: debug
    bleak: debug
    bleak_retry_connector: debug
```

## Theory

The device **likely requires bonding/pairing** to:
1. Properly negotiate connection parameters
2. Avoid firmware timeout during service discovery
3. Maintain connection stability

The disconnect after `ServicesResolved` suggests the device's firmware has a built-in timeout or requirement that's not being met during the initial connection handshake.
