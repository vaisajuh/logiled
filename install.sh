#!/usr/bin/env bash
# Install logiled for the current user, plus the udev rule (needs sudo once).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

echo "==> Installing udev rule (sudo required)"
sudo install -m 644 data/70-logiled.rules /etc/udev/rules.d/70-logiled.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw

echo "==> Linking 'logiled' into ~/.local/bin"
mkdir -p ~/.local/bin ~/.local/share/applications
ln -sf "$PWD/logiled-run" ~/.local/bin/logiled
install -m 644 data/logiled.desktop ~/.local/share/applications/logiled.desktop

echo "Done. Try:  logiled info   or   logiled gui"
