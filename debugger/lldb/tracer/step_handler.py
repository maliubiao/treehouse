import atexit
import collections
import fnmatch
import logging
import os
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import lldb
from op_parser import OperandType, parse_disassembly_line, parse_operands

from .events import StepAction
from .utils import get_symbol_type_str

if TYPE_CHECKING:
    from .core import Tracer


class StepHandler:
    def __init__(self, tracer: "Tracer") -> None:
        self.tracer: Tracer = tracer
        self.logger: logging.Logger = tracer.logger
        self._last_source_key: Optional[str] = None
        self._max_cached_files: int = 10
        # 使用PC作为key缓存指令信息 (mnemonic, parsed_operands)
        self.instruction_info_cache: Dict[int, tuple[str, list]] = {}
        self.line_cache: Dict[str, lldb.SBLineEntry] = {}
        self.function_start_addrs = set()
        self.expression_hooks = self.tracer.config_manager.get_expression_hooks()
        self.function_range_cache = {}
        # 统一缓存格式: (symbol_name, module_path, symbol_type)
        self.addr_to_symbol_cache: Dict[int, tuple[str, str, int]] = {}
        # 添加LRU缓存用于管理断点（地址 -> 断点ID）
        self.breakpoint_lru = collections.OrderedDict()
        self.max_lru_size = 100  # 最大缓存大小
        fn = self.tracer.config_manager.get_call_trace_file()
        self.frame_count = -1
        self.base_frame_count = -1
        self.previous_line = ["", 0]  # (filepath, line_num)
        self.frame_variables = {}
        # 获取日志模式配置
        self.log_mode = self.tracer.config_manager.get_log_mode()
        # 编译单元行条目缓存
        self.compile_unit_entries_cache: Dict[str, list] = {}
        # 行条目排序缓存
        self.sorted_line_entries_cache: Dict[str, list] = {}
        # 行号到下一行条目映射缓存
        self.line_to_next_line_cache: Dict[str, Dict[int, int]] = {}

    @lru_cache(maxsize=100)
    def _get_file_lines(self, filepath: str) -> Optional[List[str]]:
        try:
            with open(filepath, "rb") as f:
                content = f.read()
                return content.decode("utf-8").splitlines()
        except (FileNotFoundError, PermissionError) as e:
            self.logger.error("Error reading file %s: %s", filepath, str(e))
            return None
        except (UnicodeDecodeError, IOError) as e:
            self.logger.error("Unexpected error reading file %s: %s", filepath, str(e))
            return None

    def _get_compile_unit_line_entries(self, compile_unit: lldb.SBCompileUnit) -> List[lldb.SBLineEntry]:
        """获取并缓存编译单元的行条目"""
        cache_key = f"{compile_unit.GetFileSpec().fullpath}-{compile_unit.GetNumLineEntries()}"
        if cache_key in self.compile_unit_entries_cache:
            return self.compile_unit_entries_cache[cache_key]

        entries = []
        for i in range(compile_unit.GetNumLineEntries()):
            entry = compile_unit.GetLineEntryAtIndex(i)
            if entry.IsValid():
                entries.append(entry)

        # 缓存结果
        self.compile_unit_entries_cache[cache_key] = entries
        return entries

    def _get_sorted_line_entries(self, frame, filepath: str) -> List[lldb.SBLineEntry]:
        """获取按行号排序的行条目"""
        if filepath in self.sorted_line_entries_cache:
            return self.sorted_line_entries_cache[filepath]

        # 获取所有编译单元的行条目并排序
        all_entries = []

        entries = self._get_compile_unit_line_entries(frame.compile_unit)
        all_entries.extend(entries)

        # 按行号排序
        sorted_entries = sorted(all_entries, key=lambda e: e.GetLine())
        self.sorted_line_entries_cache[filepath] = sorted_entries
        return sorted_entries

    def _build_line_to_next_line_cache(self, filepath: str, sorted_entries: List[lldb.SBLineEntry]) -> Dict[int, tuple]:
        """构建行号到下一行条目的映射缓存，包含下一行列信息"""
        if filepath in self.line_to_next_line_cache:
            return self.line_to_next_line_cache[filepath]

        cache = {}
        # 创建行号和列号的元组列表
        line_entries = [(entry.GetLine(), entry.GetColumn()) for entry in sorted_entries if entry.GetLine() > 0]
        line_entries.sort()  # 按行号和列号排序

        # 构建映射: 每行 -> (下一有效行号, 下一行的列号)
        for i in range(len(line_entries) - 1):
            current_line = line_entries[i][0]
            next_line = line_entries[i + 1][0]
            next_column = line_entries[i + 1][1]
            if current_line not in cache:  # 只保存第一次出现的行号映射
                cache[current_line] = (next_line, next_column)

        # 最后一行映射到自身，列号为0
        if line_entries:
            last_line = line_entries[-1][0]
            if last_line not in cache:
                cache[last_line] = (last_line, 0)

        self.line_to_next_line_cache[filepath] = cache
        return cache

    def _get_source_code_range(self, frame: lldb.SBFrame, filepath: str, start_line: int) -> str:
        """获取从起始行到下一行条目前的源代码，考虑列信息"""
        lines = self._get_file_lines(filepath)
        if not lines or start_line <= 0:
            return ""

        # 尝试获取下一行号及列号
        sorted_entries = self._get_sorted_line_entries(frame, filepath)
        line_cache = self._build_line_to_next_line_cache(filepath, sorted_entries)

        # 获取下一行信息：(行号, 列号)
        next_info = line_cache.get(start_line, (start_line, 0))
        end_line, next_column = next_info

        # 单行情况
        if start_line == end_line:
            if start_line - 1 < len(lines):
                return lines[start_line - 1].strip()
            return ""

        # 多行情况
        source_lines = []

        # 如果下一行的列号是0，不提取end_line
        if next_column == 0:
            end_line = end_line - 1

        # 提取从起始行到结束行的代码
        for line_num in range(start_line, end_line + 1):
            if line_num - 1 < len(lines):
                source_lines.append(lines[line_num - 1])

        return " ".join(source_lines).strip()

    def _is_address_in_current_function(self, frame: lldb.SBFrame, addr: int) -> bool:
        """检查地址是否在当前函数范围内（带缓存优化）"""
        if not frame.symbol:
            return False

        # 尝试从缓存获取地址范围
        if addr in self.function_range_cache:
            start_addr, end_addr = self.function_range_cache[addr]
            return start_addr <= addr < end_addr

        # 缓存未命中，计算地址范围
        start_addr = frame.symbol.GetStartAddress().GetLoadAddress(self.tracer.target)
        end_addr = frame.symbol.GetEndAddress().GetLoadAddress(self.tracer.target)

        if start_addr == lldb.LLDB_INVALID_ADDRESS or end_addr == lldb.LLDB_INVALID_ADDRESS:
            return False

        # 存入缓存
        self.function_range_cache[addr] = (start_addr, end_addr)
        return start_addr <= addr < end_addr

    def _execute_expression_hooks(self, filepath: str, line_num: int, frame: lldb.SBFrame) -> List[str]:
        """执行匹配的表达式钩子并返回结果列表"""
        expr_results = []
        for hook in self.expression_hooks:
            if filepath != hook.get("path") or hook.get("line") != line_num:
                continue
            # 获取表达式并执行
            expression = hook.get("expr")
            if expression:
                try:
                    result = frame.EvaluateExpression(expression)
                    if result.error.Success():
                        expr_results.append(f"{expression} = {result.GetValue()}")
                    else:
                        expr_results.append(f"[EXPR] {expression} failed: {result.error.GetCString()}")
                except Exception as e:
                    expr_results.append(f"[EXPR] {expression} exception: {str(e)}")
        return expr_results

    def dump_locals(self, frame: lldb.SBFrame, line: int) -> None:
        variables = frame.GetVariables(True, True, False, True)
        varaible_text = []

        for var in variables:
            if var.IsValid():
                var_name = var.GetName()
                var_value = var.GetSummary()
                if not var_value:
                    var_value = var.GetValue()
                if not var_value:
                    continue
                if var_value.startswith("0x0"):
                    try:
                        var_value = int(var_value, 16)
                        var_value = hex(var_value)
                    except ValueError:
                        pass
                if var_name in self.frame_variables and self.frame_variables[var_name] == var_value:
                    continue
                if var.GetDeclaration().line > line:
                    continue
                self.frame_variables[var_name] = var_value
                varaible_text.append(f"({var.GetType().GetName()}){var_name}={var_value}")
        return varaible_text

    def _log_source_mode(self, indent: str, source_info: str, source_line: str, debug_values: List[str]) -> None:
        """Source mode日志输出 - 只显示源代码行和变量"""
        if source_info:
            self.logger.info(
                "%s%s // %s, %s", indent, source_line, source_info, ", ".join(debug_values) if debug_values else ""
            )

    def _log_instruction_mode(
        self,
        indent: str,
        pc: int,
        first_inst_offset: int,
        mnemonic: str,
        operands: str,
        source_info: str,
        source_line: str,
        debug_values: List[str],
    ) -> None:
        """Instruction mode日志输出 - 显示完整汇编指令"""
        if source_line:
            self.logger.info(
                "%s0x%x <+%d> %s %s ; %s // %s; -> %s",
                indent,
                pc,
                first_inst_offset,
                mnemonic,
                operands,
                source_info,
                source_line,
                ", ".join(debug_values) if debug_values else "",
            )
        else:
            self.logger.info(
                "%s0x%x <+%d> %s %s ; %s; -> %s",
                indent,
                pc,
                first_inst_offset,
                mnemonic,
                operands,
                source_info,
                ", ".join(debug_values) if debug_values else "",
            )

    def on_step_hit(self, frame: lldb.SBFrame) -> StepAction:
        """Handle step events with detailed debug information."""
        pc: int = frame.GetPCAddress().GetLoadAddress(self.tracer.target)
        next_pc = frame.addr
        if pc not in self.instruction_info_cache:
            instructions: lldb.SBInstructions = frame.symbol.GetInstructions(self.tracer.target)
            self.function_start_addrs.add(frame.symbol.GetStartAddress().GetLoadAddress(self.tracer.target))
            first_inst: lldb.SBInstruction = instructions.GetInstructionAtIndex(0)
            first_inst_offset = (
                first_inst.GetAddress().GetLoadAddress(self.tracer.target) - first_inst.GetAddress().GetFileAddress()
            )
            for inst in instructions:
                mnemonic: str = inst.GetMnemonic(self.tracer.target)
                loaded_address: int = inst.GetAddress().GetFileAddress() + first_inst_offset
                operands: str = inst.GetOperands(self.tracer.target)
                self.instruction_info_cache[loaded_address] = (
                    mnemonic,
                    operands,
                    inst.size,
                    inst.GetAddress().file_addr - first_inst.GetAddress().file_addr,
                )
                # if mnemonic == "svc":
                #     self.break_at_syscall(loaded_address)
        mnemonic, operands, size, first_inst_offset = self.instruction_info_cache[pc]
        next_pc = pc + size
        parsed_operands = parse_operands(operands, max_ops=4)
        debug_values: List[str] = self._capture_register_values(frame, mnemonic, parsed_operands)
        if pc in self.line_cache:
            line_entry: lldb.SBLineEntry = self.line_cache[pc]
        else:
            line_entry: lldb.SBLineEntry = frame.GetLineEntry()
            self.line_cache[pc] = line_entry
        source_info: str = ""
        source_line: str = ""
        if pc in self.function_start_addrs:
            if frame.args:
                debug_values.append(f"args of {frame.symbol.name}")
                for arg in frame.args:
                    debug_values.append(f"{arg.name}={arg.value}")
        frames_count = frame.thread.GetNumFrames()
        if self.base_frame_count == -1:
            indent = frames_count * "  "
        else:
            indent = (frames_count - self.base_frame_count) * "  "
        has_source = line_entry.IsValid()

        if line_entry.IsValid():
            filepath: str = line_entry.GetFileSpec().fullpath
            if self.tracer.source_ranges.should_skip_source_file_by_path(filepath):
                return StepAction.SOURCE_STEP_OVER
            line_num: int = int(line_entry.GetLine())
            column: int = line_entry.GetColumn()

            # 构建源信息字符串
            if line_num > 0:
                source_info = f"{filepath}:{line_num}"
                if column > 0:
                    source_info += f":{column}"
            else:
                source_info = f"{filepath}:<no line>"

            # 执行表达式钩子并获取结果
            expr_results = self._execute_expression_hooks(filepath, line_num, frame)
            debug_values.extend(expr_results)
            # 获取源代码片段
            source_line = self._get_source_code_range(frame, filepath, line_num)
            # 只有在行号有效时才获取局部变量
            if line_num > 0:
                variables = self.dump_locals(frame, line_num)
                debug_values.extend(variables)

        current_source_key: str = f"{source_info};{source_line}"
        if hasattr(self, "_last_source_key") and current_source_key == self._last_source_key:
            source_info = ""
            source_line = ""
        self._last_source_key = current_source_key
        write_leave_later = False
        if frames_count != self.frame_count:
            self.frame_variables = {}
            if has_source:
                if frames_count > self.frame_count:
                    if source_info:
                        self.logger.info("%sENTER", indent)
                else:
                    write_leave_later = True
            self.frame_count = frames_count
        # 根据日志模式选择输出格式
        if self.log_mode == "source":
            self._log_source_mode(indent, source_info, source_line, debug_values)
        else:  # 默认使用instruction模式
            self._log_instruction_mode(
                indent, pc, first_inst_offset, mnemonic, operands, source_info, source_line, debug_values
            )
        if has_source and source_info and write_leave_later:
            self.logger.info("%sLEAVE", indent + "  ")
        return self._determine_step_action(mnemonic, parsed_operands, frame, next_pc, indent)

    def _capture_register_values(self, frame: lldb.SBFrame, mnemonic: str, parsed_operands) -> List[str]:
        """Capture register and memory values for logging"""
        registers: List[str] = []
        captured_regs = []
        if mnemonic == "ldr":
            parsed_operands = parsed_operands[1:]
        for operand in parsed_operands:
            if operand.type == OperandType.REGISTER:
                if operand.value in captured_regs:
                    continue
                captured_regs.append(operand.value)
                registers.extend(self._capture_register_value(frame, operand.value))
            elif operand.type == OperandType.MEMREF:
                memref: Dict[str, Any] = operand.value
                registers.extend(self._capture_memory_value(frame, mnemonic, memref))
        return registers

    def _capture_register_value(self, frame: lldb.SBFrame, reg_name: str) -> List[str]:
        """Capture value of a single register"""
        normalized_reg = self._normalize_register_name(reg_name)
        reg_val: lldb.SBValue = frame.FindRegister(normalized_reg)
        if not reg_val or not reg_val.IsValid():
            # self.logger.warning("Invalid register: %s", normalized_reg)
            return []

        # Check if this is an ARM64 floating-point register (v0-v31, d0-d31, s0-s31, etc)
        if normalized_reg.startswith(("v", "d", "s", "q")) and normalized_reg[1:].isdigit():
            # For vector/SIMD registers
            if normalized_reg.startswith("v"):
                try:
                    # Try to display in different formats based on available methods
                    if reg_val.GetData().GetFloat:
                        return [f"${normalized_reg}={reg_val.GetData().GetFloat():.6g}"]
                    # Fallback to hex representation
                    return [f"${normalized_reg}={reg_val.value}"]
                except Exception:
                    return [f"${normalized_reg}={reg_val.value}"]
            # For double precision floating point
            elif normalized_reg.startswith("d"):
                try:
                    as_float = float(reg_val.GetValue())
                    return [f"${normalized_reg}={as_float:.6g}"]
                except (ValueError, TypeError):
                    return [f"${normalized_reg}={reg_val.value}"]
            # For single precision floating point
            elif normalized_reg.startswith("s"):
                try:
                    as_float = float(reg_val.GetValue())
                    return [f"${normalized_reg}={as_float:.6g}"]
                except (ValueError, TypeError):
                    return [f"${normalized_reg}={reg_val.value}"]
            else:
                return [f"${normalized_reg}={reg_val.value}"]
        else:
            # For integer registers
            try:
                return [f"${normalized_reg}={hex(int(reg_val.value, 16))}"]
            except (ValueError, TypeError):
                return [f"${normalized_reg}={reg_val.value}"]

    def _normalize_register_name(self, reg_name: str) -> str:
        """Normalize register names for consistency"""
        if reg_name == "x29":
            return "fp"
        if reg_name == "x30":
            return "lr"
        return reg_name

    def _capture_memory_value(self, frame: lldb.SBFrame, mnemonic: str, memref: Dict[str, Any]) -> List[str]:
        """Capture memory value from memory reference operand"""
        base_reg = memref.get("base_reg", "")
        if not base_reg:
            return []

        normalized_base = self._normalize_register_name(base_reg)
        base_reg_val: lldb.SBValue = frame.FindRegister(normalized_base)
        if not base_reg_val or not base_reg_val.IsValid():
            self.logger.error("Failed to get base register: %s", normalized_base)
            return []

        base_value: int = base_reg_val.unsigned
        offset_value: int = self._parse_offset(memref.get("offset", ""))
        index_value: int = 0
        index_reg: Optional[str] = None

        if "index" in memref and memref["index"]:
            index_reg = memref["index"]
            normalized_index = self._normalize_register_name(index_reg)
            index_reg_val: lldb.SBValue = frame.FindRegister(normalized_index)
            if not index_reg_val or not index_reg_val.IsValid():
                self.logger.error("Failed to get index register: %s", normalized_index)
            else:
                index_value = index_reg_val.unsigned
                if "shift_op" in memref and "shift_amount" in memref:
                    index_value = self._apply_shift_operation(index_value, memref)

        addr: int = base_value + offset_value + index_value
        expr_str = self._build_expression_string(base_reg, offset_value, index_reg, memref)

        # 确定读取的字节数
        bytesize = self._get_memory_operand_size(mnemonic)
        error = lldb.SBError()
        value: int = self.tracer.process.ReadUnsignedFromMemory(addr, bytesize, error)
        if error.Success():
            return [f"{expr_str} = [0x{addr:x}] = 0x{value:x}"]
        self.logger.error("Failed to read memory at address 0x%x: %s", addr, error.GetCString())
        return []

    def _parse_offset(self, offset_str: str) -> int:
        """Parse offset value from string representation"""
        if not offset_str:
            return 0
        try:
            return int(offset_str.strip("#"), 0)
        except ValueError:
            self.logger.error("Failed to parse offset: %s", offset_str)
            return 0

    def _apply_shift_operation(self, value: int, memref: Dict[str, Any]) -> int:
        """Apply shift operation to index value"""
        shift_op: str = memref["shift_op"]
        shift_amount_str: str = memref["shift_amount"].strip("#")
        try:
            shift_amount: int = int(shift_amount_str, 0)
        except ValueError:
            self.logger.error("Failed to parse shift_amount: %s", memref["shift_amount"])
            return value

        if shift_op == "lsl":
            return value << shift_amount
        if shift_op == "lsr":
            return value >> shift_amount
        if shift_op == "asr":
            # 算术右移（带符号扩展）
            if value & (1 << 63):  # 检查最高位
                sign_ext = (1 << 64) - (1 << (64 - shift_amount))
                return (value >> shift_amount) | sign_ext
            return value >> shift_amount
        if shift_op == "ror":
            # 循环右移
            shift_amount %= 64  # 确保在0-63范围内
            return (value >> shift_amount) | (value << (64 - shift_amount)) & 0xFFFFFFFFFFFFFFFF
        return value

    def _build_expression_string(
        self, base_reg: str, offset_value: int, index_reg: Optional[str], memref: Dict[str, Any]
    ) -> str:
        """Build expression string for memory reference"""
        expr_str = f"[{base_reg}"
        if offset_value != 0:
            expr_str += f" + {offset_value:#x}"
        if index_reg:
            expr_str += f" + {index_reg}"
            if "shift_op" in memref:
                expr_str += f" {memref['shift_op']} #{memref['shift_amount'].strip('#')}"
        expr_str += "]"
        return expr_str

    def _get_memory_operand_size(self, mnemonic: str) -> int:
        """Determine memory operand size from mnemonic"""
        if mnemonic.endswith("b"):
            return 1
        if mnemonic.endswith("h"):
            return 2
        if mnemonic.endswith("w"):
            return 4
        return self.tracer.target.GetAddressByteSize()

    def _set_return_breakpoint(self, lr_value: int) -> bool:
        """设置返回地址断点，使用LRU缓存管理"""
        # 检查是否已在缓存中
        if lr_value in self.breakpoint_lru:
            # 更新为最近使用
            self.breakpoint_lru.move_to_end(lr_value)
            return True

        # 创建新断点
        bp: lldb.SBBreakpoint = self.tracer.target.BreakpointCreateByAddress(lr_value)
        if not bp.IsValid():
            self.logger.error("Failed to set breakpoint at address 0x%x", lr_value)
            return False

        bp.SetOneShot(False)
        bp_id = bp.GetID()

        # 加入全局表
        self.tracer.breakpoint_table[lr_value] = bp_id
        self.tracer.breakpoint_seen.add(bp_id)

        # 加入LRU缓存
        self.breakpoint_lru[lr_value] = bp_id

        # 如果缓存满，淘汰最久未使用的断点
        if len(self.breakpoint_lru) > self.max_lru_size:
            old_addr, old_bp_id = self.breakpoint_lru.popitem(last=False)
            # 删除断点
            self.tracer.target.BreakpointDelete(old_bp_id)
            # 从全局表中移除
            if old_addr in self.tracer.breakpoint_table:
                del self.tracer.breakpoint_table[old_addr]
            if old_bp_id in self.tracer.breakpoint_seen:
                self.tracer.breakpoint_seen.remove(old_bp_id)
        return True

    def _get_address_info(self, addr: int) -> tuple[str, str, int]:
        """统一获取地址的符号信息，带缓存"""
        if addr in self.addr_to_symbol_cache:
            return self.addr_to_symbol_cache[addr]

        resolved = self.tracer.target.ResolveLoadAddress(addr)
        symbol = resolved.symbol
        if symbol:
            symbol_name = symbol.name
            symbol_type = symbol.type
        else:
            symbol_name = f"0x{addr:x}"
            symbol_type = lldb.eSymbolTypeInvalid

        module_fullpath = resolved.module.file.fullpath if resolved.module and resolved.module.file else "unknown"
        # 统一缓存格式: (符号名, 模块路径, 符号类型)
        self.addr_to_symbol_cache[addr] = (symbol_name, module_fullpath, symbol_type)
        return symbol_name, module_fullpath, symbol_type

    def _handle_branch_instruction(
        self, mnemonic: str, target_addr: int, frame: lldb.SBFrame, next_pc: int, indent: str
    ) -> StepAction:
        """统一处理分支指令逻辑"""

        # 检查目标地址是否在当前函数内
        if self._is_address_in_current_function(frame, target_addr):
            return StepAction.SOURCE_STEP_IN

        # 获取地址信息
        symbol_name, module_fullpath, symbol_type = self._get_address_info(target_addr)

        # 检查是否应该跳过该地址
        skip_address = self.tracer.modules.should_skip_address(
            target_addr, module_fullpath
        ) or self.tracer.source_ranges.should_skip_source_address_dynamic(target_addr)

        # 根据指令类型处理
        if mnemonic in ("br", "braa", "brab", "blraa", "blr"):
            if skip_address:
                self.logger.info("%s%s Skipping jump to register value: %s", indent, mnemonic, symbol_name)
                if mnemonic in ("br", "braa", "brab"):
                    self._set_return_breakpoint(next_pc)
                return StepAction.SOURCE_STEP_OVER
            if mnemonic in ("blraa", "blr"):
                self.logger.info(
                    "%s%s CALL %s, %s",
                    indent,
                    mnemonic,
                    symbol_name,
                    frame.module,
                )
            else:
                self.logger.info("%s%s branching to register: %s, %s", indent, mnemonic, symbol_name, frame.module)
            return StepAction.SOURCE_STEP_IN

        elif mnemonic == "b":
            if skip_address:
                self.logger.info("%s%s skipping branch to: %s", indent, mnemonic, symbol_name)
                return StepAction.SOURCE_STEP_OVER

            self._set_return_breakpoint(next_pc)
            self.logger.info("%s%s branching to address: %s (%s)", indent, mnemonic, hex(target_addr), symbol_name)
            return StepAction.SOURCE_STEP_IN

        elif mnemonic == "bl":
            if symbol_type == lldb.eSymbolTypeTrampoline or skip_address:
                self._set_return_breakpoint(next_pc)
                self.logger.info(
                    "%s%s CALL %s, %s %s",
                    indent,
                    mnemonic,
                    hex(target_addr),
                    symbol_name,
                    get_symbol_type_str(symbol_type),
                )
                return StepAction.SOURCE_STEP_OVER

            self.logger.info(
                "%s%s CALL %s, %s, %s, %s",
                indent,
                mnemonic,
                hex(target_addr),
                symbol_name,
                frame.module,
                get_symbol_type_str(symbol_type),
            )
            return StepAction.SOURCE_STEP_IN

        return StepAction.SOURCE_STEP_IN

    def _determine_step_action(
        self, mnemonic: str, parsed_operands, frame: lldb.SBFrame, next_pc: int, indent: str
    ) -> StepAction:
        # 处理分支指令
        if mnemonic in ("br", "braa", "brab", "blraa", "blr", "b", "bl"):
            target_addr = None
            # 寄存器分支指令
            if mnemonic in ("br", "braa", "brab", "blraa", "blr"):
                if parsed_operands[0].type == OperandType.REGISTER:
                    reg_val: lldb.SBValue = frame.FindRegister(parsed_operands[0].value)
                    if not reg_val.IsValid():
                        self.logger.warning("Failed to get register value: %s", parsed_operands[0].value)
                        return StepAction.CONTINUE
                    target_addr = reg_val.unsigned
            # 直接分支指令
            elif mnemonic in ("b", "bl"):
                target_addr_str = parsed_operands[0].value
                try:
                    target_addr = int(target_addr_str, 16)
                except ValueError:
                    self.logger.error("Failed to parse target address: %s", target_addr_str)
                    return StepAction.SOURCE_STEP_IN

            if target_addr is not None:
                return self._handle_branch_instruction(mnemonic, target_addr, frame, next_pc, indent)

        # 处理返回指令
        elif mnemonic.startswith("ret"):
            self.logger.info(
                "%s%s RETURN %s %s",
                indent,
                mnemonic,
                frame.symbol.name if frame.symbol else "unknown",
                frame.module,
            )

        # 默认执行单步进入
        return StepAction.SOURCE_STEP_IN
