#!/bin/sh
# Explicit host setup helper. The Brick never invokes this script automatically.
set -eu

device="${1:-can0}"
bitrate="${2:-500000}"

case "$device" in
  *[!a-zA-Z0-9_.-]*|'')
    echo "Invalid CAN interface name" >&2
    exit 2
    ;;
esac

case "$bitrate" in
  *[!0-9]*|'')
    echo "Invalid bitrate" >&2
    exit 2
    ;;
esac

if [ "$(id -u)" -ne 0 ]; then
  echo "Run explicitly with sudo: sudo scripts/configure_can0.sh $device $bitrate" >&2
  exit 2
fi

ip link set "$device" down 2>/dev/null || true
ip link set "$device" type can bitrate "$bitrate"
ip link set "$device" up
ip -details -statistics link show "$device"
