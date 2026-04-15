# QWatch Pro / H59 Control

Reverse-engineered Bluetooth control for the H59_9405 smartwatch. This CLI utility allows you to control the device, extract biometric data, and sync alarms using its High-Speed Large Data protocol.

## Features

- **Heart Rate Monitoring**: Start continuous tracking, access historical logs, and configure auto-measurement intervals.
- **Sleep Data Sync**: Export deep sleep, light sleep, and REM phases using the Large Data protocol.
- **Alarm Management**: Bulk sync up to 10 alarms with custom labels and recurrence masks.
- **Reminders**: Configure hydration and sedentary alerts.
- **System Commands**: Reboot the watch, fetch battery status, and sync time.
- **Tools**: Trigger vibration patterns and remote camera shutter.

## Installation

We use `uv` for modern, fast dependency management.

1. Install [uv](https://docs.astral.sh/uv/) if you haven't already:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
2. Clone this repository and configure the environment:
   ```bash
   uv sync
   ```

## Usage

Run the controller through the python module:
```bash
PYTHONPATH=src uv run python -m watchcontrol <command>
```

The script automatically caches your watch's address in `.watch_address` after the first successful scan, making subsequent queries instantaneous.

### Example Commands

* **Device Discovery**
  ```bash
  python -m watchcontrol scan
  ```
* **Battery & System**
  ```bash
  python -m watchcontrol battery
  python -m watchcontrol time
  python -m watchcontrol reboot
  ```
* **Alarms & Reminders**
  ```bash
  python -m watchcontrol get-alarms
  python -m watchcontrol set-alarm 0 on --hour 7 --minute 0 --label "Wake Up"
  python -m watchcontrol del-alarm 0
  python -m watchcontrol set-sedentary on -i 60 --start-h 8 --end-h 20
  ```
* **Biometrics**
  ```bash
  python -m watchcontrol measure-hr -d 60      # Real-time HR stream
  python -m watchcontrol sync-sleep -d 0       # Today's sleep data
  python -m watchcontrol get-hr-config         # Auto-HR settings
  ```

Run `python -m watchcontrol -h` for the full list of available arguments.

## Protocol Details
The watch uses standard 16-byte GATT writes for basic commands, and a sequence-based "Large Data" stream on `de5b...` characteristics for sleep history, heart rate logs, and alarms.