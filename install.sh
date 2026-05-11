#!/bin/bash
set -e

# Locked-In "One-Shot" Installer for Linux (Arch/Debian/Fedora)
# -----------------------------------------------------------

echo "--- Installing Locked-In ---"

# 1. System Dependency Detection
if command -v pacman &> /dev/null; then
    echo "[1/5] Arch Linux detected. Installing dependencies via pacman..."
    sudo pacman -S --needed python qt6-base hyprlock libpulse
elif command -v apt-get &> /dev/null; then
    echo "[1/5] Debian/Ubuntu detected. Installing dependencies via apt..."
    sudo apt-get update
    sudo apt-get install -y python3 python3-venv qt6-base-dev pulseaudio-utils
    echo "NOTE: hyprlock may need to be installed manually on your system."
elif command -v dnf &> /dev/null; then
    echo "[1/5] Fedora detected. Installing dependencies via dnf..."
    sudo dnf install -y python3 qt6-qtbase-devel pulseaudio-utils
else
    echo "[!] Unknown package manager. Please ensure you have the following installed:"
    echo "    - Python 3.11+"
    echo "    - Qt6 Base libraries"
    echo "    - hyprlock (for lockout feature)"
    echo "    - pactl (pulseaudio-utils/libpulse)"
    read -p "Press Enter to continue once dependencies are met..."
fi

# 2. Virtual Environment Setup
echo "[2/5] Setting up Python virtual environment..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
./.venv/bin/pip install -e .

# 3. Port Selection
echo "[3/5] Selecting available port..."
PORT=8765
# Use python to check port availability as it's more portable than nc/ss
while python3 -c "import socket; s=socket.socket(); s.settimeout(0.1); exit(0 if s.connect_ex(('127.0.0.1', $PORT)) == 0 else 1)" &>/dev/null; do
    echo "[!] Port $PORT is in use, trying $((PORT+1))..."
    PORT=$((PORT+1))
done
echo "[*] Selected port $PORT."

# 4. Configuration Setup
echo "[4/5] Checking configuration..."
if [ ! -f "config.toml" ]; then
    echo "Creating config.toml from example..."
    cp config.example.toml config.toml
    # Update config.toml with the detected port
    sed -i "s/port = 8765/port = $PORT/" config.toml
fi

# 5. Systemd Service Generation
echo "[5/5] Generating systemd user services..."
mkdir -p ~/.config/systemd/user

# Use $PWD to get absolute paths
WORKING_DIR="$PWD"
VENV_BIN="$PWD/.venv/bin/locked-in"

# Locked-In Daemon Service
cat <<EOF > ~/.config/systemd/user/locked-in.service
[Unit]
Description=Locked-In Daemon
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
WorkingDirectory=$WORKING_DIR
ExecStart=$VENV_BIN run-legacy
Restart=on-failure
RestartSec=2

[Install]
WantedBy=graphical-session.target
EOF

# Locked-In Web Dashboard Service
cat <<EOF > ~/.config/systemd/user/locked-in-web.service
[Unit]
Description=Locked-In Web Dashboard

[Service]
Type=simple
WorkingDirectory=$WORKING_DIR
ExecStart=$VENV_BIN web --port $PORT
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
EOF

# Locked-In Browser Opener (Optional)
cat <<EOF > ~/.config/systemd/user/locked-in-browser.service
[Unit]
Description=Open Locked-In dashboard in browser on login
After=locked-in-web.service graphical-session.target
Requires=locked-in-web.service
Wants=graphical-session.target

[Service]
Type=oneshot
ExecStartPre=/bin/sleep 4
ExecStart=/bin/sh -c 'exec xdg-open http://localhost:$PORT'
RemainAfterExit=yes
Environment=DISPLAY=:1
Environment=WAYLAND_DISPLAY=wayland-1
Environment=XDG_RUNTIME_DIR=/run/user/$(id -u)

[Install]
WantedBy=default.target
EOF

# 6. Enable and Start
echo "[6/6] Reloading and starting services..."
systemctl --user daemon-reload
systemctl --user enable --now locked-in.service
systemctl --user enable --now locked-in-web.service

# Enable lingering for the current user so services start on boot
echo "[*] Enabling user lingering for persistent startup..."
sudo loginctl enable-linger $(whoami)

echo "------------------------------------------------"
echo "DONE! Locked-In is installed and active."
echo "Dashboard: http://localhost:$PORT"
echo "CLI: ./.venv/bin/locked-in status"
echo "------------------------------------------------"
