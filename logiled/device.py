"""High-level control of a Logitech mouse: lighting, DPI, report rate, onboard mode."""

from dataclasses import dataclass, field

from .hidpp import HIDPP, HIDPPError, find_devices

# HID++ 2.0 feature IDs
DEVICE_NAME = 0x0005
ADJUSTABLE_DPI = 0x2201
REPORT_RATE = 0x8060
COLOR_LED_EFFECTS = 0x8070
ONBOARD_PROFILES = 0x8100

# 0x8070 effect IDs and the names we expose for them
EFFECT_NAMES = {
    0x0000: "off",
    0x0001: "static",
    0x0002: "pulse",
    0x0003: "cycle",
    0x0008: "boot",
    0x0009: "demo",
    0x000A: "breathe",
    0x000B: "ripple",
}
EFFECT_IDS = {name: eid for eid, name in EFFECT_NAMES.items()}

# Which parameters each effect uses (drives both CLI validation and the GUI)
EFFECT_PARAMS = {
    "off": (),
    "static": ("color",),
    "pulse": ("color", "speed"),
    "cycle": ("period", "brightness"),
    "breathe": ("color", "period", "brightness"),
    "ripple": ("color", "period"),
}

ZONE_LOCATIONS = {
    0x0001: "primary",
    0x0002: "logo",
    0x0003: "left",
    0x0004: "right",
    0x0005: "combined",
    0x0006: "primary-1",
    0x0007: "primary-2",
    0x0008: "primary-3",
    0x0009: "primary-4",
    0x000A: "primary-5",
    0x000B: "primary-6",
}

MODE_ONBOARD = 1
MODE_HOST = 2


@dataclass
class Zone:
    index: int
    location: int
    effects: dict = field(default_factory=dict)  # effect name -> effect index

    @property
    def name(self):
        return ZONE_LOCATIONS.get(self.location, f"zone{self.index}")


def effect_params(effect, color=(255, 255, 255), period=3000, brightness=100, speed=50):
    """Encode the 10 effect-parameter bytes of a 0x8070 SetZoneEffect request."""
    r, g, b = color
    period = max(0, min(0xFFFF, int(period)))
    # Intensity 0 means "device default" (100%), so 1..100 is passed through as-is.
    brightness = max(1, min(100, int(brightness)))
    if effect == "off":
        p = []
    elif effect == "static":
        p = [r, g, b, 0]
    elif effect == "pulse":
        p = [r, g, b, max(0, min(255, int(speed)))]
    elif effect == "cycle":
        p = [0, 0, 0, 0, 0, period >> 8, period & 0xFF, brightness]
    elif effect == "breathe":
        p = [r, g, b, period >> 8, period & 0xFF, 0, brightness]
    elif effect == "ripple":
        p = [r, g, b, 0, period >> 8, period & 0xFF]
    else:
        raise ValueError(f"unsupported effect {effect!r}")
    return bytes(p).ljust(10, b"\0")


