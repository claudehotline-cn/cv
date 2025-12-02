#!/usr/bin/env bash
set -euo pipefail

# Minimal wrapper for Triton's perf_analyzer for VA/Triton tuning
# Requirements:
#   - perf_analyzer available in PATH
#   - Triton server reachable (TRITON_URL), enable HTTP/GRPC in VA if using in-process

usage() {
  cat <<EOF
Usage: $(basename "$0") -m <model> [-u <url>] [-c <concurrency_list>] [-d <duration_s>] [--shape <input:WxHxC or dims>]

Options:
  -m  Model name (required)
  -u  Triton URL (default: "+${TRITON_URL:-localhost:8001}+")
  -c  Concurrency list (comma-separated, default: 1,2,4,8)
  -d  Duration seconds per setting (default: 10)
  --shape  Input shape descriptor for perf_analyzer --shape (optional)
  --protocol http|grpc (default: grpc)
  --report <file>  Output CSV report path (default: perf_report.csv)

Example:
  TRITON_URL=localhost:8001 $(basename "$0") -m ens_det_trt_full -c 1,2,4,8 --protocol grpc --report det_perf.csv
EOF
}

MODEL=""; URL="${TRITON_URL:-localhost:8001}"; CONC="1,2,4,8"; DUR=10; SHAPE=""; PROTO="grpc"; REPORT="perf_report.csv"
while [[ $# -gt 0 ]]; do
  case "$1" in
    -m) MODEL="$2"; shift 2 ;;
    -u) URL="$2"; shift 2 ;;
    -c) CONC="$2"; shift 2 ;;
    -d) DUR="$2"; shift 2 ;;
    --shape) SHAPE="$2"; shift 2 ;;
    --protocol) PROTO="$2"; shift 2 ;;
    --report) REPORT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1"; usage; exit 2 ;;
  esac
done

if [[ -z "$MODEL" ]]; then echo "-m <model> required"; usage; exit 2; fi
if ! command -v perf_analyzer >/dev/null 2>&1; then echo "perf_analyzer not found in PATH" >&2; exit 3; fi

ARGS=("-m" "$MODEL" "-u" "$URL" "--protocol" "$PROTO" "--concurrency-range" "$CONC" "-p" "$DUR" "--measurement-interval" "1000" "--percentile" "95" "--latency-report-file" "$REPORT")
if [[ -n "$SHAPE" ]]; then ARGS+=("--shape" "$SHAPE"); fi

echo "[perf] perf_analyzer ${ARGS[*]}"
perf_analyzer "${ARGS[@]}"
echo "[perf] report => $REPORT"

