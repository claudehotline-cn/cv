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
set(CUDA_OBJECTS "")
if(USE_CUDA)
    if(NOT CUDAToolkit_ROOT AND EXISTS "C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.9")
        set(CUDAToolkit_ROOT "C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.9")
    endif()
    find_package(CUDAToolkit QUIET)
    if(CUDAToolkit_FOUND AND CUDAToolkit_NVCC_EXECUTABLE)
        add_definitions(-DUSE_CUDA)
        file(GLOB_RECURSE CUDA_SOURCE_FILES "src/*.cu")
        if(CUDA_SOURCE_FILES)
            set(CUDA_BUILD_DIR "${CMAKE_CURRENT_BINARY_DIR}/cuda")
            file(MAKE_DIRECTORY "${CUDA_BUILD_DIR}")

            set(CUDA_NVCC_ARGS --std=c++17 -Xcompiler "/MD /EHsc" -I "${CMAKE_CURRENT_SOURCE_DIR}/src" -I "${CMAKE_CURRENT_SOURCE_DIR}/include")
            if(ONNXRUNTIME_INCLUDE_DIR)
                list(APPEND CUDA_NVCC_ARGS -I "${ONNXRUNTIME_INCLUDE_DIR}")
            endif()
            if(CUDAToolkit_INCLUDE_DIRS)
                foreach(cuda_inc IN LISTS CUDAToolkit_INCLUDE_DIRS)
                    list(APPEND CUDA_NVCC_ARGS -I "${cuda_inc}")
                endforeach()
            endif()
            set(VA_CUDA_ARCH "90" CACHE STRING "CUDA compute capability (e.g. 75, 86, 90, 120)")
            if(VA_CUDA_ARCH)
                list(APPEND CUDA_NVCC_ARGS -gencode "arch=compute_${VA_CUDA_ARCH},code=sm_${VA_CUDA_ARCH}")
            endif()

            foreach(CUDA_FILE IN LISTS CUDA_SOURCE_FILES)
                get_filename_component(CUDA_BASENAME "${CUDA_FILE}" NAME_WE)
                set(CUDA_OBJECT "${CUDA_BUILD_DIR}/${CUDA_BASENAME}.obj")
                add_custom_command(
                    OUTPUT "${CUDA_OBJECT}"
                    COMMAND "${CUDAToolkit_NVCC_EXECUTABLE}" -c "${CUDA_FILE}" -o "${CUDA_OBJECT}" ${CUDA_NVCC_ARGS}
                    DEPENDS "${CUDA_FILE}"
                    COMMENT "Building CUDA object ${CUDA_BASENAME}.obj"
                    VERBATIM
                )
                list(APPEND CUDA_OBJECTS "${CUDA_OBJECT}")
            endforeach()
        endif()
        message(STATUS "CUDA found: ${CUDAToolkit_VERSION} - GPU inference enabled (nvcc compile)")
    else()
        message(WARNING "CUDA toolkit not found or nvcc unavailable - GPU inference disabled")
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
if(CUDAToolkit_FOUND)
    include_directories(${CUDAToolkit_INCLUDE_DIRS})
endif()

file(GLOB_RECURSE SOURCES "src/*.cpp")
file(GLOB_RECURSE HEADERS "include/*.h" "src/*.hpp")

add_executable(${PROJECT_NAME} ${SOURCES} ${HEADERS} ${CUDA_OBJECTS})

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

if(JSONCPP_LIBRARY)
    target_link_libraries(${PROJECT_NAME} PRIVATE ${JSONCPP_LIBRARY})
endif()

if(ONNXRUNTIME_LIB)
    target_link_libraries(${PROJECT_NAME} PRIVATE ${ONNXRUNTIME_LIB})
endif()

if(USE_CUDA AND CUDAToolkit_FOUND)
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
