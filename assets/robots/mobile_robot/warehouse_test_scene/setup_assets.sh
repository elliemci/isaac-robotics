
#!/bin/bash

set -e

PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)

ASSET_DIR="$PROJECT_ROOT/assets/robots/mobile_robot/warehouse_test_scene"

URL="https://github.com/elliemci/isaac-robotics/releases/download/v1.0-nav2-assets/sim_interfaces_assets.tar.gz" -O /tmp/sim_interfaces_assets.tar.gz

if [ -d "$ASSET_DIR/home/elliemcintosh/Documents/sim_interfaces_assets" ]; then
    echo "Assets already installed."
    exit 0
fi

mkdir -p "$ASSET_DIR"

echo "Downloading Isaac Sim assets..."

wget "$URL" \
-0 /tmp/sim_interfaces_assets.tar.gz

echo "Extracting..."

tar -xzf sim_interfaces_assets.tar.gz \
-C "$ASET_DIR"

echo "Done."