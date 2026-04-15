"""
Protocol — Command/response definitions for the smart bracelet.
Derived from com.oudmon.ble library analysis.
"""

import datetime
from dataclasses import dataclass, field
from enum import IntEnum


# =============================================================================
# Service & Characteristic UUIDs
# =============================================================================
# Standard Service (AB)
STD_SERVICE_UUID = "6e40fff0-b5a3-f393-e0a9-e50e24dcca9e"
STD_WRITE_CHAR = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
STD_NOTIFY_CHAR = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

# Large Data Service (BC)
DATA_SERVICE_UUID = "de5bf728-d711-4e47-af26-65e3012a5dc7"
DATA_WRITE_CHAR = "de5bf72a-d711-4e47-af26-65e3012a5dc7"
DATA_NOTIFY_CHAR = "de5bf729-d711-4e47-af26-65e3012a5dc7"


class CommandID(IntEnum):
    """Command IDs for standard 0xAB packets."""
    SET_TIME = 0x01
    TAKE_PICTURE = 0x02
    GET_BATTERY = 0x03
    REBOOT = 0x08
    AUTO_HR_CONFIG = 0x16       # 22 decimal
    SET_ALARM = 35              # 0x23
    GET_ALARM = 36              # 0x24
    SET_SIT_LONG = 37           # 0x25
    SET_DRINK_WATER = 39        # 0x27
    GET_SLEEP_LEGACY = 0x44     # 68 decimal
    GET_STEPS_TODAY = 0x48      # 72 decimal
    REAL_TIME_HEART_RATE = 0x1E # 30 decimal
    START_HEART_RATE = 0x69     # 105 decimal
    STOP_HEART_RATE = 0x6A      # 106 decimal
    FIND_DEVICE = 0x50          # 80 decimal
    PUSH_MSG = 0x72             # 114 decimal

class ActionID(IntEnum):
    """Action IDs for large data 0xBC packets."""
    LOCATION = 0x20             # 32
    SLEEP_SYNC = 0x27           # 39
    MANUAL_HR_LOG = 0x28        # 40
    STEP_SYNC = 0x29            # 41
    BLOOD_OXYGEN = 0x2A         # 42
    ALARM = 0x2C                # 44
    AUTO_HR_LOG = 0x75          # 117

def calc_crc16(data: bytes) -> int:
    """CRC16 algorithm from APK (Polynomial 0xA001)."""
    if not data:
        return 65535
    crc = 65535
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 65535


@dataclass
class Packet:
    """Unified packet structure for standard (16-byte) and large-data protocols."""
    is_large_data: bool = False
    cmd_id: int = 0
    action_id: int = 0
    payload: bytes = field(default_factory=bytes)

    def to_bytes(self) -> bytes:
        if not self.is_large_data:
            # Standard 16-byte packet: [cmd_id, payload..., checksum]
            data = bytearray(16)
            data[0] = self.cmd_id & 0xFF
            
            payload_len = min(len(self.payload), 14)
            data[1:1+payload_len] = self.payload[:payload_len]
            
            # Checksum is sum of first 15 bytes
            data[15] = sum(data[:15]) & 0xFF
            return bytes(data)
        else:
            # Large Packet (BC): [0xBC, action, lenL, lenH, crcL, crcH, payload...]
            length = len(self.payload)
            crc = calc_crc16(self.payload)
            header_bytes = bytes([
                0xBC,
                self.action_id,
                length & 0xFF,
                (length >> 8) & 0xFF,
                crc & 0xFF,
                (crc >> 8) & 0xFF
            ])
            return header_bytes + self.payload

    @classmethod
    def from_bytes(cls, data: bytes) -> 'Packet':
        if not data:
            return None
        
        # Detect Small (16-byte) vs Large (BC) packets
        if data[0] == 0xBC:
            if len(data) < 6: return None
            action_id = data[1]
            length = data[2] | (data[3] << 8)
            return cls(is_large_data=True, action_id=action_id, payload=data[6:6+length])
        elif data[0] != 0xBC:
            # Standard packet: [cmd_id, ...payload]
            # Use data[0] as cmd_id and data[1:] as payload
            # Note: 16-byte fixed packets like those with checksums will work fine too
            return cls(is_large_data=False, cmd_id=data[0], payload=data[1:])
        else:
            return None


