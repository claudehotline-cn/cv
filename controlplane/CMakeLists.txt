cmake_minimum_required(VERSION 3.20)
project(controlplane LANGUAGES CXX)

# vcpkg-integrated VS path hint for find_package
if (EXISTS "H:/Program Files/Microsoft Visual Studio/2022/Community/VC/vcpkg/installed/x64-windows")
  list(PREPEND CMAKE_PREFIX_PATH "H:/Program Files/Microsoft Visual Studio/2022/Community/VC/vcpkg/installed/x64-windows")
  if (EXISTS "H:/Program Files/Microsoft Visual Studio/2022/Community/VC/vcpkg/installed/x64-windows/share/protobuf/protobuf-config.cmake")
    set(Protobuf_DIR "H:/Program Files/Microsoft Visual Studio/2022/Community/VC/vcpkg/installed/x64-windows/share/protobuf")
  endif()
  if (EXISTS "H:/Program Files/Microsoft Visual Studio/2022/Community/VC/vcpkg/installed/x64-windows/share/grpc/gRPCConfig.cmake")
    set(gRPC_DIR "H:/Program Files/Microsoft Visual Studio/2022/Community/VC/vcpkg/installed/x64-windows/share/grpc")
  endif()
endif()
if (EXISTS "D:/Projects/vcpkg/installed/x64-windows")
  list(PREPEND CMAKE_PREFIX_PATH "D:/Projects/vcpkg/installed/x64-windows")
  if (EXISTS "D:/Projects/vcpkg/installed/x64-windows/share/protobuf/protobuf-config.cmake")
    set(Protobuf_DIR "D:/Projects/vcpkg/installed/x64-windows/share/protobuf")
  endif()
  if (EXISTS "D:/Projects/vcpkg/installed/x64-windows/share/grpc/gRPCConfig.cmake")
    set(gRPC_DIR "D:/Projects/vcpkg/installed/x64-windows/share/grpc")
  endif()
endif()

# Avoid picking up Anaconda packages
list(APPEND CMAKE_IGNORE_PREFIX_PATH "H:/anaconda3" "H:/anaconda3/Library")

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Protobuf CONFIG REQUIRED)
find_package(gRPC CONFIG REQUIRED)
find_package(nlohmann_json CONFIG REQUIRED)
find_package(mysql-concpp CONFIG QUIET)
if (NOT mysql-concpp_FOUND)
  find_package(unofficial-mysql-connector-cpp CONFIG QUIET)
endif()

