cmake_minimum_required(VERSION 3.20)
project(lro VERSION 0.1.0 LANGUAGES CXX)

option(LRO_HEADER_ONLY "Build header-only LRO library" ON)

if(LRO_HEADER_ONLY)
  add_library(lro INTERFACE)
  add_library(lro::lro ALIAS lro)
  target_include_directories(lro INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
  target_compile_features(lro INTERFACE cxx_std_17)
else()
  add_library(lro STATIC)
  add_library(lro::lro ALIAS lro)
  target_include_directories(lro PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>)
  target_compile_features(lro PUBLIC cxx_std_17)
  # TODO: add src/*.cpp when moving beyond header-only
endif()

