#include <stdio.h>
#include <string.h>
#include <ctype.h>
#include <stdlib.h>

typedef enum {
    OPERAND_REGISTER,    // xN 或 wN 寄存器
    OPERAND_IMMEDIATE,   // #立即数
    OPERAND_MEMREF,      // [内存引用]
    OPERAND_ADDRESS,     // 0x 开头的地址
    OPERAND_OTHER        // 未分类
} OperandType;

typedef struct {
    char base_reg[32];   // 基址寄存器
    char offset[32];     // 偏移量
} MemRef;

typedef struct {
    OperandType type;
    union {
        char value[128];     // 通用值存储
        MemRef memref;       // 内存引用结构化数据
    };
} Operand;

typedef enum {
    STATE_START,
    STATE_IN_REG,
    STATE_IN_IMM,
    STATE_IN_MEM_BASE,
    STATE_IN_MEM_OFFSET,
    STATE_IN_ADDR,
    STATE_IN_OTHER
} ParseState;

int parse_operands(const char* str, Operand* ops, int max_ops) {
    ParseState state = STATE_START;
    int len = strlen(str);
    int pos = 0;
    char buffer[128] = {0};
    int buf_pos = 0;
    int op_count = 0;
    
    MemRef memref = { .base_reg = "", .offset = "" };

    // 预处理：去除注释和前后空格
    char clean_str[256];
    const char* comment = strchr(str, ';');
    if (comment) {
        strncpy(clean_str, str, comment - str);
        clean_str[comment - str] = '\0';
    } else {
        strcpy(clean_str, str);
    }
    
    // 去除前后空格
    len = strlen(clean_str);
    while (len > 0 && isspace(clean_str[len-1])) clean_str[--len] = '\0';
    const char *start = clean_str;
    while (*start && isspace(*start)) start++;
    len = strlen(start);
    if (start != clean_str) memmove(clean_str, start, len+1);

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
            } else if (c == '0' && pos+1 < len && clean_str[pos+1] == 'x') {
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
                if (c == ',') pos++; // 跳过逗号
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
                if (c == ',') pos++; // 跳过逗号
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
		    pos ++;
                    state = STATE_START;
                    continue;
                }
                state = STATE_IN_MEM_OFFSET;
                pos++; // 跳过逗号
                while (pos < len && isspace(clean_str[pos])) pos++;
                pos--; // 补偿循环的pos++
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
		pos ++;
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
                if (c == ',') pos++; // 跳过逗号
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
                if (c == ',') pos++; // 跳过逗号
                continue;
            }
            buffer[buf_pos++] = c;
            break;
        }

        pos++;
    }

    return op_count;
}

const char* operand_type_to_str(OperandType type) {
    switch(type) {
        case OPERAND_REGISTER:  return "REGISTER";
        case OPERAND_IMMEDIATE: return "IMMEDIATE";
        case OPERAND_MEMREF:    return "MEMREF";
        case OPERAND_ADDRESS:   return "ADDRESS";
        default:                return "OTHER";
    }
}

int main() {
    const char* examples[] = {
        "sp", "[x29, #-0x4]", "#0x90", "0x10000140c",
        "x8", "#5", "[sp]", 
        "stp    x29, x30, [sp, #0x80]", "blr    x8", "0x10000140c",
        "[x0, x1]", "[#0x20]", "[, #0x30]", "x8, [x8, #0x8]"
    };

    for (int i = 0; i < sizeof(examples)/sizeof(examples[0]); i++) {
        Operand ops[4] = {0};
        int count = parse_operands(examples[i], ops, 4);
        
        printf("Input: %s\n", examples[i]);
        for (int j = 0; j < count; j++) {
            if (ops[j].type == OPERAND_MEMREF) {
                printf("  Operand %d: %-10s (base: %-8s offset: %s)\n", 
                       j+1,
                       operand_type_to_str(ops[j].type),
                       ops[j].memref.base_reg,
                       ops[j].memref.offset);
            } else {
                printf("  Operand %d: %-10s (%s)\n", 
                       j+1,
                       operand_type_to_str(ops[j].type),
                       ops[j].value);
            }
        }
        printf("\n");
    }
    return 0;
}
