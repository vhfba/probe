#!/bin/bash

set -e

echo "Installing Beacon Agent..."

INSTALL_DIR="/opt/beacon-agent"
CONFIG_DIR="/etc/beacon-agent"

sudo mkdir -p "$INSTALL_DIR"
sudo mkdir -p "$INSTALL_DIR/plugins"
sudo mkdir -p "$CONFIG_DIR"

echo "Copying files..."

sudo cp pi_agent.py "$INSTALL_DIR/"
sudo cp -r plugins "$INSTALL_DIR/" 2>/dev/null || true
sudo cp configs/config.yaml "$CONFIG_DIR/config.yaml"

echo "Installing launcher..."

cat <<EOF | sudo tee /usr/bin/beacon-agent >/dev/null
#!/bin/bash
exec /usr/bin/python3 /opt/beacon-agent/pi_agent.py
EOF

sudo chmod +x /usr/bin/beacon-agent

echo "Installing systemd service..."

cat <<EOF | sudo tee /etc/systemd/system/beacon-agent.service >/dev/null
[Unit]
Description=Beacon Agent
After=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/beacon-agent
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
EOF

echo "Installing dependencies..."

if command -v pacman >/dev/null; then
    sudo pacman -Sy --needed \
        python \
        python-requests \
        python-yaml \
        libnl
fi

if command -v apt >/dev/null; then
    sudo apt update

    sudo apt install -y \
        python3 \
        python3-requests \
        python3-yaml \
        libnl-3-dev \
        libnl-genl-3-dev
fi

echo "Reloading systemd..."

sudo systemctl daemon-reload

echo "Enabling service..."

sudo systemctl enable beacon-agent
sudo systemctl restart beacon-agent

echo ""
echo "Beacon Agent installed successfully."
echo ""
echo "Logs:"
echo "journalctl -u beacon-agent -f"