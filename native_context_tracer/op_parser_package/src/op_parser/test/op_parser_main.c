#include "op_parser.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

void test_operand_parsing() {
  // 测试原始功能
  struct {
    const char *input;
    OperandType type;
    const char *value;
    const char *base_reg;
    const char *index_reg;
    const char *shift_op;
    const char *shift_amount;
    const char *offset;
  } test_cases[] = {
      {"sp", OPERAND_REGISTER, "sp", "", "", "", "", ""},
      {"[x29, #-0x4]", OPERAND_MEMREF, "", "x29", "", "", "", "#-0x4"},
      {"#0x90", OPERAND_IMMEDIATE, "#0x90", "", "", "", "", ""},
      {"0x10000140c", OPERAND_ADDRESS, "0x10000140c", "", "", "", "", ""},
      {"x8", OPERAND_REGISTER, "x8", "", "", "", "", ""},
      {"#5", OPERAND_IMMEDIATE, "#5", "", "", "", "", ""},
      {"[sp]", OPERAND_MEMREF, "", "sp", "", "", "", ""},
      {"blr    x8", OPERAND_REGISTER, "x8", "", "", "", "", ""},
      {"[x0, x1]", OPERAND_MEMREF, "", "x0", "x1", "", "", ""},
      {"[#0x20]", OPERAND_MEMREF, "", "", "", "", "", "#0x20"},
      {"[, #0x30]", OPERAND_MEMREF, "", "", "", "", "", "#0x30"},
      {"x8, [x8, #0x8]", OPERAND_REGISTER, "x8", "", "", "", "", ""},
      // 新增测试复杂内存引用
      {"[x17, x16, lsl #3]", OPERAND_MEMREF, "", "x17", "x16", "lsl", "#3", ""},
      {"[x1, x2, lsl #1]", OPERAND_MEMREF, "", "x1", "x2", "lsl", "#1", ""},
      {"[x3, x4, lsr #2]", OPERAND_MEMREF, "", "x3", "x4", "lsr", "#2", ""},
      {"[x5, x6, asr #3]", OPERAND_MEMREF, "", "x5", "x6", "asr", "#3", ""},
      {"[x7, x8, ror #4]", OPERAND_MEMREF, "", "x7", "x8", "ror", "#4", ""},
  };

  for (int i = 0; i < sizeof(test_cases) / sizeof(test_cases[0]); i++) {
    Operand ops[4] = {0};
    int count = parse_operands(test_cases[i].input, ops, 4);

    printf("Input: %s\n", test_cases[i].input);
    assert(count > 0 && "Failed to parse operand");

    if (test_cases[i].type == OPERAND_MEMREF) {
      assert(ops[0].type == OPERAND_MEMREF);
      assert(strcmp(ops[0].memref.base_reg, test_cases[i].base_reg) == 0);
      assert(strcmp(ops[0].memref.index_reg, test_cases[i].index_reg) == 0);
      assert(strcmp(ops[0].memref.shift_op, test_cases[i].shift_op) == 0);
      assert(strcmp(ops[0].memref.shift_amount, test_cases[i].shift_amount) ==
             0);
      assert(strcmp(ops[0].memref.offset, test_cases[i].offset) == 0);

      printf(
          "  Operand: MEMREF (base: %s, index: %s, shift: %s %s, offset: %s)\n",
          ops[0].memref.base_reg, ops[0].memref.index_reg,
          ops[0].memref.shift_op, ops[0].memref.shift_amount,
          ops[0].memref.offset);
    } else {
      assert(ops[0].type == test_cases[i].type);
      assert(strcmp(ops[0].value, test_cases[i].value) == 0);
      printf("  Operand: %s (%s)\n", operand_type_to_str(ops[0].type),
             ops[0].value);
    }
    printf("\n");
  }
}

void test_disassembly_parsing() {
  // 测试反汇编解析功能
  const char *disassembly =
      "0x100001240 <+0>:   sub    sp, sp, #0x90\n"
      "0x100001244 <+4>:   stp    x29, x30, [sp, #0x80]\n"
      "0x100001248 <+8>:   add    x29, sp, #0x80\n"
      "0x10000124c <+12>:  stur   wzr, [x29, #-0x4]\n"
      "0x100001250 <+16>:  ldr    x17, [x17, x16, lsl #3]\n";

  DisasmLine lines[5];
  int line_count = parse_disassembly(disassembly, lines, 5);

  printf("\nDisassembly parsing test:\n");
  assert(line_count == 5);

  struct {
    uint64_t addr;
    int offset;
    const char *opcode;
    int operand_count;
  } expected[] = {
      {0x100001240, 0, "sub", 3},  {0x100001244, 4, "stp", 3},
      {0x100001248, 8, "add", 3},  {0x10000124c, 12, "stur", 2},
      {0x100001250, 16, "ldr", 2},
  };

  for (int i = 0; i < line_count; i++) {
    printf("Addr: 0x%llx, Offset: %d, Opcode: %s\n", lines[i].addr,
           lines[i].offset, lines[i].opcode);

    assert(lines[i].addr == expected[i].addr);
    assert(lines[i].offset == expected[i].offset);
    assert(strcmp(lines[i].opcode, expected[i].opcode) == 0);
    assert(lines[i].operand_count == expected[i].operand_count);

    for (int j = 0; j < lines[i].operand_count; j++) {
      if (lines[i].operands[j].type == OPERAND_MEMREF) {
        printf("  Operand %d: %-10s (base: %-8s index: %-8s shift: %-5s %-8s "
               "offset: %s)\n",
               j + 1, operand_type_to_str(lines[i].operands[j].type),
               lines[i].operands[j].memref.base_reg,
               lines[i].operands[j].memref.index_reg,
               lines[i].operands[j].memref.shift_op,
               lines[i].operands[j].memref.shift_amount,
               lines[i].operands[j].memref.offset);
      } else {
        printf("  Operand %d: %-10s (%s)\n", j + 1,
               operand_type_to_str(lines[i].operands[j].type),
               lines[i].operands[j].value);
      }
    }
    printf("\n");
  }
}

int main() {
  test_operand_parsing();
  test_disassembly_parsing();
  printf("All tests passed!\n");
  return 0;
}