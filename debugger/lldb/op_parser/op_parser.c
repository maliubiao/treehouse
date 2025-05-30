#include "op_parser.h"
#include <ctype.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int parse_hex(const char *str, uint64_t *value) {
  if (str == NULL || *str == '\0')
    return 0;

  char *endptr;
  *value = strtoull(str, &endptr, 16);
  return (*endptr == '\0') ? 1 : 0;
}

int parse_disassembly_line(const char *line, DisasmLine *disasm_line) {
  if (line == NULL || disasm_line == NULL)
    return 0;

  memset(disasm_line, 0, sizeof(DisasmLine));

  LineParseState state = LINE_STATE_START;
  int pos = 0;
  char buffer[128] = {0};
  int buf_pos = 0;
  int addr_parsed = 0;

  while (line[pos] != '\0') {
    char c = line[pos];

    switch (state) {
    case LINE_STATE_START:
      if (c == '0' && line[pos + 1] == 'x') {
        state = LINE_STATE_IN_ADDR;
        buffer[buf_pos++] = c;
        buffer[buf_pos++] = line[++pos]; // 跳过x
      } else if (addr_parsed && isalpha(c)) {
        state = LINE_STATE_IN_OPCODE;
        disasm_line->opcode[buf_pos++] = c;
      }
      break;

    case LINE_STATE_IN_ADDR:
      if (isxdigit(c)) {
        buffer[buf_pos++] = c;
      } else if (c == ' ' || c == '<') {
        if (!parse_hex(buffer, &disasm_line->addr)) {
          return 0;
        }
        addr_parsed = 1;
        buf_pos = 0;
        memset(buffer, 0, sizeof(buffer));
        state = (c == '<') ? LINE_STATE_IN_FUNC : LINE_STATE_AFTER_ADDR;
      }
      break;

    case LINE_STATE_AFTER_ADDR:
      if (c == '<') {
        state = LINE_STATE_IN_FUNC;
      } else if (isalpha(c)) {
        state = LINE_STATE_IN_OPCODE;
        disasm_line->opcode[buf_pos++] = c;
      }
      break;

    case LINE_STATE_IN_FUNC:
      if (c == '>') {
        state = LINE_STATE_AFTER_FUNC;
      }
      break;

    case LINE_STATE_AFTER_FUNC:
      if (isalpha(c)) {
        state = LINE_STATE_IN_OPCODE;
        disasm_line->opcode[buf_pos++] = c;
      }
      break;

    case LINE_STATE_IN_OPCODE:
      if (isspace(c)) {
        disasm_line->opcode[buf_pos] = '\0';
        buf_pos = 0;
        state = LINE_STATE_IN_OPERANDS;
        while (line[pos] && isspace(line[pos]))
          pos++;
        pos--; // 补偿循环的pos++
      } else {
        disasm_line->opcode[buf_pos++] = c;
      }
      break;

    case LINE_STATE_IN_OPERANDS:
      if (c != '\0') {
        disasm_line->operand_count =
            parse_operands(line + pos, disasm_line->operands, 4);
        return 1;
      }
      break;
    }

    pos++;
  }

  return 1;
}

int parse_disassembly(const char *disassembly, DisasmLine *lines,
                      int max_lines) {
  if (disassembly == NULL || lines == NULL || max_lines <= 0)
    return 0;

  int line_count = 0;
  const char *line_start = disassembly;
  const char *line_end;

  while ((line_end = strchr(line_start, '\n')) != NULL &&
         line_count < max_lines) {
    char line[256] = {0};
    strncpy(line, line_start, line_end - line_start);

    if (parse_disassembly_line(line, &lines[line_count])) {
      line_count++;
    }

    line_start = line_end + 1;
  }

  // 处理最后一行
  if (*line_start && line_count < max_lines) {
    if (parse_disassembly_line(line_start, &lines[line_count])) {
      line_count++;
    }
  }

  return line_count;
}

