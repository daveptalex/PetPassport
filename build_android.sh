#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || { echo "Execute primeiro: ./setup.sh"; exit 1; }
. .venv/bin/activate
flet doctor
flet build apk --python-version 3.12 --product "Pet Passport" --org "pt.petpassport" --project pet_passport
flet build aab --python-version 3.12 --product "Pet Passport" --org "pt.petpassport" --project pet_passport
printf '\nAPK: build/apk\nAAB: build/aab\n'
