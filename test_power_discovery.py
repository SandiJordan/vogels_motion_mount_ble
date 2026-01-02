"""
Script to discover power control commands by testing unknown characteristics.
Run this against your device to find which UUID controls power.
"""

import asyncio
from bleak import BleakClient

# Unknown characteristics that might control power
UNKNOWN_CHARS = [
    "c005fa05-0651-4800-b000-000000000000",  # write-only
    "c005fa06-0651-4800-b000-000000000000",  # read/write
    "c005fa23-0651-4800-b000-000000000000",  # read/write/notify
    "c005fa24-0651-4800-b000-000000000000",  # write-only
    "c005fa25-0651-4800-b000-000000000000",  # read/write/notify
    "c005fa26-0651-4800-b000-000000000000",  # read/write
    "c005fa28-0651-4800-b000-000000000000",  # read/notify
    "c005fa29-0651-4800-b000-000000000000",  # read
    "c005fa30-0651-4800-b000-000000000000",  # read/write
    "c005fa32-0651-4800-b000-000000000000",  # read/write
    "c005fa33-0651-4800-b000-000000000000",  # write-only
    "c005fa35-0651-4800-b000-000000000000",  # read/write/notify
    "c005fa36-0651-4800-b000-000000000000",  # read/write/notify
    "c005fa38-0651-4800-b000-000000000000",  # read
    "c005fa3a-0651-4800-b000-000000000000",  # read/write/notify
]

# Test payloads to try
TEST_PAYLOADS = [
    bytes([0x01]),           # Single byte: 1
    bytes([0x00]),           # Single byte: 0
    bytes([0x01, 0x00]),     # Two bytes
    bytes([0xff]),           # Single byte: 255
    bytes([0x01, 0x01]),     # Power on pattern
    bytes([0x00, 0x00]),     # Power off pattern
]

async def discover_power_command(device_address: str):
    """Test unknown characteristics to find power control."""
    async with BleakClient(device_address) as client:
        print(f"Connected to {device_address}")
        
        for char_uuid in UNKNOWN_CHARS:
            print(f"\n--- Testing {char_uuid} ---")
            
            try:
                # Try to read first
                data = await client.read_gatt_char(char_uuid)
                print(f"  Current value: {data.hex()}")
            except Exception as e:
                print(f"  Cannot read: {e}")
            
            try:
                # Try writing test payloads
                for payload in TEST_PAYLOADS:
                    await client.write_gatt_char(char_uuid, payload)
                    print(f"  Wrote: {payload.hex()}")
                    await asyncio.sleep(0.5)
                    
                    # Try to read back
                    try:
                        result = await client.read_gatt_char(char_uuid)
                        print(f"    Read back: {result.hex()}")
                    except:
                        pass
                        
            except Exception as e:
                print(f"  Cannot write: {e}")

if __name__ == "__main__":
    # Replace with your device MAC address
    DEVICE_ADDRESS = "E4:15:F6:54:2D:AE"
    asyncio.run(discover_power_command(DEVICE_ADDRESS))
