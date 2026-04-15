"""
CLI entry point for watchcontrol.
"""

import argparse
import asyncio
import sys
from .scanner import scan, find_watch
from .client import WatchClient


async def get_client(args):
    """Helper to get a WatchClient instance with address resolution."""
    address = args.address
    if not address:
        address = await find_watch()
        if not address:
            print("Error: Could not find watch automatically. Please specify address.")
            sys.exit(1)
    return WatchClient(address)


async def handle_command(args):
    if args.command == "scan":
        await scan(timeout=args.timeout, name_filter=args.filter)
    
    elif args.command == "get-hr-config":
        async with await get_client(args) as client:
            config = await client.get_auto_hr_config(debug=args.debug)
            print("Automatic Heart Rate Configuration:")
            print(f"  Enabled:  {'Yes' if config['enabled'] else 'No'}")
            print(f"  Interval: {config['interval']} minutes")
            print(f"  Alarm Low:  {config['low_alarm']} bpm")
            print(f"  Alarm High: {config['high_alarm']} bpm")

    elif args.command == "set-hr-config":
        enabled = args.state == "on"
        async with await get_client(args) as client:
            config = await client.set_auto_hr_config(
                enabled, args.interval, low_alarm=args.low, high_alarm=args.high, debug=args.debug
            )
            print("Successfully updated heart rate configuration.")
            print(f"  Enabled:  {'Yes' if config['enabled'] else 'No'}")
            print(f"  Interval: {config['interval']} minutes")

    elif args.command == "sync-hr":
        async with await get_client(args) as client:
            result = await client.sync_hr_history(day_offset=args.days)
            if not result or not result["data"]:
                print("No HR logs found.")
                return
            
            print(f"\n--- HR History (Offset: {args.day}, Interval: {result['interval']} min) ---")
            # Assuming HR logs are simple list of bpm
            for i, bpm in enumerate(result["data"]):
                if bpm > 0:
                    time_m = i * result['interval']
                    time_str = f"{time_m // 60:02d}:{time_m % 60:02d}"
                    print(f"[{time_str}] {bpm} bpm")

    elif args.command == "set-sedentary":
        state = args.state == "on"
        async with await get_client(args) as client:
            await client.set_sedentary_reminder(
                state, interval=args.interval, 
                start_h=args.start_h, end_h=args.end_h
            )
            print(f"Sedentary reminder set to {args.state} ({args.interval} min).")

    elif args.command == "set-hydration":
        state = args.state == "on"
        async with await get_client(args) as client:
            await client.set_hydration_reminder(
                args.index, state, args.hour, args.minute
            )
            print(f"Hydration reminder {args.index} set to {args.state} at {args.hour:02d}:{args.minute:02d}.")

    elif args.command == "get-alarms":
        async with await get_client(args) as client:
            alarms = await client.get_all_alarms()
            if not alarms:
                print("No alarms configured.")
                return
            
            print("\n--- Watch Alarms ---")
            print(f"{'Idx':<4} | {'State':<5} | {'Time':<5} | {'Label':<15} | {'Days'}")
            print("-" * 55)
            
            days_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            for i, a in enumerate(alarms):
                state = "ON" if a["enabled"] else "OFF"
                time_str = f"{a['hour']:02d}:{a['minute']:02d}"
                label = a.get("label", "")[:15]
                
                active_days = []
                for j in range(7):
                    if a["week_mask"] & (1 << j):
                        active_days.append(days_names[j])
                
                days_str = ", ".join(active_days) if active_days else "Once"
                print(f"{i:<4} | {state:<5} | {time_str:<5} | {label:<15} | {days_str}")

    elif args.command == "set-alarm":
        state = args.state == "on"
        async with await get_client(args) as client:
            await client.set_alarm(
                args.index, state, args.hour, args.minute, label=args.label
            )
            print(f"Alarm {args.index} ('{args.label}') set to {args.state} at {args.hour:02d}:{args.minute:02d}.")

    elif args.command == "del-alarm":
        async with await get_client(args) as client:
            alarms = await client.get_all_alarms()
            if 0 <= args.index < len(alarms):
                removed = alarms.pop(args.index)
                await client.write_alarms(alarms)
                print(f"Deleted alarm {args.index} ('{removed.get('label', '')}').")
            else:
                print(f"Error: Alarm index {args.index} out of range.")

    elif args.command == "sync-sleep":
        SLEEP_TYPES = {
            2: "LIGHT SLEEP",
            3: "DEEP SLEEP",
            4: "REM",
            5: "AWAKE",
        }
        async with await get_client(args) as client:
            result = await client.sync_sleep(day_offset=args.days, debug=args.debug)
            if not result:
                print("No sleep data found.")
                return

            sh, sm = result["start_minutes"] // 60 % 24, result["start_minutes"] % 60
            eh, em = result["end_minutes"]   // 60 % 24, result["end_minutes"]   % 60
            total  = result["total_minutes"]

            print(f"\n--- Sleep Data (Night of {result['date']}) ---")
            print(f"Period : {sh:02d}:{sm:02d} -> {eh:02d}:{em:02d}  ({total // 60}h {total % 60}min total)")

            if not result["segments"]:
                print("No sleep segments in response.")
                return

            print("\nTimeline:")
            t = result["start_minutes"]
            for seg in result["segments"]:
                h, m = (t // 60) % 24, t % 60
                label = SLEEP_TYPES.get(seg["type"], f"UNKNOWN({seg['type']})")
                print(f"  {h:02d}:{m:02d}  {label:<12} ({seg['duration']} min)")
                t += seg["duration"]

    elif args.command in ["time", "battery", "reboot", "camera", "hr", "vibrate", "measure-hr"]:
        async with await get_client(args) as client:
            if args.command == "time":
                await client.set_time()
                print("Clock synchronized.")
            
            elif args.command == "battery":
                info = await client.get_battery()
                if info:
                    print(f"Battery Level: {info['level']}%")
                    print(f"Status: {'Charging' if info['charging'] else 'Discharging'}")
            
            elif args.command == "reboot":
                await client.reboot()
                print("Reboot signal sent.")
            
            elif args.command == "camera":
                await client.take_picture()
                print("Remote photo triggered.")
                
            elif args.command == "vibrate":
                await client.vibrate(duration=args.duration, interval=args.interval)
                print("Vibrate command complete.")

            elif args.command == "hr":
                state = args.state.lower() == "on"
                await client.set_heart_rate(state)
                print(f"Heart rate monitor: {args.state}")

            elif args.command == "measure-hr":
                duration = -1 if args.continuous else args.duration
                await client.measure_heart_rate(duration=duration, debug=args.debug)

    else:
        print("Use -h for help.")


def main():
    parser = argparse.ArgumentParser(
        prog="watchcontrol",
        description="QWatch Pro smart watch controller",
    )
    sub = parser.add_subparsers(dest="command")

    # --- scan ---
    p_scan = sub.add_parser("scan", help="Scan for nearby BLE devices")
    p_scan.add_argument("-t", "--timeout", type=float, default=10.0)
    p_scan.add_argument("-f", "--filter", type=str, default=None,
                        help="Filter devices by name substring")

    # --- common args for device commands ---
    def add_address(p):
        p.add_argument("address", nargs="?", help="BLE device address (optional, will auto-scan if missing)")

    # --- time ---
    p_time = sub.add_parser("time", help="Sync time to the watch")
    add_address(p_time)

    # --- battery ---
    p_bat = sub.add_parser("battery", help="Get battery level")
    add_address(p_bat)

    # --- reboot ---
    p_reb = sub.add_parser("reboot", help="Reboot the watch")
    add_address(p_reb)

    # --- camera ---
    p_cam = sub.add_parser("camera", help="Trigger camera remote")
    add_address(p_cam)
    
    # --- vibrate ---
    p_vib = sub.add_parser("vibrate", help="Trigger watch vibration")
    add_address(p_vib)
    p_vib.add_argument("-d", "--duration", type=float, default=None,
                       help="Vibration duration in seconds (continuous loop)")
    p_vib.add_argument("-i", "--interval", type=float, default=0.1,
                       help="Pulse interval for continuous mode (default: 0.1s)")
    
    # --- hr ---
    p_hr = sub.add_parser("hr", help="Set heart rate monitor state")
    add_address(p_hr)
    p_hr.add_argument("state", choices=["on", "off"], help="Measurement state")

    # --- measure-hr ---
    p_mhr = sub.add_parser("measure-hr", help="Start manual heart rate measurement")
    add_address(p_mhr)
    p_mhr.add_argument("-d", "--duration", type=float, default=60,
                        help="Measurement duration in seconds (default: 60)")
    p_mhr.add_argument("-c", "--continuous", action="store_true",
                        help="Measure indefinitely until Ctrl+C")
    p_mhr.add_argument("--debug", action="store_true",
                        help="Show raw packets for debugging")

    # --- get-hr-config ---
    p_ghr = sub.add_parser("get-hr-config", help="Read auto-HR settings")
    add_address(p_ghr)
    p_ghr.add_argument("--debug", action="store_true", help="Show raw packets")

    # --- set-hr-config ---
    p_shr = sub.add_parser("set-hr-config", help="Update auto-HR settings")
    add_address(p_shr)
    p_shr.add_argument("state", choices=["on", "off"], help="Auto-HR state")
    p_shr.add_argument("-i", "--interval", type=int, default=10, help="Interval in minutes")
    p_shr.add_argument("--low", type=int, default=0, help="Low threshold")
    p_shr.add_argument("--high", type=int, default=0, help="High threshold")
    p_shr.add_argument("--debug", action="store_true", help="Show raw packets")

    # --- sync-hr ---
    p_synchr = sub.add_parser("sync-hr", help="Sync historical HR logs")
    add_address(p_synchr)
    p_synchr.add_argument("-d", "--days", type=int, default=0, help="Days ago offset")

    # --- sync-sleep ---
    p_slp = sub.add_parser("sync-sleep", help="Sync sleep data (Data Channel)")
    add_address(p_slp)
    p_slp.add_argument("-d", "--days", type=int, default=1, help="Days ago offset")
    p_slp.add_argument("--debug", action="store_true", help="Print raw payload bytes")

    # --- reminders ---
    p_ssit = sub.add_parser("set-sedentary", help="Set sedentary reminder")
    add_address(p_ssit)
    p_ssit.add_argument("state", choices=["on", "off"])
    p_ssit.add_argument("-i", "--interval", type=int, default=60, help="Interval in minutes")
    p_ssit.add_argument("--start-h", type=int, default=8)
    p_ssit.add_argument("--end-h", type=int, default=21)

    p_shyd = sub.add_parser("set-hydration", help="Set hydration reminder")
    add_address(p_shyd)
    p_shyd.add_argument("index", type=int, help="Index 0-7")
    p_shyd.add_argument("state", choices=["on", "off"])
    p_shyd.add_argument("--hour", type=int, required=True)
    p_shyd.add_argument("--minute", type=int, required=True)

    # --- alarms ---
    p_galr = sub.add_parser("get-alarms", help="Get all watch alarms")
    add_address(p_galr)

    p_salr = sub.add_parser("set-alarm", help="Set a watch alarm index")
    add_address(p_salr)
    p_salr.add_argument("index", type=int, help="Index (0 to current max)")
    p_salr.add_argument("state", choices=["on", "off"])
    p_salr.add_argument("--hour", type=int, required=True)
    p_salr.add_argument("--minute", type=int, required=True)
    p_salr.add_argument("--label", type=str, default="Alarm", help="Alarm label text")

    p_dalr = sub.add_parser("del-alarm", help="Delete a watch alarm")
    add_address(p_dalr)
    p_dalr.add_argument("index", type=int, help="Index of alarm to delete")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        asyncio.run(handle_command(args))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
