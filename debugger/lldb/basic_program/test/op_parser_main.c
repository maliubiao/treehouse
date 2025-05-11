#include "op_parser.h"
#include <stdio.h>

int main() {
  // 测试原始功能
  const char *examples[] = {"sp",        "[x29, #-0x4]",
                            "#0x90",     "0x10000140c",
                            "x8",        "#5",
                            "[sp]",      "stp    x29, x30, [sp, #0x80]",
                            "blr    x8", "0x10000140c",
                            "[x0, x1]",  "[#0x20]",
                            "[, #0x30]", "x8, [x8, #0x8]"};

  for (int i = 0; i < sizeof(examples) / sizeof(examples[0]); i++) {
    Operand ops[4] = {0};
    int count = parse_operands(examples[i], ops, 4);

    printf("Input: %s\n", examples[i]);
    for (int j = 0; j < count; j++) {
      if (ops[j].type == OPERAND_MEMREF) {
        printf("  Operand %d: %-10s (base: %-8s offset: %s)\n", j + 1,
               operand_type_to_str(ops[j].type), ops[j].memref.base_reg,
               ops[j].memref.offset);
      } else {
        printf("  Operand %d: %-10s (%s)\n", j + 1,
               operand_type_to_str(ops[j].type), ops[j].value);
      }
    }
    printf("\n");
  }

  // 测试反汇编解析功能
  const char *disassembly = "0x100001240 <+0>:   sub    sp, sp, #0x90\n"
                            "0x100001244 <+4>:   stp    x29, x30, [sp, #0x80]\n"
                            "0x100001248 <+8>:   add    x29, sp, #0x80\n"
                            "0x10000124c <+12>:  stur   wzr, [x29, #-0x4]\n";

  DisasmLine lines[4];
  int line_count = parse_disassembly(disassembly, lines, 4);

  printf("\nDisassembly parsing test:\n");
  for (int i = 0; i < line_count; i++) {
    printf("Addr: 0x%llx, Opcode: %s\n", lines[i].addr, lines[i].opcode);
    for (int j = 0; j < lines[i].operand_count; j++) {
      if (lines[i].operands[j].type == OPERAND_MEMREF) {
        printf("  Operand %d: %-10s (base: %-8s offset: %s)\n", j + 1,
               operand_type_to_str(lines[i].operands[j].type),
               lines[i].operands[j].memref.base_reg,
               lines[i].operands[j].memref.offset);
      } else {
        printf("  Operand %d: %-10s (%s)\n", j + 1,
               operand_type_to_str(lines[i].operands[j].type),
               lines[i].operands[j].value);
      }
    }
    printf("\n");
  }

  return 0;
}