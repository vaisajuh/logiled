"""GTK3 graphical interface."""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from .device import EFFECT_PARAMS, Mouse, parse_color  # noqa: E402
from .hidpp import HIDPPError, HIDPPTimeout  # noqa: E402

DEVICE_ERRORS = (OSError, ValueError, HIDPPError, HIDPPTimeout)

PRESET_COLORS = [
    ("Red", "ff0000"),
    ("Orange", "ff5000"),
    ("Yellow", "ffc800"),
    ("Green", "00ff00"),
    ("Cyan", "00ffff"),
    ("Blue", "0030ff"),
    ("Purple", "9000ff"),
    ("Pink", "ff0090"),
    ("White", "ffffff"),
]

CSS = b"""
.swatch { min-width: 28px; min-height: 28px; padding: 0; border-radius: 6px; background-image: none; }
.swatch-selected { border: 3px solid @theme_selected_bg_color; }
""" + b"".join(
    f".swatch-{hexcode} {{ background-color: #{hexcode}; }}\n".encode() for _name, hexcode in PRESET_COLORS
)


def _row(grid, row, label, widget):
    lbl = Gtk.Label(label=label, xalign=0)
    grid.attach(lbl, 0, row, 1, 1)
    grid.attach(widget, 1, row, 1, 1)
    widget.set_hexpand(True)
    return lbl


