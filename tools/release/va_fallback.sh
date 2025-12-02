#!/usr/bin/env bash
set -euo pipefail

VA_ADDR="${VA_ADDR:-127.0.0.1:50051}"
DEVICE="${DEVICE_ID:-0}"

usage(){ echo "Usage: $0 [--va-addr host:port] [--device <id>]"; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --va-addr) VA_ADDR="$2"; shift 2;;
    --device) DEVICE="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown arg: $1"; usage; exit 2;;
  esac
done

# Switch provider to CUDA as a safe fallback
exec controlplane/build/va_set_engine --va-addr "$VA_ADDR" --provider cuda --device "$DEVICE"

