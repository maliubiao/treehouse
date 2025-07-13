from typing import Any, Dict, List, Optional

import lldb

from .structs import LibcStructs


class ABI:
    """
    Provides a generic interface for handling Application Binary Interface (ABI)
    details, such as argument passing and return value conventions.
    """

    # Maps platform identifiers to their register conventions.
    REGISTER_MAPS = {
        "arm64": {"args": [f"x{i}" for i in range(8)], "return": "x0", "lr": "lr"},
        "x86_64": {
            "args": ["rdi", "rsi", "rdx", "rcx", "r8", "r9"],
            "return": "rax",
            "lr": "rip",  # On x86_64, the return address is on the stack, pointed to by rsp.
        },
    }

    @staticmethod
    def get_platform_abi(target: lldb.SBTarget) -> str:
        """Determines the platform ABI from the target's triple."""
        triple = target.GetTriple()
        if "arm64" in triple or "aarch64" in triple:
            return "arm64"
        if "x86_64" in triple:
            return "x86_64"
        return "unknown"

    @staticmethod
    def get_function_args(frame: lldb.SBFrame, abi_type: str, count: int = 4) -> Dict[str, int]:
        """
        Retrieves the first `count` function arguments from registers
        based on the platform ABI.
        """
        args = {}
        reg_map = ABI.REGISTER_MAPS.get(abi_type)
        if not reg_map:
            return args

        for i in range(min(count, len(reg_map["args"]))):
            reg_name = reg_map["args"][i]
            reg_val = frame.FindRegister(reg_name)
            if reg_val.IsValid():
                args[reg_name] = reg_val.GetValueAsUnsigned()
        return args

    @staticmethod
    def get_return_value(frame: lldb.SBFrame, abi_type: str) -> int:
        """Retrieves the return value from the appropriate register."""
        reg_map = ABI.REGISTER_MAPS.get(abi_type)
        if reg_map:
            reg = frame.FindRegister(reg_map["return"])
            if reg.IsValid():
                return reg.GetValueAsUnsigned()
        return 0

    @staticmethod
    def get_lr_register(frame: lldb.SBFrame, abi_type: str) -> Optional[int]:
        """
        Retrieves the link register (return address) value.
        Note: This is straightforward on ARM but more complex on x86.
        """
        reg_map = ABI.REGISTER_MAPS.get(abi_type)
        if not reg_map:
            return None

        # On ARM64, the return address is in the LR register before the call.
        if abi_type == "arm64":
            lr_reg = frame.FindRegister(reg_map["lr"])
            return lr_reg.GetValueAsUnsigned() if lr_reg.IsValid() else None

        # On x86_64, the return address is the value at the top of the stack.
        if abi_type == "x86_64":
            rsp = frame.FindRegister("rsp")
            if rsp.IsValid():
                error = lldb.SBError()
                # The return address is an 8-byte value on a 64-bit system.
                ret_addr = frame.GetThread().GetProcess().ReadPointerFromMemory(rsp.GetValueAsUnsigned(), error)
                if error.Success():
                    return ret_addr
        return None


