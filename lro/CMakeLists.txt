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
# Build-tree alias to match installed namespace usage
add_library(lro::lro_runtime ALIAS lro_runtime)
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

# Install & Export (find_package support)
include(CMakePackageConfigHelpers)
set(LRO_INSTALL_CMAKEDIR "lib/cmake/lro")

install(TARGETS lro_runtime
    EXPORT lroTargets
    ARCHIVE DESTINATION lib
    LIBRARY DESTINATION lib
    RUNTIME DESTINATION bin)
install(DIRECTORY include/ DESTINATION include)

export(EXPORT lroTargets NAMESPACE lro:: FILE ${CMAKE_CURRENT_BINARY_DIR}/lroTargets.cmake)
configure_package_config_file(
    ${CMAKE_CURRENT_SOURCE_DIR}/lroConfig.cmake.in
    ${CMAKE_CURRENT_BINARY_DIR}/lroConfig.cmake
    INSTALL_DESTINATION ${LRO_INSTALL_CMAKEDIR}
)
# Provide version file for find_package(lro VERSION ...)
write_basic_package_version_file(
    ${CMAKE_CURRENT_BINARY_DIR}/lroConfigVersion.cmake
    VERSION 1.0.0
    COMPATIBILITY SameMajorVersion)
install(EXPORT lroTargets NAMESPACE lro:: DESTINATION ${LRO_INSTALL_CMAKEDIR})
install(FILES
    ${CMAKE_CURRENT_BINARY_DIR}/lroConfig.cmake
    ${CMAKE_CURRENT_BINARY_DIR}/lroConfigVersion.cmake
    DESTINATION ${LRO_INSTALL_CMAKEDIR})

# Tests (not built by default; target exists for manual build)
add_subdirectory(tests)

# ---- Examples ----
# REST example (mock router, no real HTTP framework dependency)
add_executable(example_rest
  examples/rest_server/main.cpp
  adapters/rest_simplehttpserver/routes.cpp)
target_include_directories(example_rest PRIVATE adapters/rest_simplehttpserver)
target_link_libraries(example_rest PRIVATE lro_runtime)

# gRPC/Protobuf (optional)
find_package(Protobuf QUIET)
find_package(gRPC QUIET)
if (Protobuf_FOUND AND gRPC_FOUND)
  message(STATUS "Found gRPC and Protobuf, enabling example_grpc")
  set(PROTO_SRC_DIR ${CMAKE_CURRENT_SOURCE_DIR}/adapters/grpc)
  set(PROTO_FILE ${PROTO_SRC_DIR}/lro.proto)
  set(GENERATED_DIR ${CMAKE_CURRENT_BINARY_DIR}/generated)
  file(MAKE_DIRECTORY ${GENERATED_DIR})
  add_custom_command(
    OUTPUT ${GENERATED_DIR}/lro.pb.cc ${GENERATED_DIR}/lro.pb.h ${GENERATED_DIR}/lro.grpc.pb.cc ${GENERATED_DIR}/lro.grpc.pb.h
    COMMAND $<TARGET_FILE:protobuf::protoc>
      --grpc_out ${GENERATED_DIR}
      --cpp_out ${GENERATED_DIR}
      --plugin=protoc-gen-grpc=$<TARGET_FILE:gRPC::grpc_cpp_plugin>
      -I ${PROTO_SRC_DIR}
      ${PROTO_FILE}
    DEPENDS ${PROTO_FILE}
    VERBATIM)

  add_library(lro_grpc_objs
    ${GENERATED_DIR}/lro.pb.cc
    ${GENERATED_DIR}/lro.grpc.pb.cc
    adapters/grpc/server.cpp)
  target_compile_definitions(lro_grpc_objs PUBLIC LRO_WITH_GRPC=1)
  target_include_directories(lro_grpc_objs PUBLIC ${GENERATED_DIR} adapters/grpc include)
  target_link_libraries(lro_grpc_objs PUBLIC gRPC::grpc++ protobuf::libprotobuf lro_runtime)

  add_executable(example_grpc examples/grpc_server/main.cpp)
  target_include_directories(example_grpc PRIVATE ${GENERATED_DIR} adapters/grpc)
  target_link_libraries(example_grpc PRIVATE lro_grpc_objs)
else()
  message(STATUS "gRPC/Protobuf not found; skipping gRPC adapter build")
endif()
