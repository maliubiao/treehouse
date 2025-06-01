from typing import Any, Dict, Optional

import cffi
import lldb


class LibcStructs:
    """处理libc结构体的解析和访问"""

    # 常见libc结构体定义 (以Linux x86_64为例)
    STRUCT_DEFS = {
        "stat": """
            typedef struct {
                unsigned long st_dev;
                unsigned long st_ino;
                unsigned long st_nlink;
                unsigned int st_mode;
                unsigned int st_uid;
                unsigned int st_gid;
                unsigned int __pad0;
                unsigned long st_rdev;
                long st_size;
                long st_blksize;
                long st_blocks;
                struct timespec st_atim;
                struct timespec st_mtim;
                struct timespec st_ctim;
                long __unused[3];
            } stat_t;
        """,
        "timespec": """
            typedef struct {
                long tv_sec;
                long tv_nsec;
            } timespec_t;
        """,
        "dirent": """
            typedef struct {
                long d_ino;
                off_t d_off;
                unsigned short d_reclen;
                unsigned char d_type;
                char d_name[256];
            } dirent_t;
        """,
    }

    def __init__(self, target: lldb.SBTarget):
        self.target = target
        self.ffi = cffi.FFI()
        self._load_struct_defs()

    def _load_struct_defs(self):
        """加载所有预定义的结构体"""
        for name, defn in self.STRUCT_DEFS.items():
            try:
                self.ffi.cdef(defn)
            except cffi.CDefError as e:
                print(f"Failed to load struct {name}: {str(e)}")

    def get_struct(self, name: str, addr: int) -> Optional[Dict[str, Any]]:
        """
        获取指定地址的结构体内容
        :param name: 结构体名称
        :param addr: 内存地址
        :return: 解析后的结构体字典或None
        """
        if not addr:
            return None

        # 优先使用LLDB表达式解析
        lldb_result = self._get_via_lldb(name, addr)
        if lldb_result is not None:
            return lldb_result

        # 回退到CFFI解析
        return self._get_via_cffi(name, addr)

    def _get_via_lldb(self, name: str, addr: int) -> Optional[Dict[str, Any]]:
        """通过LLDB表达式解析结构体"""
        expr = f"*(struct {name} *){addr}"
        result = self.target.EvaluateExpression(expr)

        if not result.IsValid() or result.GetError().Fail():
            return None

        return {
            child.GetName(): child.GetValue()
            for i in range(result.GetNumChildren())
            for child in [result.GetChildAtIndex(i)]
        }

    def _get_via_cffi(self, name: str, addr: int) -> Optional[Dict[str, Any]]:
        """通过CFFI解析结构体"""
        if name not in self.STRUCT_DEFS:
            return None

        try:
            process = self.target.GetProcess()
            struct_type = f"{name}_t"
            size = self.ffi.sizeof(struct_type)

            error = lldb.SBError()
            buf = process.ReadMemory(addr, size, error)
            if error.Fail():
                return None

            cdata = self.ffi.cast(f"{struct_type} *", addr)
            return self._cdata_to_dict(cdata)
        except (cffi.CDataError, lldb.SBError) as e:
            print(f"Failed to parse struct {name}: {str(e)}")
            return None

    def _cdata_to_dict(self, cdata) -> Dict[str, Any]:
        """将CFFI的cdata对象转换为Python字典"""
        result = {}
        for field in dir(cdata):
            if not field.startswith("_"):
                try:
                    value = getattr(cdata, field)
                    if isinstance(value, (int, float, str, bytes)):
                        result[field] = value
                    elif hasattr(value, "__class__"):
                        result[field] = self._cdata_to_dict(value)
                except (AttributeError, TypeError):
                    continue
        return result

    def add_struct_definition(self, name: str, definition: str) -> bool:
        """
        添加自定义结构体定义
        :param name: 结构体名称
        :param definition: C语言结构体定义
        :return: 是否添加成功
        """
        try:
            self.ffi.cdef(definition)
            self.STRUCT_DEFS[name] = definition
            return True
        except cffi.CDefError as e:
            print(f"Failed to add struct {name}: {str(e)}")
            return False
