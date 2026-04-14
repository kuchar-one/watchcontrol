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

    async def get_auto_hr_config(self, debug: bool = False):
        """Read current automatic heart rate configuration."""
        await self._send(protocol.Packet(cmd_id=protocol.CommandID.AUTO_HR_CONFIG, payload=bytes([0x01])))
        packet = await self._wait_for_packet(cmd_id=protocol.CommandID.AUTO_HR_CONFIG)
        
        if debug:
            print(f"DEBUG: HR Config Packet -> {packet.payload.hex()}")
            
        if len(packet.payload) < 4:
             raise ValueError("Insufficient data in HR config response")
             
        # Payload comes back as [mode, enabled, interval, start_interval, low, high]
        enabled = packet.payload[1] == 1
        interval = packet.payload[2]
        start_interval = packet.payload[3] if packet.payload[3] != 0 else 5
        low = packet.payload[4] if len(packet.payload) > 4 else 0
        high = packet.payload[5] if len(packet.payload) > 5 else 0
        
        return {
            "enabled": enabled,
            "interval": interval,
            "start_interval": start_interval,
            "low_alarm": low,
            "high_alarm": high
        }

    async def set_auto_hr_config(self, enabled: bool, interval: int, start_interval: int = 5,
                                  low_alarm: int = 0, high_alarm: int = 0, debug: bool = False):
        """Update automatic heart rate configuration."""
        payload = bytes([
            0x02,                 # Write mode
            1 if enabled else 2,  # Enabled(1)/Disabled(2)
            interval & 0xFF,
            start_interval & 0xFF,
            low_alarm & 0xFF,
            high_alarm & 0xFF
        ])
        await self._send(protocol.Packet(cmd_id=protocol.CommandID.AUTO_HR_CONFIG, payload=payload))
        return await self.get_auto_hr_config(debug=debug)

    async def sync_sleep(self, day_offset: int = 0):
        """
        Sync sleep data for the given day offset using the high-speed BC channel.
        0 = Today, 1 = Yesterday, etc.
        """
        print(f"Requesting sleep data (BC Channel) for day offset {day_offset}...")
        # Large Data Packet: [day_offset, 15, 0, 95]
        payload = bytes([day_offset & 0xFF, 15, 0, 95])
        await self._send(protocol.Packet(is_large_data=True, action_id=protocol.ActionID.SLEEP_SYNC, payload=payload))
        
        sleep_segments = []
        try:
            while True:
                packet = await self._wait_for_packet(action_id=protocol.ActionID.SLEEP_SYNC, timeout=5.0)
                
                # Check for "No Data" response (usually a single byte 0x00)
                if len(packet.payload) <= 1:
                    if not sleep_segments:
                        print(f"No sleep records found for offset {day_offset}.")
                    break
                    
                # Payload: [Year, Month, Day, TimeIndex, currentSeq, totalSeq, q1...q7]
                if len(packet.payload) < 6:
                    continue # Fragment or unknown
                    
                year = protocol.bcd_to_decimal(packet.payload[0]) + 2000
                month = protocol.bcd_to_decimal(packet.payload[1])
                day = protocol.bcd_to_decimal(packet.payload[2])
                time_idx = packet.payload[3]
                curr_seq = packet.payload[4]
                total_seq = packet.payload[5]
                
                qualities = list(packet.payload[6:])
                sleep_segments.append({
                    "date": f"{year}-{month:02d}-{day:02d}",
                    "time_index": time_idx,
                    "qualities": qualities
                })
                
                if curr_seq >= total_seq - 1:
                    break
        except asyncio.TimeoutError:
            if not sleep_segments:
                print("Sync timed out (no data received).")
                return None
            print("Sync timed out (partial data).")
            
        return sleep_segments

    async def sync_hr_history(self, day_offset: int = 0):
        """
        Sync historical heart rate logs using the high-speed BC channel.
        0 = Today, 1 = Yesterday, etc.
        """
        print(f"Requesting heart rate logs (BC Channel) for day offset {day_offset}...")
        hr_data = []
        packet_idx = 0
        interval = 0
        
        try:
            while True:
                # Payload: [day_offset, packet_idx]
                payload = bytes([day_offset & 0xFF, packet_idx & 0xFF])
                await self._send(protocol.Packet(is_large_data=True, action_id=protocol.ActionID.AUTO_HR_LOG, payload=payload))
                
                packet = await self._wait_for_packet(action_id=protocol.ActionID.AUTO_HR_LOG, timeout=5.0)
                
                if len(packet.payload) <= 1:
                    if not hr_data:
                        print(f"No HR logs found for offset {day_offset}.")
                    break

                # Response payload: [day, interval, total_pkgs, curr_pkg, ...data]
                if len(packet.payload) < 4:
                    break
                    
                day = packet.payload[0]
                interval = packet.payload[1]
                total_pkgs = packet.payload[2]
                curr_pkg = packet.payload[3]
                
                # Each byte in data is an HR reading
                hr_data.extend(list(packet.payload[4:]))
                
                if curr_pkg >= total_pkgs - 1 or total_pkgs == 0:
                    break
                packet_idx = curr_pkg + 1
                
        except asyncio.TimeoutError:
            if not hr_data:
                return None
            print("Sync timed out (partial logs).")
            
        return {"day": day_offset, "interval": interval, "data": hr_data}

    async def set_sedentary_reminder(self, enabled: bool, interval: int = 60, 
                                     start_h: int = 8, start_m: int = 0,
                                     end_h: int = 21, end_m: int = 0,
                                     week_mask: int = 0x7F):
        """Set sedentary (long sitting) reminder."""
        # Payload: [enable(1/2), startH, startM, endH, endM, intervalL, intervalH, weekMask]
        payload = bytes([
            1 if enabled else 2,
            protocol.decimal_to_bcd(start_h),
            protocol.decimal_to_bcd(start_m),
            protocol.decimal_to_bcd(end_h),
            protocol.decimal_to_bcd(end_m),
            interval & 0xFF,
            (interval >> 8) & 0xFF,
            week_mask & 0xFF
        ])
        await self._send(protocol.Packet(cmd_id=protocol.CommandID.SET_SIT_LONG, payload=payload))

    async def set_hydration_reminder(self, index: int, enabled: bool, hour: int, minute: int, week_mask: int = 0x7F):
        """Set a hydration (drink water) reminder."""
        # Payload: [index(0-7), enable(1/0), hourBCD, minBCD, bits for week...]
        payload = [
            index & 0x07,
            1 if enabled else 0,
            protocol.decimal_to_bcd(hour),
            protocol.decimal_to_bcd(minute)
        ]
        # Add week bits as individual bytes (Monday to Sunday)
        for i in range(7):
            payload.append(1 if (week_mask & (1 << i)) else 0)
            
        await self._send(protocol.Packet(cmd_id=protocol.CommandID.SET_DRINK_WATER, payload=bytes(payload)))

    async def sync_alarms(self):
        """Fetch all alarms using the high-speed BC protocol."""
        # Request read: [0x01]
        await self._send(protocol.Packet(
            is_large_data=True, 
            action_id=protocol.ActionID.ALARM, 
            payload=bytes([0x01])
        ))
        
        packet = await self._wait_for_packet(action_id=protocol.ActionID.ALARM)
        if not packet or len(packet.payload) < 2:
            return []
            
        # Payload: [Status, Total, Beans...]
        # Status usually 1 for SUCCESS? 
        total = packet.payload[1]
        alarms = []
        
        offset = 2
        for _ in range(total):
            if offset + 4 > len(packet.payload): break
            
            length = packet.payload[offset]
            repeat_enable = packet.payload[offset+1]
            minutes = packet.payload[offset+2] | (packet.payload[offset+3] << 8)
            
            content_len = length - 4
            content = ""
            if content_len > 0:
                try:
                    content_slice = packet.payload[offset+4 : offset+4+content_len]
                    content = content_slice.decode("utf-8").strip("\x00")
                except:
                    content = "Alarm"
                    
            alarms.append({
                "enabled": (repeat_enable & 0x80) != 0,
                "week_mask": repeat_enable & 0x7F,
                "hour": minutes // 60,
                "minute": minutes % 60,
                "label": content,
                "minutes": minutes
            })
            offset += length
            
        return alarms

    async def write_alarms(self, alarms: list):
        """Upload the entire alarm set to the watch (bulk sync)."""
        # Payload: [0x02, Total, Beans...]
        payload = bytearray([0x02, len(alarms) & 0xFF])
        
        for a in alarms:
            label_bytes = (a.get("label", "") or "").encode("utf-8")
            length = len(label_bytes) + 4
            
            repeat_enable = (a.get("week_mask", 0x7F) & 0x7F)
            if a.get("enabled", True):
                repeat_enable |= 0x80
                
            total_minutes = (a["hour"] * 60) + a["minute"]
            
            payload.append(length & 0xFF)
            payload.append(repeat_enable & 0xFF)
            payload.append(total_minutes & 0xFF)
            payload.append((total_minutes >> 8) & 0xFF)
            payload.extend(label_bytes)
            
        await self._send(protocol.Packet(
            is_large_data=True,
            action_id=protocol.ActionID.ALARM,
            payload=bytes(payload)
        ))

    async def get_alarm(self, index: int):
        """Read an alarm by its list index (wrapper for bulk sync)."""
        alarms = await self.sync_alarms()
        if 0 <= index < len(alarms):
            res = alarms[index]
            res["index"] = index
            return res
        return None

    async def get_all_alarms(self):
        """Wrapper for sync_alarms."""
        return await self.sync_alarms()

    async def set_alarm(self, index: int, enabled: bool, hour: int, minute: int, week_mask: int = 0x7F, label: str = ""):
        """Configure alarm via Read-Modify-Write (bulk sync)."""
        alarms = await self.sync_alarms()
        
        # If index exists, update it. If not, pad or append.
        new_alarm = {
            "enabled": enabled,
            "hour": hour,
            "minute": minute,
            "week_mask": week_mask,
            "label": label
        }
        
        if index < len(alarms):
            alarms[index] = new_alarm
        else:
            # Append if it's the next index, or just push
            alarms.append(new_alarm)
            
        await self.write_alarms(alarms)

    async def measure_heart_rate(self, duration: float = 60, debug: bool = False):
        """
        Trigger heart rate measurement and stream real-time results.
        Uses a background task to ensure the notification queue is drained promptly.
        """
        msg = f"for {duration}s" if duration > 0 else "indefinitely"
        print(f"Starting continuous heart rate measurement {msg}...")
        
        # Mode 1: Standard measurement
        await self._send(protocol.Packet(cmd_id=protocol.CommandID.START_HEART_RATE, payload=bytes([0x01, 0x01])))
        
        start_time = asyncio.get_event_loop().time()
        
        listener_task = asyncio.create_task(self._listener_hr(start_time, debug))
        last_heartbeat_time = start_time
        
        try:
            while True:
                current_time = asyncio.get_event_loop().time()
                elapsed = current_time - start_time
                if duration > 0 and elapsed >= duration:
                    break
                
                # Note: On H59_9405, sending "Continue" (0x01, 0x03) suppresses pulse readings.
                # We stay silent to let the sensor settle.
                await asyncio.sleep(0.5)

                await asyncio.sleep(0.5)
        finally:
            listener_task.cancel()
            try:
                await listener_task
            except asyncio.CancelledError:
                pass
            print("\nStopping heart rate sensor...")
            try:
                await self._send(protocol.Packet(cmd_id=protocol.CommandID.START_HEART_RATE, payload=bytes([0x01, 0x04])))
            except:
                pass
            print("Sensor stopped.")

    async def _listener_hr(self, start_time, debug: bool):
        """Background listener for heart rate results."""
        while True:
            try:
                packet = await self._wait_for_packet(timeout=1.0)
                elapsed = asyncio.get_event_loop().time() - start_time
                
                if debug:
                    target = "ACT" if packet.is_large_data else "CMD"
                    print(f"[{elapsed:4.1f}s] DEBUG: {target} {packet.cmd_id or packet.action_id} P={packet.payload.hex()}")

                # Standard logic for real-time HR in AB packets (non-large-data)
                # Check multiple sources for pulse values
                if not packet.is_large_data:
                    hr_val = 0
                    if packet.cmd_id == protocol.CommandID.REAL_TIME_HEART_RATE: # 30 / 0x1E
                        hr_val = packet.payload[0]
                    elif packet.cmd_id == protocol.CommandID.START_HEART_RATE: # 105 / 0x69
                        # Offset varies by model, H59_9405 has it at payload[2]
                        if len(packet.payload) > 2: hr_val = packet.payload[2]
                    elif packet.cmd_id == 0x73:
                        if len(packet.payload) > 3: hr_val = packet.payload[3]
                    
                    if hr_val > 0 and hr_val < 255:
                        print(f"[{elapsed:4.1f}s] ❤️  Current Heart Rate: {hr_val} bpm")
                        
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                if debug:
                    print(f"DEBUG: Listener error: {e}")
