import struct
from typing import Any, Dict, List, Optional, Set, Tuple

import lldb

from debugger.lldb.tracer.libc.structs import LibcStructs


class ABI:
    """处理不同平台的ABI调用约定"""

    # 定义各平台寄存器映射
    REGISTER_MAPS = {
        "arm64": {"args": [f"x{i}" for i in range(8)], "return": "x0", "lr": "lr"},
        "x86_64": {"args": ["rdi", "rsi", "rdx", "rcx", "r8", "r9"], "return": "rax", "lr": "rip"},
    }

    # 定义常见libc函数的寄存器需求
    FUNCTION_REGS = {
        "arm64": {
            "fopen": {"x0", "x1"},
            "open": {"x0", "x1", "x2"},
            "openat": {"x0", "x1", "x2", "x3"},
            "close": {"x0"},
            "read": {"x0", "x1", "x2"},
            "write": {"x0", "x1", "x2"},
            "stat": {"x0", "x1"},
            "fstat": {"x0", "x1"},
            "lstat": {"x0", "x1"},
            "malloc": {"x0"},
            "free": {"x0"},
            "mktemp": {"x0"},
            "tmpfile": set(),
            "sync": set(),
            "lseek": {"x0", "x1", "x2"},
            "unlink": {"x0"},
        },
        "x86_64": {
            "fopen": {"rdi", "rsi"},
            "open": {"rdi", "rsi", "rdx"},
            "openat": {"rdi", "rsi", "rdx", "rcx"},
            "close": {"rdi"},
            "read": {"rdi", "rsi", "rdx"},
            "write": {"rdi", "rsi", "rdx"},
            "stat": {"rdi", "rsi"},
            "fstat": {"rdi", "rsi"},
            "lstat": {"rdi", "rsi"},
            "malloc": {"rdi"},
            "free": {"rdi"},
            "mktemp": {"rdi"},
            "tmpfile": set(),
            "sync": set(),
            "lseek": {"rdi", "rsi", "rdx"},
            "unlink": {"rdi"},
        },
    }

    @staticmethod
    def get_platform_abi(target: lldb.SBTarget) -> str:
        """获取目标平台的ABI类型"""
        triple = target.GetTriple()
        if "arm64" in triple:
            return "arm64"
        if "x86_64" in triple:
            return "x86_64"
        return "unknown"

    @staticmethod
    def get_function_args(frame: lldb.SBFrame, abi_type: str, func_name: Optional[str] = None) -> Dict[str, int]:
        """根据ABI类型和函数名获取函数参数寄存器值"""
        args = {}
        if abi_type not in ABI.REGISTER_MAPS:
            return args

        # 获取函数需要的寄存器集合
        required_regs = ABI._get_required_registers(abi_type, func_name)

        for reg_name in required_regs:
            reg = frame.FindRegister(reg_name)
            if reg.IsValid():
                args[reg_name] = reg.unsigned

        return args

    @staticmethod
    def _get_required_registers(abi_type: str, func_name: Optional[str]) -> Set[str]:
        """获取函数需要的寄存器集合"""
        if not func_name or abi_type not in ABI.FUNCTION_REGS:
            # 默认返回所有参数寄存器
            return set(ABI.REGISTER_MAPS.get(abi_type, {}).get("args", []))

        # 返回函数特定的寄存器集合
        return ABI.FUNCTION_REGS[abi_type].get(func_name, set(ABI.REGISTER_MAPS[abi_type]["args"]))

    @staticmethod
    def get_return_value(frame: lldb.SBFrame, abi_type: str) -> int:
        """根据ABI类型获取返回值"""
        if abi_type in ABI.REGISTER_MAPS:
            reg_name = ABI.REGISTER_MAPS[abi_type]["return"]
            reg = frame.FindRegister(reg_name)
            if reg.IsValid():
                return reg.unsigned
        return 0

    @staticmethod
    def get_lr_register(frame: lldb.SBFrame, abi_type: str) -> Optional[int]:
        """获取链接寄存器(LR)值"""
        if abi_type in ABI.REGISTER_MAPS:
            reg_name = ABI.REGISTER_MAPS[abi_type]["lr"]
            lr_reg = frame.FindRegister(reg_name)
            return lr_reg.unsigned if lr_reg.IsValid() else None
        return None


