cmake_minimum_required(VERSION 3.16)
project(VideoAnalyzer)

set(VCPKG_APPLOCAL_DEPS OFF)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Hint OpenCV install if environment provides typical Windows paths
if (NOT DEFINED OpenCV_DIR)
    if (EXISTS "H:/opencv/build/x64/vc16/lib/OpenCVConfig.cmake")
        set(OpenCV_DIR "H:/opencv/build/x64/vc16/lib" CACHE PATH "OpenCV CMake config" FORCE)
    elseif (EXISTS "H:/opencv/build/OpenCVConfig.cmake")
        set(OpenCV_DIR "H:/opencv/build" CACHE PATH "OpenCV CMake config" FORCE)
    endif()
endif()
if (DEFINED OpenCV_DIR)
    list(PREPEND CMAKE_PREFIX_PATH "${OpenCV_DIR}")
endif()
message(STATUS "OpenCV_DIR hint: ${OpenCV_DIR}")

# vcpkg hints early (for OpenCV, etc.)
set(VCPKG_ROOT_DIR "$ENV{VCPKG_ROOT}")
if (NOT VCPKG_ROOT_DIR)
    set(VCPKG_ROOT_DIR "${CMAKE_SOURCE_DIR}/../vcpkg")
endif()
if (NOT EXISTS "${VCPKG_ROOT_DIR}")
    set(VCPKG_ROOT_DIR "D:/Projects/vcpkg")
endif()
if (EXISTS "${VCPKG_ROOT_DIR}/installed/x64-windows")
    list(PREPEND CMAKE_PREFIX_PATH "${VCPKG_ROOT_DIR}/installed/x64-windows")
endif()
# Additional common vcpkg locations (VS-integrated or custom drive)
if (EXISTS "H:/vcpkg/installed/x64-windows")
    list(PREPEND CMAKE_PREFIX_PATH "H:/vcpkg/installed/x64-windows")
endif()
if (EXISTS "H:/Program Files/Microsoft Visual Studio/2022/Community/VC/vcpkg/installed/x64-windows")
    list(PREPEND CMAKE_PREFIX_PATH "H:/Program Files/Microsoft Visual Studio/2022/Community/VC/vcpkg/installed/x64-windows")
endif()

# Ninja+MSVC: 避免为对象编译生成 PDB（会通过 -Fd 传给 NVCC 并导致报错）
if (MSVC AND CMAKE_GENERATOR MATCHES "Ninja")
    set(CMAKE_MSVC_DEBUG_INFORMATION_FORMAT "Embedded") # /Z7, no /Fd
endif()

if(MSVC)
    # Keep MSVC defaults to avoid toolchain-specific flag issues
else()
    # In Linux containers avoid global compile options; rely on defaults
endif()

