#!/usr/bin/env bash
# install.sh — single-command install for gpu-status.
#
# Stages the repo and puts the `gpu-status` command on your PATH.
#
#   git clone https://github.com/JugglerMaster/gpu-status.git
#   cd gpu-status
#   ./install.sh
#
# or, as one line (clones itself):
#   curl -fsSL https://raw.githubusercontent.com/JugglerMaster/gpu-status/main/install.sh | bash
#
# The script is stdlib-only, so no pip/venv is required.
set -euo pipefail

REPO_URL="https://github.com/JugglerMaster/gpu-status.git"
BRANCH="main"
BIN_DIR="${HOME}/.local/bin"

# 1. Source: use the current dir if we're inside the repo, else clone to a staging dir.
if [ -f "$(pwd)/gpu_status.py" ]; then
  SRC="$(pwd)"
  OWNED=1
else
  SRC="$(mktemp -d)"
  OWNED=0
  git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$SRC"
fi

# 2. Install: copy the stdlib-only script into the user's bin dir.
mkdir -p "$BIN_DIR"
cp "$SRC/gpu_status.py" "$BIN_DIR/gpu-status"
chmod +x "$BIN_DIR/gpu-status"

# 3. Clean up the staging dir (only the one we created).
if [ "$OWNED" = 0 ]; then
  rm -rf "$SRC"
fi

# 4. Verify the command is reachable.
if command -v gpu-status >/dev/null 2>&1; then
  echo "Installed: $(command -v gpu-status)"
else
  echo "Installed to $BIN_DIR/gpu-status, but $BIN_DIR is not on your PATH."
  echo "Add it to your shell rc, then re-source:"
  echo "  echo 'export PATH=\"\$BIN_DIR:\$PATH\"' >> ~/.bashrc   # or ~/.zshrc"
fi

echo
echo "Try it:"
echo "  gpu-status --help"
echo "  gpu-status --watch 2"
