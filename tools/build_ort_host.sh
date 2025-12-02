#!/usr/bin/env bash
set -euo pipefail

# Build ONNX Runtime v1.23.2 on host with CUDA and arch "90;120",
# then package headers+libs to docker/ort-prebuilt/onnxruntime-<ver>-cuda/{include,lib}
# so Dockerfile.gpu can consume them without building inside the container.

ORT_VERSION=${ORT_VERSION:-1.23.2}
CUDA_HOME=${CUDA_HOME:-/usr/local/cuda}
CUDNN_HOME=${CUDNN_HOME:-/usr}
CUDA_VERSION=${CUDA_VERSION:-12.9}
ARCHS=${ARCHS:-120}
PARALLEL=${PARALLEL:-8}
GENERATOR=${GENERATOR:-Ninja}
PYTHON=${PYTHON:-python3}

# TensorRT (optional)
USE_TRT=${USE_TRT:-0}                 # 1 to enable when headers present
TENSORRT_HOME=${TENSORRT_HOME:-/usr}

# Paths
ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
SRC_DIR=${SRC_DIR:-"$ROOT_DIR/.onnxruntime-src"}
BUILD_DIR=${BUILD_DIR:-"$ROOT_DIR/.onnxruntime-build"}
DEST_DIR=${DEST_DIR:-"$ROOT_DIR/docker/ort-prebuilt/onnxruntime-${ORT_VERSION}-cuda"}

echo "[build-ort] ORT_VERSION=${ORT_VERSION} ARCHS=${ARCHS} CUDA=${CUDA_VERSION}"
echo "[build-ort] CUDA_HOME=${CUDA_HOME} CUDNN_HOME=${CUDNN_HOME}"
echo "[build-ort] SRC_DIR=${SRC_DIR} BUILD_DIR=${BUILD_DIR} DEST_DIR=${DEST_DIR}"

command -v cmake >/dev/null || { echo "cmake not found"; exit 1; }
command -v ${PYTHON} >/dev/null || { echo "python not found"; exit 1; }

# Validate build generator tool or gracefully fallback
GEN_PROG=""
case "${GENERATOR}" in
  Ninja) GEN_PROG="ninja" ;;
  "Unix Makefiles") GEN_PROG="make" ;;
  *) GEN_PROG="" ;;
esac
if [ -n "${GEN_PROG}" ] && ! command -v "${GEN_PROG}" >/dev/null 2>&1; then
  if [ "${GENERATOR}" = "Ninja" ] && command -v make >/dev/null 2>&1; then
    echo "[build-ort] 'ninja' not found; falling back to GENERATOR='Unix Makefiles'"
    GENERATOR="Unix Makefiles"
  else
    echo "[build-ort] Required build tool for generator '${GENERATOR}' not found: ${GEN_PROG}" >&2
    echo "[build-ort] Install with: sudo apt-get install -y ninja-build (or build-essential for make)" >&2
    exit 1
  fi
fi

cmake --version || true
${PYTHON} -V || true

# Fetch source
if [ ! -d "${SRC_DIR}/.git" ]; then
  rm -rf "${SRC_DIR}"
  git clone --depth 1 --branch "v${ORT_VERSION}" https://github.com/microsoft/onnxruntime.git "${SRC_DIR}"
else
  git -C "${SRC_DIR}" fetch --depth 1 origin "v${ORT_VERSION}" && git -C "${SRC_DIR}" checkout -f "v${ORT_VERSION}"
fi

# Optional: install helper python modules for smoother build logs
${PYTHON} -m pip install --upgrade pip wheel setuptools >/dev/null 2>&1 || true
${PYTHON} -m pip install psutil flatbuffers >/dev/null 2>&1 || true

TRT_FLAGS=()
if [ "${USE_TRT}" = "1" ] && [ -f "${TENSORRT_HOME}/include/NvInfer.h" ]; then
  echo "[build-ort] Enable TensorRT EP"
  TRT_FLAGS=(--use_tensorrt --tensorrt_home="${TENSORRT_HOME}")
fi

mkdir -p "${BUILD_DIR}"
pushd "${SRC_DIR}" >/dev/null

set -x
${PYTHON} tools/ci_build/build.py \
  --config Release \
  --build_dir "${BUILD_DIR}" \
  --build_shared_lib \
  --skip_tests \
  --parallel ${PARALLEL} \
  --cmake_generator "${GENERATOR}" \
  --use_cuda --cuda_home="${CUDA_HOME}" --cudnn_home="${CUDNN_HOME}" \
  --cuda_version="${CUDA_VERSION}" \
  --cmake_extra_defines "CMAKE_CUDA_ARCHITECTURES=${ARCHS}" \
  --cmake_extra_defines "onnxruntime_USE_FLASH_ATTENTION=OFF" \
  --cmake_extra_defines "FETCHCONTENT_TRY_FIND_PACKAGE_MODE=NEVER" \
  "${TRT_FLAGS[@]}"
set +x

popd >/dev/null

# Package headers+libs to DEST_DIR
mkdir -p "${DEST_DIR}/include" "${DEST_DIR}/lib"
echo "[build-ort] Copy headers"
cp -rv "${SRC_DIR}/include/onnxruntime" "${DEST_DIR}/include/" 2>/dev/null || true

echo "[build-ort] Collect libraries"
mapfile -t LIBS < <(find "${BUILD_DIR}" -type f \( -name 'libonnxruntime*.so*' -o -name 'libonnxruntime_providers_*' \) | sort)
if [ ${#LIBS[@]} -eq 0 ]; then
  echo "ERROR: No ONNX Runtime shared libraries found under ${BUILD_DIR}" >&2
  find "${BUILD_DIR}" -maxdepth 3 -type f | sed -n '1,200p' >&2
  exit 1
fi
for f in "${LIBS[@]}"; do
  cp -v "$f" "${DEST_DIR}/lib/"
done

if ! ls "${DEST_DIR}/lib/libonnxruntime.so"* >/dev/null 2>&1; then
  echo "ERROR: libonnxruntime.so missing in ${DEST_DIR}/lib" >&2
  exit 1
fi

echo "[build-ort] Prepared artifacts in: ${DEST_DIR}"
echo "[build-ort] Next: build the Docker image"
echo "  docker compose -f docker/compose/docker-compose.yml -f docker/compose/docker-compose.gpu.override.yml build --no-cache va"
echo "  docker compose -f docker/compose/docker-compose.yml -f docker/compose/docker-compose.gpu.override.yml up -d va"