find_package(OpenCV REQUIRED)
find_package(Threads REQUIRED)
option(VA_USE_LOCAL_YAML "Use bundled yaml-cpp under third_party" OFF)
set(YAML_LOCAL_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../third_party/yaml-cpp/yaml-cpp-0.8.0")
if (VA_USE_LOCAL_YAML AND EXISTS "${YAML_LOCAL_ROOT}/CMakeLists.txt")
    set(YAML_CPP_TARGET yaml-cpp)
    add_subdirectory("${YAML_LOCAL_ROOT}" "${CMAKE_BINARY_DIR}/yaml-cpp" EXCLUDE_FROM_ALL)
else()
    find_package(yaml-cpp REQUIRED)
    if (TARGET yaml-cpp::yaml-cpp)
        set(YAML_CPP_TARGET yaml-cpp::yaml-cpp)
    elseif (TARGET yaml-cpp)
        set(YAML_CPP_TARGET yaml-cpp)
    else()
        # Fallback: some distros only export 'yaml-cpp' without namespace
        set(YAML_CPP_TARGET yaml-cpp)
    endif()
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
option(WITH_CUDA_KERNELS "Build CUDA kernels (device-side decode/NMS/overlay)" OFF)
option(WITH_NVDEC "Build NVDEC-based RTSP source (scaffold)" OFF)
option(WITH_NVENC "Build NVENC-based H264 encoder (FFmpeg wrapper)" OFF)
option(VA_DISABLE_HTTP_PUBLIC "Disable public HTTP routes (keep WHEP/metrics)" OFF)
option(VA_REST_DEPRECATED_410 "Expose deprecated VA REST endpoints as 410 Gone placeholders when public HTTP disabled" OFF)
## gRPC 为必需能力：构建必须具备 Protobuf/gRPC，且默认开启服务端
option(VA_BUILD_TESTS "Build unit test targets" OFF)
option(VA_WITH_MYSQL "Enable MySQL-backed storage (mysql-connector-c++)" OFF)
## 默认 CUDA 架构（可在配置时覆盖）
## 示例覆盖：-DVA_CUDA_ARCHS=89 或 -DCMAKE_CUDA_ARCHITECTURES=89
set(VA_CUDA_ARCHS "89" CACHE STRING "CUDA SM architectures for NVCC (e.g. 89;90;120)")
if(USE_CUDA)
    find_package(CUDAToolkit QUIET)
    if(CUDAToolkit_FOUND)
        add_definitions(-DUSE_CUDA)
        if(WITH_CUDA_KERNELS)
            set(HAVE_CUDA_KERNELS ON)
            message(STATUS "CUDA found: ${CUDAToolkit_VERSION} - building with NVCC kernels")
        else()
            set(HAVE_CUDA_KERNELS OFF)
            message(STATUS "CUDA found: ${CUDAToolkit_VERSION} - building without NVCC kernels")
        endif()
    else()
        set(HAVE_CUDA_KERNELS OFF)
        message(WARNING "CUDA not found - GPU inference disabled")
    endif()
endif()

# Optional: JSONCPP
find_path(JSONCPP_INCLUDE_DIR NAMES json/json.h PATHS /usr/local/include /usr/include PATH_SUFFIXES jsoncpp)
find_library(JSONCPP_LIBRARY NAMES jsoncpp PATHS /usr/local/lib /usr/lib)

# In-Process Triton (libtritonserver) —— 唯一保留的 Triton 路径
option(USE_TRITON_INPROCESS "Enable Triton in-process integration (libtritonserver)" OFF)
if (USE_TRITON_INPROCESS)
    # Allow hint via TRITON_SERVER_ROOT (default /opt/tritonserver)
    set(TRITON_SERVER_ROOT $ENV{TRITON_SERVER_ROOT})
    if (NOT TRITON_SERVER_ROOT)
        set(TRITON_SERVER_ROOT "/opt/tritonserver")
    endif()
    if (EXISTS "${TRITON_SERVER_ROOT}/include/triton/core/tritonserver.h")
        add_definitions(-DUSE_TRITON_INPROCESS)
        # Only add include path to the inproc sources to avoid polluting global include dirs
        set_source_files_properties(
            src/analyzer/triton_inproc_server_host.cpp
            src/analyzer/triton_inproc_session.cpp
            PROPERTIES
                COMPILE_OPTIONS "-I${TRITON_SERVER_ROOT}/include"
        )
        # Defer linking to after add_executable
        find_library(TRITONSERVER_LIB NAMES tritonserver PATHS ${TRITON_SERVER_ROOT}/lib)
        set(TRITONSERVER_LIB_RESOLVED ${TRITONSERVER_LIB})
        if (NOT TRITONSERVER_LIB_RESOLVED)
            message(WARNING "libtritonserver.so not found under ${TRITON_SERVER_ROOT}/lib; ensure runtime LD_LIBRARY_PATH contains it")
        endif()
    else()
        message(WARNING "tritonserver.h not found under ${TRITON_SERVER_ROOT}/include; disabling USE_TRITON_INPROCESS")
        set(USE_TRITON_INPROCESS OFF)
    endif()
endif()

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

# Allow overriding ORT DLL directory explicitly (folder containing onnxruntime*.dll)
set(ONNXRUNTIME_DLL_DIR "$ENV{ONNXRUNTIME_DLL_DIR}" CACHE PATH "Directory that contains onnxruntime*.dll (optional override)")

# Optional vcpkg-installed dependencies
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

# Optional: TensorRT (native session)
find_path(TENSORRT_INCLUDE_DIR NAMES NvInfer.h PATHS /usr/include /usr/local/include ENV CPATH)
find_library(NVINFER_LIB NAMES nvinfer)
find_library(NVONNXPARSER_LIB NAMES nvonnxparser)
if (TENSORRT_INCLUDE_DIR AND NVINFER_LIB AND NVONNXPARSER_LIB)
    set(TENSORRT_FOUND TRUE)
    message(STATUS "TensorRT found: enabling USE_TENSORRT")
    add_definitions(-DUSE_TENSORRT)
    include_directories(${TENSORRT_INCLUDE_DIR})
else()
    set(TENSORRT_FOUND FALSE)
    message(STATUS "TensorRT not found: native TensorRT session disabled")
endif()

file(GLOB_RECURSE SOURCES "src/*.cpp")
# Exclude tool executables from main target sources; they have their own targets
list(FILTER SOURCES EXCLUDE REGEX ".*/src/tools/.*\\.cpp$")
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
    src/analyzer/multistage/node_join.cpp
    src/analyzer/multistage/node_reid_smooth.cpp
    src/analyzer/multistage/node_track_ocsort.cpp
    src/core/source_reconnects.cpp
    src/core/nvdec_events.cpp
    # Storage: DB repositories
    src/storage/session_repo.cpp
    src/storage/graph_repo.cpp
    src/storage/source_repo.cpp)

add_executable(${PROJECT_NAME} ${SOURCES} ${HEADERS} ${CUDA_SOURCES})
if (HAVE_CUDA_KERNELS)
    target_compile_definitions(${PROJECT_NAME} PRIVATE VA_HAS_CUDA_KERNELS)
endif()

if (TENSORRT_FOUND)
    target_link_libraries(${PROJECT_NAME} PRIVATE ${NVINFER_LIB} ${NVONNXPARSER_LIB})
endif()
if (CUDAToolkit_FOUND)
    # Ensure host code sees cuda_runtime.h so GPU postproc runtime paths are enabled
    target_include_directories(${PROJECT_NAME} PRIVATE ${CUDAToolkit_INCLUDE_DIRS})
endif()

# When NVCC kernels are not compiled, add CPU/link stubs for CUDA-dependent symbols
if (UNIX AND NOT HAVE_CUDA_KERNELS)
    target_sources(${PROJECT_NAME} PRIVATE src/analyzer/cuda/cuda_kernels_stubs.cpp)
endif()

target_compile_definitions(${PROJECT_NAME} PRIVATE IXWEBSOCKET_USE_TLS=0)

if (VA_DISABLE_HTTP_PUBLIC)
    target_compile_definitions(${PROJECT_NAME} PRIVATE VA_DISABLE_HTTP_PUBLIC)
