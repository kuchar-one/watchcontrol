"""
BLE Scanner — Discover nearby BLE devices and identify the smart bracelet.
"""

import os
import asyncio
from bleak import BleakScanner
from .protocol import STD_SERVICE_UUID

CACHE_FILE = ".watch_address"


async def scan(timeout: float = 10.0, name_filter: str | None = None, filter_by_service: bool = False):
    """Scan for BLE devices, optionally filtering by name or service code."""
    print(f"Scanning for BLE devices ({timeout}s)...")
    devices = await BleakScanner.discover(timeout=timeout)
    
    results = []
    print(f"\n{'RSSI':>6} | {'Address':<18} | {'Name'}")
    print("-" * 40)
    
    # Filter for our specific service or name if provided
    for dev in sorted(devices, key=lambda d: getattr(d, 'rssi', -999) or -999, reverse=True):
        name = dev.name or "Unknown"
        address = dev.address
        rssi = getattr(dev, 'rssi', "?")
        
        match = False
        if name_filter:
            if dev.name and name_filter.lower() in dev.name.lower():
                match = True
        else:
            if STD_SERVICE_UUID.lower() in [s.lower() for s in dev.metadata.get("uuids", [])]:
                match = True
            elif dev.name and "H59_" in dev.name:
                match = True

        results.append(dev)
        match_str = "*" if match else " "
        print(f"{rssi:>4} dBm {match_str} | {address:<18} | {name}")

    if not results:
        print("  No devices found.")

    return results


def get_cached_address() -> str | None:
    """Retrieve the cached watch address if it exists."""
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            return f.read().strip()
    return None


def set_cached_address(address: str):
    """Save the watch address to the local cache."""
    with open(CACHE_FILE, "w") as f:
        f.write(address)


async def find_watch(timeout: float = 5.0, use_cache: bool = True) -> str | None:
    """Auto-discover the H59 smartwatch and return its address."""
    if use_cache:
        cached = get_cached_address()
        if cached:
            # Note: We don't verify if it's in range here to save time.
            # The client will report if connection fails.
            return cached

    print(f"Auto-discovering watch (model: H59_9405) with {timeout}s scan...")
    devices = await scan(timeout=timeout, name_filter="H59")
    if devices:
        target = devices[0]
        print(f"Found watch: {target.name} ({target.address})")
        set_cached_address(target.address)
        return target.address
    return None


async def main():
    import sys
    name_filter = sys.argv[1] if len(sys.argv) > 1 else None
    await scan(name_filter=name_filter)


if __name__ == "__main__":
    asyncio.run(main())