class LibcArgParser:
    """
    Parses arguments for specific libc functions based on their raw values.
    This class encapsulates the logic for interpreting arguments for various
    libc calls, such as resolving string pointers or formatting structs.
    """

    MAX_STRING_LEN = 256
    MAX_BUF_PREVIEW = 16

    def __init__(self, arg_regs: List[str], struct_parser: LibcStructs, process: lldb.SBProcess):
        self.arg_regs = arg_regs
        self.struct_parser = struct_parser
        self.process = process
        # A dispatch table for custom argument parsers.
        self.parser_map = {
            "open": self._parse_open_args,
            "read": self._parse_read_write_args,
            "write": self._parse_read_write_args,
            "stat": self._parse_stat_args,
            "fstat": self._parse_fstat_args,
            "close": lambda a: [f"fd={self._get_arg(0, a)}"],
            "malloc": lambda a: [f"size={self._get_arg(0, a)}"],
            "free": lambda a: [f"ptr=0x{self._get_arg(0, a):x}"],
            "fork": lambda a: [],
            "execve": self._parse_execve_args,
            "waitpid": self._parse_waitpid_args,
            "kill": self._parse_kill_args,
            "pipe": lambda a: [f"pipefd=0x{self._get_arg(0, a):x}"],
            "dup2": lambda a: [f"oldfd={self._get_arg(0, a)}", f"newfd={self._get_arg(1, a)}"],
            "getpid": lambda a: [],
            "getppid": lambda a: [],
            "exit": lambda a: [f"status={self._get_arg(0, a)}"],
            "creat": self._parse_creat_args,
            "lseek": self._parse_lseek_args,
            "unlink": self._parse_unlink_args,
            "rename": self._parse_rename_args,
            "mkdir": self._parse_mkdir_args,
        }

    def parse(self, func_name: str, args: Dict[str, int]) -> List[str]:
        """
        Parses the arguments of a known libc function into a human-readable list.
        """
        parser = self.parser_map.get(func_name)
        return parser(args) if parser else self._default_parse(args)

    def _get_arg(self, index: int, args: Dict[str, int]) -> int:
        """Safely gets the nth argument value from the args dictionary."""
        if index < len(self.arg_regs):
            return args.get(self.arg_regs[index], 0)
        return 0

    def _default_parse(self, args: Dict[str, int]) -> List[str]:
        """Default parser: just show register names and hex values."""
        return [f"{reg}=0x{val:x}" for reg, val in args.items()]

    def _read_string(self, addr: int) -> str:
        """Reads a null-terminated string from memory."""
        if addr == 0:
            return "<nullptr>"
        error = lldb.SBError()
        mem = self.process.ReadMemory(addr, self.MAX_STRING_LEN, error)
        if error.Fail():
            return f"<invalid_addr:0x{addr:x}>"

        try:
            # Find the null terminator and decode.
            null_pos = mem.find(b"\x00")
            if null_pos != -1:
                return mem[:null_pos].decode("utf-8", "replace")
            return mem.decode("utf-8", "replace") + "..."
        except UnicodeDecodeError:
            return mem.hex()

    def _preview_buffer(self, addr: int, size: int) -> str:
        """Reads a small part of a buffer and returns a hex preview."""
        if addr == 0 or size <= 0:
            return ""
        error = lldb.SBError()
        mem = self.process.ReadMemory(addr, size, error)
        if error.Fail():
            return "<read_error>"
        return mem.hex()

    def _parse_open_args(self, args: Dict[str, int]) -> List[str]:
        path = self._read_string(self._get_arg(0, args))
        flags = self._get_arg(1, args)
        mode = self._get_arg(2, args)
        return [f'path="{path}"', f"flags=0x{flags:x}", f"mode=0o{mode:o}"]

    def _parse_creat_args(self, args: Dict[str, int]) -> List[str]:
        path = self._read_string(self._get_arg(0, args))
        mode = self._get_arg(1, args)
        return [f'path="{path}"', f"mode=0o{mode:o}"]

    def _parse_read_write_args(self, args: Dict[str, int]) -> List[str]:
        fd = self._get_arg(0, args)
        buf_addr = self._get_arg(1, args)
        count = self._get_arg(2, args)
        buf_preview = self._preview_buffer(buf_addr, min(count, self.MAX_BUF_PREVIEW))
        return [f"fd={fd}", f"buf=0x{buf_addr:x} [{buf_preview}]", f"count={count}"]

    def _parse_lseek_args(self, args: Dict[str, int]) -> List[str]:
        fd = self._get_arg(0, args)
        offset = self._get_arg(1, args)
        whence = self._get_arg(2, args)
        return [f"fd={fd}", f"offset={offset}", f"whence={whence}"]

    def _parse_stat_args(self, args: Dict[str, int]) -> List[str]:
        path = self._read_string(self._get_arg(0, args))
        buf_addr = self._get_arg(1, args)
        stat_info = self.struct_parser.get_struct("stat", buf_addr, self.process)
        return [f'path="{path}"', f"stat_buf={stat_info or f'0x{buf_addr:x}'}"]

    def _parse_fstat_args(self, args: Dict[str, int]) -> List[str]:
        fd = self._get_arg(0, args)
        buf_addr = self._get_arg(1, args)
        stat_info = self.struct_parser.get_struct("stat", buf_addr, self.process)
        return [f"fd={fd}", f"stat_buf={stat_info or f'0x{buf_addr:x}'}"]

    def _parse_unlink_args(self, args: Dict[str, int]) -> List[str]:
        path = self._read_string(self._get_arg(0, args))
        return [f'path="{path}"']

    def _parse_rename_args(self, args: Dict[str, int]) -> List[str]:
        old_path = self._read_string(self._get_arg(0, args))
        new_path = self._read_string(self._get_arg(1, args))
        return [f'old="{old_path}"', f'new="{new_path}"']

    def _parse_mkdir_args(self, args: Dict[str, int]) -> List[str]:
        path = self._read_string(self._get_arg(0, args))
        mode = self._get_arg(1, args)
        return [f'path="{path}"', f"mode=0o{mode:o}"]

    def _parse_execve_args(self, args: Dict[str, int]) -> List[str]:
        path = self._read_string(self._get_arg(0, args))
        argv = self._get_arg(1, args)
        envp = self._get_arg(2, args)
        return [f'path="{path}"', f"argv=0x{argv:x}", f"envp=0x{envp:x}"]

    def _parse_waitpid_args(self, args: Dict[str, int]) -> List[str]:
        pid = self._get_arg(0, args)
        status = self._get_arg(1, args)
        options = self._get_arg(2, args)
        return [f"pid={pid}", f"status=0x{status:x}", f"options=0x{options:x}"]

    def _parse_kill_args(self, args: Dict[str, int]) -> List[str]:
        pid = self._get_arg(0, args)
        sig = self._get_arg(1, args)
        return [f"pid={pid}", f"sig={sig}"]


class LibcABI(ABI):
    """
    Extends the generic ABI handler with specific parsing logic for common
    libc function arguments (e.g., resolving string pointers).
    """

    def __init__(self, target: lldb.SBTarget):
        super().__init__()
        self.struct_parser = LibcStructs(target)
        self.abi_type = self.get_platform_abi(target)
        self.arg_regs = self.REGISTER_MAPS.get(self.abi_type, {}).get("args", [])

    def parse_args(self, func_name: str, args: Dict[str, int], process: lldb.SBProcess) -> List[str]:
        """
        Parses the arguments of a known libc function into a human-readable list
        by delegating to a specialized parser.
        """
        parser = LibcArgParser(self.arg_regs, self.struct_parser, process)
        return parser.parse(func_name, args)