endif()
if (VA_REST_DEPRECATED_410)
    target_compile_definitions(${PROJECT_NAME} PRIVATE VA_REST_DEPRECATED_410)
endif()

target_include_directories(${PROJECT_NAME}
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)

target_link_libraries(${PROJECT_NAME}
    PRIVATE ${OpenCV_LIBS}
    PRIVATE Threads::Threads
    PRIVATE ${YAML_CPP_TARGET})

# Link libtritonserver after target is defined (if in-process enabled)
if (USE_TRITON_INPROCESS AND TRITONSERVER_LIB_RESOLVED)
    # Ensure linker can resolve transitive deps (e.g., libdcgm) at link time
    target_link_directories(${PROJECT_NAME} PRIVATE ${TRITON_SERVER_ROOT}/lib)
    target_link_libraries(${PROJECT_NAME} PRIVATE ${TRITONSERVER_LIB_RESOLVED})
endif()

# 全局开启 TRITON_ENABLE_GPU，确保 Triton ipc.h 使用 CUDA 路径（避免与 stub 冲突）
add_definitions(-DTRITON_ENABLE_GPU)
# Ensure HTTP/GRPC function prototypes are visible when building against libtritonserver
add_definitions(-DTRITON_ENABLE_HTTP -DTRITON_ENABLE_GRPC)

# 将 OpenSSL 放在链接尾部（如需静态对象解析）
find_package(OpenSSL)
if (OpenSSL_FOUND)
    target_link_libraries(${PROJECT_NAME} PRIVATE OpenSSL::SSL OpenSSL::Crypto)
else()
    find_library(SSL_LIB ssl)
    find_library(CRYPTO_LIB crypto)
    if (SSL_LIB AND CRYPTO_LIB)
        target_link_libraries(${PROJECT_NAME} PRIVATE ${SSL_LIB} ${CRYPTO_LIB})
    endif()
endif()

