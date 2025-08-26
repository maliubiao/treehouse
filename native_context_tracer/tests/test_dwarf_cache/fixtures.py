"""
Test fixtures for DWARF cache tests
"""

import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import List, Optional
from unittest.mock import MagicMock, Mock

import lldb

# Add the project root to the Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from native_context_tracer.dwarf_cache import CacheMetadata, LineEntryData


@dataclass
class MockCompileUnit:
    """Mock SBCompileUnit for testing"""

    file_path: str
    uuid: str = "test-uuid-12345"
    num_entries: int = 100
    directory: str = "/test/src"
    filename: str = "test.cpp"

    def GetFileSpec(self):
        spec = Mock()
        spec.GetDirectory.return_value = self.directory
        spec.GetFilename.return_value = self.filename
        spec.fullpath = self.file_path
        return spec

    def GetModule(self):
        module = Mock()
        module.GetUUIDString.return_value = self.uuid
        module.GetFileSpec.return_value = self.GetFileSpec()
        return module

    def GetNumLineEntries(self):
        return self.num_entries


@dataclass
class MockLineEntry:
    """Mock SBLineEntry for testing"""

    file: str
    line: int
    column: int
    start_addr: int = 0x1000
    end_addr: int = 0x1004

    def GetFileSpec(self):
        spec = Mock()
        spec.fullpath = self.file
        return spec

    def GetLine(self):
        return self.line

    def GetColumn(self):
        return self.column

    def GetStartAddress(self):
        addr = Mock()
        addr.IsValid.return_value = True
        addr.GetLoadAddress.return_value = self.start_addr
        return addr

    def GetEndAddress(self):
        addr = Mock()
        addr.IsValid.return_value = True
        addr.GetLoadAddress.return_value = self.end_addr
        return addr

    def IsValid(self):
        return True


def create_mock_line_entries(count: int, start_line: int = 1) -> List[MockLineEntry]:
    """Create a list of mock line entries for testing"""
    entries = []
    for i in range(count):
        entries.append(
            MockLineEntry(
                file="/test/src/test.cpp",
                line=start_line + i,
                column=1,
                start_addr=0x1000 + i * 4,
                end_addr=0x1004 + i * 4,
            )
        )
    return entries


def create_test_file_with_content(temp_dir: str, filename: str, content: str) -> str:
    """Create a test file with specified content"""
    file_path = os.path.join(temp_dir, filename)
    with open(file_path, "w") as f:
        f.write(content)
    return file_path


class TempDirectory:
    """Context manager for temporary directories"""

    def __init__(self):
        self.temp_dir = None

    def __enter__(self):
        self.temp_dir = tempfile.mkdtemp(prefix="dwarf_cache_test_")
        return self.temp_dir

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
