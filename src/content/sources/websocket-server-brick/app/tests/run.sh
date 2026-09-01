#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
app_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
compose_file="$app_dir/.cache/app-compose.yaml"

if [ ! -f "$compose_file" ]; then
    printf '%s\n' "App runtime configuration not found: $compose_file" >&2
    printf '%s\n' "Start this App with arduino-app-cli before running the test." >&2
    exit 1
fi

if ! docker compose -f "$compose_file" ps --status running --quiet main | grep -q .; then
    printf '%s\n' "The App main service is not running." >&2
    printf '%s\n' "Start this App with arduino-app-cli before running the test." >&2
    exit 1
fi

exec docker compose -f "$compose_file" exec -T main \
    /app/.cache/.venv/bin/python -B /app/tests/websocket_test.py "$@"
