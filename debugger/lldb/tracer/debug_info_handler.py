import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import lldb
from op_parser import OperandType

from . import sb_value_printer

if TYPE_CHECKING:
    from .core import Tracer


class DebugInfoHandler:
    def __init__(self, tracer: "Tracer") -> None:
        self.tracer: "Tracer" = tracer
        self.logger: logging.Logger = tracer.logger
        self.frame_variables = {}

    def reset_frame_variables(self) -> None:
        self.frame_variables = {}

    def dump_locals(self, frame: lldb.SBFrame, line: int) -> List[str]:
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
                var_value = sb_value_printer.format_sbvalue(var, shallow_aggregate=True)
                self.frame_variables[var_name] = var_value
                varaible_text.append(f"({var.GetType().GetName()}){var_name}={var_value}")
        return varaible_text

    def capture_register_values(self, frame: lldb.SBFrame, mnemonic: str, parsed_operands) -> List[str]:
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
                    # Fallback to general value string (e.g., hex representation for vectors)
                    return [f"${normalized_reg}={reg_val.GetValue()}"]
                except Exception:
                    return [f"${normalized_reg}={reg_val.GetValue()}"]
            # For double precision floating point
            elif normalized_reg.startswith("d"):
                try:
                    as_float = float(reg_val.GetValue())
                    return [f"${normalized_reg}={as_float:.6g}"]
                except (ValueError, TypeError):
                    return [f"${normalized_reg}={reg_val.GetValue()}"]
            # For single precision floating point
            elif normalized_reg.startswith("s"):
                try:
                    as_float = float(reg_val.GetValue())
                    return [f"${normalized_reg}={as_float:.6g}"]
                except (ValueError, TypeError):
                    return [f"${normalized_reg}={reg_val.GetValue()}"]
            else:
                return [f"${normalized_reg}={reg_val.GetValue()}"]
        else:
            # For integer registers
            try:
                # Attempt to convert to int and then hex, falling back to GetValue()
                return [f"${normalized_reg}={hex(int(reg_val.GetValue(), 16))}"]
            except (ValueError, TypeError):
                return [f"${normalized_reg}={reg_val.GetValue()}"]

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
