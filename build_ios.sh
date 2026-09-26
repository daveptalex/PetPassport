#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ "$(uname -s)" != "Darwin" ]; then
  echo "A compilação iOS/IPA exige macOS com Xcode."
  exit 1
fi
[ -d .venv ] || { echo "Execute primeiro: ./setup.sh"; exit 1; }
. .venv/bin/activate
flet doctor
flet build ipa --python-version 3.12 --product "Pet Passport" --org "pt.petpassport" --project pet_passport
printf '\niOS build: build/ipa\n'
