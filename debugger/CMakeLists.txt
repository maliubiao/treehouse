cmake_minimum_required(VERSION 3.15)

project(terminal-llm-tracer LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Platform detection
if(CMAKE_SYSTEM_NAME STREQUAL "Darwin")
    set(PLATFORM_MACOS TRUE)
elseif(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    set(PLATFORM_LINUX TRUE)
endif()

# Compiler options
if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU" OR CMAKE_CXX_COMPILER_ID STREQUAL "Clang")
    add_compile_options(-Wall -Wextra -fno-exceptions -fno-rtti)
    add_compile_options($<$<CONFIG:RELEASE>:-O3 -flto>)
    add_compile_options($<$<CONFIG:DEBUG>:-g -fno-omit-frame-pointer>)
    set(CMAKE_INTERPROCEDURAL_OPTIMIZATION TRUE)
endif()

# Sanitizers and instrumentation
option(ENABLE_ASAN "Enable AddressSanitizer" OFF)
option(ENABLE_COVERAGE "Enable code coverage instrumentation" OFF)

if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU" OR CMAKE_CXX_COMPILER_ID STREQUAL "Clang")
    if(ENABLE_ASAN)
        add_compile_options(-fsanitize=address)
        add_link_options(-fsanitize=address)
        if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
            add_link_options(-static-libasan)
        endif()
    endif()

    if(ENABLE_COVERAGE)
        if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
            add_compile_options(--coverage)
            add_link_options(--coverage)
        elseif(CMAKE_CXX_COMPILER_ID STREQUAL "Clang")
            add_compile_options(-fprofile-instr-generate -fcoverage-mapping)
            add_link_options(-fprofile-instr-generate -fcoverage-mapping)
        endif()
    endif()
endif()

# RPATH settings
if(PLATFORM_MACOS)
    set(CMAKE_INSTALL_RPATH "@loader_path/../lib")
    set(CMAKE_BUILD_WITH_INSTALL_RPATH TRUE)
elseif(PLATFORM_LINUX)
    set(CMAKE_INSTALL_RPATH "$ORIGIN/../lib")
endif()

# Architecture detection
if(PLATFORM_MACOS AND CMAKE_OSX_ARCHITECTURES STREQUAL "arm64")
    add_compile_options(-arch arm64)
endif()

# Symbol visibility (moved after target creation)
add_compile_options(-fvisibility=hidden)

# Find dependencies with proper component specifications
find_package(Python 3.11.11 REQUIRED COMPONENTS Interpreter Development Development.Module)
#find_package(Python 3.11.11 EXACT REQUIRED COMPONENTS Interpreter Development Development.Module)

# Configure pybind11 with updated policies
cmake_policy(SET CMP0135 NEW)  # Handle FetchContent timestamp policy

# Define target library
add_library(tracer_core SHARED
    cpp/tracer_core.cpp
)

# Add target-specific definitions after target creation
target_compile_definitions(tracer_core PRIVATE TRACER_CORE_VISIBILITY)

# Link libraries with modern CMake syntax
target_link_libraries(tracer_core PRIVATE
    Python::Python
)

# Set output directory to match Python import path
set_target_properties(tracer_core PROPERTIES
    PREFIX ""
    SUFFIX ".so"
    LIBRARY_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}
)

# Documentation generation
find_package(Doxygen REQUIRED)
doxygen_add_docs(
    doc
    ${PROJECT_SOURCE_DIR}/cpp
    COMMENT "Generate API documentation"
)

# Installation rules
install(TARGETS tracer_core
    LIBRARY DESTINATION lib
    ARCHIVE DESTINATION lib
)
install(DIRECTORY ${CMAKE_SOURCE_DIR}/cpp/
    DESTINATION include
    FILES_MATCHING PATTERN "*.h")

# Version management
set(PROJECT_VERSION 1.0.0)