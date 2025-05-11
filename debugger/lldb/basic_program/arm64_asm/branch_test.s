.arch armv8-a
    .text
    .align 2
    .global _main
    .extern _printf
    .extern _sleep
    .extern _usleep

msg_b:      .asciz "B instruction: jumping from 0x%lx to 0x%lx\n"
msg_bl:     .asciz "BL instruction: calling func1 from 0x%lx, LR=0x%lx\n"
msg_blr:    .asciz "BLR instruction: calling func2 via register from 0x%lx, LR=0x%lx\n"
msg_br:     .asciz "BR instruction: jumping to func3 via register from 0x%lx\n"
msg_ret:    .asciz "RET instruction: returning from 0x%lx to 0x%lx\n"
msg_cond:   .asciz "B.eq instruction: condition met, jumping from 0x%lx to 0x%lx\n"
msg_nocond: .asciz "B.eq instruction: condition not met, continuing at 0x%lx\n"
msg_sleep:  .asciz "Sleeping for 0.5 second...\n"

_main:
    stp x29, x30, [sp, -16]!

    adr x0, msg_b
    adr x1, .Lafter_b
    bl _printf
    b .Lb_target

.Lb_target:
    adr x0, msg_b
    adr x1, .Lb_target
    adr x2, .Lafter_b
    bl _printf
    bl _sleep_demo
    b .Lafter_b

.Lafter_b:
    adr x0, msg_bl
    adr x1, .Lafter_bl
    bl _printf
    bl _sleep_demo
    bl func1

.Lafter_bl:
    mov w0, #1
    mov w1, #1
    cmp w0, w1
    adr x0, msg_cond
    adr x1, .Lafter_cond
    bl _printf
    bl _sleep_demo
    b.eq .Lcond_target

    adr x0, msg_nocond
    adr x1, .Lafter_cond
    bl _printf
    bl _sleep_demo
    b .Lafter_cond

.Lcond_target:
    adr x0, msg_cond
    adr x1, .Lcond_target
    adr x2, .Lafter_cond
    bl _printf
    bl _sleep_demo

.Lafter_cond:
    adr x0, msg_blr
    adr x1, .Lafter_blr
    bl _printf
    bl _sleep_demo
    adr x9, func2
    blr x9

.Lafter_blr:
    adr x0, msg_br
    adr x1, .Lafter_br
    bl _printf
    bl _sleep_demo
    adr x9, func3
    br x9

.Lafter_br:
    mov w0, #0
    ldp x29, x30, [sp], 16
    ret

func1:
    stp x29, x30, [sp, -16]!
    adr x0, msg_bl
    adr x1, .Lafter_bl
    mov x2, x30
    bl _printf
    bl _sleep_demo
    ldp x29, x30, [sp], 16
    ret

func2:
    stp x29, x30, [sp, -16]!
    adr x0, msg_blr
    adr x1, .Lafter_blr
    mov x2, x30
    bl _printf
    bl _sleep_demo
    ldp x29, x30, [sp], 16
    ret

func3:
    stp x29, x30, [sp, -16]!
    adr x0, msg_br
    adr x1, .Lafter_br
    bl _printf
    adr x0, msg_ret
    adr x1, .Lafter_br
    mov x2, x30
    bl _printf
    bl _sleep_demo
    ldp x29, x30, [sp], 16
    ret

_sleep_demo:
    stp x29, x30, [sp, -16]!
    adr x0, msg_sleep
    bl _printf
    ldr w0, =500000  // 修正立即数加载方式
    bl _usleep
    ldp x29, x30, [sp], 16
    ret