class Window(Gtk.Window):
    def __init__(self, mouse: Mouse):
        super().__init__(title="Logitech Mouse Control")
        self.mouse = mouse
        self.set_border_width(12)
        self.set_default_size(420, -1)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add(box)

        title = Gtk.Label(xalign=0)
        title.set_markup(f"<big><b>{GLib.markup_escape_text(mouse.name())}</b></big>")
        box.pack_start(title, False, False, 0)

        box.pack_start(self._lighting_frame(), False, False, 0)
        box.pack_start(self._performance_frame(), False, False, 0)

        self.status = Gtk.Label(xalign=0)
        self.status.get_style_context().add_class("dim-label")
        box.pack_start(self.status, False, False, 0)

    # --- Lighting ---

    def _lighting_frame(self):
        frame = Gtk.Frame(label="Lighting")
        grid = Gtk.Grid(column_spacing=12, row_spacing=8, margin=10)
        frame.add(grid)

        try:
            self.zones = self.mouse.zones()
        except DEVICE_ERRORS as e:
            grid.attach(Gtk.Label(label=f"Lighting not supported: {e}"), 0, 0, 2, 1)
            return frame

        self.zone_combo = Gtk.ComboBoxText()
        self.zone_combo.append("all", "All zones")
        for z in self.zones:
            self.zone_combo.append(str(z.index), z.name.capitalize())
        self.zone_combo.set_active_id("all")
        self.zone_combo.connect("changed", self._on_zone_changed)
        _row(grid, 0, "Zone", self.zone_combo)

        self.effect_combo = Gtk.ComboBoxText()
        self.effect_combo.connect("changed", self._on_effect_changed)
        _row(grid, 1, "Effect", self.effect_combo)

        self.color_box = self._color_picker()
        self.color_lbl = _row(grid, 2, "Color", self.color_box)

        self.period = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1000, 20000, 500)
        self.period.set_value(4000)
        self.period.connect("format-value", lambda _s, v: f"{v / 1000:.1f} s")
        self.period_lbl = _row(grid, 3, "Period", self.period)

        self.brightness = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 100, 1)
        self.brightness.set_value(100)
        self.brightness.connect("format-value", lambda _s, v: f"{int(v)} %")
        self.brightness_lbl = _row(grid, 4, "Brightness", self.brightness)

        self.speed = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 255, 1)
        self.speed.set_value(50)
        self.speed_lbl = _row(grid, 5, "Speed", self.speed)

        self.persist = Gtk.CheckButton(label="Save to device memory")
        self.persist.set_active(True)
        grid.attach(self.persist, 0, 6, 2, 1)

        apply_btn = Gtk.Button(label="Apply lighting")
        apply_btn.get_style_context().add_class("suggested-action")
        apply_btn.connect("clicked", self._apply_lighting)
        grid.attach(apply_btn, 0, 7, 2, 1)

        self._on_zone_changed(self.zone_combo)
        return frame

    def _selected_zones(self):
        zid = self.zone_combo.get_active_id()
        return self.zones if zid == "all" else [self.zones[int(zid)]]

    def _on_zone_changed(self, _combo):
        current = self.effect_combo.get_active_id()
        zones = self._selected_zones()
        # Only offer effects every selected zone supports.
        effects = [e for e in EFFECT_PARAMS if all(e in z.effects for z in zones)]
        self.effect_combo.remove_all()
        for e in effects:
            self.effect_combo.append(e, e.capitalize())
        if not (current in effects and self.effect_combo.set_active_id(current)):
            self.effect_combo.set_active_id("static" if "static" in effects else effects[0] if effects else None)

    def _on_effect_changed(self, combo):
        used = EFFECT_PARAMS.get(combo.get_active_id(), ())
        for name, widgets in (
            ("color", (self.color_box, self.color_lbl)),
            ("period", (self.period, self.period_lbl)),
            ("brightness", (self.brightness, self.brightness_lbl)),
            ("speed", (self.speed, self.speed_lbl)),
        ):
            for w in widgets:
                w.set_visible(name in used)
                w.set_no_show_all(name not in used)

    def _color_picker(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        swatches = Gtk.Box(spacing=4)
        self.swatches = {}
        for name, hexcode in PRESET_COLORS:
            btn = Gtk.Button(tooltip_text=name)
            btn.get_style_context().add_class("swatch")
            btn.get_style_context().add_class(f"swatch-{hexcode}")
            btn.connect("clicked", lambda _b, h=hexcode: self._set_color(parse_color(h), apply=True))
            swatches.pack_start(btn, False, False, 0)
            self.swatches[hexcode] = btn
        box.pack_start(swatches, False, False, 0)

        custom = Gtk.Box(spacing=6)
        self.color_btn = Gtk.ColorButton(use_alpha=False, title="Choose a lighting color")
        self.color_btn.connect("color-set", self._on_color_button)
        custom.pack_start(self.color_btn, False, False, 0)
        custom.pack_start(Gtk.Label(label="Custom…  #"), False, False, 0)
        self.hex_entry = Gtk.Entry(width_chars=7, max_length=7, placeholder_text="RRGGBB")
        self.hex_entry.connect("activate", self._on_hex_entry)
        custom.pack_start(self.hex_entry, False, False, 0)
        box.pack_start(custom, False, False, 0)

        self._set_color((0, 0x30, 0xFF))
        return box

    def _set_color(self, rgb, apply=False):
        self.color = rgb
        hexcode = "%02x%02x%02x" % rgb
        self.color_btn.set_rgba(Gdk.RGBA(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 1.0))
        self.hex_entry.set_text(hexcode)
        for code, btn in self.swatches.items():
            ctx = btn.get_style_context()
            (ctx.add_class if code == hexcode else ctx.remove_class)("swatch-selected")
        if apply:
            self._apply_lighting(None)

    def _on_color_button(self, btn):
        rgba = btn.get_rgba()
        self._set_color((round(rgba.red * 255), round(rgba.green * 255), round(rgba.blue * 255)), apply=True)

    def _on_hex_entry(self, entry):
        try:
            self._set_color(parse_color(entry.get_text()), apply=True)
        except ValueError as e:
            self.set_status(str(e))

    def _apply_lighting(self, _btn):
        effect = self.effect_combo.get_active_id()
        if effect not in EFFECT_PARAMS:
            return
        params = dict(
            color=self.color,
            period=int(self.period.get_value()),
            brightness=int(self.brightness.get_value()),
            speed=int(self.speed.get_value()),
        )
        try:
            for zone in self._selected_zones():
                self.mouse.set_effect(zone, effect, persist=self.persist.get_active(), **params)
            self.set_status(f"Applied {effect}")
        except DEVICE_ERRORS as e:
            self.set_status(f"Error: {e}")

    # --- DPI, report rate, mode ---

    def _performance_frame(self):
        frame = Gtk.Frame(label="Performance")
        grid = Gtk.Grid(column_spacing=12, row_spacing=8, margin=10)
        frame.add(grid)
        row = 0

        try:
            choices = self.mouse.dpi_choices()
            step = choices[1] - choices[0] if len(choices) > 1 else 50
            self.dpi = Gtk.SpinButton.new_with_range(choices[0], choices[-1], step)
            self.dpi.set_value(self.mouse.dpi())
            dpi_box = Gtk.Box(spacing=6)
            dpi_box.pack_start(self.dpi, True, True, 0)
            btn = Gtk.Button(label="Set")
            btn.connect("clicked", self._apply_dpi)
            dpi_box.pack_start(btn, False, False, 0)
            _row(grid, row, "DPI", dpi_box)
            row += 1
        except DEVICE_ERRORS:
            pass

        try:
            rate = Gtk.ComboBoxText()
            for hz in self.mouse.report_rates():
                rate.append(str(hz), f"{hz} Hz")
            rate.set_active_id(str(self.mouse.report_rate()))
            rate.connect("changed", self._apply_rate)
            _row(grid, row, "Polling rate", rate)
            row += 1
        except DEVICE_ERRORS:
            pass

        try:
            mode = self.mouse.mode()
            if mode:
                combo = Gtk.ComboBoxText()
                combo.append("onboard", "Onboard profiles")
                combo.append("host", "Host (software) control")
                combo.set_active_id(mode)
                combo.connect("changed", self._apply_mode)
                _row(grid, row, "Mode", combo)
                row += 1
        except DEVICE_ERRORS:
            pass

        if row == 0:
            grid.attach(Gtk.Label(label="No adjustable settings found"), 0, 0, 2, 1)
        return frame

    def _apply_dpi(self, _btn):
        try:
            value = self.mouse.set_dpi(int(self.dpi.get_value()))
            self.dpi.set_value(value)
            self.set_status(f"DPI set to {value}")
        except DEVICE_ERRORS as e:
            self.set_status(f"Error: {e}")

    def _apply_rate(self, combo):
        try:
            self.mouse.set_report_rate(int(combo.get_active_id()))
            self.set_status(f"Polling rate set to {combo.get_active_id()} Hz")
        except DEVICE_ERRORS as e:
            self.set_status(f"Error: {e}")

    def _apply_mode(self, combo):
        try:
            self.mouse.set_mode(combo.get_active_id())
            self.set_status(f"Mode set to {combo.get_active_id()}")
        except DEVICE_ERRORS as e:
            self.set_status(f"Error: {e}")

    def set_status(self, text):
        self.status.set_text(text)


def run(devnode=None):
    try:
        mouse = Mouse.open(devnode)
    except (RuntimeError, PermissionError, *DEVICE_ERRORS) as e:
        dialog = Gtk.MessageDialog(
            message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.CLOSE, text="Cannot open mouse"
        )
        dialog.format_secondary_text(str(e))
        dialog.run()
        return 1
    win = Window(mouse)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
    mouse.close()
    return 0
