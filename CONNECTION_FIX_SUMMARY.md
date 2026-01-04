# BLE Connection Issue - Root Cause and Fixes Applied

## Problem Summary
The Vogels Motion Mount BLE integration was experiencing persistent connection failures with two main error patterns:

1. **TimeoutError**: Failed to connect after 3-11 retry attempts
2. **Connection Slot Exhaustion**: "No backend with an available connection slot" error

The device would attempt to reconnect repeatedly, but each failed attempt would consume a connection slot on the Bluetooth adapter. After ~11-15 failed attempts, the adapter ran out of slots and couldn't recover without restarting the Bluetooth service.

## Root Causes Identified

### 1. Adapter Slot Exhaustion
- The Bluetooth adapter has a limited number of concurrent connection slots (typically 4-7)
- When a connection attempt fails, the slot sometimes isn't immediately freed
- Repeated connection attempts (even failed ones) consume slots faster than they're released
- Once exhausted, the adapter rejects all new connections until restarted

### 2. Aggressive Retry Strategy
- `establish_connection()` in bleak_retry_connector was making many attempts by default
- Each attempt consumed resources and could leave stale connections
- The coordinator was making 2+ retries on transient errors
- No maximum retry limit existed, causing infinite reconnection loops

### 3. Incomplete Cleanup
- When connections failed, the Bluetooth client objects weren't always properly cleaned up
- The keep-alive mechanism could fail silently
- Service discovery timeout had no early-exit when connection was lost

### 4. Device DDoS Protection
- The Vogels device has a 30-second cooldown after disconnect
- Rapid reconnection attempts trigger DDoS protection
- The cooldown wasn't always being respected in the retry logic

## Fixes Applied

### 1. **client.py - Connection Timeout (Line 509)**
```python
client = await asyncio.wait_for(
    establish_connection(..., max_attempts=3),
    timeout=30.0  # 30 second total timeout
)
```
**Impact**: Added an overall 30-second timeout wrapper. If connection takes longer than 30 seconds, we stop immediately instead of retrying indefinitely.

### 2. **client.py - Improved Error Cleanup (Lines 526-541)**
Added cleanup of partially-created client objects if connection fails:
```python
except (BleakNotFoundError, BleakConnectionError, BleakError) as err:
    try:
        if 'client' in locals() and hasattr(client, 'disconnect'):
            await client.disconnect()
    except Exception as cleanup_err:
        _LOGGER.debug("Error cleaning up client: %s", cleanup_err)
```
**Impact**: Ensures no stale connections left in the adapter's connection table.

### 3. **client.py - Service Discovery Robustness (Lines 604-620)**
Enhanced service discovery wait loop:
- Checks if connection is still active during wait
- Properly exits if connection drops
- Logs warning if timeout occurs without discovering services
**Impact**: Prevents hanging on service discovery and detects lost connections early.

### 4. **client.py - Aggressive Disconnect (Lines 253-276)**
```python
async def disconnect(self):
    # Timeout on disconnect to prevent hangs
    await asyncio.wait_for(client.disconnect(), timeout=5.0)
    # Sleep 1 second instead of 0.5 for better cleanup
    await asyncio.sleep(1.0)
```
**Impact**: Ensures proper resource cleanup and gives BlueZ time to free adapter slots.

### 5. **coordinator.py - Max Retry Limit (Line 47)**
```python
MAX_RECONNECT_ATTEMPTS = 20
```
Added a maximum of 20 consecutive reconnect attempts before giving up.
**Impact**: Prevents infinite reconnection loops when device is truly offline.

### 6. **coordinator.py - Maximum Attempt Check (Lines 474-488)**
```python
if self._reconnect_attempts >= MAX_RECONNECT_ATTEMPTS:
    raise UpdateFailed(
        "Maximum reconnection attempts exceeded. "
        "Check device is powered on and Bluetooth is functioning."
    )
```
**Impact**: Clear failure message instead of silently retrying forever.

### 7. **coordinator.py - Smarter Exponential Backoff (Lines 646-675)**
Improved backoff strategy:
- Attempts 1-5: 30-60 second delays (quick recovery for transient issues)
- Attempts 6-10: 1-2 minute delays (allow adapter to recover)
- Attempts 11+: 2-5 minute delays (respect device DDoS protection)
- Capped at 5 minutes to avoid excessive delays
**Impact**: Balances between quick reconnection for transient issues and respecting device protection.

## Expected Behavior After Fixes

1. **First connection failure**: Device will wait 30-60 seconds and retry
2. **Repeated failures**: Delays increase exponentially, respecting the 30-second device cooldown
3. **After 20 attempts**: Coordinator stops and waits for user action or manual reconnect
4. **Successful connection**: Reconnect attempt counter resets to 0
5. **Adapter exhaustion**: Errors are logged clearly, requesting Bluetooth adapter restart

## Troubleshooting If Issues Persist

### If still getting "No backend with available connection slot":

1. **Restart Bluetooth Adapter**:
   ```bash
   sudo systemctl restart bluetooth
   ```

2. **Check for Stale Connections**:
   ```bash
   bluetoothctl
   info E4:15:F6:54:2D:AE
   # Should show Connected: no
   ```

3. **Remove and Re-pair Device**:
   ```bash
   bluetoothctl
   remove E4:15:F6:54:2D:AE
   # Restart Home Assistant integration
   ```

4. **Check Home Assistant Logs**:
   ```
   Settings -> System -> Logs
   ```
   Look for: "BLE connection error", "Attempt" to track retry pattern

### If getting persistent TimeoutError:

1. **Check Bluetooth Range**: Device might be too far away
2. **Check Device Power**: Ensure device is charged and powered on
3. **Check for Interference**: 2.4 GHz Wi-Fi, microwaves, baby monitors can interfere
4. **Device Firmware**: Ensure Vogels device firmware is up-to-date
5. **Bluetooth Hardware**: Check if Bluetooth adapter is failing with `bluetoothctl list`

## Monitoring

Check logs for these messages to monitor connection health:

✅ **Good Signs**:
- "Successfully established connection to E4:15:F6:54:2D:AE"
- "Reconnect attempts on successful update" (reset to 0)

⚠️ **Warning Signs**:
- Repeated "BLE connection error for E4:15:F6:54:2D:AE. Attempt N."
- "Scheduling automatic reconnection in X seconds"

❌ **Critical Signs**:
- "No backend with an available connection slot"
- "Maximum reconnection attempts (20) exceeded"
- "Failed to cancel connection" from bleak

## Testing the Fixes

After the code changes are deployed:

1. Monitor the logs for at least 1 hour
2. Check that reconnect delays are increasing (not stuck in fast loop)
3. Verify device eventually reconnects or shows clear failure message
4. Test manual reconnect: `Developer Tools > Services > Refresh`

