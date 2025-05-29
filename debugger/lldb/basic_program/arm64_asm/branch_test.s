.arch armv8-a
    .section __TEXT,__cstring
    .align 0
msg_b:      .asciz "B instruction: jumping from 0x%lx to 0x%lx\n"
msg_bl:     .asciz "BL instruction: calling func1 from 0x%lx, LR=0x%lx\n"
msg_blr:    .asciz "BLR instruction: calling func2 via register from 0x%lx, LR=0x%lx\n"
msg_br:     .asciz "BR instruction: jumping to func3 via register from 0x%lx\n"
msg_ret:    .asciz "RET instruction: returning from 0x%lx to 0x%lx\n"
msg_cond:   .asciz "B.%s instruction: condition %s, jumping from 0x%lx to 0x%lx\n"
msg_nocond: .asciz "B.%s instruction: condition not met, continuing at 0x%lx\n"
msg_sleep:  .asciz "Sleeping for 0.1 second...\n"
msg_tbz:    .asciz "TBZ instruction: bit %d not set, jumping from 0x%lx to 0x%lx\n"
msg_cbz:    .asciz "CBZ instruction: %s zero, jumping from 0x%lx to 0x%lx\n"
eq_str:     .asciz "eq"
ne_str:     .asciz "ne"
gt_str:     .asciz "gt"
lt_str:     .asciz "lt"
ge_str:     .asciz "ge"
le_str:     .asciz "le"
cs_str:     .asciz "cs"
cc_str:     .asciz "cc"
mi_str:     .asciz "mi"
pl_str:     .asciz "pl"
vs_str:     .asciz "vs"
vc_str:     .asciz "vc"
hi_str:     .asciz "hi"
ls_str:     .asciz "ls"
hs_str:     .asciz "hs"
lo_str:     .asciz "lo"
zero_str:   .asciz "is"
notzero_str:.asciz "is not"

    .text
    .align 2
    .globl _run_branch_tests
    .extern _printf
    .extern _sleep
    .extern _usleep

_run_branch_tests:
    stp x29, x30, [sp, -16]!

    // Test unconditional branch (B)
    adrp x0, msg_b@PAGE
    add x0, x0, msg_b@PAGEOFF
    adr x1, .Lafter_b
    bl _printf
    bl _sleep_demo
    .align 2
    b .Lb_target

.Lb_target:
    .align 2
    adrp x0, msg_b@PAGE
    add x0, x0, msg_b@PAGEOFF
    adr x1, .Lb_target
    adr x2, .Lafter_b
    bl _printf
    bl _sleep_demo
    .align 2
    b .Lafter_b

.Lafter_b:
    .align 2
    // Test branch with link (BL)
    adrp x0, msg_bl@PAGE
    add x0, x0, msg_bl@PAGEOFF
    adr x1, .Lafter_bl
    bl _printf
    bl _sleep_demo
    .align 2
    bl func1

