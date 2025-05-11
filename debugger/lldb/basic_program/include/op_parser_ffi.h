

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

const char* operand_type_to_str(OperandType type);
int parse_operands(const char* str, Operand* ops, int max_ops);