def decimal_to_bcd(val: int) -> int:
    """Convert decimal integer to BCD byte."""
    return ((val // 10) << 4) | (val % 10)


def bcd_to_decimal(val: int) -> int:
    """Convert BCD byte to decimal integer."""
    return ((val >> 4) & 0x0F) * 10 + (val & 0x0F)


def create_set_time_packet(timestamp: datetime.datetime = None) -> Packet:
    """
    Creates a SET_TIME packet.
    Payload format: [Year%100, Month, Day, Hour, Min, Sec (all BCD), Language, TimezoneOffset]
    """
    if timestamp is None:
        timestamp = datetime.datetime.now()
    
    payload = bytearray(8)
    payload[0] = decimal_to_bcd(timestamp.year % 100)
    payload[1] = decimal_to_bcd(timestamp.month)
    payload[2] = decimal_to_bcd(timestamp.day)
    payload[3] = decimal_to_bcd(timestamp.hour)
    payload[4] = decimal_to_bcd(timestamp.minute)
    payload[5] = decimal_to_bcd(timestamp.second)
    
    # Language: 1 for English (based on initMap in SetTimeReq.java)
    payload[6] = 1
    
    # Timezone: ((Offset_hours + 24) % 24) * 2 + 1
    # For now, let's just use a simplified version or 0/UTC
    offset_hours = timestamp.astimezone().utcoffset().total_seconds() / 3600
    tz_val = int(((offset_hours + 24) % 24) * 2 + 1)
    payload[7] = tz_val & 0xFF
    
    return Packet(cmd_id=CommandID.SET_TIME, payload=bytes(payload))


def create_find_device_packet() -> Packet:
    """Creates a packet to trigger vibration on the watch."""
    # Payload is fixed [0x55, 0xAA] based on FindDeviceReq.java
    return Packet(cmd_id=CommandID.FIND_DEVICE, payload=bytes([0x55, 0xAA]))


def create_push_msg_packet(msg_type: int, content: str = "") -> Packet:
    """
    Creates a PUSH_MSG packet (ID 114 / 0x72).
    Payload format: [type, total_pkgs, current_pkg, ...data]
    Max data per packet is 11 bytes.
    """
    content_bytes = content.encode("utf-8")[:11]
    payload = bytearray(14)  # 16-2 = 14 bytes available
    payload[0] = msg_type & 0xFF
    payload[1] = 1  # Total packages (assuming 1 for simple triggers)
    payload[2] = 1  # Current package index
    payload[3:3+len(content_bytes)] = content_bytes
    
    return Packet(cmd_id=CommandID.PUSH_MSG, payload=bytes(payload))


class HRAction:
    START = 0  # Default for Mode 1
    CONTINUE = 3
    STOP = 4

def create_start_hr_packet(mode: int = 1, action: int = HRAction.START) -> Packet:
    """
    Creates a packet to start heart rate measurement.
    - mode 1: Standard manual (SIMPLE_REQ).
    - mode 6: Real-time streaming mode.
    - action: See HRAction class.
    """
    return Packet(cmd_id=CommandID.START_HEART_RATE, payload=bytes([mode & 0xFF, action & 0xFF]))


def create_stop_hr_packet() -> Packet:
    """Creates a packet to stop heart rate measurement."""
    # Stop HR -> [0x04, 0x00]
    return Packet(cmd_id=CommandID.START_HEART_RATE, payload=bytes([HRAction.STOP, 0x00]))

def create_read_hr_config_packet() -> Packet:
    """Creates a packet to read auto HR configuration."""
    return Packet(cmd_id=CommandID.AUTO_HR_CONFIG, payload=bytes([0x01]))

def create_write_hr_config_packet(enabled: bool, interval: int, start_interval: int = 5,
                                  low_alarm: int = 0, high_alarm: int = 0) -> Packet:
    """Creates a packet to write auto HR configuration."""
    payload = [
        0x02,                 # Write mode
        1 if enabled else 2, # Enabled(1)/Disabled(2)
        interval & 0xFF,
        start_interval & 0xFF,
        low_alarm & 0xFF,
        high_alarm & 0xFF
    ]
    return Packet(cmd_id=CommandID.AUTO_HR_CONFIG, payload=bytes(payload))

