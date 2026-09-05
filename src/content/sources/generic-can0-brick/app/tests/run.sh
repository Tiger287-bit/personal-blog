#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
app_dir="$(cd -- "${script_dir}/.." && pwd)"

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="${app_dir}/bricks:${app_dir}/python:${app_dir}/tests${PYTHONPATH:+:${PYTHONPATH}}"
exec python3 -B -m unittest discover -s "${script_dir}" -p "test_*.py" -v

