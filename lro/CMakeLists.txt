cmake_minimum_required(VERSION 3.20)
project(lro_runtime_v2 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# 编译库目标（严格按示例思路）
add_library(lro_runtime
    src/lro/executors.cpp
    src/lro/state_store_mem.cpp
    src/lro/runner.cpp
)
target_include_directories(lro_runtime PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_compile_features(lro_runtime PUBLIC cxx_std_17)

# 兼容旧有头文件引用：保留别名目标，便于 VA 渐进迁移
add_library(lro_header_only INTERFACE)
add_library(lro::lro ALIAS lro_header_only)
target_include_directories(lro_header_only INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
target_compile_features(lro_header_only INTERFACE cxx_std_17)

# 可选依赖：JSON（示例中查找 nlohmann/json.hpp）
find_path(JSON_INCLUDE_DIR nlohmann/json.hpp)
if (JSON_INCLUDE_DIR)
  target_include_directories(lro_runtime PUBLIC ${JSON_INCLUDE_DIR})
endif()

# gRPC/Protobuf 示例（可选，若不存在则跳过）
find_package(Protobuf QUIET)
find_package(gRPC QUIET)
if (Protobuf_FOUND AND gRPC_FOUND)
  message(STATUS "Found gRPC and Protobuf, adapters can be enabled later")
endif()
