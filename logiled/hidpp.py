"""Minimal HID++ 2.0 transport over Linux hidraw (no third-party dependencies)."""

import glob
import os
import select
import time
from dataclasses import dataclass

LOGITECH_VID = 0x046D

REPORT_SHORT = 0x10
REPORT_LONG = 0x11
LONG_LEN = 20
PARAMS_LEN = LONG_LEN - 4

# Software ID placed in the low nibble of the function byte so we can tell our
# replies apart from unsolicited device notifications (which use swid 0).
SW_ID = 0x0B

ERRORS = {
    0x01: "unknown",
    0x02: "invalid argument",
    0x03: "out of range",
    0x04: "hardware error",
    0x05: "logitech internal",
    0x06: "invalid feature index",
    0x07: "invalid function",
    0x08: "busy",
    0x09: "unsupported",
}


class HIDPPError(Exception):
    def __init__(self, code, feature_index=None, function=None):
        self.code = code
        msg = ERRORS.get(code, f"error 0x{code:02x}")
        if feature_index is not None:
            msg = f"{msg} (feature index {feature_index}, function {function})"
        super().__init__(msg)


class HIDPPTimeout(Exception):
    pass


@dataclass
class HidrawInfo:
    devnode: str
    name: str
    product_id: int


def _supports_hidpp_long(descriptor: bytes) -> bool:
    # Vendor usage page 0xFF00 together with report ID 0x11 marks the HID++ interface.
    return b"\x06\x00\xff" in descriptor and b"\x85\x11" in descriptor


def find_devices():
    """Yield hidraw nodes of Logitech devices that expose a HID++ long-report interface."""
    for sys_path in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            with open(os.path.join(sys_path, "device", "uevent")) as f:
                uevent = dict(line.strip().split("=", 1) for line in f if "=" in line)
            with open(os.path.join(sys_path, "device", "report_descriptor"), "rb") as f:
                descriptor = f.read()
        except OSError:
            continue
        # HID_ID looks like "0003:0000046D:0000C08B"
        try:
            _bus, vid, pid = (int(x, 16) for x in uevent.get("HID_ID", "").split(":"))
        except ValueError:
            continue
        if vid != LOGITECH_VID or not _supports_hidpp_long(descriptor):
            continue
        yield HidrawInfo(
            devnode="/dev/" + os.path.basename(sys_path),
            name=uevent.get("HID_NAME", "Logitech device"),
            product_id=pid,
        )


class HIDPP:
    """A HID++ 2.0 endpoint: a hidraw file descriptor plus a device index."""

    def __init__(self, fd, device_index=0xFF):
        self.fd = fd
        self.index = device_index
        self._features = {}

    @classmethod
    def open(cls, devnode):
        try:
            fd = os.open(devnode, os.O_RDWR | os.O_NONBLOCK)
        except PermissionError:
            raise PermissionError(
                f"No permission to open {devnode}. Install the udev rule "
                "(./install.sh) or run once with sudo."
            ) from None
        dev = cls(fd)
        # Wired/direct devices answer on index 0xFF; receiver-paired ones on 1..6.
        for index in (0xFF, 1, 2, 3, 4, 5, 6):
            dev.index = index
            try:
                dev.protocol_version()
                return dev
            except (HIDPPError, HIDPPTimeout):
                continue
        os.close(fd)
        raise HIDPPTimeout(f"{devnode} did not answer HID++ 2.0 requests")

    def close(self):
        os.close(self.fd)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _drain(self):
        while select.select([self.fd], [], [], 0)[0]:
            try:
                os.read(self.fd, 64)
            except BlockingIOError:
                break

    def request(self, feature_index, function, *params, timeout=1.0):
        """Send a long report and return the 16 parameter bytes of the matching reply."""
        if len(params) > PARAMS_LEN:
            raise ValueError("too many parameters")
        func_byte = ((function & 0x0F) << 4) | SW_ID
        msg = bytes([REPORT_LONG, self.index, feature_index, func_byte])
        msg += bytes(params).ljust(PARAMS_LEN, b"\0")
        self._drain()
        os.write(self.fd, msg)

        remaining = timeout
        while remaining > 0:
            start = time.monotonic()
            if not select.select([self.fd], [], [], remaining)[0]:
                break
            remaining -= time.monotonic() - start
            try:
                reply = os.read(self.fd, 64)
            except BlockingIOError:
                continue
            if len(reply) < 7 or reply[0] not in (REPORT_SHORT, REPORT_LONG):
                continue
            if reply[1] != self.index:
                continue
            # HID++ 2.0 error: [rid, idx, 0xFF, feature_index, func_byte, code]
            # HID++ 1.0 error: [rid, idx, 0x8F, sub_id, address, code]
            if reply[2] in (0xFF, 0x8F) and reply[3] == feature_index and reply[4] == func_byte:
                raise HIDPPError(reply[5], feature_index, function)
            if reply[2] == feature_index and reply[3] == func_byte:
                return reply[4:].ljust(PARAMS_LEN, b"\0")
        raise HIDPPTimeout(f"no reply to feature {feature_index} function {function}")

    # --- Root feature (always index 0) ---

    def protocol_version(self):
        reply = self.request(0x00, 1, 0, 0, 0x5A, timeout=0.3)
        if reply[2] != 0x5A:
            raise HIDPPTimeout("bad ping reply")
        return reply[0], reply[1]

    def feature_index(self, feature_id):
        """Return the index of a feature, or None if the device lacks it."""
        if feature_id not in self._features:
            reply = self.request(0x00, 0, feature_id >> 8, feature_id & 0xFF)
            self._features[feature_id] = reply[0] or None
        return self._features[feature_id]

    def feature_request(self, feature_id, function, *params):
        index = self.feature_index(feature_id)
        if index is None:
            raise HIDPPError(0x09)
        return self.request(index, function, *params)
