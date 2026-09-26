#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || { echo "Execute primeiro: ./setup.sh"; exit 1; }
. .venv/bin/activate
flet run
