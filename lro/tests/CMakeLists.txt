cmake_minimum_required(VERSION 3.20)

add_executable(lro_unit_tests
    test_min.cpp)
target_link_libraries(lro_unit_tests PRIVATE lro_runtime)
set_target_properties(lro_unit_tests PROPERTIES EXCLUDE_FROM_ALL TRUE)

