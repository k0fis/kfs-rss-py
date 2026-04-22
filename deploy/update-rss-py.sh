#!/bin/bash
set -e

VERSION=${1:-latest}
REPO="k0fis/kfs-rss-py"
INSTALL_DIR="/opt/rss-backend-py"
SERVICE="kfs-rss-py"

echo "=== kfs-rss-py update ==="

# Resolve version
if [ "$VERSION" = "latest" ]; then
    API_URL="https://api.github.com/repos/$REPO/releases/latest"
else
    API_URL="https://api.github.com/repos/$REPO/releases/tags/$VERSION"
fi

echo "Fetching release info from $API_URL..."
ASSET_URL=$(curl -sf "$API_URL" | python3 -c "
import sys, json
data = json.load(sys.stdin)
assets = data.get('assets', [])
for a in assets:
    if a['name'].endswith('.tar.gz'):
        print(a['browser_download_url'])
        break
")

if [ -z "$ASSET_URL" ]; then
    echo "ERROR: No .tar.gz asset found in release"
    exit 1
fi

TAG=$(curl -sf "$API_URL" | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])")
echo "Version: $TAG"

# Download
TMPDIR=$(mktemp -d)
echo "Downloading $ASSET_URL..."
curl -sL "$ASSET_URL" -o "$TMPDIR/release.tar.gz"

# Backup current .py files
if [ -f "$INSTALL_DIR/rss_api.py" ]; then
    echo "Backing up current version..."
    mkdir -p "$INSTALL_DIR/.backup"
    cp "$INSTALL_DIR"/*.py "$INSTALL_DIR/.backup/" 2>/dev/null || true
    cp "$INSTALL_DIR/requirements.txt" "$INSTALL_DIR/.backup/" 2>/dev/null || true
fi

# Extract
echo "Extracting to $INSTALL_DIR..."
tar xzf "$TMPDIR/release.tar.gz" -C "$INSTALL_DIR"
rm -rf "$TMPDIR"

# Update deps
echo "Updating dependencies..."
"$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"

# Restart
echo "Restarting $SERVICE..."
systemctl restart "$SERVICE"
sleep 3

if systemctl is-active --quiet "$SERVICE"; then
    echo "=== OK: $SERVICE is running ($TAG) ==="
else
    echo "ERROR: $SERVICE failed to start, rolling back..."
    cp "$INSTALL_DIR/.backup"/*.py "$INSTALL_DIR/" 2>/dev/null || true
    cp "$INSTALL_DIR/.backup/requirements.txt" "$INSTALL_DIR/" 2>/dev/null || true
    systemctl restart "$SERVICE"
    echo "Rolled back. Check: journalctl -u $SERVICE -n 30"
    exit 1
fi
