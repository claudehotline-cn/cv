cmake_minimum_required(VERSION 3.16)
project(VideoSourceManager)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(MSVC)
    add_compile_options(/W4 /utf-8)
else()
    add_compile_options(-Wall -Wextra -pedantic)
endif()

# vcpkg toolchain (optional)
if (EXISTS "D:/Projects/vcpkg/scripts/buildsystems/vcpkg.cmake")
    set(CMAKE_TOOLCHAIN_FILE "D:/Projects/vcpkg/scripts/buildsystems/vcpkg.cmake")
endif()

# OpenCV (optional, used by RTSP reader stub via VideoCapture)
find_package(OpenCV QUIET)


set(SRC
    src/main.cpp
    src/app/config.cpp
    src/app/source_agent.cc
    src/app/controller/source_controller.cc
    src/app/rpc/grpc_server.cc
    src/app/metrics/metrics_exporter.cc
    src/app/rest/rest_server.cc)
if (OpenCV_FOUND)
    list(APPEND SRC src/adapters/inputs/ffmpeg_rtsp_reader.cc)
    target_compile_definitions(${PROJECT_NAME} PRIVATE VSM_WITH_OPENCV=1)
else()
    message(WARNING "OpenCV not found; building VSM without RTSP reader (ffmpeg_rtsp_reader)")
endif()
set(HDR
    src/app/config.hpp
    src/app/source_agent.h
    src/app/controller/source_controller.h
    src/app/rpc/grpc_server.h
    src/app/metrics/metrics_exporter.h
    src/app/rest/rest_server.h
    src/adapters/inputs/ffmpeg_rtsp_reader.h
    src/adapters/outputs/to_analyzer_link.h)

add_executable(${PROJECT_NAME} ${SRC} ${HDR})
target_include_directories(${PROJECT_NAME} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)

# gRPC / Protobuf (REQUIRED)
# VSM 必须提供 gRPC 能力；如未找到依赖，直接中止配置
find_package(Protobuf CONFIG QUIET)
if (NOT Protobuf_FOUND)
    find_package(Protobuf REQUIRED)
endif()
find_package(gRPC CONFIG QUIET)
if (NOT gRPC_FOUND)
    find_package(PkgConfig REQUIRED)
    pkg_check_modules(GRPCPP REQUIRED grpc++)
    set(gRPC_FOUND TRUE)
    set(GRPC_INCLUDE_DIRS ${GRPCPP_INCLUDE_DIRS})
    set(GRPC_LIBRARIES ${GRPCPP_LIBRARIES})
endif()
add_definitions(-DUSE_GRPC)
set(_PROTO_DIR ${CMAKE_CURRENT_SOURCE_DIR}/proto)
set(_GEN_DIR ${CMAKE_BINARY_DIR}/generated)
file(MAKE_DIRECTORY ${_GEN_DIR})
set(pb_cc  ${_GEN_DIR}/source_control.pb.cc)
set(pb_h   ${_GEN_DIR}/source_control.pb.h)
set(grpc_cc ${_GEN_DIR}/source_control.grpc.pb.cc)
set(grpc_h  ${_GEN_DIR}/source_control.grpc.pb.h)
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
add_custom_command(OUTPUT ${pb_cc} ${pb_h}
    COMMAND ${_PROTOC_EXE} ARGS --cpp_out ${_GEN_DIR} -I ${_PROTO_DIR} ${_PROTO_DIR}/source_control.proto
    DEPENDS ${_PROTO_DIR}/source_control.proto)
add_custom_command(OUTPUT ${grpc_cc} ${grpc_h}
    COMMAND ${_PROTOC_EXE} ARGS --grpc_out ${_GEN_DIR} --plugin=protoc-gen-grpc=${_GRPC_CPP_PLUGIN} -I ${_PROTO_DIR} ${_PROTO_DIR}/source_control.proto
    DEPENDS ${_PROTO_DIR}/source_control.proto)
add_library(vsm_source_control_proto ${pb_cc} ${grpc_cc})
target_include_directories(vsm_source_control_proto PUBLIC ${_GEN_DIR})
# Ensure protobuf headers from vcpkg are preferred to avoid version mismatch
if (EXISTS "D:/Projects/vcpkg/installed/x64-windows/include")
    target_include_directories(vsm_source_control_proto PUBLIC "D:/Projects/vcpkg/installed/x64-windows/include")
    target_include_directories(${PROJECT_NAME} PRIVATE "D:/Projects/vcpkg/installed/x64-windows/include")
endif()
if (TARGET protobuf::libprotobuf)
  if (TARGET gRPC::grpc++)
    target_link_libraries(vsm_source_control_proto PUBLIC gRPC::grpc++ protobuf::libprotobuf)
  else()
    if (DEFINED GRPC_INCLUDE_DIRS)
      target_include_directories(vsm_source_control_proto PUBLIC ${GRPC_INCLUDE_DIRS})
    endif()
    target_link_libraries(vsm_source_control_proto PUBLIC ${GRPC_LIBRARIES} protobuf::libprotobuf)
  endif()
