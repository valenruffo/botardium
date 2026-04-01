#!/usr/bin/env bash
set -euo pipefail

cd /workspaces/bot_ig

if [ -f botardium-panel/web/package-lock.json ]; then
  cd botardium-panel/web
  npm ci
  cd /workspaces/bot_ig
fi

python -m pip install --upgrade pip setuptools wheel
python -m pip install \
  fastapi \
  "uvicorn[standard]" \
  pydantic \
  openai \
  google-genai \
  packaging \
  pyinstaller \
  pytest \
  httpx \
  patchright \
  pure-python-adb \
  ddgs

if [ -f .env.example ] && [ ! -f .env ]; then
  cp .env.example .env
fi

mkdir -p .tmp/logs config database

echo "Devcontainer listo."
