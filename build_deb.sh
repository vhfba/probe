#!/bin/bash
# Run this from the root of your probe repo:
#   chmod +x build_deb.sh
#   ./build_deb.sh
#
# Produces: beacon-probe_1.0.0.deb

set -e

PACKAGE=beacon-probe
VERSION=1.0.0
BUILD_DIR=".deb-build/${PACKAGE}_${VERSION}"

echo "==> Cleaning previous build..."
rm -rf .deb-build
mkdir -p "$BUILD_DIR"

echo "==> Copying package skeleton..."
# Copy the DEBIAN control files from this repo's deb/ folder
cp -r deb/DEBIAN "$BUILD_DIR/DEBIAN"
cp -r deb/lib    "$BUILD_DIR/lib"
cp -r deb/etc    "$BUILD_DIR/etc"

echo "==> Copying agent and default config..."
mkdir -p "$BUILD_DIR/usr/lib/beacon-probe"
mkdir -p "$BUILD_DIR/usr/lib/beacon-probe/configs"

# Main agent
cp pi_agent.py "$BUILD_DIR/usr/lib/beacon-probe/pi_agent.py"

# Default config template (installed to /etc on first boot by postinst)
cp deb/usr/lib/beacon-probe/configs/config.yaml.default \
   "$BUILD_DIR/usr/lib/beacon-probe/configs/config.yaml.default"

# Optional: bundle any pre-built plugins
if [ -d "plugins" ] && [ "$(ls -A plugins)" ]; then
    echo "==> Bundling plugins..."
    mkdir -p "$BUILD_DIR/etc/beacon-probe/plugins"
    cp -r plugins/. "$BUILD_DIR/etc/beacon-probe/plugins/"
fi

echo "==> Setting permissions..."
chmod 755 "$BUILD_DIR/DEBIAN/postinst"
chmod 755 "$BUILD_DIR/DEBIAN/prerm"

echo "==> Building .deb..."
dpkg-deb --build --root-owner-group "$BUILD_DIR"

mv ".deb-build/${PACKAGE}_${VERSION}.deb" "./${PACKAGE}_${VERSION}.deb"
rm -rf .deb-build

echo ""
echo "Done: ${PACKAGE}_${VERSION}.deb"
echo ""
echo "Install on a Pi with:"
echo "  scp ${PACKAGE}_${VERSION}.deb pi@<PI_IP>:~/"
echo "  ssh pi@<PI_IP> 'sudo dpkg -i ${PACKAGE}_${VERSION}.deb'"
echo "  ssh pi@<PI_IP> 'sudo nano /etc/beacon-probe/configs/config.yaml'"
echo "  ssh pi@<PI_IP> 'sudo systemctl start beacon-probe'"
