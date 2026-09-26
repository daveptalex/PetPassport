#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Erro: Python 3 não encontrado. Instale Python 3.10 ou superior."
  exit 1
fi

# SecureStorage em Linux desktop precisa de libsecret. FilePicker desktop beneficia de zenity.
if [ "$(uname -s 2>/dev/null || true)" = "Linux" ] && command -v apt-get >/dev/null 2>&1; then
  missing=()
  dpkg -s libsecret-1-0 >/dev/null 2>&1 || missing+=(libsecret-1-0)
  dpkg -s libsecret-1-dev >/dev/null 2>&1 || missing+=(libsecret-1-dev)
  command -v zenity >/dev/null 2>&1 || missing+=(zenity)
  if [ ${#missing[@]} -gt 0 ]; then
    echo "Dependências Linux recomendadas em falta: ${missing[*]}"
    if [ "$(id -u)" -eq 0 ]; then
      apt-get update
      apt-get install -y "${missing[@]}"
    elif command -v sudo >/dev/null 2>&1; then
      sudo apt-get update
      sudo apt-get install -y "${missing[@]}"
    else
      echo "Sem sudo/root: continuei sem as instalar. Para desktop, instale-as manualmente."
    fi
  fi
fi

if [ ! -d .venv ]; then
  "$PYTHON" -m venv .venv
fi
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m flet --version || flet --version
printf '\nInstalação concluída. Execute ./run_web.sh ou ./run_desktop.sh\n'