else()
  if (TARGET gRPC::grpc++)
    target_link_libraries(vsm_source_control_proto PUBLIC gRPC::grpc++ ${Protobuf_LIBRARIES})
    if (DEFINED Protobuf_INCLUDE_DIRS)
      target_include_directories(vsm_source_control_proto PUBLIC ${Protobuf_INCLUDE_DIRS})
    endif()
  else()
    if (DEFINED Protobuf_INCLUDE_DIRS)
      target_include_directories(vsm_source_control_proto PUBLIC ${Protobuf_INCLUDE_DIRS})
    endif()
    if (DEFINED GRPC_INCLUDE_DIRS)
      target_include_directories(vsm_source_control_proto PUBLIC ${GRPC_INCLUDE_DIRS})
    endif()
    target_link_libraries(vsm_source_control_proto PUBLIC ${GRPC_LIBRARIES} ${Protobuf_LIBRARIES})
  endif()
endif()
target_include_directories(${PROJECT_NAME} PRIVATE ${_GEN_DIR})
target_link_libraries(${PROJECT_NAME} PRIVATE vsm_source_control_proto)

# Add VA AnalyzerControl proto for gRPC client calls from VSM (attach_apply via gRPC)
set(VA_PROTO_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../video-analyzer/proto")
set(va_pb_cc  ${_GEN_DIR}/analyzer_control.pb.cc)
set(va_pb_h   ${_GEN_DIR}/analyzer_control.pb.h)
set(va_grpc_cc ${_GEN_DIR}/analyzer_control.grpc.pb.cc)
set(va_grpc_h  ${_GEN_DIR}/analyzer_control.grpc.pb.h)
if (EXISTS "${VA_PROTO_DIR}/analyzer_control.proto")
  add_custom_command(OUTPUT ${va_pb_cc} ${va_pb_h}
      COMMAND ${_PROTOC_EXE} ARGS --cpp_out ${_GEN_DIR} -I ${VA_PROTO_DIR} ${VA_PROTO_DIR}/analyzer_control.proto
      DEPENDS ${VA_PROTO_DIR}/analyzer_control.proto)
  add_custom_command(OUTPUT ${va_grpc_cc} ${va_grpc_h}
      COMMAND ${_PROTOC_EXE} ARGS --grpc_out ${_GEN_DIR} --plugin=protoc-gen-grpc=${_GRPC_CPP_PLUGIN} -I ${VA_PROTO_DIR} ${VA_PROTO_DIR}/analyzer_control.proto
      DEPENDS ${VA_PROTO_DIR}/analyzer_control.proto)
  add_library(va_analyzer_control_proto ${va_pb_cc} ${va_grpc_cc})
  target_include_directories(va_analyzer_control_proto PUBLIC ${_GEN_DIR})
  if (TARGET protobuf::libprotobuf)
    if (TARGET gRPC::grpc++)
      target_link_libraries(va_analyzer_control_proto PUBLIC gRPC::grpc++ protobuf::libprotobuf)
    else()
      if (DEFINED GRPC_INCLUDE_DIRS)
        target_include_directories(va_analyzer_control_proto PUBLIC ${GRPC_INCLUDE_DIRS})
      endif()
      target_link_libraries(va_analyzer_control_proto PUBLIC ${GRPC_LIBRARIES} protobuf::libprotobuf)
    endif()
  else()
    if (TARGET gRPC::grpc++)
      target_link_libraries(va_analyzer_control_proto PUBLIC gRPC::grpc++ ${Protobuf_LIBRARIES})
      if (DEFINED Protobuf_INCLUDE_DIRS)
        target_include_directories(va_analyzer_control_proto PUBLIC ${Protobuf_INCLUDE_DIRS})
      endif()
    else()
      if (DEFINED Protobuf_INCLUDE_DIRS)
        target_include_directories(va_analyzer_control_proto PUBLIC ${Protobuf_INCLUDE_DIRS})
      endif()
      if (DEFINED GRPC_INCLUDE_DIRS)
        target_include_directories(va_analyzer_control_proto PUBLIC ${GRPC_INCLUDE_DIRS})
      endif()
        target_link_libraries(va_analyzer_control_proto PUBLIC ${GRPC_LIBRARIES} ${Protobuf_LIBRARIES})
    endif()
  endif()
  target_link_libraries(${PROJECT_NAME} PRIVATE va_analyzer_control_proto)
endif()

if (OpenCV_FOUND)
    target_include_directories(${PROJECT_NAME} PRIVATE ${OpenCV_INCLUDE_DIRS})
    target_link_libraries(${PROJECT_NAME} PRIVATE ${OpenCV_LIBS})
endif()
if (WIN32)
    target_link_libraries(${PROJECT_NAME} PRIVATE ws2_32)
endif()

set_target_properties(${PROJECT_NAME} PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")

# Optional unified CLI (va_vsm_cli) built within video-source-manager tree
# Requires gRPC/Protobuf and accesses VA/VSM proto definitions
add_subdirectory(tools/va_vsm_cli)
