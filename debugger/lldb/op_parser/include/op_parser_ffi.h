typedef enum {
  OPERAND_REGISTER,  // xN 或 wN 寄存器
  OPERAND_IMMEDIATE, // #立即数
  OPERAND_MEMREF,    // [内存引用]
  OPERAND_ADDRESS,   // 0x 开头的地址
  OPERAND_OTHER      // 未分类
} OperandType;

typedef struct {
  char base_reg[32]; // 基址寄存器
  char offset[32];   // 偏移量
} MemRef;

typedef struct {
  OperandType type;
  union {
    char value[128]; // 通用值存储
    MemRef memref;   // 内存引用结构化数据
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

typedef enum {
  LINE_STATE_START,
  LINE_STATE_IN_ADDR,
  LINE_STATE_AFTER_ADDR,
  LINE_STATE_IN_FUNC,
  LINE_STATE_AFTER_FUNC,
  LINE_STATE_IN_OPCODE,
  LINE_STATE_IN_OPERANDS
} LineParseState;

typedef struct {
  uint64_t addr;
  char opcode[32];
  Operand operands[4];
  int operand_count;
} DisasmLine;

const char *operand_type_to_str(OperandType type);
int parse_operands(const char *str, Operand *ops, int max_ops);
int parse_disassembly_line(const char *line, DisasmLine *disasm_line);
int parse_disassembly(const char *disassembly, DisasmLine *lines,
                      int max_lines);