class LibcABI(ABI):
    """处理libc函数的特殊参数解析"""

    MAX_STRING_LEN = 256  # 最大字符串读取长度
    MAX_BUF_PREVIEW = 32  # 最大缓冲区预览字节数

    def __init__(self, target: lldb.SBTarget):
        super().__init__()
        self.struct_parser = LibcStructs(target)

    def parse_args(self, func_name: str, args: Dict[str, int], process: lldb.SBProcess) -> List[str]:
        """解析特定libc函数的参数"""
        parser = self._get_parser(func_name)
        return parser(args, process) if parser else self._default_parse(args)

    def _get_parser(self, func_name: str):
        """获取特定函数的解析器"""
        parsers = {
            "fopen": self._parse_fopen_args,
            "open": self._parse_open_args,
            "openat": self._parse_openat_args,
            "close": self._parse_close_args,
            "fclose": self._parse_close_args,
            "read": self._parse_read_args,
            "write": self._parse_write_args,
            "stat": self._parse_stat_args,
            "fstat": self._parse_fstat_args,
            "lstat": self._parse_stat_args,
            "malloc": self._parse_malloc_args,
            "calloc": self._parse_calloc_args,
            "realloc": self._parse_realloc_args,
            "free": self._parse_malloc_args,
            "strcpy": self._parse_str_args,
            "strncpy": self._parse_str_args,
            "strcat": self._parse_str_args,
            "strncat": self._parse_str_args,
            "mkstemp": self._parse_mktemp_args,
            "tmpfile": self._parse_no_args,
            "sync": self._parse_no_args,
            "lseek": self._parse_lseek_args,
            "unlink": self._parse_unlink_args,
        }
        return parsers.get(func_name)

    def _parse_fopen_args(self, args: Dict[str, int], process: lldb.SBProcess) -> List[str]:
        """解析fopen参数"""
        path_ptr = args.get("x0", args.get("rdi", 0))
        mode_ptr = args.get("x1", args.get("rsi", 0))

        path = self._read_string_if_valid(path_ptr, process)
        mode = self._read_string_if_valid(mode_ptr, process)
        return [f'path="{path}"', f'mode="{mode}"']

    def _parse_open_args(self, args: Dict[str, int], process: lldb.SBProcess) -> List[str]:
        """解析open/openat参数"""
        path_ptr = args.get("x0", args.get("rdi", 0))
        flags = args.get("x1", args.get("rsi", 0))
        mode = args.get("x2", args.get("rdx", 0))

        path = self._read_string_if_valid(path_ptr, process)
        return [f'path="{path}"', f"flags=0x{flags:x}", f"mode=0o{mode:o}"]

    def _parse_openat_args(self, args: Dict[str, int], process: lldb.SBProcess) -> List[str]:
        """解析openat参数"""
        dfd = args.get("x0", args.get("rdi", 0))
        path_ptr = args.get("x1", args.get("rsi", 0))
        flags = args.get("x2", args.get("rdx", 0))
        mode = args.get("x3", args.get("rcx", 0))

        path = self._read_string_if_valid(path_ptr, process)
        return [f"dfd={dfd}", f'path="{path}"', f"flags=0x{flags:x}", f"mode=0o{mode:o}"]

    def _parse_close_args(self, args: Dict[str, int], process: lldb.SBProcess) -> List[str]:
        """解析close/fclose参数"""
        fd = args.get("x0", args.get("rdi", 0))
        # 添加有效性检查
        if not self._validate_fd(fd, process):
            return [f"fd={fd} (invalid)"]
        return [f"fd={fd}"]

    def _parse_read_args(self, args: Dict[str, int], process: lldb.SBProcess) -> List[str]:
        """解析read参数"""
        fd = args.get("x0", args.get("rdi", 0))
        buf = args.get("x1", args.get("rsi", 0))
        count = args.get("x2", args.get("rdx", 0))

        # 添加缓冲区预览
        preview = self._preview_buffer(buf, min(count, self.MAX_BUF_PREVIEW), process)
        return [f"fd={fd}", f"buf=0x{buf:x}{preview}", f"count={count}"]

    def _parse_write_args(self, args: Dict[str, int], process: lldb.SBProcess) -> List[str]:
        """解析write参数"""
        fd = args.get("x0", args.get("rdi", 0))
        buf = args.get("x1", args.get("rsi", 0))
        count = args.get("x2", args.get("rdx", 0))

        # 添加缓冲区预览
        preview = self._preview_buffer(buf, min(count, self.MAX_BUF_PREVIEW), process)
        return [f"fd={fd}", f"buf=0x{buf:x}{preview}", f"count={count}"]

    def _parse_stat_args(self, args: Dict[str, int], process: lldb.SBProcess) -> List[str]:
        """解析stat/lstat参数"""
        path_ptr = args.get("x0", args.get("rdi", 0))
        stat_buf = args.get("x1", args.get("rsi", 0))

        path = self._read_string_if_valid(path_ptr, process)
        stat_info = self.struct_parser.get_struct("stat", stat_buf) if stat_buf else None
        if stat_info:
            return [f'path="{path}"', f"stat_info={stat_info}"]
        return [f'path="{path}"', f"stat_buf=0x{stat_buf:x}"]

    def _parse_fstat_args(self, args: Dict[str, int], process: lldb.SBProcess) -> List[str]:
        """解析fstat参数"""
        fd = args.get("x0", args.get("rdi", 0))
        stat_buf = args.get("x1", args.get("rsi", 0))

        stat_info = self.struct_parser.get_struct("stat", stat_buf) if stat_buf else None
        if stat_info:
            return [f"fd={fd}", f"stat_info={stat_info}"]
        return [f"fd={fd}", f"stat_buf=0x{stat_buf:x}"]

    def _parse_malloc_args(self, args: Dict[str, int], _: lldb.SBProcess) -> List[str]:
        """解析malloc/free参数"""
        size = args.get("x0", args.get("rdi", 0))
        return [f"size={size}"]

    def _parse_calloc_args(self, args: Dict[str, int], _: lldb.SBProcess) -> List[str]:
        """解析calloc参数"""
        nmemb = args.get("x1", args.get("rsi", 0))
        size = args.get("x0", args.get("rdi", 0))
        return [f"nmemb={nmemb}", f"size={size}"]

    def _parse_realloc_args(self, args: Dict[str, int], _: lldb.SBProcess) -> List[str]:
        """解析realloc参数"""
        ptr = args.get("x1", args.get("rsi", 0))
        size = args.get("x0", args.get("rdi", 0))
        return [f"ptr=0x{ptr:x}", f"size={size}"]

    def _parse_str_args(self, args: Dict[str, int], process: lldb.SBProcess) -> List[str]:
        """解析字符串操作函数参数"""
        dest = args.get("x0", args.get("rdi", 0))
        src_ptr = args.get("x1", args.get("rsi", 0))

        src = self._read_string_if_valid(src_ptr, process, max_len=128)
        result = [f"dest=0x{dest:x}", f'src="{src}"']

        if "x2" in args or "rdx" in args:
            n = args.get("x2", args.get("rdx", 0))
            result.append(f"n={n}")
        return result

    def _parse_mktemp_args(self, args: Dict[str, int], process: lldb.SBProcess) -> List[str]:
        """解析mktemp参数"""
        template_ptr = args.get("x0", args.get("rdi", 0))
        template = self._read_string_if_valid(template_ptr, process)
        return [f'template="{template}"']

    def _parse_no_args(self, args: Dict[str, int], process: lldb.SBProcess) -> List[str]:
        """解析无参数函数"""
        return []

    def _parse_lseek_args(self, args: Dict[str, int], process: lldb.SBProcess) -> List[str]:
        """解析lseek参数"""
        fd = args.get("x0", args.get("rdi", 0))
        offset = args.get("x1", args.get("rsi", 0))
        whence = args.get("x2", args.get("rdx", 0))

        # 转换whence为可读字符串
        whence_map = {0: "SEEK_SET", 1: "SEEK_CUR", 2: "SEEK_END"}
        whence_str = whence_map.get(whence, f"UNKNOWN({whence})")

        return [f"fd={fd}", f"offset={offset}", f"whence={whence_str}"]

    def _parse_unlink_args(self, args: Dict[str, int], process: lldb.SBProcess) -> List[str]:
        """解析unlink参数"""
        path_ptr = args.get("x0", args.get("rdi", 0))
        path = self._read_string_if_valid(path_ptr, process)
        return [f'path="{path}"']

    def _default_parse(self, args: Dict[str, int]) -> List[str]:
        """默认参数解析"""
        return [f"{reg}=0x{val:x}" for reg, val in args.items()]

    def _read_string_if_valid(self, addr: int, process: lldb.SBProcess, max_len: int = MAX_STRING_LEN) -> str:
        """安全读取字符串，验证指针有效性"""
        if addr == 0:
            return "NULL"
        if not self._validate_pointer(addr, process):
            return f"<invalid: 0x{addr:x}>"
        return self._read_string(addr, process, max_len)

    @staticmethod
    def _read_string(addr: int, process: lldb.SBProcess, max_len: int = MAX_STRING_LEN) -> str:
        """从内存地址读取字符串"""
        error = lldb.SBError()
        buf = process.ReadMemory(addr, max_len, error)

        if error.Fail():
            return f"<error: {error.GetCString()}>"

        # 找到第一个null终止符
        null_pos = buf.find(b"\x00")
        if null_pos != -1:
            buf = buf[:null_pos]

        try:
            return buf.decode("utf-8", errors="replace")
        except UnicodeDecodeError:
            return buf.hex()

    @staticmethod
    def _preview_buffer(addr: int, size: int, process: lldb.SBProcess) -> str:
        """生成缓冲区预览字符串"""
        if addr == 0 or size <= 0:
            return ""

        try:
            error = lldb.SBError()
            buf = process.ReadMemory(addr, size, error)
            if error.Fail():
                return " <read error>"

            # 生成十六进制预览
            hex_str = buf.hex()[:16]
            if len(hex_str) >= 16:
                hex_str = hex_str[:14] + ".."

            return f" [0x{hex_str}]"
        except Exception:
            return " <preview error>"

    @staticmethod
    def _validate_pointer(addr: int, process: lldb.SBProcess) -> bool:
        """验证指针是否有效"""
        if addr == 0:
            return True  # NULL指针是有效的

        error = lldb.SBError()
        # 尝试读取1字节来验证指针
        process.ReadMemory(addr, 1, error)
        return not error.Fail()

    @staticmethod
    def _validate_fd(fd: int, process: lldb.SBProcess) -> bool:
        """验证文件描述符是否有效（简单检查）"""
        if fd < 0:
            return False
        if fd <= 2:  # 标准输入/输出/错误通常有效
            return True
        return True  # 更复杂的检查需要系统调用

    @staticmethod
    def _read_struct(addr: int, process: lldb.SBProcess, struct_format: str) -> Dict[str, Any]:
        """从内存地址读取结构体"""
        if addr == 0:
            return {"error": "NULL pointer"}

        # 计算结构体大小
        struct_size = struct.calcsize(struct_format)
        error = lldb.SBError()
        buf = process.ReadMemory(addr, struct_size, error)

        if error.Fail():
            return {"error": error.GetCString()}

        try:
            unpacked = struct.unpack(struct_format, buf)
            return dict(zip(struct_format.split()[1:], unpacked))
        except struct.error as e:
            return {"error": str(e)}