.Lafter_bl:
    .align 2
    // Test all condition codes
    mov w0, #1
    mov w1, #1
    cmp w0, w1
    
    // EQ condition
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, eq_str@PAGE
    add x1, x1, eq_str@PAGEOFF
    adrp x2, eq_str@PAGE
    add x2, x2, eq_str@PAGEOFF
    adr x3, .Lafter_cond
    bl _printf
    bl _sleep_demo
    .align 2
    b.eq .Lcond_target

    // NE condition
    mov w0, #1
    mov w1, #2
    cmp w0, w1
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, ne_str@PAGE
    add x1, x1, ne_str@PAGEOFF
    adrp x2, ne_str@PAGE
    add x2, x2, ne_str@PAGEOFF
    adr x3, .Lafter_cond
    bl _printf
    bl _sleep_demo
    .align 2
    b.ne .Lcond_target

    // GT condition (greater than)
    mov w0, #5
    mov w1, #3
    cmp w0, w1
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, gt_str@PAGE
    add x1, x1, gt_str@PAGEOFF
    adrp x2, gt_str@PAGE
    add x2, x2, gt_str@PAGEOFF
    adr x3, .Lafter_cond
    bl _printf
    bl _sleep_demo
    .align 2
    b.gt .Lcond_target

    // LT condition (less than)
    mov w0, #2
    mov w1, #4
    cmp w0, w1
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, lt_str@PAGE
    add x1, x1, lt_str@PAGEOFF
    adrp x2, lt_str@PAGE
    add x2, x2, lt_str@PAGEOFF
    adr x3, .Lafter_cond
    bl _printf
    bl _sleep_demo
    .align 2
    b.lt .Lcond_target

    // GE condition (greater or equal)
    mov w0, #5
    mov w1, #5
    cmp w0, w1
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, ge_str@PAGE
    add x1, x1, ge_str@PAGEOFF
    adrp x2, ge_str@PAGE
    add x2, x2, ge_str@PAGEOFF
    adr x3, .Lafter_cond
    bl _printf
    bl _sleep_demo
    .align 2
    b.ge .Lcond_target

    // LE condition (less or equal)
    mov w0, #3
    mov w1, #5
    cmp w0, w1
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, le_str@PAGE
    add x1, x1, le_str@PAGEOFF
    adrp x2, le_str@PAGE
    add x2, x2, le_str@PAGEOFF
    adr x3, .Lafter_cond
    bl _printf
    bl _sleep_demo
    .align 2
    b.le .Lcond_target

    // Continue with other conditions...
    // CS/HS (carry set / unsigned higher or same)
    mov w0, #0xFFFFFFFF
    adds w0, w0, #1  // Set carry flag
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, cs_str@PAGE
    add x1, x1, cs_str@PAGEOFF
    adrp x2, cs_str@PAGE
    add x2, x2, cs_str@PAGEOFF
    adr x3, .Lafter_cond
    bl _printf
    bl _sleep_demo
    .align 2
    b.cs .Lcond_target

    // CC/LO (carry clear / unsigned lower)
    mov w0, #1
    adds w0, w0, #1  // Clear carry flag
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, cc_str@PAGE
    add x1, x1, cc_str@PAGEOFF
    adrp x2, cc_str@PAGE
    add x2, x2, cc_str@PAGEOFF
    adr x3, .Lafter_cond
    bl _printf
    bl _sleep_demo
    .align 2
    b.cc .Lcond_target

    // MI (negative)
    mov w0, #-1
    cmp w0, #0
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, mi_str@PAGE
    add x1, x1, mi_str@PAGEOFF
    adrp x2, mi_str@PAGE
    add x2, x2, mi_str@PAGEOFF
    adr x3, .Lafter_cond
    bl _printf
    bl _sleep_demo
    .align 2
    b.mi .Lcond_target

    // PL (positive or zero)
    mov w0, #1
    cmp w0, #0
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, pl_str@PAGE
    add x1, x1, pl_str@PAGEOFF
    adrp x2, pl_str@PAGE
    add x2, x2, pl_str@PAGEOFF
    adr x3, .Lafter_cond
    bl _printf
    bl _sleep_demo
    .align 2
    b.pl .Lcond_target

    // VS (overflow set)
    mov w0, #0x7FFFFFFF
    adds w0, w0, #1  // Set overflow
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, vs_str@PAGE
    add x1, x1, vs_str@PAGEOFF
    adrp x2, vs_str@PAGE
    add x2, x2, vs_str@PAGEOFF
    adr x3, .Lafter_cond
    bl _printf
    bl _sleep_demo
    .align 2
    b.vs .Lcond_target

    // VC (overflow clear)
    mov w0, #1
    adds w0, w0, #1  // Clear overflow
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, vc_str@PAGE
    add x1, x1, vc_str@PAGEOFF
    adrp x2, vc_str@PAGE
    add x2, x2, vc_str@PAGEOFF
    adr x3, .Lafter_cond
    bl _printf
    bl _sleep_demo
    .align 2
    b.vc .Lcond_target

    // HI (unsigned higher)
    mov w0, #10
    mov w1, #5
    cmp w0, w1
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, hi_str@PAGE
    add x1, x1, hi_str@PAGEOFF
    adrp x2, hi_str@PAGE
    add x2, x2, hi_str@PAGEOFF
    adr x3, .Lafter_cond
    bl _printf
    bl _sleep_demo
    .align 2
    b.hi .Lcond_target

    // LS (unsigned lower or same)
    mov w0, #3
    mov w1, #5
    cmp w0, w1
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, ls_str@PAGE
    add x1, x1, ls_str@PAGEOFF
    adrp x2, ls_str@PAGE
    add x2, x2, ls_str@PAGEOFF
    adr x3, .Lafter_cond
    bl _printf
    bl _sleep_demo
    .align 2
    b.ls .Lcond_target

