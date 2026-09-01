#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
app_dir="$(cd -- "${script_dir}/.." && pwd)"
site_packages="$(find "${app_dir}/.cache/.venv/lib" -mindepth 2 -maxdepth 2 -type d -name site-packages -print -quit 2>/dev/null || true)"

if [[ -z "${site_packages}" ]]; then
  echo "App Lab virtual environment not found. Run arduino-app-cli app start first." >&2
  exit 1
fi

export PYTHONPATH="${site_packages}:${app_dir}/bricks${PYTHONPATH:+:${PYTHONPATH}}"
exec python3 "$@"
