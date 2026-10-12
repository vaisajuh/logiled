# logiled

Control the lighting, DPI, polling rate and onboard-profile mode of Logitech
HID++ 2.0 mice on Linux. Built for the **G502 (SE) HERO**, but it should work on
other Logitech mice with the `COLOR_LED_EFFECTS` (0x8070) feature.

Pure Python 3 with no dependencies. The GUI uses GTK 3 (`python3-gi`, which comes with Ubuntu/Pop!_OS).

## Install

```bash
./install.sh
```

This installs a udev rule so your user can access the mouse without sudo,
links `logiled` into `~/.local/bin`, and adds a "Logitech Mouse Control" app
launcher. You may need to unplug and replug the mouse once.

## Usage

```bash
logiled list                                   # detected devices
logiled info                                   # name, mode, DPI, rate, lighting zones
logiled gui                                    # graphical interface

logiled led static  -c ff0000                  # all zones solid red
logiled led breathe -z logo -c 00aaff -p 4000 -b 80
logiled led cycle   -p 10000                   # rainbow cycle, 10 s period
logiled led off     -z primary
logiled led static  -c 00ff00 --no-save        # temporary, not stored on the mouse

logiled dpi                                    # show DPI
logiled dpi 1600                               # set DPI (snaps to a supported value)
logiled rate 1000                              # polling rate in Hz
logiled mode host                              # software control (vs. onboard)
```

Zones can be given by name (`primary`, `logo`) or index. `logiled info` shows
which effects each zone supports.

## Notes

- By default lighting is saved to the mouse's memory, so it stays after replugging.
- In **onboard** mode the mouse uses its stored profiles, and DPI/rate changes may be
  overridden by the active profile. If a change doesn't stick, run `logiled mode host`.
  In host mode the settings last until the mouse is unplugged.
- Close Solaar/Piper/G Hub-like tools while using logiled, so they don't overwrite your settings.

## Development

```bash
./logiled-run info                             # run from the source tree
python3 -m unittest discover -s tests          # protocol tests with a simulated mouse
```

Layout: `logiled/hidpp.py` (HID++ transport over hidraw), `logiled/device.py`
(features), `logiled/cli.py`, `logiled/gui.py`.

## How it's built

- **Finding the mouse.** `hidpp.py` scans `/sys/class/hidraw/*` for Logitech
  (`046d`) interfaces whose HID report descriptor has the vendor usage page
  `0xFF00` and long report ID `0x11`, which is the HID++ interface.
- **HID++ 2.0 transport.** Requests are 20-byte long reports:
  `[0x11, device index, feature index, function << 4 | software id, 16 params]`.
  The software ID tells our replies apart from the mouse's own notifications,
  and error replies are decoded into readable messages. Wired mice answer on
  device index `0xFF`; receiver-paired ones on 1–6, so both are tried.
- **Features.** HID++ 2.0 devices number their features differently, so each
  feature ID is first looked up through the root feature (`0x0000`) and the
  index is cached. `device.py` then implements:
  - `0x8070` COLOR_LED_EFFECTS: enumerates zones and the effects each one
    supports, and sets an effect with its 10 parameter bytes (color, period,
    brightness) plus a flag to store it on the mouse
  - `0x2201` adjustable DPI, including the compressed "range with step" lists
  - `0x8060` report rate, `0x8100` onboard profiles (host vs. onboard mode),
    `0x0005` device name
- **Front ends:** `cli.py` (argparse) and `gui.py` (GTK 3 via PyGObject).
- **Tests** run the real transport against a simulated mouse on the other end
  of a socket pair, so the packet encoding is tested without hardware.

## Related projects

Part of a small set of Linux lighting tools, all pure Python with no third-party dependencies:

- [clcr](https://github.com/vaisajuh/clcr): Lighting Control Center: one tkinter desktop app for all three devices below (bundles their drivers)
- [akkoctl](https://github.com/vaisajuh/akkoctl): Akko 5075B Plus-S keyboard: RGB backlight, sidelights, keymap and macros
- [caselight](https://github.com/vaisajuh/caselight): ASUS Aura USB controller: motherboard and ARGB header lighting
- **logiled** (this repo): Logitech G502 HERO mouse: lighting, DPI, polling rate and onboard mode

## License

MIT. See [LICENSE](LICENSE).
