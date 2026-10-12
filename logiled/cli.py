"""Command-line interface: `logiled info | led | dpi | rate | mode | list | gui`."""

import argparse
import sys

from .device import EFFECT_PARAMS, Mouse, parse_color
from .hidpp import HIDPPError, HIDPPTimeout, find_devices


def cmd_list(args):
    found = False
    for info in find_devices():
        found = True
        print(f"{info.devnode}  {info.name}  (pid {info.product_id:04x})")
    if not found:
        print("No Logitech HID++ devices found.")


def cmd_info(mouse, args):
    print(f"Device:   {mouse.name()}  [{mouse.devnode}]")
    if (mode := mouse.mode()) is not None:
        print(f"Mode:     {mode}")
    try:
        print(f"DPI:      {mouse.dpi()}  (range {_range(mouse.dpi_choices())})")
    except HIDPPError:
        pass
    try:
        rates = ", ".join(str(r) for r in mouse.report_rates())
        print(f"Rate:     {mouse.report_rate()} Hz  (supported: {rates})")
    except HIDPPError:
        pass
    try:
        for zone in mouse.zones():
            print(f"Zone {zone.index}:   {zone.name:10} effects: {', '.join(zone.effects)}")
    except HIDPPError:
        print("Lighting: not supported (no 0x8070 feature)")


def _range(values):
    return f"{values[0]}-{values[-1]}" if values else "?"


def cmd_led(mouse, args):
    params = {}
    if args.color:
        params["color"] = parse_color(args.color)
    if args.period is not None:
        params["period"] = args.period
    if args.brightness is not None:
        params["brightness"] = args.brightness
    if args.speed is not None:
        params["speed"] = args.speed
    for zone in mouse.find_zones(args.zone):
        mouse.set_effect(zone, args.effect, persist=not args.no_save, **params)
        print(f"{zone.name}: {args.effect}")


def cmd_dpi(mouse, args):
    if args.value is None:
        print(mouse.dpi())
    else:
        print(f"DPI set to {mouse.set_dpi(args.value)}")


def cmd_rate(mouse, args):
    if args.hz is None:
        print(f"{mouse.report_rate()} Hz")
    else:
        supported = mouse.report_rates()
        if args.hz not in supported:
            sys.exit(f"Unsupported rate; choose from {supported}")
        mouse.set_report_rate(args.hz)
        print(f"Report rate set to {args.hz} Hz")


def cmd_mode(mouse, args):
    if args.mode is None:
        print(mouse.mode() or "device has no onboard profiles")
    else:
        mouse.set_mode(args.mode)
        print(f"Mode set to {args.mode}")


def build_parser():
    p = argparse.ArgumentParser(prog="logiled", description="Control Logitech mouse lighting and settings")
    p.add_argument("-d", "--device", help="hidraw node to use (default: first Logitech HID++ device)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list detected Logitech HID++ devices")
    sub.add_parser("info", help="show device name, mode, DPI, report rate and lighting zones")
    sub.add_parser("gui", help="open the graphical interface")

    led = sub.add_parser("led", help="set a lighting effect")
    led.add_argument("effect", choices=list(EFFECT_PARAMS))
    led.add_argument("-z", "--zone", default="all", help="zone name or index (default: all)")
    led.add_argument("-c", "--color", help="RRGGBB hex color, e.g. ff0000")
    led.add_argument("-p", "--period", type=int, help="effect period in ms (cycle/breathe/ripple)")
    led.add_argument("-b", "--brightness", type=int, help="brightness 1-100 (cycle/breathe)")
    led.add_argument("-s", "--speed", type=int, help="speed 0-255 (pulse)")
    led.add_argument("--no-save", action="store_true", help="don't store the effect in device memory")

    dpi = sub.add_parser("dpi", help="get or set sensor DPI")
    dpi.add_argument("value", nargs="?", type=int)

    rate = sub.add_parser("rate", help="get or set polling rate in Hz")
    rate.add_argument("hz", nargs="?", type=int)

    mode = sub.add_parser("mode", help="get or set onboard-profile mode (host = software control)")
    mode.add_argument("mode", nargs="?", choices=["host", "onboard"])
    return p


COMMANDS = {"info": cmd_info, "led": cmd_led, "dpi": cmd_dpi, "rate": cmd_rate, "mode": cmd_mode}


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "list":
        return cmd_list(args)
    if args.command == "gui":
        from .gui import run

        return run(args.device)
    try:
        with Mouse.open(args.device) as mouse:
            COMMANDS[args.command](mouse, args)
    except (PermissionError, RuntimeError, ValueError, HIDPPError, HIDPPTimeout) as e:
        sys.exit(f"logiled: {e}")


if __name__ == "__main__":
    main()
