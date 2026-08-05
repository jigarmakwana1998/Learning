#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"

node_major=$(node --version | sed 's/^v//' | cut -d. -f1)
if [ "$node_major" -lt 24 ]; then
    echo "agent-browser 0.27.3 requires Node.js 24 or newer; found $(node --version)." >&2
    exit 1
fi

npm ci
if [ "$(uname -s)" = "Linux" ]; then
    npm exec -- agent-browser install --with-deps
else
    npm exec -- agent-browser install
fi
npm exec -- agent-browser doctor --offline --quick
npm exec -- gemini --version
