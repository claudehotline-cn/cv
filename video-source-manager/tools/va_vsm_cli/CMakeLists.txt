cmake_minimum_required(VERSION 3.16)
project(vsm_va_vsm_cli)

if (NOT USE_GRPC)
    message(STATUS "VSM: USE_GRPC=OFF, skip va_vsm_cli")
    return()
endif()

find_package(protobuf CONFIG QUIET)
find_package(gRPC CONFIG QUIET)
if (NOT Protobuf_FOUND OR NOT gRPC_FOUND)
    message(WARNING "VSM: gRPC/Protobuf not found; skip va_vsm_cli")
    return()
endif()

set(REPO_ROOT ${CMAKE_SOURCE_DIR}/..)
get_filename_component(REPO_ROOT ${REPO_ROOT} ABSOLUTE)

set(_VA_PROTO_DIR ${REPO_ROOT}/video-analyzer/proto)
set(_VSM_PROTO_DIR ${CMAKE_SOURCE_DIR}/proto)
set(_GEN_DIR ${CMAKE_BINARY_DIR}/generated-cli)
file(MAKE_DIRECTORY ${_GEN_DIR})

set(PROTO_LIST
    ${_VA_PROTO_DIR}/analyzer_control.proto
    ${_VA_PROTO_DIR}/pipeline.proto
    ${_VSM_PROTO_DIR}/source_control.proto)

set(GEN_SRCS)
set(GEN_HDRS)
foreach(proto ${PROTO_LIST})
    get_filename_component(fname ${proto} NAME_WE)
    set(pb_cc  ${_GEN_DIR}/${fname}.pb.cc)
    set(pb_h   ${_GEN_DIR}/${fname}.pb.h)
    list(APPEND GEN_SRCS ${pb_cc})
    list(APPEND GEN_HDRS ${pb_h})
    add_custom_command(
        OUTPUT ${pb_cc} ${pb_h}
        COMMAND protobuf::protoc
        ARGS --cpp_out ${_GEN_DIR}
             -I ${_VA_PROTO_DIR}
             -I ${_VSM_PROTO_DIR}
             ${proto}
        DEPENDS ${proto}
    )
endforeach()

add_custom_command(
    OUTPUT ${_GEN_DIR}/analyzer_control.grpc.pb.cc ${_GEN_DIR}/analyzer_control.grpc.pb.h
    COMMAND protobuf::protoc
    ARGS --grpc_out ${_GEN_DIR}
         --plugin=protoc-gen-grpc=$<TARGET_FILE:gRPC::grpc_cpp_plugin>
         -I ${_VA_PROTO_DIR}
         ${_VA_PROTO_DIR}/analyzer_control.proto
    DEPENDS ${_VA_PROTO_DIR}/analyzer_control.proto)

add_custom_command(
    OUTPUT ${_GEN_DIR}/source_control.grpc.pb.cc ${_GEN_DIR}/source_control.grpc.pb.h
    COMMAND protobuf::protoc
    ARGS --grpc_out ${_GEN_DIR}
         --plugin=protoc-gen-grpc=$<TARGET_FILE:gRPC::grpc_cpp_plugin>
         -I ${_VSM_PROTO_DIR}
         ${_VSM_PROTO_DIR}/source_control.proto
    DEPENDS ${_VSM_PROTO_DIR}/source_control.proto)

add_executable(va_vsm_cli
    ${GEN_SRCS}
    ${_GEN_DIR}/analyzer_control.grpc.pb.cc
    ${_GEN_DIR}/source_control.grpc.pb.cc
    main.cpp)

target_include_directories(va_vsm_cli PRIVATE ${_GEN_DIR})
# Prefer vcpkg protobuf headers to avoid mismatch with other environments
if (EXISTS "D:/Projects/vcpkg/installed/x64-windows/include")
    target_include_directories(va_vsm_cli PRIVATE "D:/Projects/vcpkg/installed/x64-windows/include")
endif()
target_link_libraries(va_vsm_cli PRIVATE gRPC::grpc++ protobuf::libprotobuf)

set_target_properties(va_vsm_cli PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