int parse_operands(const char *str, Operand *ops, int max_ops) {
  ParseState state = STATE_START;
  int len = strlen(str);
  int pos = 0;
  char buffer[128] = {0};
  int buf_pos = 0;
  int op_count = 0;

  MemRef memref = {0};

  // 预处理：去除注释和前后空格
  char clean_str[256];
  const char *comment = strchr(str, ';');
  if (comment) {
    strncpy(clean_str, str, comment - str);
    clean_str[comment - str] = '\0';
  } else {
    strcpy(clean_str, str);
  }

  // 去除前后空格
  len = strlen(clean_str);
  while (len > 0 && isspace(clean_str[len - 1]))
    clean_str[--len] = '\0';
  const char *start = clean_str;
  while (*start && isspace(*start))
    start++;
  len = strlen(start);
  if (start != clean_str)
    memmove(clean_str, start, len + 1);

  while (pos <= len && op_count < max_ops) {
    char c = pos < len ? clean_str[pos] : '\0';

    switch (state) {
    case STATE_START:
      if (c == 'x' || c == 'w' || c == 's' || c == 'd') {
        state = STATE_IN_REG;
        buffer[buf_pos++] = c;
      } else if (c == '#') {
        state = STATE_IN_IMM;
        buffer[buf_pos++] = c;
      } else if (c == '[') {
        state = STATE_IN_MEM_BASE;
      } else if (c == '0' && pos + 1 < len && clean_str[pos + 1] == 'x') {
        state = STATE_IN_ADDR;
        buffer[buf_pos++] = c;
        buffer[buf_pos++] = clean_str[++pos]; // 跳过x
      } else if (!isspace(c)) {
        state = STATE_IN_OTHER;
        buffer[buf_pos++] = c;
      }
      break;

    case STATE_IN_REG:
      if (isalnum(c)) {
        buffer[buf_pos++] = c;
      } else {
        ops[op_count].type = OPERAND_REGISTER;
        strncpy(ops[op_count].value, buffer, buf_pos);
        ops[op_count].value[buf_pos] = '\0';
        op_count++;
        buf_pos = 0;
        memset(buffer, 0, sizeof(buffer));
        state = STATE_START;
        if (c == ',')
          pos++; // 跳过逗号
        continue;
      }
      break;

    case STATE_IN_IMM:
      if (isxdigit(c) || c == 'x') {
        buffer[buf_pos++] = c;
      } else {
        ops[op_count].type = OPERAND_IMMEDIATE;
        strncpy(ops[op_count].value, buffer, buf_pos);
        ops[op_count].value[buf_pos] = '\0';
        op_count++;
        buf_pos = 0;
        memset(buffer, 0, sizeof(buffer));
        state = STATE_START;
        if (c == ',')
          pos++; // 跳过逗号
        continue;
      }
      break;

    case STATE_IN_MEM_BASE:
      if (c == ',' || c == ']' || c == '\0') {
        strncpy(memref.base_reg, buffer, buf_pos);
        memref.base_reg[buf_pos] = '\0';
        buf_pos = 0;
        memset(buffer, 0, sizeof(buffer));

        if (c == ']' || c == '\0') {
          ops[op_count].type = OPERAND_MEMREF;
          memcpy(&ops[op_count].memref, &memref, sizeof(MemRef));
          op_count++;
          memset(&memref, 0, sizeof(memref));
          pos++;
          state = STATE_START;
          continue;
        }
        // 遇到逗号后，检查下一个字符是否是寄存器名
        pos++;
        while (pos < len && isspace(clean_str[pos]))
          pos++;
        if (pos < len && (clean_str[pos] == 'x' || clean_str[pos] == 'w')) {
          state = STATE_IN_MEM_INDEX;
        } else if (clean_str[pos] == '#') {
          state = STATE_IN_MEM_OFFSET;
        } else {
          state = STATE_START;
        }
        pos--; // 补偿循环的pos++
      } else {
        buffer[buf_pos++] = c;
      }
      break;

    case STATE_IN_MEM_INDEX:
      if (c == ',' || c == ']' || c == '\0') {
        strncpy(memref.index_reg, buffer, buf_pos);
        memref.index_reg[buf_pos] = '\0';
        buf_pos = 0;
        memset(buffer, 0, sizeof(buffer));

        if (c == ']' || c == '\0') {
          ops[op_count].type = OPERAND_MEMREF;
          memcpy(&ops[op_count].memref, &memref, sizeof(MemRef));
          op_count++;
          memset(&memref, 0, sizeof(memref));
          pos++;
          state = STATE_START;
          continue;
        }
        // 遇到逗号后，准备解析移位操作
        pos++;
        while (pos < len && isspace(clean_str[pos]))
          pos++;
        state = STATE_IN_MEM_SHIFT;
        pos--; // 补偿循环的pos++
      } else {
        buffer[buf_pos++] = c;
      }
      break;

    case STATE_IN_MEM_SHIFT:
      if (c == ']' || c == '\0') {
        ops[op_count].type = OPERAND_MEMREF;
        memcpy(&ops[op_count].memref, &memref, sizeof(MemRef));
        op_count++;
        memset(&memref, 0, sizeof(memref));
        buf_pos = 0;
        memset(buffer, 0, sizeof(buffer));
        pos++;
        state = STATE_START;
        continue;
      } else if (c == ',') {
        // 跳过逗号，继续解析偏移量
        pos++;
        while (pos < len && isspace(clean_str[pos]))
          pos++;
        state = STATE_IN_MEM_OFFSET;
        pos--; // 补偿循环的pos++
      } else if (isspace(c)) {
        // 跳过空格
      } else if (isalpha(c)) {
        // 解析移位操作符 (lsl, lsr, asr, ror)
        buffer[buf_pos++] = c;
      } else if (c == '#') {
        // 移位量 - 检查是否已经收集了移位操作符
        if (buf_pos > 0) {
          // 保存移位操作符
          buffer[buf_pos] = '\0';
          strncpy(memref.shift_op, buffer, sizeof(memref.shift_op) - 1);
          buf_pos = 0;
        }
        // 开始收集移位量
        state = STATE_IN_MEM_SHIFT_AMOUNT;
        buffer[buf_pos++] = c;
      }
      break;

    case STATE_IN_MEM_SHIFT_AMOUNT:
      if (c == ']' || c == ',' || isspace(c) || c == '\0') {
        // 保存移位量
        buffer[buf_pos] = '\0';
        strncpy(memref.shift_amount, buffer, sizeof(memref.shift_amount) - 1);
        buf_pos = 0;

        if (c == ']' || c == '\0') {
          ops[op_count].type = OPERAND_MEMREF;
          memcpy(&ops[op_count].memref, &memref, sizeof(MemRef));
          op_count++;
          memset(&memref, 0, sizeof(memref));
          state = STATE_START;
          if (c != '\0')
            pos++;
          continue;
        } else if (c == ',') {
          // 后面可能还有偏移量
          state = STATE_IN_MEM_OFFSET;
        } else {
          // 空格后可能是']'或逗号，继续处理
          state = STATE_IN_MEM_SHIFT;
          continue; // 不增加pos，让外层循环处理当前字符
        }
      } else {
        buffer[buf_pos++] = c;
      }
      break;

    case STATE_IN_MEM_OFFSET:
      if (c == ']' || c == '\0') {
        strncpy(memref.offset, buffer, buf_pos);
        memref.offset[buf_pos] = '\0';
        ops[op_count].type = OPERAND_MEMREF;
        memcpy(&ops[op_count].memref, &memref, sizeof(MemRef));
        op_count++;
        memset(&memref, 0, sizeof(memref));
        buf_pos = 0;
        memset(buffer, 0, sizeof(buffer));
        pos++;
        state = STATE_START;
        continue;
      } else {
        buffer[buf_pos++] = c;
      }
      break;

    case STATE_IN_ADDR:
      if (isxdigit(c)) {
        buffer[buf_pos++] = c;
      } else {
        ops[op_count].type = OPERAND_ADDRESS;
        strncpy(ops[op_count].value, buffer, buf_pos);
        ops[op_count].value[buf_pos] = '\0';
        op_count++;
        buf_pos = 0;
        memset(buffer, 0, sizeof(buffer));
        state = STATE_START;
        if (c == ',')
          pos++; // 跳过逗号
        continue;
      }
      break;

    case STATE_IN_OTHER:
      if (c == ',' || c == ' ' || c == '\0') {
        ops[op_count].type = OPERAND_OTHER;
        strncpy(ops[op_count].value, buffer, buf_pos);
        ops[op_count].value[buf_pos] = '\0';
        op_count++;
        buf_pos = 0;
        memset(buffer, 0, sizeof(buffer));
        state = STATE_START;
        if (c == ',')
          pos++; // 跳过逗号
        continue;
      }
      buffer[buf_pos++] = c;
      break;
    }

    pos++;
  }

  // 处理最后一个操作数
  if (state == STATE_IN_MEM_BASE || state == STATE_IN_MEM_INDEX ||
      state == STATE_IN_MEM_OFFSET || state == STATE_IN_MEM_SHIFT ||
      state == STATE_IN_MEM_SHIFT_AMOUNT) {
    if (state == STATE_IN_MEM_SHIFT && buf_pos > 0) {
      // 处理未保存的移位操作符
      buffer[buf_pos] = '\0';
      strncpy(memref.shift_op, buffer, sizeof(memref.shift_op) - 1);
    } else if (state == STATE_IN_MEM_SHIFT_AMOUNT && buf_pos > 0) {
      // 处理未保存的移位量
      buffer[buf_pos] = '\0';
      strncpy(memref.shift_amount, buffer, sizeof(memref.shift_amount) - 1);
    }

    ops[op_count].type = OPERAND_MEMREF;
    memcpy(&ops[op_count].memref, &memref, sizeof(MemRef));
    op_count++;
  }

  return op_count;
}

const char *operand_type_to_str(OperandType type) {
  switch (type) {
  case OPERAND_REGISTER:
    return "REGISTER";
  case OPERAND_IMMEDIATE:
    return "IMMEDIATE";
  case OPERAND_MEMREF:
    return "MEMREF";
  case OPERAND_ADDRESS:
    return "ADDRESS";
  default:
    return "OTHER";
  }
}