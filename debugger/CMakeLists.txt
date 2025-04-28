cmake_minimum_required(VERSION 3.15)

project(treehouse-tracer LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(Python_VERSION "3.11" CACHE STRING "Target Python version (3.8-3.12)")
set(Python_EXECUTABLE "" CACHE FILEPATH "Path to Python executable")
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
 set(CMAKE_SHARED_LINKER_FLAGS "${CMAKE_SHARED_LINKER_FLAGS} -Wl,-S")

# Platform detection (host and target)
if(ANDROID)
    set(PLATFORM_ANDROID TRUE)
elseif(CMAKE_SYSTEM_NAME STREQUAL "Darwin")
    set(PLATFORM_APPLE TRUE)
elseif(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    set(PLATFORM_LINUX TRUE)
elseif(CMAKE_SYSTEM_NAME STREQUAL "Windows")
    set(PLATFORM_WINDOWS TRUE)
    # Windows-specific settings
    set(CMAKE_WINDOWS_EXPORT_ALL_SYMBOLS ON)
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
endif()

message(STATUS "Host system: ${CMAKE_HOST_SYSTEM_NAME}")
message(STATUS "Target system: ${CMAKE_SYSTEM_NAME}")

# 平台定义转换
add_compile_definitions(
    $<$<BOOL:${PLATFORM_APPLE}>:PLATFORM_APPLE>
    $<$<BOOL:${PLATFORM_LINUX}>:PLATFORM_LINUX>
    $<$<BOOL:${PLATFORM_WINDOWS}>:PLATFORM_WINDOWS>
    $<$<BOOL:${PLATFORM_ANDROID}>:PLATFORM_ANDROID>
)

# 统一架构定义
if(CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64|AMD64")
    set(ARCH_X86_64 TRUE)
    set(ARCH_STRING "x86_64")
elseif(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|ARM64")
    set(ARCH_ARM64 TRUE)
    set(ARCH_STRING "arm64")
    add_compile_options(-DARM_ARCH)
else()
    execute_process(COMMAND uname -m 
        OUTPUT_VARIABLE ARCH_STRING 
        OUTPUT_STRIP_TRAILING_WHITESPACE)
    if(NOT ARCH_STRING)
        set(ARCH_STRING "unknown")
    endif()
endif()

add_compile_definitions(
    $<$<BOOL:${ARCH_X86_64}>:ARCH_X86_64>
    $<$<BOOL:${ARCH_ARM64}>:ARCH_ARM64>
    ARCH_STRING="${ARCH_STRING}"
)

# Compiler options
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    add_compile_options(-Wall -Wextra -fno-exceptions -fno-rtti )
    if(CMAKE_BUILD_TYPE STREQUAL "Release")
        add_compile_options(-O3 -flto)
    elseif(CMAKE_BUILD_TYPE STREQUAL "Debug")
        add_compile_options(-gdwarf -fno-omit-frame-pointer)
    endif()
    
    if(ARCH_X86_64)
        add_compile_options(-march=native)
    elseif(ARCH_ARM64 AND PLATFORM_APPLE)
        add_compile_options(-arch arm64)
    endif()
    
    set(CMAKE_INTERPROCEDURAL_OPTIMIZATION TRUE)
elseif(MSVC)
    add_compile_options(/W4 /EHsc /permissive- /bigobj /std:c++20)
    if(CMAKE_BUILD_TYPE STREQUAL "Debug")
        add_compile_options(/Zi /DEBUG)
    endif()
endif()

# Sanitizers and instrumentation
option(ENABLE_ASAN "Enable AddressSanitizer" OFF)
option(ENABLE_COVERAGE "Enable code coverage instrumentation" OFF)

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
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

add_compile_definitions(
    $<$<BOOL:${ENABLE_ASAN}>:ENABLE_ASAN>
   $<$<BOOL:${ENABLE_COVERAGE}>:ENABLE_COVERAGE>
)

# RPATH settings
if(PLATFORM_APPLE)
    set(CMAKE_INSTALL_RPATH "@loader_path/../lib")
    set(CMAKE_BUILD_WITH_INSTALL_RPATH TRUE)
elseif(PLATFORM_LINUX)
    set(CMAKE_INSTALL_RPATH "$ORIGIN/../lib")
endif()

# Symbol visibility (moved after target creation)
if(NOT PLATFORM_WINDOWS)
    add_compile_options(-fvisibility=hidden)
endif()

set(components Interpreter Development Development.Module)

if(Python_EXECUTABLE)
    set(Python_FIND_VIRTUALENV FIRST)
    find_package(Python ${Python_VERSION} EXACT REQUIRED COMPONENTS ${components})
else()
    find_package(Python ${Python_VERSION} REQUIRED COMPONENTS ${components})
endif()

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

# Set Python include directories
target_include_directories(tracer_core PRIVATE
    ${Python_INCLUDE_DIRS}
)

# Set output directory to match Python import path
if(PLATFORM_WINDOWS)
    set(SUFFIX ".pyd")
    # Windows-specific output naming
    set_target_properties(tracer_core PROPERTIES
        PREFIX ""
        SUFFIX ${SUFFIX}
        LIBRARY_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}
        RUNTIME_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}
    )
else()
    set(SUFFIX ".so")
    set_target_properties(tracer_core PROPERTIES
        PREFIX ""
        SUFFIX ${SUFFIX}
        LIBRARY_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}
    )
endif()

# Installation rules
if(PLATFORM_WINDOWS)
    install(TARGETS tracer_core 
        RUNTIME DESTINATION Scripts
        LIBRARY DESTINATION Scripts
        ARCHIVE DESTINATION lib
    )
else()
    install(TARGETS tracer_core
        LIBRARY DESTINATION lib
        ARCHIVE DESTINATION lib
    )
endif()

# Version management
set(PROJECT_VERSION 1.0.0)

# Windows-specific post-build steps
if(PLATFORM_WINDOWS)
    add_custom_command(TARGET tracer_core POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            $<TARGET_FILE:tracer_core>
            ${CMAKE_SOURCE_DIR}/tracer_core.pyd
        COMMENT "Copying Windows Python extension module"
    )
endif()
