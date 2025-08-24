import os
import subprocess
import sys
from pathlib import Path

from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext


class CMakeExtension(Extension):
    def __init__(self, name, source_dir="."):
        super().__init__(name, sources=[])
        self.source_dir = os.path.abspath(source_dir)


class CMakeBuild(build_ext):
    def run(self):
        try:
            out = subprocess.check_output(["cmake", "--version"])
            print(f"CMake version: {out.decode().strip()}")
        except OSError:
            raise RuntimeError("CMake must be installed to build the extensions")

        for ext in self.extensions:
            self.build_extension(ext)

    def build_extension(self, ext):
        ext_dir = os.path.abspath(os.path.dirname(self.get_ext_fullpath(ext.name)))
        cmake_args = [
            f"-DCMAKE_LIBRARY_OUTPUT_DIRECTORY={ext_dir}",
            f"-DPYTHON_EXECUTABLE={sys.executable}",
        ]

        cfg = "Debug" if self.debug else "Release"
        build_args = ["--config", cfg]

        cmake_args += [f"-DCMAKE_BUILD_TYPE={cfg}"]

        # Assuming Makefiles
        build_args += ["--", "-j2"]

        build_temp = os.path.join(self.build_temp, ext.name)
        if not os.path.exists(build_temp):
            os.makedirs(build_temp)

        # Configure and build
        subprocess.check_call(["cmake", ext.source_dir] + cmake_args, cwd=build_temp)
        subprocess.check_call(["cmake", "--build", "."] + build_args, cwd=build_temp)

        # The library is already built in the extension directory due to CMAKE_LIBRARY_OUTPUT_DIRECTORY
        # We just need to verify it exists
        lib_name = "libop_parser.so" if sys.platform != "darwin" else "libop_parser.dylib"
        lib_path = os.path.join(ext_dir, lib_name)

        if not os.path.exists(lib_path):
            raise RuntimeError(f"Library not found at {lib_path}")


# Read the contents of README.md for long description
with open("README.md", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="op-parser",
    version="0.1.0",
    author="Your Name",
    author_email="your.email@example.com",
    description="ARM instruction operand parser with C extensions",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=["op_parser"],
    package_dir={"": "src"},
    ext_modules=[CMakeExtension("op_parser", source_dir="src/op_parser")],
    cmdclass=dict(build_ext=CMakeBuild),
    zip_safe=False,
    python_requires=">=3.7",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Software Development :: Libraries",
        "Topic :: Software Development :: Disassemblers",
    ],
)