.Lcond_target:
    .align 2
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, eq_str@PAGE
    add x1, x1, eq_str@PAGEOFF
    adrp x2, eq_str@PAGE
    add x2, x2, eq_str@PAGEOFF
    adr x3, .Lcond_target
    adr x4, .Lafter_cond
    bl _printf
    bl _sleep_demo

.Lafter_cond:
    .align 2
    // Test branch with link to register (BLR)
    adrp x0, msg_blr@PAGE
    add x0, x0, msg_blr@PAGEOFF
    adr x1, .Lafter_blr
    bl _printf
    bl _sleep_demo
    adr x9, func2
    .align 2
    blr x9

.Lafter_blr:
    .align 2
    // Test branch to register (BR)
    adrp x0, msg_br@PAGE
    add x0, x0, msg_br@PAGEOFF
    adr x1, .Lafter_br
    bl _printf
    bl _sleep_demo
    adr x9, func3
    .align 2
    br x9

.Lafter_br:
    .align 2
    // Test CBZ/CBNZ
    mov x0, #0
    adrp x1, msg_cbz@PAGE
    add x1, x1, msg_cbz@PAGEOFF
    adrp x2, zero_str@PAGE
    add x2, x2, zero_str@PAGEOFF
    adr x3, .Lcbz_target
    bl _printf
    bl _sleep_demo
    .align 2
    cbz x0, .Lcbz_target

.Lcbz_target:
    .align 2
    // Test TBZ/TBNZ
    mov x0, #0x1
    adrp x1, msg_tbz@PAGE
    add x1, x1, msg_tbz@PAGEOFF
    mov x2, #1
    adr x3, .Ltbz_target
    bl _printf
    bl _sleep_demo
    .align 2
    tbz x0, #1, .Ltbz_target

.Ltbz_target:
    .align 2
    mov w0, #0
    ldp x29, x30, [sp], 16
    ret

func1:
    stp x29, x30, [sp, -16]!
    adrp x0, msg_bl@PAGE
    add x0, x0, msg_bl@PAGEOFF
    adr x1, .Lafter_bl
    mov x2, x30
    bl _printf
    bl _sleep_demo
    ldp x29, x30, [sp], 16
    ret

func2:
    stp x29, x30, [sp, -16]!
    adrp x0, msg_blr@PAGE
    add x0, x0, msg_blr@PAGEOFF
    adr x1, .Lafter_blr
    mov x2, x30
    bl _printf
    bl _sleep_demo
    ldp x29, x30, [sp], 16
    ret

func3:
    stp x29, x30, [sp, -16]!
    adrp x0, msg_br@PAGE
    add x0, x0, msg_br@PAGEOFF
    adr x1, .Lafter_br
    bl _printf
    adrp x0, msg_ret@PAGE
    add x0, x0, msg_ret@PAGEOFF
    adr x1, .Lafter_br
    mov x2, x30
    bl _printf
    bl _sleep_demo
    ldp x29, x30, [sp], 16
    ret

_sleep_demo:
    stp x29, x30, [sp, -16]!
    adrp x0, msg_sleep@PAGE
    add x0, x0, msg_sleep@PAGEOFF
    bl _printf
    movz w0, #0x86a0
    movk w0, #0x1, lsl 16
    bl _usleep
    ldp x29, x30, [sp], 16
    ret