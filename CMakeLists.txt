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
option(BUILD_VIDEO_SOURCE_MANAGER "Build video-source-manager project" OFF)
option(BUILD_CONTROLPLAIN "Build controlplain project" OFF)
option(BUILD_VA_VSM_CLI "Build VA/VSM CLI tools (requires gRPC toolchain)" OFF)

# Subprojects
if(BUILD_VIDEO_ANALYZER AND EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/video-analyzer/CMakeLists.txt)
  add_subdirectory(video-analyzer)
endif()

if(BUILD_VIDEO_SOURCE_MANAGER AND EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/video-source-manager/CMakeLists.txt)
  add_subdirectory(video-source-manager)
endif()

if(BUILD_CONTROLPLAIN AND EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/controlplain/CMakeLists.txt)
  add_subdirectory(controlplain)
endif()

if(BUILD_VA_VSM_CLI AND EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/tools/va_vsm_cli/CMakeLists.txt)
  add_subdirectory(tools/va_vsm_cli)
endif()

message(STATUS "cv_root configured: VA=${BUILD_VIDEO_ANALYZER} VSM=${BUILD_VIDEO_SOURCE_MANAGER} CP=${BUILD_CONTROLPLAIN} CLI=${BUILD_VA_VSM_CLI}")
