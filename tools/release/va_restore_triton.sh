#!/usr/bin/env bash
set -euo pipefail

VA_ADDR="${VA_ADDR:-127.0.0.1:50051}"
MODEL="${MODEL:-}"
VERSION="${VERSION:-}"

usage(){ echo "Usage: $0 [--va-addr host:port] --model <name> [--version <ver>]"; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --va-addr) VA_ADDR="$2"; shift 2;;
    --model) MODEL="$2"; shift 2;;
    --version) VERSION="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown arg: $1"; usage; exit 2;;
  esac
done

[[ -n "$MODEL" ]] || { usage; exit 2; }

# Ensure provider=triton and in-process enabled, then switch model
controlplane/build/va_set_engine --va-addr "$VA_ADDR" --provider triton --opt triton_inproc=true --opt triton_model="$MODEL" ${VERSION:+--opt triton_model_version=$VERSION} >/dev/null
exec controlplane/build/va_release --va-addr "$VA_ADDR" --pipeline det --node model --triton-model "$MODEL" ${VERSION:+--triton-version $VERSION}

