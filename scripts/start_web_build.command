#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB_DIR="$ROOT_DIR/Open-LLM-VTuber-Web"

if [ ! -d "$WEB_DIR" ]; then
  echo "Web directory not found: $WEB_DIR"
  exit 1
fi

cd "$WEB_DIR"
echo "Building web frontend..."
npm run build:web
