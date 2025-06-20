import collections
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Dict, List, Optional

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
        self.step_in = StepAction.STEP_IN if self.log_mode == "instruction" else StepAction.SOURCE_STEP_IN
        self.step_over = StepAction.STEP_OVER if self.log_mode == "instruction" else StepAction.SOURCE_STEP_OVER
        self.step_out = StepAction.SOURCE_STEP_OUT
        # Expression extraction tools
        self.parser_loader = ParserLoader()
        self.expression_extractor = ExpressionExtractor()
        self.source_file_extensions = {".c", ".cpp", ".cxx", ".cc"}
        self.branch_trace_info = {}
        self.current_frame_branch_counter = {}
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

    def _evaluate_source_expressions(self, frame: lldb.SBFrame, filepath: str, line_num: int) -> List[str]:
        """Extract and evaluate expressions from the current source line."""
        # 检查文件后缀，只处理C/C++源文件
        if not any(filepath.endswith(ext) for ext in self.source_file_extensions):
            return []

        # 检查缓存
        if filepath not in self.expression_cache:
            try:
                with open(filepath, "rb") as f:
                    source_code = f.read()
                parser, _, _ = self.parser_loader.get_parser(filepath)
                tree = parse_code_file(filepath, parser)
                self.expression_cache[filepath] = self.expression_extractor.extract(tree.root_node, source_code)
            except Exception as e:
                self.logger.warning(f"Failed to parse {filepath} for expressions: {e}")
                self.expression_cache[filepath] = {}  # 缓存空结果以避免重试
                return []

        # 获取当前帧的本地变量
        locals_map = {}
        for local_var in frame.GetVariables(True, True, False, True):
            if local_var.IsValid() and local_var.name:
                locals_map[local_var.name] = local_var

        line_expressions = self.expression_cache[filepath].get(line_num - 1, [])
        if not line_expressions:
            return []

        evaluated_values = []
        mark_remove = []
        for _, expr_text, _ in line_expressions:
            if not expr_text:
                continue

            # 首先检查是否是简单的变量引用，可以直接从locals获取
            if expr_text in locals_map:
                value = locals_map[expr_text]
                value_str = sb_value_printer.format_sbvalue(value, shallow_aggregate=True)
                evaluated_values.append(f"{expr_text}={value_str}")
                continue
            if "*" in expr_text:
                mark_remove.append(expr_text)
                continue
            # 对于复杂表达式，使用 LLDB 求值
            result: lldb.SBValue = frame.EvaluateExpression(expr_text)
            if result.error.Success():
                if result.GetValue() is not None:
                    value_str = sb_value_printer.format_sbvalue(result, shallow_aggregate=True)
                    evaluated_values.append(f"{expr_text}={value_str}")
            else:
                err = result.error.GetCString()
                # if "undeclared identifier" in err or "no member" in err:
                mark_remove.append(expr_text)
                # self.logger.debug(f"Failed to evaluate expression '{expr_text}': {result.error.GetCString()}")

        if mark_remove:
            # 如果有未声明的标识符，移除它们
            for expr in mark_remove:
                for i, (expr_type, expr_text, _) in enumerate(line_expressions):
                    if expr_text == expr:
                        line_expressions[i] = (None, None, None)
        return evaluated_values

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

    def on_step_hit(self, frame: lldb.SBFrame, reason: str) -> StepAction:
        """Handle step events with detailed debug information."""
        self.logger.info("on_step_hit called with reason: %s", reason)
        pc: int = frame.GetPCAddress().GetLoadAddress(self.tracer.target)
        next_pc = frame.addr
        self.last_pc = pc
        if pc not in self.instruction_info_cache:
            instructions: lldb.SBInstructions = frame.symbol.GetInstructions(self.tracer.target)
            first_inst_loaded_addr = frame.symbol.GetStartAddress().GetLoadAddress(self.tracer.target)
            self.function_start_addrs.add(first_inst_loaded_addr)
            first_inst: lldb.SBInstruction = instructions.GetInstructionAtIndex(0)
            first_inst_offset = (
                first_inst.GetAddress().GetLoadAddress(self.tracer.target) - first_inst.GetAddress().GetFileAddress()
            )
            should_skip = self.should_skip_address(first_inst_loaded_addr)
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
                if not should_skip and self.is_return_instruction(mnemonic):
                    self._update_lru_breakpoint(loaded_address)
        if pc not in self.instruction_info_cache:
            self.logger.error("Instruction info not found for PC: 0x%x", pc)
            return self.step_in

        mnemonic, operands, size, first_inst_offset = self.instruction_info_cache[pc]
        next_pc = pc + size
        parsed_operands = parse_operands(operands, max_ops=4)
        debug_values: List[str] = self.debug_info_handler.capture_register_values(frame, mnemonic, parsed_operands)
        if pc in self.line_cache:
            line_entry: lldb.SBLineEntry = self.line_cache[pc]
        else:
            line_entry: lldb.SBLineEntry = frame.GetLineEntry()
            self.line_cache[pc] = line_entry
        source_info: str = ""
        source_line: str = ""
        resolved_filepath: Optional[str] = None
        if pc in self.function_start_addrs:
            if frame.args:
                debug_values.append(f"args of {frame.symbol.name}")
                for arg in frame.args:
                    debug_values.append(f"{arg.name}={arg.value}")
        frames_count = frame.thread.GetNumFrames()
        if frames_count != 0:
            if self.base_frame_count == -1:
                indent = frames_count * "  "
            else:
                indent = (frames_count - self.base_frame_count) * "  "
        if line_entry.IsValid():
            original_filepath: str = line_entry.GetFileSpec().fullpath
            resolved_filepath = self.source_handler.resolve_source_path(original_filepath)
            if resolved_filepath and self.tracer.source_ranges.should_skip_source_file_by_path(resolved_filepath):
                return self.step_over
            line_num: int = int(line_entry.GetLine())
            column: int = line_entry.GetColumn()

            # 构建源信息字符串
            if resolved_filepath:
                if line_num > 0:
                    source_info = f"{resolved_filepath}:{line_num}"
                    if column > 0:
                        source_info += f":{column}"
                else:
                    source_info = f"{resolved_filepath}:<no line>"
            else:
                # 即使解析失败，也使用原始路径
                if line_num > 0:
                    source_info = f"{original_filepath}:{line_num}"
                    if column > 0:
                        source_info += f":{column}"
                else:
                    source_info = f"{original_filepath}:<no line>"

            # 执行表达式钩子并获取结果
            if resolved_filepath:
                expr_results = self._execute_expression_hooks(resolved_filepath, line_num, frame)
                debug_values.extend(expr_results)
            else:
                expr_results = []
                self.logger.warning("Skipping expression hooks due to unresolved file path: %s", original_filepath)

            # 获取源代码片段
            if resolved_filepath:
                source_line = self.source_handler.get_source_code_range(frame, resolved_filepath, line_num)
            else:
                source_line = ""
                self.logger.warning(
                    "Skipping source code extraction due to unresolved file path: %s", original_filepath
                )

            # 只有在行号有效且路径已解析时才获取局部变量
            if line_num > 0 and resolved_filepath:
                # Evaluate expressions from source code
                source_expr_values = self._evaluate_source_expressions(frame, resolved_filepath, line_num)
                debug_values.extend(source_expr_values)

        current_source_key: str = f"{source_info};{source_line}"
        if hasattr(self, "_last_source_key") and current_source_key == self._last_source_key:
            source_info = ""
            source_line = ""
        self._last_source_key = current_source_key
        # 根据日志模式选择输出格式
        if self.log_mode == "source":
            self._log_source_mode(indent, source_info, source_line, debug_values)
        else:  # 默认使用instruction模式
            self._log_instruction_mode(
                indent, pc, first_inst_offset, mnemonic, operands, source_info, source_line, debug_values
            )
        if pc in self.branch_trace_info:
            pc, target_addr, next_pc, func_name, module_path = self.branch_trace_info[pc]
            self.logger.info(
                "%sbranch finished: %s, start from 0x%x, branch to 0x%x, symbol: %s, path: %s",
                indent,
                hex(next_pc),
                pc,
                target_addr,
                func_name,
                module_path,
            )
        return self._determine_step_action(mnemonic, parsed_operands, frame, pc, next_pc, indent)

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

        # 检查目标地址是否在当前函数内
        if self._is_address_in_current_function(frame, target_addr):
            return self.step_in

        # 获取地址信息
        symbol_name, module_fullpath, symbol_type = self._get_address_info(target_addr)

        # 检查是否应该跳过该地址
        skip_address = self.tracer.modules.should_skip_address(
            target_addr, module_fullpath
        ) or self.tracer.source_ranges.should_skip_source_address_dynamic(target_addr)

        # 根据指令类型处理
        if mnemonic in ("br", "braa", "brab", "blraa", "blr"):
            if skip_address:
                # self.logger.info("%s%s Skipping jump to register value: %s", indent, mnemonic, symbol_name)
                if mnemonic in ("br", "braa", "brab"):
                    self._update_lru_breakpoint(next_pc)
                return self.step_over
            # if mnemonic in ("blraa", "blr"):
            #     self.logger.info(
            #         "%s%s CALL %s, %s",
            #         indent,
            #         mnemonic,
            #         symbol_name,
            #         frame.module,
            #     )
            # else:
            #     self.logger.info("%s%s branching to register: %s, %s", indent, mnemonic, symbol_name, frame.module)
            return self.step_in

        elif mnemonic == "b":
            if skip_address:
                self.logger.info("%s%s skipping branch to: %s", indent, mnemonic, symbol_name)
                return self.step_over

            self._update_lru_breakpoint(next_pc)
            # self.logger.info("%s%s branching to address: %s (%s)", indent, mnemonic, hex(target_addr), symbol_name)
            return self.step_in

        elif mnemonic == "bl":
            if symbol_type == lldb.eSymbolTypeTrampoline or skip_address:
                self._update_lru_breakpoint(next_pc)
                # self.logger.info(
                #     "%s%s CALL %s, %s %s",
                #     indent,
                #     mnemonic,
                #     hex(target_addr),
                #     symbol_name,
                #     get_symbol_type_str(symbol_type),
                # )
                if skip_address:
                    return self.step_over
                else:
                    return self.step_in
            # self.logger.info(
            #     "%s%s CALL %s, %s, %s, %s",
            #     indent,
            #     mnemonic,
            #     hex(target_addr),
            #     symbol_name,
            #     frame.module,
            #     get_symbol_type_str(symbol_type),
            # )
            return self.step_in

        return self.step_in

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
            "ret",
            "retl",
            "retw",
            "retq",
            "retx",
            "retd",
            "retn",
            "retns",
        )

    def is_return_instruction(self, mnemonic: str) -> bool:
        """检查指令是否为返回指令"""
        return mnemonic.startswith("ret") or mnemonic in ("retl", "retw", "retq", "retx", "retd", "retn", "retns")

    def before_new_frame(self, frame: lldb.SBFrame):
        cfa_addr = frame.GetCFA()
        if cfa_addr in self.current_frame_branch_counter:
            self.current_frame_branch_counter[frame.GetCFA()].clear()

    def _determine_step_action(
        self, mnemonic: str, parsed_operands, frame: lldb.SBFrame, pc: int, next_pc: int, indent: str
    ) -> StepAction:
        # 处理分支指令
        if mnemonic in ("br", "braa", "brab", "blraa", "blr", "b", "bl") or mnemonic.startswith("b."):
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
                    return self.step_in
            elif mnemonic.startswith("b."):
                # 处理条件分支指令
                if len(parsed_operands) > 0 and parsed_operands[0].type == OperandType.ADDRESS:
                    target_addr_str = parsed_operands[0].value
                    try:
                        target_addr = int(target_addr_str, 16)
                    except ValueError:
                        self.logger.error("Failed to parse target address: %s", target_addr_str)
                        return self.step_in
            if target_addr is not None:
                offset = 0
                start_addr, end_addr = (
                    frame.symbol.GetStartAddress().GetLoadAddress(self.tracer.target),
                    frame.symbol.GetEndAddress().GetLoadAddress(self.tracer.target),
                )
                if start_addr < target_addr < end_addr:
                    offset = target_addr - start_addr
                if offset:
                    cfa_addr = frame.GetCFA()
                    if cfa_addr not in self.current_frame_branch_counter:
                        self.current_frame_branch_counter[cfa_addr] = defaultdict(int)
                    self.current_frame_branch_counter[cfa_addr][next_pc] += 1
                    if self.current_frame_branch_counter[cfa_addr][next_pc] > 20:
                        self.logger.warning(
                            "%s%s Too many branches in function %s+%d from PC: 0x%x, stepping out",
                            indent,
                            mnemonic,
                            frame.symbol.name if frame.symbol else "unknown",
                            offset,
                            pc,
                        )
                        self.remove_any_breakpoint_within_range(start_addr, end_addr)
                        return self.step_out
                    function_name = frame.symbol.name if frame.symbol else "unknown"
                    self.logger.info(
                        "%s%s Branching within function %s+%d from PC: 0x%x count=%d",
                        indent,
                        mnemonic,
                        function_name,
                        offset,
                        pc,
                        self.current_frame_branch_counter[cfa_addr][next_pc],
                    )
                else:
                    self.branch_trace_info[next_pc] = [
                        pc,
                        target_addr,
                        next_pc,
                        frame.symbol.name if frame.symbol else "unknown",
                        frame.module.file.fullpath if frame.module else "unknown",
                    ]
                    self.logger.info(
                        "%s%s Branching to address: %s (%s) from PC: 0x%x, module=%s",
                        indent,
                        mnemonic,
                        hex(target_addr),
                        frame.symbol.name if frame.symbol else "unknown",
                        pc,
                        frame.module.file.fullpath if frame.module else "unknown",
                    )

                return self._handle_branch_instruction(mnemonic, target_addr, frame, pc, next_pc, indent)

        # 处理返回指令
        elif mnemonic.startswith("ret"):
            self.before_new_frame(frame)
            if frame.function:
                return_type_name = frame.function.GetType().GetFunctionReturnType().name
                if len(parsed_operands) != 0:
                    register = parsed_operands[0].value
                    expr = "(%s)$%s" % (return_type_name, register)
                elif return_type_name != "void":
                    expr = "(%s)%s" % (return_type_name, "$x0")
                else:
                    expr = ""
                if expr:
                    sb_value: lldb.SBValue = frame.EvaluateExpression(expr)
                    if sb_value.IsValid():
                        value_str = sb_value_printer.format_sbvalue(sb_value, shallow_aggregate=True)
                        self.logger.info(
                            "%s%s RETURN VALUE %s=%s signature=%s",
                            indent,
                            mnemonic,
                            expr,
                            value_str,
                            frame.function.GetType().name,
                        )
                    else:
                        self.logger.warning(
                            "%s%s RETURN expression failed: %s",
                            indent,
                            mnemonic,
                            sb_value.error.GetCString(),
                        )
            # read return value
            self.logger.info(
                "%s%s RETURN %s %s",
                indent,
                mnemonic,
                frame.symbol.name if frame.symbol else "unknown",
                frame.module,
            )
        # 默认执行单步进入
        return self.step_in
