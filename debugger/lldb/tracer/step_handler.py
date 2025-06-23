import collections
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import lldb
from op_parser import OperandType, parse_operands

from tree import ParserLoader, parse_code_file

from . import sb_value_printer
from .debug_info_handler import DebugInfoHandler
from .events import StepAction
from .expr_extractor import ExpressionExtractor
from .source_handler import SourceHandler
from .utils import get_symbol_type_str

if TYPE_CHECKING:
    from .core import Tracer

BRANCH_MAX_TOLERANCE = 10


class StepHandler:
    def __init__(self, tracer: "Tracer", bind_thread_id=None) -> None:
        self.tracer: Tracer = tracer
        self.logger: logging.Logger = tracer.logger

        # Handlers for specific tasks
        self.source_handler = SourceHandler(tracer)
        self.debug_info_handler = DebugInfoHandler(tracer)

        self._last_source_key: Optional[str] = None

        # Caches
        self.instruction_info_cache: Dict[int, tuple[str, list]] = {}
        self.line_cache: Dict[str, lldb.SBLineEntry] = {}
        self.function_start_addrs = set()
        self.function_range_cache = {}
        self.addr_to_symbol_cache: Dict[int, tuple[str, str, int]] = {}
        self.breakpoint_lru = collections.OrderedDict()
        self.max_lru_size = 100
        self.expression_cache: Dict[str, Dict[int, list]] = {}

        # State
        self.expression_hooks = self.tracer.config_manager.get_expression_hooks()
        self.frame_count = -1
        self.base_frame_count = -1
        self.log_mode = self.tracer.config_manager.get_log_mode()
        self.step_action = self.tracer.config_manager.get_step_action()
        self.insutruction_mode = self.log_mode == "instruction"
        self.step_in = StepAction.STEP_IN if self.log_mode == "instruction" else StepAction.SOURCE_STEP_IN
        self.step_over = StepAction.STEP_OVER if self.log_mode == "instruction" else StepAction.SOURCE_STEP_OVER
        self.step_out = StepAction.SOURCE_STEP_OUT
        # Expression extraction tools
        self.parser_loader = ParserLoader()
        self.expression_extractor = ExpressionExtractor()
        self.source_file_extensions = {".c", ".cpp", ".cxx", ".cc"}
        self.branch_trace_info = {}
        self.current_frame_branch_counter = {}
        self.current_frame_line_counter = {}
        self.bind_thread_id = bind_thread_id

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

        if lldb.LLDB_INVALID_ADDRESS in (start_addr, end_addr):
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

    def _evaluate_source_expressions(self, frame: lldb.SBFrame, filepath: str, line_num: int) -> List[str]:
        """Extract and evaluate expressions from the current source line."""
        if not filepath or not any(filepath.endswith(ext) for ext in self.source_file_extensions):
            return []

        # 获取或初始化缓存
        if filepath not in self.expression_cache:
            try:
                with open(filepath, "rb") as f:
                    source_code = f.read()
                parser, _, _ = self.parser_loader.get_parser(filepath)
                tree = parse_code_file(filepath, parser)
                self.expression_cache[filepath] = self.expression_extractor.extract(tree.root_node, source_code)
            except (IOError, SyntaxError) as e:
                self.logger.warning(f"Failed to parse {filepath} for expressions: {e}")
                self.expression_cache[filepath] = {}
                return []

        # 处理表达式求值
        return self._process_line_expressions(frame, filepath, line_num)

    def _process_line_expressions(self, frame: lldb.SBFrame, filepath: str, line_num: int) -> List[str]:
        """处理单行的表达式求值"""
        line_expressions = self.expression_cache[filepath].get(line_num - 1, [])
        if not line_expressions:
            return []

        evaluated_values = []
        locals_map = self._get_frame_locals(frame)

        for expr_info in line_expressions:
            expr_text = expr_info[1]
            if not expr_text:
                continue

            if expr_text in locals_map:
                evaluated_values.append(f"{expr_text}={locals_map[expr_text]}")
            elif "*" not in expr_text:
                self._evaluate_complex_expression(frame, expr_text, evaluated_values)

        return evaluated_values

    def _get_frame_locals(self, frame: lldb.SBFrame) -> Dict[str, str]:
        """获取当前帧的本地变量"""
        locals_map = {}
        for local_var in frame.GetVariables(True, True, False, True):
            if local_var.IsValid() and local_var.name:
                locals_map[local_var.name] = sb_value_printer.format_sbvalue(local_var, shallow_aggregate=True)
        return locals_map

    def _evaluate_complex_expression(self, frame: lldb.SBFrame, expr_text: str, evaluated_values: List[str]) -> None:
        """评估复杂表达式"""
        result = frame.EvaluateExpression(expr_text)
        if result.error.Success() and result.GetValue() is not None:
            value_str = sb_value_printer.format_sbvalue(result, shallow_aggregate=True)
            evaluated_values.append(f"{expr_text}={value_str}")

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

    def step_action_str_to_enum(self, action_str: str) -> StepAction:
        """将步进动作字符串转换为枚举类型"""
        action_str = action_str.lower()
        if action_str == "step_in":
            return StepAction.STEP_IN
        elif action_str == "step_over":
            return StepAction.STEP_OVER
        elif action_str == "step_out":
            return StepAction.STEP_OUT
        elif action_str == "source_step_in":
            return StepAction.SOURCE_STEP_IN
        elif action_str == "source_step_over":
            return StepAction.SOURCE_STEP_OVER
        else:
            self.logger.error("Unknown step action: %s", action_str)
            return StepAction.STEP_IN

    def on_step_hit(self, frame: lldb.SBFrame, reason: str) -> StepAction:
        """Handle step events with detailed debug information."""
        pc = frame.GetPCAddress().GetLoadAddress(self.tracer.target)
        self.last_pc = pc

        if self.tracer.modules.should_skip_address(pc, frame.module.file.fullpath):
            self.logger.info("get out of module: %s", frame.module.file.fullpath)
            return self.step_out

        if pc not in self.instruction_info_cache:
            self._cache_instruction_info(frame, pc)

        instruction_info = self.instruction_info_cache.get(pc)
        if not instruction_info:
            self.logger.error("Instruction info not found for PC: 0x%x", pc)
            return self.step_in

        mnemonic, operands, size, first_inst_offset = instruction_info
        next_pc = pc + size
        line_entry = self._get_line_entry(frame, pc)
        source_info, source_line, resolved_filepath = self._process_source_info(frame, line_entry)
        if line_entry.IsValid():
            step_config = self.step_action.get(resolved_filepath)
            if step_config:
                [start, end], action = step_config
                if start <= line_entry.GetLine() < end:
                    self.logger.info(
                        "Using step action from config: %s for %s at line %d",
                        action,
                        resolved_filepath,
                        line_entry.GetLine(),
                    )
                    return self.step_action_str_to_enum(action)
            cfa_addr = frame.GetCFA()
            if cfa_addr not in self.current_frame_line_counter:
                self.current_frame_line_counter[cfa_addr] = defaultdict(int)
            self.current_frame_line_counter[cfa_addr][line_entry.GetLine()] += 1
            if self.current_frame_line_counter[cfa_addr][line_entry.GetLine()] > BRANCH_MAX_TOLERANCE:
                self.logger.warning(
                    "Line %d in frame %s has been hit more than 20 times, get out of this frame",
                    line_entry.GetLine(),
                    frame.GetFunctionName() or "unknown function",
                )
                return self.step_out
        debug_values = self._process_debug_info(frame, mnemonic, operands, resolved_filepath)
        if resolved_filepath and self.tracer.source_ranges.should_skip_source_file_by_path(resolved_filepath):
            return self.step_over

        frames_count = frame.thread.GetNumFrames()
        if frames_count != 0:
            if self.base_frame_count == -1:
                indent = frames_count * "  "
            else:
                indent = (frames_count - self.base_frame_count) * "  "
        self._log_step_info(indent, mnemonic, operands, first_inst_offset, pc, source_info, source_line, debug_values)

        return self._determine_step_action(mnemonic, parse_operands(operands, max_ops=4), frame, pc, next_pc, indent)

    def _cache_instruction_info(self, frame: lldb.SBFrame, pc: int) -> None:
        """缓存指令信息"""
        instructions = frame.symbol.GetInstructions(self.tracer.target)
        first_inst_loaded_addr = frame.symbol.GetStartAddress().GetLoadAddress(self.tracer.target)
        self.function_start_addrs.add(first_inst_loaded_addr)
        first_inst = instructions.GetInstructionAtIndex(0)
        first_inst_offset = (
            first_inst.GetAddress().GetLoadAddress(self.tracer.target) - first_inst.GetAddress().GetFileAddress()
        )

        for inst in instructions:
            loaded_address = inst.GetAddress().GetFileAddress() + first_inst_offset
            self.instruction_info_cache[loaded_address] = (
                inst.GetMnemonic(self.tracer.target),
                inst.GetOperands(self.tracer.target),
                inst.size,
                inst.GetAddress().file_addr - first_inst.GetAddress().file_addr,
            )

    def _process_debug_info(self, frame: lldb.SBFrame, mnemonic: str, operands: str, resolved_path: str) -> List[str]:
        """处理调试信息"""
        parsed_operands = parse_operands(operands, max_ops=4)
        debug_values = self.debug_info_handler.capture_register_values(frame, mnemonic, parsed_operands)
        debug_values.extend(self._evaluate_source_expressions(frame, resolved_path, frame.GetLineEntry().GetLine()))
        return debug_values

    def _get_line_entry(self, frame: lldb.SBFrame, pc: int) -> lldb.SBLineEntry:
        """获取行条目信息"""
        if pc in self.line_cache:
            return self.line_cache[pc]
        line_entry = frame.GetLineEntry()
        self.line_cache[pc] = line_entry
        return line_entry

    def _process_source_info(self, frame: lldb.SBFrame, line_entry: lldb.SBLineEntry) -> Tuple[str, str, Optional[str]]:
        """处理源代码信息"""
        if not line_entry.IsValid():
            return "", "", None

        original_filepath = line_entry.GetFileSpec().fullpath
        resolved_filepath = self.source_handler.resolve_source_path(original_filepath)
        line_num = int(line_entry.GetLine())
        column = line_entry.GetColumn()

        source_info = self._build_source_info_string(original_filepath, resolved_filepath, line_num, column)
        source_line = self._get_source_line(frame, resolved_filepath, line_num) if resolved_filepath else ""

        return source_info, source_line, resolved_filepath

    def _build_source_info_string(self, original_path: str, resolved_path: str, line_num: int, column: int) -> str:
        """构建源信息字符串"""
        filepath = resolved_path or original_path
        if line_num <= 0:
            return f"{filepath}:<no line>"
        return f"{filepath}:{line_num}:{column}" if column > 0 else f"{filepath}:{line_num}"

    def _get_source_line(self, frame: lldb.SBFrame, filepath: str, line_num: int) -> str:
        """获取源代码行"""
        try:
            return self.source_handler.get_source_code_range(frame, filepath, line_num)
        except Exception as e:
            self.logger.warning("Failed to get source line: %s", str(e))
            return ""

    def _log_step_info(
        self,
        indent: str,
        mnemonic: str,
        operands: str,
        first_inst_offset: int,
        pc: int,
        source_info: str,
        source_line: str,
        debug_values: List[str],
    ) -> None:
        """记录步骤信息"""
        if self.log_mode == "source":
            self._log_source_mode(indent, source_info, source_line, debug_values)
        else:
            self._log_instruction_mode(
                indent, pc, first_inst_offset, mnemonic, operands, source_info, source_line, debug_values
            )

    def remove_any_breakpoint_within_range(self, start_addr: int, end_addr: int) -> None:
        """移除指定地址范围内的所有断点"""
        for addr in list(self.tracer.breakpoint_table.keys()):
            if start_addr <= addr < end_addr:
                self.logger.info("Removing breakpoint at address: 0x%x", addr)
                bp_id = self.tracer.breakpoint_table[addr]
                self.tracer.target.BreakpointDelete(bp_id)
                del self.tracer.breakpoint_table[addr]
                self.tracer.breakpoint_seen.remove(bp_id)
                self.breakpoint_lru.pop(addr, None)  # 从LRU缓存中移除

    def _update_lru_breakpoint(self, lr_value: int) -> bool:
        """设置返回地址断点，使用LRU缓存管理"""
        # 检查是否已在缓存中
        if lr_value in self.breakpoint_lru:
            # 更新为最近使用
            self.breakpoint_lru.move_to_end(lr_value)
            return True
        self.logger.info("Setting breakpoint at LR: 0x%x", lr_value)
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

    def should_skip_address(self, target_addr: int) -> bool:
        # 获取地址信息
        symbol_name, module_fullpath, symbol_type = self._get_address_info(target_addr)

        # 检查是否应该跳过该地址
        skip_address = self.tracer.modules.should_skip_address(
            target_addr, module_fullpath
        ) or self.tracer.source_ranges.should_skip_source_address_dynamic(target_addr)
        return skip_address

    def _handle_branch_instruction(
        self, mnemonic: str, target_addr: int, frame: lldb.SBFrame, pc: int, next_pc: int, indent: str
    ) -> StepAction:
        """统一处理分支指令逻辑"""
        if self._is_address_in_current_function(frame, target_addr):
            return self.step_in

        _, module_fullpath, _ = self._get_address_info(target_addr)
        skip_address = self._should_skip_branch_address(target_addr, module_fullpath)

        if mnemonic in ("br", "braa", "brab", "blraa", "blr"):
            if skip_address:
                if mnemonic in ("br", "braa", "brab"):
                    self._update_lru_breakpoint(next_pc)
                return self.step_over
            return self.step_in

        if mnemonic == "b":
            if skip_address:
                self.logger.info(
                    "%s%s skipping branch to: %s", indent, mnemonic, frame.symbol.name if frame.symbol else "unknown"
                )
                return self.step_over
            self._update_lru_breakpoint(next_pc)
            return self.step_in

        if mnemonic == "bl":
            if skip_address:
                self._update_lru_breakpoint(next_pc)
                return self.step_over
            return self.step_in

        return self.step_in

    def _should_skip_branch_address(self, target_addr: int, module_fullpath: str) -> bool:
        """检查是否应该跳过分支地址"""
        return self.tracer.modules.should_skip_address(
            target_addr, module_fullpath
        ) or self.tracer.source_ranges.should_skip_source_address_dynamic(target_addr)

    def log_frames(self, frame: lldb.SBFrame) -> None:
        for i in range(frame.thread.num_frames):
            f: lldb.SBFrame = frame.thread.GetFrameAtIndex(i)
            pc = f.GetPCAddress().GetLoadAddress(self.tracer.target)
            symbol = f.symbol
            if symbol:
                symbol_name = symbol.name
                module_name = f.module.file.fullpath if f.module else "unknown"
            else:
                symbol_name = "unknown"
                module_name = "unknown"
            self.logger.info(
                "Frame %d: PC=0x%x, Symbol=%s, Module=%s",
                i,
                pc,
                symbol_name,
                module_name,
            )

    def is_branch_instruction(self, mnemonic: str) -> bool:
        """检查指令是否为分支指令"""
        return mnemonic in (
            "br",
            "braa",
            "brab",
            "blraa",
            "blr",
            "b",
            "bl",
        ) or mnemonic.startswith("b.")

    def is_return_instruction(self, mnemonic: str) -> bool:
        """检查指令是否为返回指令"""
        return mnemonic.startswith("ret") or mnemonic in ("retl", "retw", "retq", "retx", "retd", "retn", "retns")

    def before_new_frame(self, frame: lldb.SBFrame):
        cfa_addr = frame.GetCFA()
        if cfa_addr in self.current_frame_branch_counter:
            self.current_frame_branch_counter[cfa_addr].clear()
        if cfa_addr in self.current_frame_line_counter:
            self.current_frame_line_counter[cfa_addr].clear()

    def _determine_step_action(
        self, mnemonic: str, parsed_operands, frame: lldb.SBFrame, pc: int, next_pc: int, indent: str
    ) -> StepAction:
        """确定步进动作"""
        if self.is_branch_instruction(mnemonic):
            return self._handle_branch_case(mnemonic, parsed_operands, frame, pc, next_pc, indent)
        if mnemonic.startswith("ret"):
            return self._handle_return_case(mnemonic, parsed_operands, frame, indent)
        return self.step_in

    def _handle_branch_case(
        self, mnemonic: str, parsed_operands, frame: lldb.SBFrame, pc: int, next_pc: int, indent: str
    ) -> StepAction:
        """处理分支指令情况"""
        target_addr = self._get_branch_target(mnemonic, parsed_operands, frame)
        if target_addr is None:
            return self.step_in

        if self._is_internal_branch(frame, target_addr, pc, next_pc, mnemonic, indent):
            return self.step_in

        return self._handle_branch_instruction(mnemonic, target_addr, frame, pc, next_pc, indent)

    def _get_branch_target(self, mnemonic: str, parsed_operands, frame: lldb.SBFrame) -> Optional[int]:
        """获取分支目标地址"""
        if mnemonic in ("br", "braa", "brab", "blraa", "blr"):
            if parsed_operands[0].type == OperandType.REGISTER:
                reg_val = frame.FindRegister(parsed_operands[0].value)
                return reg_val.unsigned if reg_val.IsValid() else None
        elif mnemonic in ("b", "bl") or mnemonic.startswith("b."):
            if parsed_operands and parsed_operands[0].type == OperandType.ADDRESS:
                try:
                    return int(parsed_operands[0].value, 16)
                except ValueError:
                    self.logger.error("Failed to parse target address: %s", parsed_operands[0].value)
        return None

    def _is_internal_branch(
        self, frame: lldb.SBFrame, target_addr: int, pc: int, next_pc: int, mnemonic: str, indent: str
    ) -> bool:
        """检查是否是内部函数分支"""
        start_addr = frame.symbol.GetStartAddress().GetLoadAddress(self.tracer.target)
        end_addr = frame.symbol.GetEndAddress().GetLoadAddress(self.tracer.target)

        if start_addr < target_addr < end_addr:
            offset = target_addr - start_addr
            cfa_addr = frame.GetCFA()
            if cfa_addr not in self.current_frame_branch_counter:
                self.current_frame_branch_counter[cfa_addr] = defaultdict(int)

            self.current_frame_branch_counter[cfa_addr][next_pc] += 1
            if self.current_frame_branch_counter[cfa_addr][next_pc] > BRANCH_MAX_TOLERANCE:
                self._handle_excessive_branches(frame, start_addr, end_addr, offset, pc, mnemonic, indent)
                return True
        return False

    def _handle_excessive_branches(
        self, frame: lldb.SBFrame, start_addr: int, end_addr: int, offset: int, pc: int, mnemonic: str, indent: str
    ) -> None:
        """处理过多的分支情况"""
        self.logger.warning(
            "%s%s Too many branches in function %s+%d from PC: 0x%x, stepping out",
            indent,
            mnemonic,
            frame.symbol.name if frame.symbol else "unknown",
            offset,
            pc,
        )
        self.remove_any_breakpoint_within_range(start_addr, end_addr)

    def _handle_return_case(self, mnemonic: str, parsed_operands, frame: lldb.SBFrame, indent: str) -> StepAction:
        """处理返回指令情况"""
        self.before_new_frame(frame)
        if frame.function:
            register = parsed_operands[0].value if parsed_operands else "x0"
            return_register = frame.FindRegister(register)
            sb_value = return_register.Cast(frame.function.GetType().GetFunctionReturnType())

            if sb_value.IsValid():
                value_str = sb_value_printer.format_sbvalue(sb_value, shallow_aggregate=True)
                self.logger.info(
                    "%s%s RETURN VALUE %s from %s",
                    indent,
                    mnemonic,
                    value_str,
                    frame.symbol.name if frame.symbol else "unknown",
                )
            else:
                self.logger.warning("%s%s RETURN expression failed: %s", indent, mnemonic, sb_value.error.GetCString())
        return self.step_out
