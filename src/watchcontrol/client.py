"""
Client — High-level async interface for communicating with the bracelet.
"""

import asyncio
import logging
from bleak import BleakClient
from . import protocol

logger = logging.getLogger(__name__)


class WatchClient:
    """
    Async context-manager client for the smart watch.
    """

    def __init__(self, address: str):
        self.address = address
        self._client: BleakClient | None = None
        self._response_queue = asyncio.Queue()

    async def __aenter__(self):
        self._client = BleakClient(self.address)
        await self._client.connect()
        
        # Subscribe to both notification channels
        await self._client.start_notify(protocol.STD_NOTIFY_CHAR, self._notification_handler)
        await self._client.start_notify(protocol.DATA_NOTIFY_CHAR, self._notification_handler)
        
        logger.info(f"Connected to {self.address} (Dual-Service)")
        return self

    async def __aexit__(self, *exc):
        if self._client and self._client.is_connected:
            try:
                await self._client.stop_notify(protocol.STD_NOTIFY_CHAR)
                await self._client.stop_notify(protocol.DATA_NOTIFY_CHAR)
            except:
                pass
            await self._client.disconnect()
        self._client = None

    def _notification_handler(self, _sender, data: bytearray):
        """Handle incoming notifications from either channel."""
        packet = protocol.Packet.from_bytes(bytes(data))
        if packet:
            target = f"ACT {packet.action_id}" if packet.is_large_data else f"CMD {packet.cmd_id}"
            logger.debug(f"Received Packet: {target} (Large={packet.is_large_data})")
            self._response_queue.put_nowait(packet)

    async def _send(self, packet: protocol.Packet):
        """Route packet to the correct characteristic based on is_large_data flag."""
        if not self._client or not self._client.is_connected:
            raise RuntimeError("Not connected")
        
        if not packet.is_large_data:
            char_uuid = protocol.STD_WRITE_CHAR
        else:
            char_uuid = protocol.DATA_WRITE_CHAR
            
        await self._client.write_gatt_char(char_uuid, packet.to_bytes())

    async def _wait_for_packet(self, cmd_id: int = None, action_id: int = None, timeout: float = 5.0) -> protocol.Packet:
        """Wait for a packet with matching Command ID or Action ID."""
        start_time = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - start_time) < timeout:
            try:
                remaining = timeout - (asyncio.get_event_loop().time() - start_time)
                packet = await asyncio.wait_for(self._response_queue.get(), timeout=remaining)
                
                if cmd_id is None and action_id is None:
                    return packet
                if cmd_id is not None and packet.cmd_id == cmd_id:
                    return packet
                if action_id is not None and packet.action_id == action_id:
                    return packet
            except asyncio.TimeoutError:
                break
        
        target = f"CMD {cmd_id}" if cmd_id else f"ACTION {action_id}"
        raise asyncio.TimeoutError(f"Timeout waiting for {target}")

    # =========================================================================
    # High-level API
    # =========================================================================

    async def set_time(self):
        """Sync current system time to the watch."""
        await self._send(protocol.create_set_time_packet())

    async def get_battery(self):
        """Fetch battery level and charging status."""
        await self._send(protocol.Packet(cmd_id=protocol.CommandID.GET_BATTERY))
        packet = await self._wait_for_command(protocol.CommandID.GET_BATTERY)
        
        # Parse payload: [level, status]
        level = packet.payload[0]
        charging = packet.payload[1] == 1
        return {"level": level, "charging": charging}

    async def reboot(self):
        """Request a watch reboot."""
        await self._send(protocol.Packet(cmd_id=protocol.CommandID.REBOOT))

    async def take_picture(self):
        """Trigger the remote camera shutter."""
        await self._send(protocol.Packet(cmd_id=protocol.CommandID.TAKE_PICTURE))
        
    async def set_heart_rate(self, enabled: bool):
        """Start or stop real-time heart rate measurement."""
        cmd_id = protocol.CommandID.START_HEART_RATE if enabled else protocol.CommandID.STOP_HEART_RATE
        packet = protocol.Packet(cmd_id=cmd_id)
        await self._send(packet)
        print(f"Heart rate {'started' if enabled else 'stopped'}.")

    async def vibrate(self, duration: float = None, interval: float = 0.1):
        """
        Trigger vibration on the watch.
        If duration is provided, it loops the 'Find Device' command to keep the motor active
        at a high frequency, creating a continuous effect.
        """
        if duration is None:
            packet = protocol.create_find_device_packet()
            await self._send(packet)
            print("Vibration (Find Device) pulse sent.")
        else:
            print(f"Continuous vibration for {duration}s (interval: {interval}s)...")
            start_time = asyncio.get_event_loop().time()
            while True:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed >= duration:
                    break
                
                packet = protocol.create_find_device_packet()
                await self._send(packet)
                
                # Wait for the interval or until the duration is up
                time_to_sleep = min(interval, duration - elapsed)
                if time_to_sleep > 0:
                    await asyncio.sleep(time_to_sleep)
            
            # Use the notification trick (Hang up) to cut off the motor immediately
            stop_packet = protocol.create_push_msg_packet(4, "Stop")
            await self._send(stop_packet)
            print("Vibration cut off.")

