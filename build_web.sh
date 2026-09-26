#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || { echo "Execute primeiro: ./setup.sh"; exit 1; }
. .venv/bin/activate
flet build web --no-cdn --python-version 3.12 --product "Pet Passport" --project pet_passport --pwa-theme-color "#2F6F62" --pwa-background-color "#F5FAF8"
printf '\nWeb/PWA offline build: build/web\n'
