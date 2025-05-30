import logging
import os
import re
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import lldb
from op_parser import OperandType, parse_operands

from .events import StepAction
from .utils import get_stop_reason_str

if TYPE_CHECKING:
    from .core import Tracer


class StepHandler:
    def __init__(self, tracer: "Tracer") -> None:
        self.tracer: Tracer = tracer
        self.logger: logging.Logger = tracer.logger
        self._last_source_key: Optional[str] = None
        self._max_cached_files: int = 10

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

    def on_step_hit(self, frame: lldb.SBFrame) -> StepAction:
        """Handle step events with detailed debug information."""
        pc: int = frame.GetPCAddress().GetLoadAddress(self.tracer.target)
        insts: lldb.SBInstructionList = self.tracer.target.ReadInstructions(frame.addr, 1)
        if insts.GetSize() == 0:
            self.logger.warning("No instructions found at PC: 0x%x", pc)
            return StepAction.CONTINUE

        inst: lldb.SBInstruction = insts.GetInstructionAtIndex(0)
        if not inst.IsValid():
            self.logger.warning("Invalid instruction at PC: 0x%x", pc)
            return StepAction.CONTINUE

        mnemonic: str = inst.GetMnemonic(self.tracer.target)
        operands: str = inst.GetOperands(self.tracer.target)
        function: str = frame.symbol.name if frame.symbol else "unknown"
        line_entry: lldb.SBLineEntry = frame.GetLineEntry()
        source_info: str = ""
        source_line: str = ""

        if line_entry.IsValid():
            filepath: str = line_entry.GetFileSpec().fullpath
            dirname, basename = os.path.split(filepath)
            parent_dir = os.path.basename(dirname)
            short_path: str = os.path.join(parent_dir, basename)
            line_num: int = line_entry.GetLine()
            source_info = f"{filepath}:{line_num}"
            lines: Optional[List[str]] = self._get_file_lines(filepath)
            if lines and 0 < line_num <= len(lines):
                source_line = lines[line_num - 1].strip()

        current_source_key: str = f"{source_info};{source_line}"
        if hasattr(self, "_last_source_key") and current_source_key == self._last_source_key:
            source_info = ""
            source_line = ""
        self._last_source_key = current_source_key

        parsed_operands = parse_operands(operands, max_ops=4)
        registers: List[str] = self._capture_register_values(frame, mnemonic, parsed_operands)

        if source_line:
            self.logger.info(
                "0x%x %s %s ; %s // %s; Debug: %s",
                pc,
                mnemonic,
                operands,
                source_info,
                source_line,
                ", ".join(registers),
            )
        else:
            self.logger.info("0x%x %s %s ; %s; Debug %s", pc, mnemonic, operands, source_info, ", ".join(registers))

        return self._determine_step_action(mnemonic, parsed_operands, frame)

    def _capture_register_values(self, frame: lldb.SBFrame, mnemonic: str, parsed_operands) -> List[str]:
        registers: List[str] = []
        for operand in parsed_operands:
            if operand.type == OperandType.REGISTER:
                normalized_reg: str = operand.value
                if normalized_reg == "x29":
                    normalized_reg = "fp"
                elif normalized_reg == "x30":
                    normalized_reg = "lr"

                reg_val: lldb.SBValue = frame.FindRegister(normalized_reg)
                if not reg_val or not reg_val.IsValid():
                    self.logger.warning("Invalid register: %s", normalized_reg)
                    continue
                registers.append(f"${normalized_reg}={reg_val.value}")
            elif operand.type == OperandType.MEMREF:
                memref: Dict[str, Any] = operand.value
                base_reg: str = memref["base_reg"]
                # 规范化寄存器名称
                if base_reg == "x29":
                    base_reg = "fp"
                elif base_reg == "x30":
                    base_reg = "lr"

                base_reg_val: lldb.SBValue = frame.FindRegister(base_reg)
                base_value: int = 0
                if not base_reg_val or not base_reg_val.IsValid():
                    self.logger.error("Failed to get base register: %s", base_reg)
                else:
                    base_value = base_reg_val.unsigned

                # 解析偏移量
                offset_value: int = 0
                if "offset" in memref and memref["offset"]:
                    try:
                        offset_str: str = memref["offset"].strip("#")
                        offset_value = int(offset_str, 0)  # 自动识别16进制或10进制
                    except ValueError:
                        self.logger.error("Failed to parse offset: %s", memref["offset"])

                # 解析索引寄存器
                index_value: int = 0
                index_reg: Optional[str] = None
                if "index" in memref and memref["index"]:
                    index_reg = memref["index"]
                    if index_reg == "x29":
                        index_reg = "fp"
                    elif index_reg == "x30":
                        index_reg = "lr"
                    index_reg_val: lldb.SBValue = frame.FindRegister(index_reg)
                    if not index_reg_val or not index_reg_val.IsValid():
                        self.logger.error("Failed to get index register: %s", index_reg)
                    else:
                        index_value = index_reg_val.unsigned

                    # 解析移位操作
                    if "shift_op" in memref and "shift_amount" in memref:
                        shift_op: str = memref["shift_op"]
                        shift_amount_str: str = memref["shift_amount"].strip("#")
                        try:
                            shift_amount: int = int(shift_amount_str, 0)
                        except ValueError:
                            self.logger.error("Failed to parse shift_amount: %s", memref["shift_amount"])
                            shift_amount = 0

                        # 应用移位操作
                        if shift_op == "lsl":
                            index_value = index_value << shift_amount
                        elif shift_op == "lsr":
                            index_value = index_value >> shift_amount
                        elif shift_op == "asr":
                            # 算术右移（带符号扩展）
                            if index_value & (1 << 63):  # 检查最高位
                                sign_ext = (1 << 64) - (1 << (64 - shift_amount))
                                index_value = (index_value >> shift_amount) | sign_ext
                            else:
                                index_value = index_value >> shift_amount
                        elif shift_op == "ror":
                            # 循环右移
                            shift_amount %= 64  # 确保在0-63范围内
                            index_value = (index_value >> shift_amount) | (index_value << (64 - shift_amount))
                            index_value &= 0xFFFFFFFFFFFFFFFF  # 限制为64位
                        else:
                            self.logger.warning("Unsupported shift operator: %s", shift_op)

                addr: int = base_value + offset_value + index_value

                # 构造表达式字符串
                expr_str: str = f"[{base_reg}"
                if offset_value != 0:
                    expr_str += f" + {offset_value:#x}"
                if index_reg:
                    expr_str += f" + {index_reg}"
                    if "shift_op" in memref:
                        expr_str += f" {memref['shift_op']} #{memref['shift_amount'].strip('#')}"
                expr_str += "]"
                # 确定读取的字节数
                if mnemonic.endswith("b"):
                    bytesize: int = 1
                elif mnemonic.endswith("h"):
                    bytesize = 2
                elif mnemonic.endswith("w"):
                    bytesize = 4
                else:
                    bytesize = self.tracer.target.GetAddressByteSize()
                error = lldb.SBError()
                value: int = self.tracer.process.ReadUnsignedFromMemory(addr, bytesize, error)
                if error.Success():
                    registers.append(f"{expr_str} = [0x{addr:016x}] = 0x{value:x}")
                else:
                    self.logger.error("Failed to read memory at address 0x%x: %s", addr, error.GetCString())
        return registers

    def _determine_step_action(self, mnemonic: str, parsed_operands, frame: lldb.SBFrame) -> StepAction:
        if mnemonic in ("br", "braa", "brab", "blraa"):
            if parsed_operands[0].type == OperandType.REGISTER:
                reg_val: lldb.SBValue = frame.FindRegister(parsed_operands[0].value)
                if not reg_val.IsValid():
                    self.logger.warning("Failed to get register value: %s", parsed_operands[0].value)
                    return StepAction.CONTINUE
                jump_to: int = reg_val.unsigned

                sym_name: str = self.tracer.modules.get_addr_symbol(jump_to)
                if self.tracer.modules.should_skip_address(
                    jump_to
                ) or self.tracer.source_ranges.should_skip_source_address(jump_to):
                    self.logger.info("%s Skipping jump to register value: %s", mnemonic, sym_name)
                    return StepAction.STEP_OVER
                self.logger.info("%s Jumping to register value: %s", mnemonic, sym_name)
        elif mnemonic == "b":
            self.logger.info("%s Branching to address: %s", mnemonic, parsed_operands[0].value)
        elif mnemonic == "bl":
            target_addr: str = parsed_operands[0].value
            raw_target_addr: int = int(target_addr, 16)

            sym_name: str = self.tracer.modules.get_addr_symbol(raw_target_addr)
            if self.tracer.modules.should_skip_address(
                raw_target_addr
            ) or self.tracer.source_ranges.should_skip_source_address(raw_target_addr):
                self.logger.info("%s Skipping branch to address: %s, %s", mnemonic, target_addr, sym_name)
                return StepAction.STEP_OVER
            self.logger.info("%s Branching to address: %s, %s", mnemonic, target_addr, sym_name)
        elif mnemonic == "ret":
            self.logger.info("Returning from function: %s", frame.symbol.name if frame.symbol else "unknown")

        return StepAction.STEP_IN