# YAML-CPP: reuse repo-bundled if present, otherwise try system
set(YAML_LOCAL_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../third_party/yaml-cpp/yaml-cpp-0.8.0")
if (EXISTS "${YAML_LOCAL_ROOT}/CMakeLists.txt")
  set(YAML_CPP_TARGET yaml-cpp)
  add_subdirectory("${YAML_LOCAL_ROOT}" "${CMAKE_BINARY_DIR}/yaml-cpp" EXCLUDE_FROM_ALL)
else()
  find_package(yaml-cpp REQUIRED)
  set(YAML_CPP_TARGET yaml-cpp::yaml-cpp)
endif()

# Proto sources from VA/VSM projects
set(VA_PROTO_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../video-analyzer/proto")
set(VSM_PROTO_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../video-source-manager/proto")

set(GEN_DIR "${CMAKE_BINARY_DIR}/generated")
file(MAKE_DIRECTORY "${GEN_DIR}")

if (EXISTS "${VA_PROTO_DIR}/analyzer_control.proto")
  add_custom_command(
    OUTPUT "${GEN_DIR}/analyzer_control.pb.cc" "${GEN_DIR}/analyzer_control.pb.h"
    COMMAND protobuf::protoc ARGS --cpp_out "${GEN_DIR}" -I "${VA_PROTO_DIR}" "${VA_PROTO_DIR}/analyzer_control.proto"
    DEPENDS "${VA_PROTO_DIR}/analyzer_control.proto")
  add_custom_command(
    OUTPUT "${GEN_DIR}/analyzer_control.grpc.pb.cc" "${GEN_DIR}/analyzer_control.grpc.pb.h"
    COMMAND protobuf::protoc ARGS --grpc_out "${GEN_DIR}" --plugin=protoc-gen-grpc=$<TARGET_FILE:gRPC::grpc_cpp_plugin> -I "${VA_PROTO_DIR}" "${VA_PROTO_DIR}/analyzer_control.proto"
    DEPENDS "${VA_PROTO_DIR}/analyzer_control.proto")
endif()

if (EXISTS "${VSM_PROTO_DIR}/source_control.proto")
  add_custom_command(
    OUTPUT "${GEN_DIR}/source_control.pb.cc" "${GEN_DIR}/source_control.pb.h"
    COMMAND protobuf::protoc ARGS --cpp_out "${GEN_DIR}" -I "${VSM_PROTO_DIR}" "${VSM_PROTO_DIR}/source_control.proto"
    DEPENDS "${VSM_PROTO_DIR}/source_control.proto")
  add_custom_command(
    OUTPUT "${GEN_DIR}/source_control.grpc.pb.cc" "${GEN_DIR}/source_control.grpc.pb.h"
    COMMAND protobuf::protoc ARGS --grpc_out "${GEN_DIR}" --plugin=protoc-gen-grpc=$<TARGET_FILE:gRPC::grpc_cpp_plugin> -I "${VSM_PROTO_DIR}" "${VSM_PROTO_DIR}/source_control.proto"
    DEPENDS "${VSM_PROTO_DIR}/source_control.proto")
endif()

add_library(cp_proto_objs
  ${GEN_DIR}/analyzer_control.pb.cc
  ${GEN_DIR}/analyzer_control.grpc.pb.cc
  ${GEN_DIR}/source_control.pb.cc
  ${GEN_DIR}/source_control.grpc.pb.cc)
target_include_directories(cp_proto_objs PUBLIC "${GEN_DIR}")
target_link_libraries(cp_proto_objs PUBLIC protobuf::libprotobuf gRPC::grpc++ gRPC::grpc)

add_executable(controlplane
  src/server/main.cpp
  src/server/cache.cpp
  src/server/grpc_clients.cpp
  src/server/config.cpp
  src/server/http_server.cpp
  src/server/http_proxy.cpp
  src/server/db.cpp
  src/server/watch_adapter.cpp
  src/server/circuit_breaker.cpp
  src/server/metrics.cpp
  src/server/logging.cpp
  src/server/store.cpp)
target_include_directories(controlplane PRIVATE include "${GEN_DIR}")
target_link_libraries(controlplane PRIVATE ${YAML_CPP_TARGET} cp_proto_objs gRPC::grpc++ protobuf::libprotobuf nlohmann_json::nlohmann_json)
if (WIN32)
  target_link_libraries(controlplane PRIVATE odbc32)
endif()
if (mysql-concpp_FOUND)
  # Prefer official alias target exposed by wrapper
  target_link_libraries(controlplane PRIVATE mysql::concpp-xdevapi)
  target_compile_definitions(controlplane PRIVATE HAVE_MYSQLX=1)
elseif (TARGET unofficial::mysql-connector-cpp::connector)
  target_link_libraries(controlplane PRIVATE unofficial::mysql-connector-cpp::connector)
  target_compile_definitions(controlplane PRIVATE HAVE_MYSQLX=1)
endif()

# Optional: use bundled MySQL Connector/C++ (classic JDBC API) under third_party
set(MYSQL_LOCAL_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../third_party/mysql-connector-c++-9.4.0-winx64")
if (EXISTS "${MYSQL_LOCAL_ROOT}/include/mysql/jdbc.h")
  message(STATUS "Using bundled MySQL Connector/C++ classic at: ${MYSQL_LOCAL_ROOT}")
  target_include_directories(controlplane PRIVATE "${MYSQL_LOCAL_ROOT}/include" "${MYSQL_LOCAL_ROOT}/include/jdbc")
  # Link import libs (VS14 folder)
  if (EXISTS "${MYSQL_LOCAL_ROOT}/lib64/vs14/mysqlcppconn.lib")
    target_link_directories(controlplane PRIVATE "${MYSQL_LOCAL_ROOT}/lib64/vs14")
    target_link_libraries(controlplane PRIVATE mysqlcppconn libssl libcrypto)
    target_compile_definitions(controlplane PRIVATE HAVE_MYSQL_JDBC=1)
    if (WIN32)
      add_custom_command(TARGET controlplane POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different "${MYSQL_LOCAL_ROOT}/lib64/mysqlcppconn-10-vs14.dll" "$<TARGET_FILE_DIR:controlplane>"
        COMMAND ${CMAKE_COMMAND} -E copy_if_different "${MYSQL_LOCAL_ROOT}/lib64/libssl-3-x64.dll" "$<TARGET_FILE_DIR:controlplane>"
        COMMAND ${CMAKE_COMMAND} -E copy_if_different "${MYSQL_LOCAL_ROOT}/lib64/libcrypto-3-x64.dll" "$<TARGET_FILE_DIR:controlplane>"
        COMMAND ${CMAKE_COMMAND} -E copy_directory "${MYSQL_LOCAL_ROOT}/bin" "$<TARGET_FILE_DIR:controlplane>"
      )
    endif()
  endif()
endif()
if (WIN32)
  target_link_libraries(controlplane PRIVATE ws2_32)
endif()
set_target_properties(controlplane PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")

