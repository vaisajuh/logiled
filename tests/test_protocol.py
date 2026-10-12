"""Protocol tests against a simulated HID++ 2.0 mouse (no hardware needed).

Run with:  python3 -m unittest discover -s tests
"""

import os
import socket
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from logiled.device import Mouse, effect_params, parse_color  # noqa: E402
from logiled.hidpp import HIDPP, HIDPPError  # noqa: E402

FEATURES = {0x0000: 0, 0x0005: 1, 0x2201: 2, 0x8060: 3, 0x8070: 4, 0x8100: 5}
NAME = b"G502 HERO Gaming Mouse"
# zone -> list of effect IDs, mirroring a G502 HERO (primary + logo)
ZONES = {0: (0x0001, [0x0000, 0x0001, 0x0003, 0x000A]), 1: (0x0002, [0x0000, 0x0001, 0x0003, 0x000A])}


class FakeMouse(threading.Thread):
    def __init__(self, sock):
        super().__init__(daemon=True)
        self.sock = sock
        self.dpi = 1600
        self.rate_ms = 1
        self.mode = 1
        self.writes = []

    def run(self):
        while True:
            try:
                msg = self.sock.recv(64)
            except OSError:
                return
            if not msg:
                return
            reply = self.handle(msg)
            if reply is not None:
                self.sock.send(reply)

    def handle(self, msg):
        rid, idx, feat, fb = msg[:4]
        p = msg[4:]
        func = fb >> 4
        if idx != 0xFF:
            return None  # silently ignore other device indexes

        def ok(*data):
            return bytes([0x11, idx, feat, fb]) + bytes(data).ljust(16, b"\0")

        def err(code):
            return bytes([0x11, idx, 0xFF, feat, fb, code]).ljust(20, b"\0")

        if feat == 0:
            if func == 0:
                fid = (p[0] << 8) | p[1]
                return ok(FEATURES.get(fid, 0))
            if func == 1:
                return ok(4, 2, p[2])
        if feat == 1:
            if func == 0:
                return ok(len(NAME))
            if func == 1:
                return ok(*NAME[p[0] : p[0] + 16])
        if feat == 2:
            if func == 1:  # 100..25600 step 50
                return ok(0, 0, 100, 0xE0, 50, 25600 >> 8, 25600 & 0xFF, 0, 0)
            if func == 2:
                return ok(0, self.dpi >> 8, self.dpi & 0xFF, 0x06, 0x40)
            if func == 3:
                self.dpi = (p[1] << 8) | p[2]
                return ok(0)
        if feat == 3:
            if func == 0:
                return ok(0b10001011)  # 1, 2, 4, 8 ms
            if func == 1:
                return ok(self.rate_ms)
            if func == 2:
                self.rate_ms = p[0]
                return ok()
        if feat == 4:
            if func == 0:
                return ok(len(ZONES))
            if func == 1:
                loc, effects = ZONES[p[0]]
                return ok(p[0], loc >> 8, loc & 0xFF, len(effects))
            if func == 2:
                eid = ZONES[p[0]][1][p[1]]
                return ok(p[0], p[1], eid >> 8, eid & 0xFF)
            if func == 3:
                self.writes.append(bytes(p[:13]))
                return ok(p[0])
        if feat == 5:
            if func == 1:
                self.mode = p[0]
                return ok()
            if func == 2:
                return ok(self.mode)
        return err(0x07)


class ProtocolTest(unittest.TestCase):
    def setUp(self):
        host, dev = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.fake = FakeMouse(dev)
        self.fake.start()
        self.host = host
        self.mouse = Mouse(HIDPP(host.fileno()), "/dev/fake", "fake")

    def tearDown(self):
        self.host.close()
        self.fake.sock.close()

    def test_ping_and_name(self):
        self.assertEqual(self.mouse.hidpp.protocol_version(), (4, 2))
        self.assertEqual(self.mouse.name(), NAME.decode())

    def test_zones(self):
        zones = self.mouse.zones()
        self.assertEqual([z.name for z in zones], ["primary", "logo"])
        self.assertEqual(zones[0].effects, {"off": 0, "static": 1, "cycle": 2, "breathe": 3})

    def test_set_static_color_uses_effect_index(self):
        logo = self.mouse.find_zones("logo")[0]
        self.mouse.set_effect(logo, "static", color=(0x12, 0x34, 0x56))
        self.assertEqual(self.fake.writes[-1], bytes([1, 1, 0x12, 0x34, 0x56, 0, 0, 0, 0, 0, 0, 0, 1]))

    def test_breathe_encoding_and_no_persist(self):
        zone = self.mouse.find_zones("0")[0]
        self.mouse.set_effect(zone, "breathe", persist=False, color=(255, 0, 0), period=5000, brightness=80)
        self.assertEqual(self.fake.writes[-1], bytes([0, 3, 255, 0, 0, 0x13, 0x88, 0, 80, 0, 0, 0, 0]))

    def test_unsupported_effect_rejected(self):
        zone = self.mouse.zones()[0]
        with self.assertRaises(ValueError):
            self.mouse.set_effect(zone, "ripple")

    def test_dpi(self):
        choices = self.mouse.dpi_choices()
        self.assertEqual((choices[0], choices[-1], choices[1] - choices[0]), (100, 25600, 50))
        self.assertEqual(self.mouse.dpi(), 1600)
        self.assertEqual(self.mouse.set_dpi(3210), 3200)  # snapped to nearest step
        self.assertEqual(self.mouse.dpi(), 3200)

    def test_report_rate(self):
        self.assertEqual(self.mouse.report_rates(), [1000, 500, 250, 125])
        self.mouse.set_report_rate(500)
        self.assertEqual(self.mouse.report_rate(), 500)

    def test_mode(self):
        self.assertEqual(self.mouse.mode(), "onboard")
        self.mouse.set_mode("host")
        self.assertEqual(self.mouse.mode(), "host")

    def test_device_error_raised(self):
        with self.assertRaises(HIDPPError):
            self.mouse.hidpp.request(4, 9)


class HelpersTest(unittest.TestCase):
    def test_parse_color(self):
        self.assertEqual(parse_color("#ff8000"), (255, 128, 0))
        self.assertEqual(parse_color("0f0"), (0, 255, 0))
        with self.assertRaises(ValueError):
            parse_color("12345")

    def test_cycle_params(self):
        self.assertEqual(effect_params("cycle", period=10000, brightness=50), bytes([0, 0, 0, 0, 0, 0x27, 0x10, 50, 0, 0]))


if __name__ == "__main__":
    unittest.main()
