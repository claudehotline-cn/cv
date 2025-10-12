cmake_minimum_required(VERSION 3.16)
project(VideoAnalyzerRoot)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

if(MSVC)
    add_compile_options(/W4)
    add_compile_definitions(_WIN32_WINNT=0x0601)
else()
    add_compile_options(-Wall -Wextra -pedantic)
endif()

find_package(OpenCV REQUIRED)
find_package(Threads REQUIRED)

set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)

# Build video-analyzer
add_subdirectory(video-analyzer)

# Optional unified CLI for VA/VSM (requires USE_GRPC and gRPC toolchain)
add_subdirectory(tools/va_vsm_cli)