def parse_color(text):
    text = text.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    if len(text) != 6:
        raise ValueError(f"invalid color {text!r}, use RRGGBB")
    value = int(text, 16)
    return (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF


class Mouse:
    def __init__(self, hidpp: HIDPP, devnode="", hid_name=""):
        self.hidpp = hidpp
        self.devnode = devnode
        self.hid_name = hid_name
        self._zones = None

    @classmethod
    def open(cls, devnode=None):
        candidates = list(find_devices())
        if devnode:
            info = next((c for c in candidates if c.devnode == devnode), None)
            name = info.name if info else devnode
        else:
            if not candidates:
                raise RuntimeError("No Logitech HID++ device found")
            info = candidates[0]
            devnode, name = info.devnode, info.name
        return cls(HIDPP.open(devnode), devnode, name)

    def close(self):
        self.hidpp.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def has(self, feature_id):
        return self.hidpp.feature_index(feature_id) is not None

    # --- Name ---

    def name(self):
        if not self.has(DEVICE_NAME):
            return self.hid_name
        length = self.hidpp.feature_request(DEVICE_NAME, 0)[0]
        chars = b""
        while len(chars) < length:
            chunk = self.hidpp.feature_request(DEVICE_NAME, 1, len(chars))
            chars += chunk[: length - len(chars)]
        return chars.decode("utf-8", "replace").rstrip("\0")

    # --- Lighting (0x8070) ---

    def zones(self):
        if self._zones is None:
            req = lambda fn, *p: self.hidpp.feature_request(COLOR_LED_EFFECTS, fn, *p)
            count = req(0)[0]
            zones = []
            for z in range(count):
                info = req(1, z)
                zone = Zone(index=z, location=(info[1] << 8) | info[2])
                for e in range(info[3]):
                    einfo = req(2, z, e)
                    effect_id = (einfo[2] << 8) | einfo[3]
                    name = EFFECT_NAMES.get(effect_id)
                    if name in EFFECT_PARAMS:
                        zone.effects[name] = e
                zones.append(zone)
            self._zones = zones
        return self._zones

    def find_zones(self, selector="all"):
        zones = self.zones()
        if selector in (None, "all"):
            return zones
        for z in zones:
            if selector == z.name or selector == str(z.index):
                return [z]
        raise ValueError(f"unknown zone {selector!r}; available: {', '.join(z.name for z in zones)}")

    def set_effect(self, zone: Zone, effect, persist=True, **params):
        if effect not in zone.effects:
            raise ValueError(
                f"zone {zone.name} does not support {effect!r}; "
                f"supported: {', '.join(zone.effects)}"
            )
        payload = effect_params(effect, **params)
        self.hidpp.feature_request(
            COLOR_LED_EFFECTS, 3, zone.index, zone.effects[effect], *payload, 1 if persist else 0
        )

    # --- DPI (0x2201) ---

    def dpi_choices(self, sensor=0):
        """Return the list of DPI values the sensor accepts."""
        reply = self.hidpp.feature_request(ADJUSTABLE_DPI, 1, sensor)[1:]
        raw = [(reply[i] << 8) | reply[i + 1] for i in range(0, len(reply) - 1, 2)]
        values = []
        i = 0
        while i < len(raw) and raw[i]:
            v = raw[i]
            if v >> 13 == 0b111 and values and i + 1 < len(raw):
                step, end = v & 0x1FFF, raw[i + 1]
                values.extend(range(values[-1] + step, end + 1, step))
                i += 2
                continue
            values.append(v)
            i += 1
        return sorted(set(values))

    def dpi(self, sensor=0):
        reply = self.hidpp.feature_request(ADJUSTABLE_DPI, 2, sensor)
        return (reply[1] << 8) | reply[2]

    def set_dpi(self, value, sensor=0):
        choices = self.dpi_choices(sensor)
        if choices and value not in choices:
            value = min(choices, key=lambda c: abs(c - value))
        self.hidpp.feature_request(ADJUSTABLE_DPI, 3, sensor, value >> 8, value & 0xFF)
        return value

    # --- Report rate (0x8060) ---

    def report_rates(self):
        """Supported polling rates in Hz, highest first."""
        flags = self.hidpp.feature_request(REPORT_RATE, 0)[0]
        return [1000 // (bit + 1) for bit in range(8) if flags & (1 << bit)]

    def report_rate(self):
        ms = self.hidpp.feature_request(REPORT_RATE, 1)[0]
        return 1000 // ms if ms else None

    def set_report_rate(self, hz):
        ms = max(1, round(1000 / hz))
        self.hidpp.feature_request(REPORT_RATE, 2, ms)

    # --- Onboard profiles mode (0x8100) ---

    def mode(self):
        if not self.has(ONBOARD_PROFILES):
            return None
        return "host" if self.hidpp.feature_request(ONBOARD_PROFILES, 2)[0] == MODE_HOST else "onboard"

    def set_mode(self, mode):
        value = {"host": MODE_HOST, "onboard": MODE_ONBOARD}[mode]
        self.hidpp.feature_request(ONBOARD_PROFILES, 1, value)


__all__ = ["Mouse", "Zone", "HIDPPError", "EFFECT_PARAMS", "parse_color", "effect_params"]
