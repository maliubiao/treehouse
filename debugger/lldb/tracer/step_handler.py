import logging
import os
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import lldb
from op_parser import OperandType, parse_operands

from .events import StepAction

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
        line_entry: lldb.SBLineEntry = frame.GetLineEntry()
        source_info: str = ""
        source_line: str = ""

        if line_entry.IsValid():
            filepath: str = line_entry.GetFileSpec().fullpath
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
        """Capture register and memory values for logging"""
        registers: List[str] = []
        for operand in parsed_operands:
            if operand.type == OperandType.REGISTER:
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
            self.logger.warning("Invalid register: %s", normalized_reg)
            return []
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
            return [f"{expr_str} = [0x{addr:016x}] = 0x{value:x}"]
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

    def _set_return_breakpoint(self, frame: lldb.SBFrame) -> bool:
        """Set a one-shot breakpoint at the return address stored in LR."""
        lr_reg = frame.FindRegister("lr")
        if not lr_reg.IsValid():
            self.logger.warning("Failed to get LR register")
            return False

        lr_value = lr_reg.unsigned
        if lr_value == 0:
            self.logger.warning("LR is 0, cannot set breakpoint")
            return False

        bp: lldb.SBBreakpoint = self.tracer.target.BreakpointCreateByAddress(lr_value)
        if not bp.IsValid():
            self.logger.error("Failed to set breakpoint at address 0x%x", lr_value)
            return False

        bp.SetOneShot(True)
        self.logger.info("Set one-shot breakpoint at 0x%x for return address", lr_value)
        self.tracer.lr_breakpoint_id = bp.GetID()
        return True

    def _determine_step_action(self, mnemonic: str, parsed_operands, frame: lldb.SBFrame) -> StepAction:
        if mnemonic in ("br", "braa", "brab", "blraa", "blr"):
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
                    if mnemonic in ("br", "braa", "brab"):
                        self._set_return_breakpoint(frame)
                    return StepAction.STEP_OVER
                self.logger.info("%s Jumping to register value: %s", mnemonic, sym_name)
        elif mnemonic == "b":
            self._set_return_breakpoint(frame)
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
