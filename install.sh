#!/usr/bin/env bash
# pyvcs installer for macOS / Linux.
# Makes the "vcs" command available from any terminal, on any machine
# this folder is copied to.
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
chmod +x "$DIR/vcs"

echo ""
echo "pyvcs installer"
echo "================"
echo "Install folder: $DIR"
echo ""

if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] python3 was not found on this computer."
    echo "Please install Python 3 first, then run this installer again."
    exit 1
fi

if [ -w /usr/local/bin ] || [ "$(id -u)" = "0" ]; then
    ln -sf "$DIR/vcs" /usr/local/bin/vcs
    echo "Linked $DIR/vcs -> /usr/local/bin/vcs"
    echo ""
    echo "Installation complete! Open a new terminal and try:"
    echo "    vcs init"
else
    echo "Could not write to /usr/local/bin (no permission)."
    echo ""
    echo "Add this line to your shell profile instead (~/.bashrc or ~/.zshrc):"
    echo "    export PATH=\"$DIR:\$PATH\""
    echo ""
    echo "Then restart your terminal (or run: source ~/.bashrc) and try:"
    echo "    vcs init"
fi
echo ""
