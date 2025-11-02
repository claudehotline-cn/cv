cmake_minimum_required(VERSION 3.16)
project(cv_root LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

if(MSVC)
    add_compile_definitions(_WIN32_WINNT=0x0601)
endif()

# Consolidated output dirs
set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)

# Build toggles (avoid forcing third-party dependencies at root)
option(BUILD_VIDEO_ANALYZER "Build video-analyzer project" ON)
option(BUILD_VIDEO_SOURCE_MANAGER "Build video-source-manager project" ON)
option(BUILD_CONTROLPLANE "Build controlplane project" ON)
option(BUILD_VA_VSM_CLI "Build VA/VSM CLI tools (requires gRPC toolchain)" ON)
option(BUILD_LRO "Build lro library and examples (auto-detects gRPC/Protobuf)" ON)

# Subprojects
if(BUILD_VIDEO_ANALYZER AND EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/video-analyzer/CMakeLists.txt)
  add_subdirectory(video-analyzer)
endif()

if(BUILD_VIDEO_SOURCE_MANAGER AND EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/video-source-manager/CMakeLists.txt)
  add_subdirectory(video-source-manager)
endif()

if(BUILD_CONTROLPLANE AND EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/controlplane/CMakeLists.txt)
  add_subdirectory(controlplane)
endif()

if(BUILD_VA_VSM_CLI AND EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/tools/va_vsm_cli/CMakeLists.txt)
  add_subdirectory(tools/va_vsm_cli)
endif()

if(BUILD_LRO AND EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/lro/CMakeLists.txt)
  add_subdirectory(lro)
endif()

message(STATUS "cv_root configured: VA=${BUILD_VIDEO_ANALYZER} VSM=${BUILD_VIDEO_SOURCE_MANAGER} CP=${BUILD_CONTROLPLANE} CLI=${BUILD_VA_VSM_CLI} LRO=${BUILD_LRO}")

