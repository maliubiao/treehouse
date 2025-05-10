cmake_minimum_required(VERSION 3.10)
project(basic_program)

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

# Shared functions static library
add_library(basic_lib STATIC basic_lib.c)
target_include_directories(basic_lib PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_definitions(basic_lib PRIVATE $<$<CONFIG:Debug>:DEBUG=1>)

# Main executable
add_executable(basic_program basic_main.c)
target_link_libraries(basic_program basic_lib so1 so2 dl)
set_target_properties(basic_program PROPERTIES
    ENABLE_EXPORTS ON
    LINK_DEPENDS_NO_SHARED ON
)
target_compile_definitions(basic_program PRIVATE $<$<CONFIG:Debug>:DEBUG=1>)

# SO1 shared library
add_library(so1 SHARED so1/basic_so1.c)
target_include_directories(so1 PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/so1)
target_link_libraries(so1 PRIVATE so2)
set_target_properties(so1 PROPERTIES
    C_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN ON
)
target_compile_definitions(so1 PRIVATE $<$<CONFIG:Debug>:DEBUG=1>)

# SO2 shared library
add_library(so2 SHARED so2/basic_so2.c)
target_include_directories(so2 PUBLIC 
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/so2
)
target_link_libraries(so2 basic_lib)
set_target_properties(so2 PROPERTIES
    C_VISIBILITY_PRESET default
    VISIBILITY_INLINES_HIDDEN OFF
)
target_compile_definitions(so2 PRIVATE $<$<CONFIG:Debug>:DEBUG=1>)

# OP parser executable
add_executable(op_parser op_parser.c)
target_link_libraries(op_parser basic_lib)
target_compile_definitions(op_parser PRIVATE $<$<CONFIG:Debug>:DEBUG=1>)