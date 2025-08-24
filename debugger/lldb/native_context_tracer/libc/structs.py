import logging
from typing import Any, Dict, Optional

import cffi
import lldb

logger = logging.getLogger(__name__)


class LibcStructs:
    """
    Parses and accesses common libc structures from the debugee's memory.

    This class uses two strategies for parsing:
    1. LLDB Expressions: Tries to use `frame.EvaluateExpression` first, which is
       often the most reliable method if DWARF info is good.
    2. CFFI: As a fallback, it reads raw memory and uses CFFI with predefined
       C struct layouts to parse the data. This is useful when debug info
       is missing or incomplete.
    """

    # C definitions for common libc structs.
    # These should be adjusted for the target architecture if it differs
    # significantly from a generic 64-bit Linux-like system.
    STRUCT_DEFS = {
        "stat": """
            struct stat {
                unsigned long st_dev;
                unsigned long st_ino;
                unsigned long st_nlink;
                unsigned int  st_mode;
                unsigned int  st_uid;
                unsigned int  st_gid;
                int           __pad0;
                unsigned long st_rdev;
                long          st_size;
                long          st_blksize;
                long          st_blocks;
                // timespec can be nested
                struct timespec st_atim;
                struct timespec st_mtim;
                struct timespec st_ctim;
                long          __unused[3];
            };
        """,
        "timespec": """
            struct timespec {
                long tv_sec;
                long tv_nsec;
            };
        """,
        "dirent": """
            struct dirent {
                long           d_ino;
                long           d_off;
                unsigned short d_reclen;
                unsigned char  d_type;
                char           d_name[256];
            };
        """,
    }

    def __init__(self, target: lldb.SBTarget):
        self.target = target
        self.ffi = cffi.FFI()
        self._load_all_struct_defs()

    def _load_all_struct_defs(self):
        """Loads all predefined C struct definitions into CFFI."""
        # Combine all definitions into a single block for CFFI
        full_cdef = "\n".join(self.STRUCT_DEFS.values())
        try:
            self.ffi.cdef(full_cdef)
            logger.debug("Successfully loaded all libc struct definitions into CFFI.")
        except cffi.CDefError as e:
            logger.error("Failed to load CFFI struct definitions: %s", e)

    def get_struct(self, name: str, addr: int, process: lldb.SBProcess) -> Optional[Dict[str, Any]]:
        """
        Retrieves and parses a struct from a given memory address.

        Args:
            name: The name of the struct (e.g., "stat").
            addr: The memory address where the struct resides.
            process: The lldb.SBProcess instance for memory reading.

        Returns:
            A dictionary representing the struct's fields, or None on failure.
        """
        if addr == 0:
            return None

        # Try the most reliable method first
        lldb_result = self._get_via_lldb(name, addr)
        if lldb_result:
            return lldb_result

        # Fallback to CFFI if LLDB fails
        logger.debug("LLDB expression failed for struct '%s', falling back to CFFI.", name)
        return self._get_via_cffi(name, addr, process)

    def _get_via_lldb(self, name: str, addr: int) -> Optional[Dict[str, Any]]:
        """Parses a struct using LLDB's expression evaluator."""
        # Create an expression to cast the address to a pointer of the correct struct type
        # and dereference it. This relies on the debugger having DWARF info for `struct {name}`.
        expr = f"*(struct {name}*){addr}"
        result_val = self.target.EvaluateExpression(expr)

        if not result_val.IsValid() or result_val.GetError().Fail():
            logger.debug("LLDB expression evaluation failed for '%s': %s", expr, result_val.GetError().GetCString())
            return None

        # Convert the resulting SBValue into a Python dictionary
        struct_dict = {}
        for i in range(result_val.GetNumChildren()):
            child = result_val.GetChildAtIndex(i)
            # Use GetValue() for simple types, or GetSummary() as a fallback.
            value_str = child.GetValue() or child.GetSummary() or ""
            struct_dict[child.GetName()] = value_str
        return struct_dict

    def _get_via_cffi(self, name: str, addr: int, process: lldb.SBProcess) -> Optional[Dict[str, Any]]:
        """Parses a struct using CFFI by reading raw memory."""
        if name not in self.STRUCT_DEFS:
            logger.warning("No CFFI definition found for struct '%s'.", name)
            return None

        try:
            # Determine the size of the struct from the CFFI definition
            cffi_type_name = f"struct {name}"
            size = self.ffi.sizeof(cffi_type_name)

            # Read the raw memory from the debuggee
            error = lldb.SBError()
            mem_buffer = process.ReadMemory(addr, size, error)
            if error.Fail():
                logger.error("Failed to read memory for struct '%s' at 0x%x: %s", name, addr, error.GetCString())
                return None

            # Cast the memory buffer to our CFFI struct pointer and dereference
            cdata = self.ffi.from_buffer(cffi_type_name + "*", mem_buffer)
            return self._cdata_to_dict(cdata[0])

        except (cffi.FFIError, TypeError) as e:
            logger.error("CFFI failed to parse struct '%s': %s", name, e, exc_info=True)
            return None

    def _cdata_to_dict(self, cdata) -> Dict[str, Any]:
        """Recursively converts a CFFI cdata object to a Python dictionary."""
        result = {}
        for field_name in dir(cdata):
            # Ignore internal CFFI fields
            if not field_name.startswith("_"):
                try:
                    value = getattr(cdata, field_name)
                    # If the field is another struct, recurse
                    if isinstance(value, cffi.CData) and hasattr(value, "__class__"):
                        result[field_name] = self._cdata_to_dict(value)
                    elif isinstance(value, bytes):
                        # Attempt to decode byte arrays as strings
                        result[field_name] = value.split(b"\x00", 1)[0].decode("utf-8", "replace")
                    else:
                        result[field_name] = value
                except (AttributeError, TypeError):
                    continue
        return result
