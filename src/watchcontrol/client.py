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

