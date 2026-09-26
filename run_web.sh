#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || { echo "Execute primeiro: ./setup.sh"; exit 1; }
. .venv/bin/activate
export FLET_WEB_NO_CDN=1
flet run --web