# Tools: TensorRT native cache builder (standalone)
if (TENSORRT_FOUND)
    add_executable(trt_cache_builder src/tools/trt_cache_builder.cpp)
    target_include_directories(trt_cache_builder PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
    if (CUDAToolkit_FOUND)
        target_include_directories(trt_cache_builder PRIVATE ${CUDAToolkit_INCLUDE_DIRS})
        # Link CUDA runtime for cudaGetDevice* symbols
        if (TARGET CUDA::cudart)
            target_link_libraries(trt_cache_builder PRIVATE CUDA::cudart)
        else()
            find_library(CUDART_LIB cudart)
            if (CUDART_LIB)
                target_link_libraries(trt_cache_builder PRIVATE ${CUDART_LIB})
            endif()
        endif()
    else()
        # Best-effort fallback: try to locate cudart even if CUDAToolkit config not found
        find_library(CUDART_LIB cudart)
        if (CUDART_LIB)
            target_link_libraries(trt_cache_builder PRIVATE ${CUDART_LIB})
        endif()
    endif()
    target_link_libraries(trt_cache_builder PRIVATE ${NVINFER_LIB} ${NVONNXPARSER_LIB})
    # Place tool under build/bin to align with Docker COPY
    set_target_properties(trt_cache_builder PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
    # Engine exporter
    add_executable(trt_engine_exporter src/tools/trt_engine_exporter.cpp)
    target_include_directories(trt_engine_exporter PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
    if (CUDAToolkit_FOUND)
        target_include_directories(trt_engine_exporter PRIVATE ${CUDAToolkit_INCLUDE_DIRS})
        if (TARGET CUDA::cudart)
            target_link_libraries(trt_engine_exporter PRIVATE CUDA::cudart)
        else()
            find_library(CUDART_LIB cudart)
            if (CUDART_LIB)
                target_link_libraries(trt_engine_exporter PRIVATE ${CUDART_LIB})
            endif()
        endif()
    else()
        find_library(CUDART_LIB cudart)
        if (CUDART_LIB)
            target_link_libraries(trt_engine_exporter PRIVATE ${CUDART_LIB})
        endif()
    endif()
    target_link_libraries(trt_engine_exporter PRIVATE ${NVINFER_LIB} ${NVONNXPARSER_LIB})
    set_target_properties(trt_engine_exporter PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
endif()

# Link LRO runtime if available (always, to satisfy lro::make_memory_store())
if (EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/../lro/CMakeLists.txt")
    add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../lro" "${CMAKE_BINARY_DIR}/lro" EXCLUDE_FROM_ALL)
    if (TARGET lro_runtime)
        target_link_libraries(${PROJECT_NAME} PRIVATE lro_runtime)
    endif()
endif()

# Control plane (embedded) sources — 无外部依赖占位，默认总是编译
target_sources(${PROJECT_NAME}
    PRIVATE
        src/controlplane/interfaces.hpp
        src/controlplane/controllers/pipeline_controller.cpp
        src/controlplane/controllers/pipeline_controller.hpp
        src/controlplane/adapters/graph_adapter_yaml.cpp
        src/controlplane/adapters/graph_adapter_yaml.hpp
        src/controlplane/exporters/prometheus_exporter.cpp
        src/controlplane/exporters/prometheus_exporter.hpp
        src/controlplane/io/from_vsm_link.hpp)

target_sources(${PROJECT_NAME}
    PRIVATE
        
        src/core/wal.cpp
        src/core/wal.hpp
        src/analyzer/model_registry.cpp
        src/analyzer/model_registry.hpp
        # Admin: WAL read-only endpoints
        src/server/rest_admin_wal.cpp)

## gRPC/Protobuf（REQUIRED）：通过 vcpkg 提示路径，强制启用
# vcpkg hints (share config packages)
if (DEFINED VCPKG_ROOT_DIR)
    if (EXISTS "${VCPKG_ROOT_DIR}/installed/x64-windows/share/protobuf/protobuf-config.cmake")
        list(PREPEND CMAKE_PREFIX_PATH "${VCPKG_ROOT_DIR}/installed/x64-windows")
        set(Protobuf_DIR "${VCPKG_ROOT_DIR}/installed/x64-windows/share/protobuf")
    endif()
    if (EXISTS "${VCPKG_ROOT_DIR}/installed/x64-windows/share/grpc/gRPCConfig.cmake")
        list(PREPEND CMAKE_PREFIX_PATH "${VCPKG_ROOT_DIR}/installed/x64-windows")
        set(gRPC_DIR "${VCPKG_ROOT_DIR}/installed/x64-windows/share/grpc")
    endif()
endif()

# Prefer config packages from vcpkg to avoid mixing with system/anaconda modules
# Prefer Protobuf config package from vcpkg; uppercase name improves DIR hinting
find_package(Protobuf CONFIG QUIET)
if (NOT Protobuf_FOUND)
    find_package(Protobuf REQUIRED)
endif()

find_package(gRPC CONFIG QUIET)
if (NOT gRPC_FOUND)
    find_package(PkgConfig REQUIRED)
    pkg_check_modules(GRPCPP REQUIRED grpc++)
    set(GRPC_FOUND TRUE)
    set(GRPC_INCLUDE_DIRS ${GRPCPP_INCLUDE_DIRS})
    set(GRPC_LIBRARIES ${GRPCPP_LIBRARIES})
endif()

message(STATUS "gRPC/Protobuf found (with fallback if needed): enabling AnalyzerControl service")
add_definitions(-DUSE_GRPC)

        set(_PROTO_DIR ${CMAKE_CURRENT_SOURCE_DIR}/proto)
        set(_VSM_PROTO_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../video-source-manager/proto)
        set(_GEN_DIR ${CMAKE_BINARY_DIR}/generated)
        file(MAKE_DIRECTORY ${_GEN_DIR})
        set(PROTO_FILES ${_PROTO_DIR}/analyzer_control.proto ${_PROTO_DIR}/pipeline.proto)

        # Generators (portable across config/module pkg layouts)
        set(_PROTOC_EXE protoc)
        if (TARGET protobuf::protoc)
            set(_PROTOC_EXE $<TARGET_FILE:protobuf::protoc>)
        elseif(DEFINED Protobuf_PROTOC_EXECUTABLE)
            set(_PROTOC_EXE ${Protobuf_PROTOC_EXECUTABLE})
        endif()
        set(_GRPC_CPP_PLUGIN grpc_cpp_plugin)
        if (TARGET gRPC::grpc_cpp_plugin)
            set(_GRPC_CPP_PLUGIN $<TARGET_FILE:gRPC::grpc_cpp_plugin>)
        else()
            find_program(GRPC_CPP_PLUGIN_EXECUTABLE grpc_cpp_plugin)
            if (GRPC_CPP_PLUGIN_EXECUTABLE)
                set(_GRPC_CPP_PLUGIN ${GRPC_CPP_PLUGIN_EXECUTABLE})
            endif()
        endif()

        set(GEN_SRCS)
        set(GEN_HDRS)
        foreach(proto ${PROTO_FILES})
            get_filename_component(fname ${proto} NAME_WE)
            set(pb_cc  ${_GEN_DIR}/${fname}.pb.cc)
            set(pb_h   ${_GEN_DIR}/${fname}.pb.h)
            list(APPEND GEN_SRCS ${pb_cc})
            list(APPEND GEN_HDRS ${pb_h})
            add_custom_command(
                OUTPUT ${pb_cc} ${pb_h}
                COMMAND ${_PROTOC_EXE}
                ARGS --cpp_out ${_GEN_DIR}
                     -I ${_PROTO_DIR}
                     ${proto}
                DEPENDS ${proto}
            )
        endforeach()

        # gRPC stubs for analyzer_control only
        set(grpc_cc ${_GEN_DIR}/analyzer_control.grpc.pb.cc)
        set(grpc_h  ${_GEN_DIR}/analyzer_control.grpc.pb.h)
        add_custom_command(
            OUTPUT ${grpc_cc} ${grpc_h}
            COMMAND ${_PROTOC_EXE}
                ARGS --grpc_out ${_GEN_DIR}
                 --plugin=protoc-gen-grpc=${_GRPC_CPP_PLUGIN}
                 -I ${_PROTO_DIR}
                 ${_PROTO_DIR}/analyzer_control.proto
            DEPENDS ${_PROTO_DIR}/analyzer_control.proto
        )

        add_library(va_analyzer_control_proto ${GEN_SRCS} ${grpc_cc})
        target_include_directories(va_analyzer_control_proto PUBLIC ${_GEN_DIR})
        if (TARGET gRPC::grpc++)
            target_link_libraries(va_analyzer_control_proto PUBLIC gRPC::grpc++ protobuf::libprotobuf)
        else()
            if (DEFINED GRPC_INCLUDE_DIRS)
                target_include_directories(va_analyzer_control_proto PUBLIC ${GRPC_INCLUDE_DIRS})
            endif()
            if (TARGET protobuf::libprotobuf)
                target_link_libraries(va_analyzer_control_proto PUBLIC ${GRPC_LIBRARIES} protobuf::libprotobuf)
            else()
                target_link_libraries(va_analyzer_control_proto PUBLIC ${GRPC_LIBRARIES} ${Protobuf_LIBRARIES})
                if (DEFINED Protobuf_INCLUDE_DIRS)
                    target_include_directories(va_analyzer_control_proto PUBLIC ${Protobuf_INCLUDE_DIRS})
                endif()
            endif()
        endif()

        target_include_directories(${PROJECT_NAME} PRIVATE ${_GEN_DIR})
        target_link_libraries(${PROJECT_NAME} PRIVATE va_analyzer_control_proto)

        # WHEP control stubs
        if (EXISTS ${_PROTO_DIR}/whep_control.proto)
            add_custom_command(
                OUTPUT ${_GEN_DIR}/whep_control.pb.cc ${_GEN_DIR}/whep_control.pb.h
                COMMAND ${_PROTOC_EXE}
                    ARGS --cpp_out ${_GEN_DIR}
                         -I ${_PROTO_DIR}
                         ${_PROTO_DIR}/whep_control.proto
                DEPENDS ${_PROTO_DIR}/whep_control.proto)
            add_custom_command(
                OUTPUT ${_GEN_DIR}/whep_control.grpc.pb.cc ${_GEN_DIR}/whep_control.grpc.pb.h
                COMMAND ${_PROTOC_EXE}
                    ARGS --grpc_out ${_GEN_DIR}
                         --plugin=protoc-gen-grpc=${_GRPC_CPP_PLUGIN}
                         -I ${_PROTO_DIR}
                         ${_PROTO_DIR}/whep_control.proto
                DEPENDS ${_PROTO_DIR}/whep_control.proto)
            add_library(va_whep_proto ${_GEN_DIR}/whep_control.pb.cc ${_GEN_DIR}/whep_control.grpc.pb.cc)
            target_include_directories(va_whep_proto PUBLIC ${_GEN_DIR})
            if (TARGET gRPC::grpc++)
                target_link_libraries(va_whep_proto PUBLIC gRPC::grpc++ protobuf::libprotobuf)
            else() 
                if (DEFINED GRPC_INCLUDE_DIRS)
                    target_include_directories(va_whep_proto PUBLIC ${GRPC_INCLUDE_DIRS})
                endif()
                if (TARGET protobuf::libprotobuf)
                    target_link_libraries(va_whep_proto PUBLIC ${GRPC_LIBRARIES} protobuf::libprotobuf)
                else()
                    target_link_libraries(va_whep_proto PUBLIC ${GRPC_LIBRARIES} ${Protobuf_LIBRARIES})
                    if (DEFINED Protobuf_INCLUDE_DIRS)
                        target_include_directories(va_whep_proto PUBLIC ${Protobuf_INCLUDE_DIRS})
                    endif()
                endif()
            endif()
            target_link_libraries(${PROJECT_NAME} PRIVATE va_whep_proto)
        endif()

        # Also generate VSM SourceControl stubs for client usage (Plan B streaming)
        if (EXISTS ${_VSM_PROTO_DIR}/source_control.proto)
            add_custom_command(
                OUTPUT ${_GEN_DIR}/source_control.pb.cc ${_GEN_DIR}/source_control.pb.h
                COMMAND ${_PROTOC_EXE}
                    ARGS --cpp_out ${_GEN_DIR}
                         -I ${_VSM_PROTO_DIR}
                         ${_VSM_PROTO_DIR}/source_control.proto
                DEPENDS ${_VSM_PROTO_DIR}/source_control.proto)
            add_custom_command(
                OUTPUT ${_GEN_DIR}/source_control.grpc.pb.cc ${_GEN_DIR}/source_control.grpc.pb.h
                COMMAND ${_PROTOC_EXE}
                    ARGS --grpc_out ${_GEN_DIR}
                         --plugin=protoc-gen-grpc=${_GRPC_CPP_PLUGIN}
                         -I ${_VSM_PROTO_DIR}
                         ${_VSM_PROTO_DIR}/source_control.proto
                DEPENDS ${_VSM_PROTO_DIR}/source_control.proto)
            add_library(va_vsm_proto ${_GEN_DIR}/source_control.pb.cc ${_GEN_DIR}/source_control.grpc.pb.cc)
            target_include_directories(va_vsm_proto PUBLIC ${_GEN_DIR})
            if (TARGET gRPC::grpc++)
                target_link_libraries(va_vsm_proto PUBLIC gRPC::grpc++ protobuf::libprotobuf)
            else()
                if (DEFINED GRPC_INCLUDE_DIRS)
                    target_include_directories(va_vsm_proto PUBLIC ${GRPC_INCLUDE_DIRS})
                endif()
                if (TARGET protobuf::libprotobuf)
                    target_link_libraries(va_vsm_proto PUBLIC ${GRPC_LIBRARIES} protobuf::libprotobuf)
                else()
                    target_link_libraries(va_vsm_proto PUBLIC ${GRPC_LIBRARIES} ${Protobuf_LIBRARIES})
                    if (DEFINED Protobuf_INCLUDE_DIRS)
                        target_include_directories(va_vsm_proto PUBLIC ${Protobuf_INCLUDE_DIRS})
                    endif()
                endif()
            endif()
            target_link_libraries(${PROJECT_NAME} PRIVATE va_vsm_proto)
        endif()

        # 始终启用 VA gRPC 服务端（构建必备）
        add_definitions(-DVA_ENABLE_GRPC_SERVER)
        target_sources(${PROJECT_NAME}
            PRIVATE
                src/controlplane/api/grpc_server.cpp
                src/controlplane/api/grpc_server.hpp)

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


## Removed DLL copy from build scripts per request

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

option(VA_BUILD_TOOLS "Build WHEP tools (probe/server)" OFF)
if (VA_BUILD_TOOLS)
  # ---- WHEP client probe (test tool) ----
  add_executable(WhepClientProbe src/tools/whep_client_probe.cpp)
  target_include_directories(WhepClientProbe PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
      ${CMAKE_CURRENT_SOURCE_DIR}/src)
  if (WIN32)
      target_include_directories(WhepClientProbe PRIVATE ${VCPKG_INCLUDE_DIR} "D:/Projects/vcpkg/installed/x64-windows/include")
  endif()
  target_link_vcpkg_library(WhepClientProbe "${DATA_CHANNEL_LIB_DEBUG}" "${DATA_CHANNEL_LIB_RELEASE}")
  target_link_vcpkg_library(WhepClientProbe "${JUICE_LIB_DEBUG}" "${JUICE_LIB_RELEASE}")
  target_link_vcpkg_library(WhepClientProbe "${MBEDTLS_LIB_DEBUG}" "${MBEDTLS_LIB_RELEASE}")
  if (WIN32)
    target_link_libraries(WhepClientProbe PRIVATE ws2_32 iphlpapi winhttp crypt32)
  endif()
  set_target_properties(WhepClientProbe PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")

  # ---- WHEP standalone server ----
  add_executable(WhepStandaloneServer src/tools/whep_standalone_server.cpp)
  target_include_directories(WhepStandaloneServer PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
      ${CMAKE_CURRENT_SOURCE_DIR}/src)
  if (WIN32)
      target_include_directories(WhepStandaloneServer PRIVATE ${VCPKG_INCLUDE_DIR} "D:/Projects/vcpkg/installed/x64-windows/include")
  endif()
  target_link_vcpkg_library(WhepStandaloneServer "${DATA_CHANNEL_LIB_DEBUG}" "${DATA_CHANNEL_LIB_RELEASE}")
  target_link_vcpkg_library(WhepStandaloneServer "${JUICE_LIB_DEBUG}" "${JUICE_LIB_RELEASE}")
  target_link_vcpkg_library(WhepStandaloneServer "${MBEDTLS_LIB_DEBUG}" "${MBEDTLS_LIB_RELEASE}")
  set_target_properties(WhepStandaloneServer PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
  if (FFMPEG_FOUND)
    if(FFMPEG_PKG_FOUND)
      target_include_directories(WhepStandaloneServer PRIVATE ${FFMPEG_PKG_INCLUDE_DIRS})
      target_link_libraries(WhepStandaloneServer PRIVATE ${FFMPEG_PKG_LIBRARIES})
    else()
      foreach(component IN LISTS FFMPEG_COMPONENTS)
        string(TOUPPER ${component} UPPER)
        if(FFMPEG_${UPPER}_INCLUDE)
          target_include_directories(WhepStandaloneServer PRIVATE ${FFMPEG_${UPPER}_INCLUDE})
        endif()
        if(FFMPEG_${UPPER}_LIB)
          target_link_libraries(WhepStandaloneServer PRIVATE ${FFMPEG_${UPPER}_LIB})
        endif()
      endforeach()
    endif()
  endif()
  if (WIN32)
    target_link_libraries(WhepStandaloneServer PRIVATE ws2_32 iphlpapi)
  endif()
endif()
target_link_vcpkg_library(${PROJECT_NAME} "${MBEDCRYPTO_LIB_DEBUG}" "${MBEDCRYPTO_LIB_RELEASE}")
target_link_vcpkg_library(${PROJECT_NAME} "${MBEDX509_LIB_DEBUG}" "${MBEDX509_LIB_RELEASE}")
target_link_vcpkg_library(${PROJECT_NAME} "${ZLIB_LIB_DEBUG}" "${ZLIB_LIB_RELEASE}")

# Prefer vcpkg jsoncpp if available (ensures proper symbol resolution on Windows)
find_library(JSONCPP_LIB_RELEASE NAMES jsoncpp PATHS ${VCPKG_LIB_DIR} NO_DEFAULT_PATH)
find_library(JSONCPP_LIB_DEBUG NAMES jsoncpp PATHS ${VCPKG_LIB_DIR_DEBUG} NO_DEFAULT_PATH)
if (JSONCPP_LIB_RELEASE OR JSONCPP_LIB_DEBUG)
    target_link_vcpkg_library(${PROJECT_NAME} "${JSONCPP_LIB_DEBUG}" "${JSONCPP_LIB_RELEASE}")
endif()

# If system JSONCPP headers are available, add include path for <json/json.h>
if (JSONCPP_INCLUDE_DIR)
    target_include_directories(${PROJECT_NAME} PRIVATE ${JSONCPP_INCLUDE_DIR})
endif()

# Optional: MySQL Connector/C++ via vcpkg (unofficial-mysql-connector-cpp)
if (VA_WITH_MYSQL)
    # 1) Prefer vcpkg package (mysql-connector-c++ 8.x, DevAPI). This only enables VA_WITH_MYSQL
    #    and allows DB feature gating; JDBC legacy headers are detected separately below.
    find_package(unofficial-mysql-connector-cpp CONFIG QUIET)
    if (unofficial-mysql-connector-cpp_FOUND)
        message(STATUS "MySQL connector (vcpkg, 8.x) found: enabling VA_WITH_MYSQL")
        target_link_libraries(${PROJECT_NAME} PRIVATE unofficial::mysql-connector-cpp::connector)
        target_compile_definitions(${PROJECT_NAME} PRIVATE VA_WITH_MYSQL)
    else()
        message(WARNING "mysql-connector-c++ (vcpkg) not found; will try Oracle legacy JDBC include/lib hints")
        target_compile_definitions(${PROJECT_NAME} PRIVATE VA_WITH_MYSQL)
    endif()

    # 2) Detect Oracle Connector/C++ (legacy JDBC API) to enable HAVE_MYSQL_JDBC
    #    Hints: set MYSQL_CONCPP_DIR to the connector root (contains include/, lib/ or lib64/)
    set(_MYSQL_CONCPP_HINTS)
    if (DEFINED ENV{MYSQL_CONCPP_DIR})
        list(APPEND _MYSQL_CONCPP_HINTS "$ENV{MYSQL_CONCPP_DIR}/include")
    endif()
    # Prefer repo-bundled binaries if present
    set(MYSQL_LOCAL_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../third_party/mysql-connector-c++-9.4.0-winx64")
    if (EXISTS "${MYSQL_LOCAL_ROOT}")
        list(APPEND _MYSQL_CONCPP_HINTS "${MYSQL_LOCAL_ROOT}/include")
    endif()
    # Common Windows install locations
    list(APPEND _MYSQL_CONCPP_HINTS
        "C:/Program Files/MySQL/Connector C++ 1.1/include"
        "C:/Program Files (x86)/MySQL/Connector C++ 1.1/include"
        "C:/Program Files/MySQL/Connector C++ 8.0/include")

    find_path(MYSQL_JDBC_INCLUDE_DIR NAMES mysql/jdbc.h PATHS ${_MYSQL_CONCPP_HINTS})
    if (MYSQL_JDBC_INCLUDE_DIR)
        message(STATUS "Found legacy JDBC headers at: ${MYSQL_JDBC_INCLUDE_DIR}")
        target_include_directories(${PROJECT_NAME} PRIVATE ${MYSQL_JDBC_INCLUDE_DIR})
        # Try to locate libmysqlcppconn (legacy connector library)
        set(_MYSQL_CONCPP_LIB_HINTS)
        if (DEFINED ENV{MYSQL_CONCPP_DIR})
            list(APPEND _MYSQL_CONCPP_LIB_HINTS "$ENV{MYSQL_CONCPP_DIR}/lib" "$ENV{MYSQL_CONCPP_DIR}/lib64" "$ENV{MYSQL_CONCPP_DIR}/lib/vs14" "$ENV{MYSQL_CONCPP_DIR}/lib64/vs14")
        endif()
        if (EXISTS "${MYSQL_LOCAL_ROOT}")
            list(APPEND _MYSQL_CONCPP_LIB_HINTS "${MYSQL_LOCAL_ROOT}/lib" "${MYSQL_LOCAL_ROOT}/lib64" "${MYSQL_LOCAL_ROOT}/lib/vs14" "${MYSQL_LOCAL_ROOT}/lib64/vs14")
        endif()
        list(APPEND _MYSQL_CONCPP_LIB_HINTS
            "C:/Program Files/MySQL/Connector C++ 1.1/lib"
            "C:/Program Files/MySQL/Connector C++ 1.1/lib64"
            "C:/Program Files (x86)/MySQL/Connector C++ 1.1/lib"
            "C:/Program Files/MySQL/Connector C++ 8.0/lib64")
        find_library(MYSQL_CPP_CONN_LIB NAMES mysqlcppconn PATHS ${_MYSQL_CONCPP_LIB_HINTS})
        if (MYSQL_CPP_CONN_LIB)
            target_link_libraries(${PROJECT_NAME} PRIVATE ${MYSQL_CPP_CONN_LIB})
            target_compile_definitions(${PROJECT_NAME} PRIVATE HAVE_MYSQL_JDBC)
            message(STATUS "Linking against legacy Connector/C++: ${MYSQL_CPP_CONN_LIB}")
        else()
            message(WARNING "Found mysql/jdbc.h but could not locate lib 'mysqlcppconn'; DB features may fail to link.")
        endif()
    else()
        message(STATUS "mysql/jdbc.h not found; DB layer will run in disabled (NullDbPool) mode.")
    endif()
endif()

# --- Post-build: copy runtime DLLs to bin (Windows) ---
if (WIN32)
    # Note: 为避免构建脚本内复制依赖，这里不做任何 DLL 拷贝。
    # 运行时依赖请在部署脚本或手动复制解决。
endif()

if (WIN32)
    # 不创建任何自动复制目标，避免构建阶段触发复制。
endif()

# Ensure vcpkg include path is visible for header-only deps (ixwebsocket, rtc/libdatachannel, jsoncpp, etc.)
if (WIN32)
    target_include_directories(${PROJECT_NAME} PRIVATE "${VCPKG_INCLUDE_DIR}")
    if (EXISTS "D:/Projects/vcpkg/installed/x64-windows/include")
        # Also add user vcpkg tree explicitly to override VS-integrated vcpkg lacking some ports
        target_include_directories(${PROJECT_NAME} PRIVATE "D:/Projects/vcpkg/installed/x64-windows/include")
    endif()
endif()

if (WIN32)
    target_link_libraries(${PROJECT_NAME} PRIVATE ws2_32 iphlpapi psapi crypt32 bcrypt)
    # Some environments with Ninja+MSVC miss Windows SDK lib directory in LIB paths.
    # Add UM lib directory explicitly when available to avoid LNK1181 on ws2_32.lib.
    if(DEFINED ENV{WindowsSdkDir})
        # Try both WindowsSDKVersion (with trailing slash) and WindowsSDKLibVersion (sometimes used)
        if(DEFINED ENV{WindowsSDKVersion})
            string(REGEX REPLACE "/$" "" _SDK_VER "$ENV{WindowsSDKVersion}")
            set(_WS_UM_LIB "$ENV{WindowsSdkDir}/Lib/${_SDK_VER}/um/x64")
            if (EXISTS "${_WS_UM_LIB}/ws2_32.lib")
                target_link_directories(${PROJECT_NAME} PRIVATE "${_WS_UM_LIB}")
            endif()
        endif()
        if(DEFINED ENV{WindowsSDKLibVersion})
            string(REGEX REPLACE "/$" "" _SDK_LIB_VER "$ENV{WindowsSDKLibVersion}")
            set(_WS_UM_LIB2 "$ENV{WindowsSdkDir}/Lib/${_SDK_LIB_VER}/um/x64")
            if (EXISTS "${_WS_UM_LIB2}/ws2_32.lib")
                target_link_directories(${PROJECT_NAME} PRIVATE "${_WS_UM_LIB2}")
            endif()
        endif()
    endif()
    # Ensure MSVC STL/UCRT/WinSDK include paths are visible to Ninja+MSVC in some CI shells
    if(DEFINED ENV{VCToolsInstallDir})
        target_include_directories(${PROJECT_NAME} PRIVATE "$ENV{VCToolsInstallDir}/include")
    endif()
    if(DEFINED ENV{UniversalCRTSdkDir} AND DEFINED ENV{UCRTVersion})
        target_include_directories(${PROJECT_NAME} PRIVATE "$ENV{UniversalCRTSdkDir}/include/$ENV{UCRTVersion}/ucrt")
    endif()
    if(DEFINED ENV{WindowsSdkDir} AND DEFINED ENV{WindowsSDKVersion})
        target_include_directories(${PROJECT_NAME} PRIVATE "$ENV{WindowsSdkDir}/Include/$ENV{WindowsSDKVersion}/um" "$ENV{WindowsSdkDir}/Include/$ENV{WindowsSDKVersion}/shared")
    endif()
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
    # On non-MSVC hosts, strip MSVC-specific -Xcompiler flags accidentally added above
    if (NOT MSVC)
        set_property(TARGET va_cuda_kernels PROPERTY COMPILE_OPTIONS "")
    endif()
    # Default CUDA architectures if not specified (e.g., Ada: 89)
    if (NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
        set(CMAKE_CUDA_ARCHITECTURES 89)
    endif()
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

# Add LRO header-only include path if present
if (EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/../lro/include")
    target_include_directories(${PROJECT_NAME} PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/../lro/include")
endif()



if (VA_BUILD_TESTS)
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
endif()





# Detect libdatachannel headers and enable RTC when available
include(CheckIncludeFileCXX)
check_include_file_cxx("rtc/rtc.hpp" HAVE_RTC_HEADER)
if (HAVE_RTC_HEADER)
    target_compile_definitions(${PROJECT_NAME} PRIVATE VA_HAVE_RTC=1)
else()
    target_compile_definitions(${PROJECT_NAME} PRIVATE VA_HAVE_RTC=0)
endif()

# On UNIX, try to link libdatachannel stack from default locations when present
if (UNIX)
    find_library(LIB_DATACHANNEL datachannel)
    find_library(LIB_JUICE juice)
    find_library(LIB_USRSCTP usrsctp)
    find_library(LIB_MBEDTLS mbedtls)
    find_library(LIB_MBEDCRYPTO mbedcrypto)
    find_library(LIB_MBEDX509 mbedx509)
    find_library(LIB_IXWEBSOCKET ixwebsocket)
    if (LIB_DATACHANNEL)
        target_link_libraries(${PROJECT_NAME} PRIVATE ${LIB_DATACHANNEL})
    endif()
    if (LIB_JUICE)
        target_link_libraries(${PROJECT_NAME} PRIVATE ${LIB_JUICE})
    endif()
    if (LIB_USRSCTP)
        target_link_libraries(${PROJECT_NAME} PRIVATE ${LIB_USRSCTP})
    endif()
    if (LIB_MBEDTLS)
        target_link_libraries(${PROJECT_NAME} PRIVATE ${LIB_MBEDTLS})
    endif()
    if (LIB_MBEDCRYPTO)
        target_link_libraries(${PROJECT_NAME} PRIVATE ${LIB_MBEDCRYPTO})
    endif()
    if (LIB_MBEDX509)
        target_link_libraries(${PROJECT_NAME} PRIVATE ${LIB_MBEDX509})
    endif()
    if (LIB_IXWEBSOCKET)
        target_link_libraries(${PROJECT_NAME} PRIVATE ${LIB_IXWEBSOCKET})
    else()
        # Fallback to header-only if lib not found
        target_compile_definitions(${PROJECT_NAME} PRIVATE IXWEBSOCKET_HEADER_ONLY)
    endif()
endif()



# In UNIX container builds, keep public HTTP routes disabled by default to reduce dependencies
if (UNIX)
    set(VA_DISABLE_HTTP_PUBLIC ON CACHE BOOL "Disable public HTTP routes on UNIX" FORCE)
    if (VA_DISABLE_HTTP_PUBLIC)
        target_compile_definitions(${PROJECT_NAME} PRIVATE VA_DISABLE_HTTP_PUBLIC)
    endif()
endif()
