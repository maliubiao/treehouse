cmake_minimum_required(VERSION 3.10)
project(op_parser)

set(CMAKE_VERBOSE_MAKEFILE ON)
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -fPIC")

# Build type configuration
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE "Debug" CACHE STRING "Choose the type of build" FORCE)
endif()

set(CMAKE_C_FLAGS_DEBUG "${CMAKE_C_FLAGS_DEBUG} -g3 -O0 -DDEBUG")
set(CMAKE_C_FLAGS_RELEASE "${CMAKE_C_FLAGS_RELEASE} -O2 -DNDEBUG")

# Enable AddressSanitizer for test target in Debug builds
if(CMAKE_BUILD_TYPE STREQUAL "Debug")
    set(CMAKE_C_FLAGS_DEBUG "${CMAKE_C_FLAGS_DEBUG} -fsanitize=address -fno-omit-frame-pointer")
endif()

# OP parser shared library for Python CFFI
add_library(op_parser_shared SHARED op_parser.c)
target_include_directories(op_parser_shared PUBLIC 
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/include
)
set_target_properties(op_parser_shared PROPERTIES
    C_VISIBILITY_PRESET default
    SOVERSION 1
    OUTPUT_NAME "op_parser"
)
target_compile_definitions(op_parser_shared PRIVATE $<$<CONFIG:Debug>:DEBUG=1>)

# OP parser test executable
add_executable(op_parser_test test/op_parser_main.c)
target_link_libraries(op_parser_test op_parser_shared)
target_include_directories(op_parser_test PUBLIC 
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/include
)

# Enable ASan for test executable in Debug builds
if(CMAKE_BUILD_TYPE STREQUAL "Debug")
    target_compile_options(op_parser_test PRIVATE -fsanitize=address)
    target_link_options(op_parser_test PRIVATE -fsanitize=address)
endif()