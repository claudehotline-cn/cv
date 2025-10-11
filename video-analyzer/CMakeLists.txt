cmake_minimum_required(VERSION 3.16)
project(VideoAnalyzer)

set(VCPKG_APPLOCAL_DEPS OFF)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Ninja+MSVC: 避免为对象编译生成 PDB（会通过 -Fd 传给 NVCC 并导致报错）
if (MSVC AND CMAKE_GENERATOR MATCHES "Ninja")
    set(CMAKE_MSVC_DEBUG_INFORMATION_FORMAT "Embedded") # /Z7, no /Fd
endif()

if(MSVC)
    # 仅对 C/C++ 生效，避免透传到 NVCC
    add_compile_options(
        $<$<COMPILE_LANGUAGE:C>:/W4>
        $<$<COMPILE_LANGUAGE:CXX>:/W4>
        $<$<COMPILE_LANGUAGE:CXX>:/utf-8>
    )
else()
    add_compile_options(
        $<$<COMPILE_LANGUAGE:C>:-Wall -Wextra -pedantic>
        $<$<COMPILE_LANGUAGE:CXX>:-Wall -Wextra -pedantic>
    )
endif()

find_package(OpenCV REQUIRED)
find_package(Threads REQUIRED)
set(YAML_LOCAL_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../third_party/yaml-cpp/yaml-cpp-0.8.0")
if(EXISTS "${YAML_LOCAL_ROOT}/CMakeLists.txt")
    set(YAML_CPP_TARGET yaml-cpp)
    add_subdirectory("${YAML_LOCAL_ROOT}" "${CMAKE_BINARY_DIR}/yaml-cpp" EXCLUDE_FROM_ALL)
else()
    find_package(yaml-cpp REQUIRED)
    set(YAML_CPP_TARGET yaml-cpp::yaml-cpp)
endif()

find_package(PkgConfig QUIET)

set(FFMPEG_LOCAL_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../third_party/ffmpeg-prebuilt/ffmpeg-master-latest-win64-lgpl-shared")
if(EXISTS "${FFMPEG_LOCAL_ROOT}")
    list(PREPEND CMAKE_PREFIX_PATH "${FFMPEG_LOCAL_ROOT}")
    list(PREPEND CMAKE_LIBRARY_PATH "${FFMPEG_LOCAL_ROOT}/lib")
    list(PREPEND CMAKE_INCLUDE_PATH "${FFMPEG_LOCAL_ROOT}/include")
endif()

set(FFMPEG_COMPONENTS avcodec avformat avutil swscale swresample)
set(FFMPEG_FOUND ON)

if(PKGCONFIG_FOUND)
    pkg_check_modules(FFMPEG_PKG QUIET libavcodec libavformat libavutil libswscale libswresample)
endif()

if(NOT FFMPEG_PKG_FOUND)
    foreach(component IN LISTS FFMPEG_COMPONENTS)
        string(TOUPPER ${component} UPPER)
        find_library(FFMPEG_${UPPER}_LIB NAMES ${component})
        find_path(FFMPEG_${UPPER}_INCLUDE NAMES libavcodec/avcodec.h libavformat/avformat.h libavutil/avutil.h)
        if(NOT FFMPEG_${UPPER}_LIB)
            set(FFMPEG_FOUND OFF)
        endif()
        endforeach()
else()
    set(FFMPEG_FOUND ON)
endif()

if(NOT FFMPEG_FOUND)
    message(WARNING "FFmpeg libraries not found. FfmpegH264Encoder will be disabled.")
endif()

# Optional: CUDA support
option(USE_CUDA "Enable CUDA support for GPU inference" ON)
option(WITH_NVDEC "Build NVDEC-based RTSP source (scaffold)" OFF)
option(WITH_NVENC "Build NVENC-based H264 encoder (FFmpeg wrapper)" OFF)
## 默认 CUDA 架构（可在配置时覆盖）
## 示例覆盖：-DVA_CUDA_ARCHS=89 或 -DCMAKE_CUDA_ARCHITECTURES=89
set(VA_CUDA_ARCHS "89" CACHE STRING "CUDA SM architectures for NVCC (e.g. 89;90;120)")
if(USE_CUDA)
    find_package(CUDAToolkit QUIET)
    if(CUDAToolkit_FOUND)
        add_definitions(-DUSE_CUDA)
        # Build without .cu kernels in this environment; use runtime CUDA API only
        set(HAVE_CUDA_KERNELS OFF)
        message(STATUS "CUDA found: ${CUDAToolkit_VERSION} - building without NVCC kernels")
    else()
        set(HAVE_CUDA_KERNELS OFF)
        message(WARNING "CUDA not found - GPU inference disabled")
    endif()
endif()

# Optional: JSONCPP
find_path(JSONCPP_INCLUDE_DIR NAMES json/json.h PATHS /usr/local/include /usr/include)
find_library(JSONCPP_LIBRARY NAMES jsoncpp PATHS /usr/local/lib /usr/lib)

# ONNX Runtime (via ONNXRUNTIME_ROOT)
# ONNX Runtime (via ONNXRUNTIME_ROOT)
# Support both standard layout (<root>/include, <root>/lib) and Windows build tree (<root>/build/Windows/Release)
find_path(ONNXRUNTIME_INCLUDE_DIR NAMES onnxruntime_cxx_api.h
    PATHS
        ${ONNXRUNTIME_ROOT}/include
        ${ONNXRUNTIME_ROOT}/build/Windows/Release/include
        /usr/local/include/onnxruntime /usr/include/onnxruntime)
find_library(ONNXRUNTIME_LIB NAMES onnxruntime
    PATHS
        ${ONNXRUNTIME_ROOT}/lib
        ${ONNXRUNTIME_ROOT}/build/Windows/Release
        /usr/local/lib /usr/lib)

# Optional vcpkg-installed dependencies
set(VCPKG_ROOT_DIR "$ENV{VCPKG_ROOT}")
if (NOT VCPKG_ROOT_DIR)
    set(VCPKG_ROOT_DIR "${CMAKE_SOURCE_DIR}/../vcpkg")
endif()
if (NOT EXISTS "${VCPKG_ROOT_DIR}")
    set(VCPKG_ROOT_DIR "D:/Projects/vcpkg")
endif()
set(VCPKG_LIB_DIR "${VCPKG_ROOT_DIR}/installed/x64-windows/lib")
set(VCPKG_LIB_DIR_DEBUG "${VCPKG_ROOT_DIR}/installed/x64-windows/debug/lib")
set(VCPKG_INCLUDE_DIR "${VCPKG_ROOT_DIR}/installed/x64-windows/include")

find_library(IXWEBSOCKET_LIB_RELEASE NAMES ixwebsocket PATHS ${VCPKG_LIB_DIR} NO_DEFAULT_PATH)
find_library(IXWEBSOCKET_LIB_DEBUG NAMES ixwebsocket PATHS ${VCPKG_LIB_DIR_DEBUG} NO_DEFAULT_PATH)
find_library(DATA_CHANNEL_LIB_RELEASE NAMES datachannel PATHS ${VCPKG_LIB_DIR} NO_DEFAULT_PATH)
find_library(DATA_CHANNEL_LIB_DEBUG NAMES datachannel PATHS ${VCPKG_LIB_DIR_DEBUG} NO_DEFAULT_PATH)
find_library(JUICE_LIB_RELEASE NAMES juice PATHS ${VCPKG_LIB_DIR} NO_DEFAULT_PATH)
find_library(JUICE_LIB_DEBUG NAMES juice PATHS ${VCPKG_LIB_DIR_DEBUG} NO_DEFAULT_PATH)
find_library(MBEDTLS_LIB_RELEASE NAMES mbedtls PATHS ${VCPKG_LIB_DIR} NO_DEFAULT_PATH)
find_library(MBEDTLS_LIB_DEBUG NAMES mbedtls PATHS ${VCPKG_LIB_DIR_DEBUG} NO_DEFAULT_PATH)
find_library(MBEDCRYPTO_LIB_RELEASE NAMES mbedcrypto PATHS ${VCPKG_LIB_DIR} NO_DEFAULT_PATH)
find_library(MBEDCRYPTO_LIB_DEBUG NAMES mbedcrypto PATHS ${VCPKG_LIB_DIR_DEBUG} NO_DEFAULT_PATH)
find_library(MBEDX509_LIB_RELEASE NAMES mbedx509 PATHS ${VCPKG_LIB_DIR} NO_DEFAULT_PATH)
find_library(MBEDX509_LIB_DEBUG NAMES mbedx509 PATHS ${VCPKG_LIB_DIR_DEBUG} NO_DEFAULT_PATH)
find_library(ZLIB_LIB_RELEASE NAMES zlib PATHS ${VCPKG_LIB_DIR} NO_DEFAULT_PATH)
find_library(ZLIB_LIB_DEBUG NAMES zlib PATHS ${VCPKG_LIB_DIR_DEBUG} NO_DEFAULT_PATH)

include_directories(${OpenCV_INCLUDE_DIRS})
include_directories(include)
if(JSONCPP_INCLUDE_DIR)
    include_directories(${JSONCPP_INCLUDE_DIR})
endif()
if(ONNXRUNTIME_INCLUDE_DIR)
    include_directories(${ONNXRUNTIME_INCLUDE_DIR})
    add_definitions(-DUSE_ONNXRUNTIME)
endif()

file(GLOB_RECURSE SOURCES "src/*.cpp")
file(GLOB_RECURSE HEADERS "include/*.h" "src/*.hpp")
if (HAVE_CUDA_KERNELS)
    file(GLOB_RECURSE CUDA_SOURCES "src/*.cu")
endif()

# Ensure newly added core metric/event sources are included even if glob caching misses them
list(APPEND SOURCES
    # Multistage analyzer core
    src/analyzer/multistage/graph.cpp
    src/analyzer/multistage/registry.cpp
    src/analyzer/multistage/node_preproc_letterbox.cpp
    src/analyzer/multistage/node_model.cpp
    src/analyzer/multistage/node_nms.cpp
    src/analyzer/multistage/node_overlay.cpp
    src/analyzer/multistage/node_roi_batch.cpp
    src/analyzer/multistage/builder_yaml.cpp
    src/analyzer/multistage/node_roi_batch_cuda.cpp
    src/analyzer/multistage/node_kpt_decode.cpp
    src/analyzer/multistage/runner.cpp
    src/analyzer/multistage/node_overlay_kpt.cpp
    src/core/drop_metrics.cpp
    src/core/source_reconnects.cpp
    src/core/nvdec_events.cpp)

add_executable(${PROJECT_NAME} ${SOURCES} ${HEADERS} ${CUDA_SOURCES})
if (HAVE_CUDA_KERNELS)
    target_compile_definitions(${PROJECT_NAME} PRIVATE VA_HAS_CUDA_KERNELS)
endif()

target_compile_definitions(${PROJECT_NAME} PRIVATE IXWEBSOCKET_HEADER_ONLY IXWEBSOCKET_USE_TLS=0)

target_include_directories(${PROJECT_NAME}
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)

target_link_libraries(${PROJECT_NAME}
    PRIVATE ${OpenCV_LIBS}
    PRIVATE Threads::Threads
    PRIVATE ${YAML_CPP_TARGET})

if(FFMPEG_FOUND)
    if(FFMPEG_PKG_FOUND)
        target_include_directories(${PROJECT_NAME} PRIVATE ${FFMPEG_PKG_INCLUDE_DIRS})
        target_link_libraries(${PROJECT_NAME} PRIVATE ${FFMPEG_PKG_LIBRARIES})
    else()
        foreach(component IN LISTS FFMPEG_COMPONENTS)
            string(TOUPPER ${component} UPPER)
            if(FFMPEG_${UPPER}_INCLUDE)
                target_include_directories(${PROJECT_NAME} PRIVATE ${FFMPEG_${UPPER}_INCLUDE})
            endif()
            if(FFMPEG_${UPPER}_LIB)
                target_link_libraries(${PROJECT_NAME} PRIVATE ${FFMPEG_${UPPER}_LIB})
            endif()
        endforeach()
    endif()
    target_compile_definitions(${PROJECT_NAME} PRIVATE USE_FFMPEG)
else()
    target_compile_definitions(${PROJECT_NAME} PRIVATE NO_FFMPEG)
endif()

# Feature toggles for scaffold files
if (USE_CUDA AND WITH_NVDEC)
    target_compile_definitions(${PROJECT_NAME} PRIVATE WITH_NVDEC)
endif()
if (USE_CUDA AND WITH_NVENC)
    target_compile_definitions(${PROJECT_NAME} PRIVATE WITH_NVENC)
endif()

if(JSONCPP_LIBRARY)
    target_link_libraries(${PROJECT_NAME} PRIVATE ${JSONCPP_LIBRARY})
endif()

if(ONNXRUNTIME_LIB)
    target_link_libraries(${PROJECT_NAME} PRIVATE ${ONNXRUNTIME_LIB})
endif()
if (CUDAToolkit_FOUND)
    target_link_libraries(${PROJECT_NAME} PRIVATE CUDA::cudart_static)
endif()

# Some ORT builds place headers under include/onnxruntime/core/session
if (ONNXRUNTIME_INCLUDE_DIR)
    if (EXISTS "${ONNXRUNTIME_INCLUDE_DIR}/onnxruntime_c_api.h")
        target_include_directories(${PROJECT_NAME} PRIVATE ${ONNXRUNTIME_INCLUDE_DIR})
    endif()
    if (EXISTS "${ONNXRUNTIME_INCLUDE_DIR}/onnxruntime/core/session/onnxruntime_c_api.h")
        target_include_directories(${PROJECT_NAME} PRIVATE "${ONNXRUNTIME_INCLUDE_DIR}/onnxruntime/core/session")
    endif()
endif()


function(target_link_vcpkg_library target debug_path release_path)
    if(debug_path AND release_path)
        target_link_libraries(${target} PRIVATE
            $<$<CONFIG:Debug>:${debug_path}>
            $<$<NOT:$<CONFIG:Debug>>:${release_path}>)
    elseif(release_path)
        target_link_libraries(${target} PRIVATE ${release_path})
    elseif(debug_path)
        target_link_libraries(${target} PRIVATE ${debug_path})
    endif()
endfunction()

target_link_vcpkg_library(${PROJECT_NAME} "${IXWEBSOCKET_LIB_DEBUG}" "${IXWEBSOCKET_LIB_RELEASE}")
target_link_vcpkg_library(${PROJECT_NAME} "${DATA_CHANNEL_LIB_DEBUG}" "${DATA_CHANNEL_LIB_RELEASE}")
target_link_vcpkg_library(${PROJECT_NAME} "${JUICE_LIB_DEBUG}" "${JUICE_LIB_RELEASE}")
target_link_vcpkg_library(${PROJECT_NAME} "${MBEDTLS_LIB_DEBUG}" "${MBEDTLS_LIB_RELEASE}")
target_link_vcpkg_library(${PROJECT_NAME} "${MBEDCRYPTO_LIB_DEBUG}" "${MBEDCRYPTO_LIB_RELEASE}")
target_link_vcpkg_library(${PROJECT_NAME} "${MBEDX509_LIB_DEBUG}" "${MBEDX509_LIB_RELEASE}")
target_link_vcpkg_library(${PROJECT_NAME} "${ZLIB_LIB_DEBUG}" "${ZLIB_LIB_RELEASE}")

# Prefer vcpkg jsoncpp if available (ensures proper symbol resolution on Windows)
find_library(JSONCPP_LIB_RELEASE NAMES jsoncpp PATHS ${VCPKG_LIB_DIR} NO_DEFAULT_PATH)
find_library(JSONCPP_LIB_DEBUG NAMES jsoncpp PATHS ${VCPKG_LIB_DIR_DEBUG} NO_DEFAULT_PATH)
if (JSONCPP_LIB_RELEASE OR JSONCPP_LIB_DEBUG)
    target_link_vcpkg_library(${PROJECT_NAME} "${JSONCPP_LIB_DEBUG}" "${JSONCPP_LIB_RELEASE}")
endif()

# Ensure vcpkg include path is visible for header-only deps (ixwebsocket, rtc/libdatachannel, jsoncpp, etc.)
target_include_directories(${PROJECT_NAME} PRIVATE "${VCPKG_INCLUDE_DIR}")
if (EXISTS "D:/Projects/vcpkg/installed/x64-windows/include")
    # Also add user vcpkg tree explicitly to override VS-integrated vcpkg lacking some ports
    target_include_directories(${PROJECT_NAME} PRIVATE "D:/Projects/vcpkg/installed/x64-windows/include")
endif()

if (WIN32)
    target_link_libraries(${PROJECT_NAME} PRIVATE ws2_32 iphlpapi psapi crypt32 bcrypt)
endif()

set_target_properties(${PROJECT_NAME} PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")

# --- CUDA kernels library (optional) ---
if (USE_CUDA AND WITH_CUDA_KERNELS AND CUDAToolkit_FOUND)
    if (CMAKE_VERSION VERSION_GREATER_EQUAL 3.18)
        cmake_policy(SET CMP0104 NEW)
        # 优先使用 VA_CUDA_ARCHS，除非用户已经显式设置了 CMAKE_CUDA_ARCHITECTURES
        if (NOT DEFINED CMAKE_CUDA_ARCHITECTURES OR CMAKE_CUDA_ARCHITECTURES STREQUAL "")
            set(CMAKE_CUDA_ARCHITECTURES ${VA_CUDA_ARCHS})
        endif()
    endif()
    # 强制使用动态 CUDA runtime，避免与上层重复链接
    set(CMAKE_CUDA_RUNTIME_LIBRARY Static)
    enable_language(CUDA)
    add_library(va_cuda_kernels STATIC
        src/analyzer/cuda/overlay_nv12_kernels.cu
        src/analyzer/cuda/overlay_kernels.cu
        src/analyzer/cuda/preproc_letterbox_kernels.cu
        src/analyzer/cuda/yolo_decode_kernels.cu
        src/analyzer/cuda/postproc_yolo_nms_kernels.cu)
    # Link cudart only at final executable to avoid mixing static/dynamic runtimes
    target_include_directories(va_cuda_kernels PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src ${CMAKE_CURRENT_SOURCE_DIR}/include)
    # Avoid leaking MSVC host flags like "-Fd, -FS" into NVCC causing
    # "A single input file is required..." under Ninja+MSVC
    set_target_properties(va_cuda_kernels PROPERTIES CUDA_PROPAGATE_HOST_FLAGS OFF)
    # Keep minimal, explicit host flags for CUDA compilation
    target_compile_options(va_cuda_kernels PRIVATE
        $<$<COMPILE_LANGUAGE:CUDA>:-Xcompiler=/MD>
        $<$<COMPILE_LANGUAGE:CUDA>:-Xcompiler=/GR>
        $<$<COMPILE_LANGUAGE:CUDA>:-Xcompiler=/EHsc>)
    # 仅对 CUDA 目标开启 Embedded 调试信息，避免 /Fd 生成 PDB
    set_property(TARGET va_cuda_kernels PROPERTY MSVC_DEBUG_INFORMATION_FORMAT "Embedded")
    target_compile_definitions(${PROJECT_NAME} PRIVATE VA_HAS_CUDA_KERNELS)
    target_link_libraries(${PROJECT_NAME} PRIVATE va_cuda_kernels)
endif()

# Ensure WebRTC/datachannel related libs from vcpkg are linked (do not skip)
if (WIN32)
    # vcpkg lib dir is resolved above; fallback to default if empty
    if (NOT EXISTS "${VCPKG_LIB_DIR}")
        set(VCPKG_LIB_DIR "D:/Projects/vcpkg/installed/x64-windows/lib")
    endif()
    foreach(LN IN ITEMS datachannel juice ixwebsocket mbedtls mbedcrypto mbedx509 usrsctp libssl libcrypto zlib)
        if (EXISTS "${VCPKG_LIB_DIR}/${LN}.lib")
            target_link_libraries(${PROJECT_NAME} PRIVATE "${VCPKG_LIB_DIR}/${LN}.lib")
        endif()
    endforeach()
endif()

# Unit test: postproc threshold override
add_executable(va_unit_test_postproc
    test/unit/test_postproc_threshold.cpp
    src/analyzer/postproc_yolo_det.cpp)

target_include_directories(va_unit_test_postproc PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_SOURCE_DIR}/include)

set_target_properties(va_unit_test_postproc PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
if (CUDAToolkit_FOUND)
    target_include_directories(va_unit_test_postproc PRIVATE ${CUDAToolkit_INCLUDE_DIRS}) # CUDA include for va_unit_test_postproc
endif()

target_compile_definitions(va_unit_test_postproc PRIVATE UNIT_TEST_NO_CUDA VA_HAS_CUDA_RUNTIME=0)

# Unit test: CUDA NV12 overlay rectangle drawing
if (CUDAToolkit_FOUND)
    add_executable(va_unit_test_overlay_cuda
        test/unit/test_overlay_cuda.cpp
        src/analyzer/renderer_overlay_cuda.cpp
        src/analyzer/renderer_overlay_cpu.cpp
        src/core/logger.cpp
        src/core/global_metrics.cpp)
    target_include_directories(va_unit_test_overlay_cuda PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
        ${CMAKE_CURRENT_SOURCE_DIR}/include
        ${CUDAToolkit_INCLUDE_DIRS})
    target_link_libraries(va_unit_test_overlay_cuda PRIVATE CUDA::cudart_static ${OpenCV_LIBS})
    # If CUDA kernels are built, link them and define VA_HAS_CUDA_KERNELS for this test
    if (TARGET va_cuda_kernels)
        target_link_libraries(va_unit_test_overlay_cuda PRIVATE va_cuda_kernels)
        target_compile_definitions(va_unit_test_overlay_cuda PRIVATE VA_HAS_CUDA_KERNELS)
    endif()
    set_target_properties(va_unit_test_overlay_cuda PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
endif()



