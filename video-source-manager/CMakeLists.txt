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
set(OpenCV_INCLUDE_DIRS "H:/opencv/build/include")
set(OpenCV_LIBRARY_DIRS "H:/opencv/build/x64/vc16/lib")
file(GLOB OpenCV_LIBS "${OpenCV_LIBRARY_DIRS}/*.lib")
include_directories(${OpenCV_INCLUDE_DIRS})


set(SRC
    src/main.cpp
    src/app/source_agent.cc
    src/app/controller/source_controller.cc
    src/app/rpc/grpc_server.cc
    src/app/metrics/metrics_exporter.cc
    src/app/rest/rest_server.cc
    src/adapters/inputs/ffmpeg_rtsp_reader.cc)
set(HDR
    src/app/source_agent.h
    src/app/controller/source_controller.h
    src/app/rpc/grpc_server.h
    src/app/metrics/metrics_exporter.h
    src/app/rest/rest_server.h
    src/adapters/inputs/ffmpeg_rtsp_reader.h
    src/adapters/outputs/to_analyzer_link.h)

add_executable(${PROJECT_NAME} ${SRC} ${HDR})
target_include_directories(${PROJECT_NAME} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)

# gRPC / Protobuf (optional)
option(USE_GRPC "Enable gRPC for VSM" ON)
if (USE_GRPC)
    find_package(protobuf CONFIG QUIET)
    find_package(gRPC CONFIG QUIET)
    if (Protobuf_FOUND AND gRPC_FOUND)
        add_definitions(-DUSE_GRPC)
        set(_PROTO_DIR ${CMAKE_CURRENT_SOURCE_DIR}/proto)
        set(_GEN_DIR ${CMAKE_BINARY_DIR}/generated)
        file(MAKE_DIRECTORY ${_GEN_DIR})
        set(pb_cc  ${_GEN_DIR}/source_control.pb.cc)
        set(pb_h   ${_GEN_DIR}/source_control.pb.h)
        set(grpc_cc ${_GEN_DIR}/source_control.grpc.pb.cc)
        set(grpc_h  ${_GEN_DIR}/source_control.grpc.pb.h)
        add_custom_command(OUTPUT ${pb_cc} ${pb_h}
            COMMAND protobuf::protoc ARGS --cpp_out ${_GEN_DIR} -I ${_PROTO_DIR} ${_PROTO_DIR}/source_control.proto
            DEPENDS ${_PROTO_DIR}/source_control.proto)
        add_custom_command(OUTPUT ${grpc_cc} ${grpc_h}
            COMMAND protobuf::protoc ARGS --grpc_out ${_GEN_DIR} --plugin=protoc-gen-grpc=$<TARGET_FILE:gRPC::grpc_cpp_plugin> -I ${_PROTO_DIR} ${_PROTO_DIR}/source_control.proto
            DEPENDS ${_PROTO_DIR}/source_control.proto)
        add_library(vsm_source_control_proto ${pb_cc} ${grpc_cc})
        target_include_directories(vsm_source_control_proto PUBLIC ${_GEN_DIR})
        target_link_libraries(vsm_source_control_proto PUBLIC gRPC::grpc++ protobuf::libprotobuf)
        target_include_directories(${PROJECT_NAME} PRIVATE ${_GEN_DIR})
        target_link_libraries(${PROJECT_NAME} PRIVATE vsm_source_control_proto)
    else()
        message(WARNING "gRPC/Protobuf not found; building VSM without RPC server")
    endif()
endif()

target_link_libraries(${PROJECT_NAME} PRIVATE ${OpenCV_LIBS})
if (WIN32)
    target_link_libraries(${PROJECT_NAME} PRIVATE ws2_32)
endif()

set_target_properties(${PROJECT_NAME} PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")

# Optional unified CLI (va_vsm_cli) built within video-source-manager tree
# Requires gRPC/Protobuf and accesses VA/VSM proto definitions
add_subdirectory(tools/va_vsm_cli)
