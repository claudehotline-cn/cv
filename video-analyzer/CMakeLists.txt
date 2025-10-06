cmake_minimum_required(VERSION 3.16)
project(VideoAnalyzer)

set(VCPKG_APPLOCAL_DEPS OFF)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(MSVC)
    add_compile_options(/W4)
    add_compile_options(/utf-8)
else()
    add_compile_options(-Wall -Wextra -pedantic)
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
find_path(ONNXRUNTIME_INCLUDE_DIR NAMES onnxruntime_cxx_api.h PATHS ${ONNXRUNTIME_ROOT}/include /usr/local/include/onnxruntime /usr/include/onnxruntime)
find_library(ONNXRUNTIME_LIB NAMES onnxruntime PATHS ${ONNXRUNTIME_ROOT}/lib /usr/local/lib /usr/lib)

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
    target_link_libraries(${PROJECT_NAME} PRIVATE CUDA::cudart)
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

if (WIN32)
    target_link_libraries(${PROJECT_NAME} PRIVATE ws2_32 iphlpapi psapi crypt32 bcrypt)
endif()

set_target_properties(${PROJECT_NAME} PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")

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

