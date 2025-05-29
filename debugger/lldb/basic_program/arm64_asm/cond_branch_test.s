.arch armv8-a
    .section __TEXT,__cstring
    .align 0
msg_cond:   .asciz "Testing %s condition...\n"
msg_jump:   .asciz "Condition %s met, jumping\n"
msg_nojump: .asciz "Condition %s not met, continuing\n"
eq_str:     .asciz "EQ"
ne_str:     .asciz "NE"
gt_str:     .asciz "GT"
lt_str:     .asciz "LT"
ge_str:     .asciz "GE"
le_str:     .asciz "LE"
cs_str:     .asciz "CS"
cc_str:     .asciz "CC"
mi_str:     .asciz "MI"
pl_str:     .asciz "PL"
vs_str:     .asciz "VS"
vc_str:     .asciz "VC"
hi_str:     .asciz "HI"
ls_str:     .asciz "LS"
hs_str:     .asciz "HS"
lo_str:     .asciz "LO"

    .text
    .align 2
    .globl _run_cond_branch_tests
    .extern _printf
    .extern _sleep

_run_cond_branch_tests:
    stp x29, x30, [sp, -16]!
    
    // Test EQ condition
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, eq_str@PAGE
    add x1, x1, eq_str@PAGEOFF
    bl _printf
    
    mov w0, #1
    mov w1, #1
    cmp w0, w1
    .align 2
    b.eq 1f
    adrp x0, msg_nojump@PAGE
    add x0, x0, msg_nojump@PAGEOFF
    adrp x1, eq_str@PAGE
    add x1, x1, eq_str@PAGEOFF
    bl _printf
    b 2f
1:  .align 2
    adrp x0, msg_jump@PAGE
    add x0, x0, msg_jump@PAGEOFF
    adrp x1, eq_str@PAGE
    add x1, x1, eq_str@PAGEOFF
    bl _printf
2:
    // Test NE condition
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, ne_str@PAGE
    add x1, x1, ne_str@PAGEOFF
    bl _printf
    
    mov w0, #1
    mov w1, #2
    cmp w0, w1
    .align 2
    b.ne 1f
    adrp x0, msg_nojump@PAGE
    add x0, x0, msg_nojump@PAGEOFF
    adrp x1, ne_str@PAGE
    add x1, x1, ne_str@PAGEOFF
    bl _printf
    b 2f
1:  .align 2
    adrp x0, msg_jump@PAGE
    add x0, x0, msg_jump@PAGEOFF
    adrp x1, ne_str@PAGE
    add x1, x1, ne_str@PAGEOFF
    bl _printf
2:
    // Test GT condition (greater than)
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, gt_str@PAGE
    add x1, x1, gt_str@PAGEOFF
    bl _printf
    
    mov w0, #5
    mov w1, #3
    cmp w0, w1
    .align 2
    b.gt 1f
    adrp x0, msg_nojump@PAGE
    add x0, x0, msg_nojump@PAGEOFF
    adrp x1, gt_str@PAGE
    add x1, x1, gt_str@PAGEOFF
    bl _printf
    b 2f
1:  .align 2
    adrp x0, msg_jump@PAGE
    add x0, x0, msg_jump@PAGEOFF
    adrp x1, gt_str@PAGE
    add x1, x1, gt_str@PAGEOFF
    bl _printf
2:
    // Test LT condition (less than)
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, lt_str@PAGE
    add x1, x1, lt_str@PAGEOFF
    bl _printf
    
    mov w0, #2
    mov w1, #4
    cmp w0, w1
    .align 2
    b.lt 1f
    adrp x0, msg_nojump@PAGE
    add x0, x0, msg_nojump@PAGEOFF
    adrp x1, lt_str@PAGE
    add x1, x1, lt_str@PAGEOFF
    bl _printf
    b 2f
1:  .align 2
    adrp x0, msg_jump@PAGE
    add x0, x0, msg_jump@PAGEOFF
    adrp x1, lt_str@PAGE
    add x1, x1, lt_str@PAGEOFF
    bl _printf
2:
    // Test GE condition (greater or equal)
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, ge_str@PAGE
    add x1, x1, ge_str@PAGEOFF
    bl _printf
    
    mov w0, #5
    mov w1, #5
    cmp w0, w1
    .align 2
    b.ge 1f
    adrp x0, msg_nojump@PAGE
    add x0, x0, msg_nojump@PAGEOFF
    adrp x1, ge_str@PAGE
    add x1, x1, ge_str@PAGEOFF
    bl _printf
    b 2f
1:  .align 2
    adrp x0, msg_jump@PAGE
    add x0, x0, msg_jump@PAGEOFF
    adrp x1, ge_str@PAGE
    add x1, x1, ge_str@PAGEOFF
    bl _printf
2:
    // Test LE condition (less or equal)
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, le_str@PAGE
    add x1, x1, le_str@PAGEOFF
    bl _printf
    
    mov w0, #3
    mov w1, #5
    cmp w0, w1
    .align 2
    b.le 1f
    adrp x0, msg_nojump@PAGE
    add x0, x0, msg_nojump@PAGEOFF
    adrp x1, le_str@PAGE
    add x1, x1, le_str@PAGEOFF
    bl _printf
    b 2f
1:  .align 2
    adrp x0, msg_jump@PAGE
    add x0, x0, msg_jump@PAGEOFF
    adrp x1, le_str@PAGE
    add x1, x1, le_str@PAGEOFF
    bl _printf
2:
    // Test CS/HS condition (carry set / unsigned higher or same)
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, cs_str@PAGE
    add x1, x1, cs_str@PAGEOFF
    bl _printf
    
    mov w0, #0xFFFFFFFF
    adds w0, w0, #1  // Set carry flag
    .align 2
    b.cs 1f
    adrp x0, msg_nojump@PAGE
    add x0, x0, msg_nojump@PAGEOFF
    adrp x1, cs_str@PAGE
    add x1, x1, cs_str@PAGEOFF
    bl _printf
    b 2f
1:  .align 2
    adrp x0, msg_jump@PAGE
    add x0, x0, msg_jump@PAGEOFF
    adrp x1, cs_str@PAGE
    add x1, x1, cs_str@PAGEOFF
    bl _printf
2:
    // Test CC/LO condition (carry clear / unsigned lower)
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, cc_str@PAGE
    add x1, x1, cc_str@PAGEOFF
    bl _printf
    
    mov w0, #1
    adds w0, w0, #1  // Clear carry flag
    .align 2
    b.cc 1f
    adrp x0, msg_nojump@PAGE
    add x0, x0, msg_nojump@PAGEOFF
    adrp x1, cc_str@PAGE
    add x1, x1, cc_str@PAGEOFF
    bl _printf
    b 2f
1:  .align 2
    adrp x0, msg_jump@PAGE
    add x0, x0, msg_jump@PAGEOFF
    adrp x1, cc_str@PAGE
    add x1, x1, cc_str@PAGEOFF
    bl _printf
2:
    // Test MI condition (negative)
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, mi_str@PAGE
    add x1, x1, mi_str@PAGEOFF
    bl _printf
    
    mov w0, #-1
    cmp w0, #0
    .align 2
    b.mi 1f
    adrp x0, msg_nojump@PAGE
    add x0, x0, msg_nojump@PAGEOFF
    adrp x1, mi_str@PAGE
    add x1, x1, mi_str@PAGEOFF
    bl _printf
    b 2f
1:  .align 2
    adrp x0, msg_jump@PAGE
    add x0, x0, msg_jump@PAGEOFF
    adrp x1, mi_str@PAGE
    add x1, x1, mi_str@PAGEOFF
    bl _printf
2:
    // Test PL condition (positive or zero)
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, pl_str@PAGE
    add x1, x1, pl_str@PAGEOFF
    bl _printf
    
    mov w0, #1
    cmp w0, #0
    .align 2
    b.pl 1f
    adrp x0, msg_nojump@PAGE
    add x0, x0, msg_nojump@PAGEOFF
    adrp x1, pl_str@PAGE
    add x1, x1, pl_str@PAGEOFF
    bl _printf
    b 2f
1:  .align 2
    adrp x0, msg_jump@PAGE
    add x0, x0, msg_jump@PAGEOFF
    adrp x1, pl_str@PAGE
    add x1, x1, pl_str@PAGEOFF
    bl _printf
2:
    // Test VS condition (overflow set)
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, vs_str@PAGE
    add x1, x1, vs_str@PAGEOFF
    bl _printf
    
    mov w0, #0x7FFFFFFF
    adds w0, w0, #1  // Set overflow
    .align 2
    b.vs 1f
    adrp x0, msg_nojump@PAGE
    add x0, x0, msg_nojump@PAGEOFF
    adrp x1, vs_str@PAGE
    add x1, x1, vs_str@PAGEOFF
    bl _printf
    b 2f
1:  .align 2
    adrp x0, msg_jump@PAGE
    add x0, x0, msg_jump@PAGEOFF
    adrp x1, vs_str@PAGE
    add x1, x1, vs_str@PAGEOFF
    bl _printf
2:
    // Test VC condition (overflow clear)
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, vc_str@PAGE
    add x1, x1, vc_str@PAGEOFF
    bl _printf
    
    mov w0, #1
    adds w0, w0, #1  // Clear overflow
    .align 2
    b.vc 1f
    adrp x0, msg_nojump@PAGE
    add x0, x0, msg_nojump@PAGEOFF
    adrp x1, vc_str@PAGE
    add x1, x1, vc_str@PAGEOFF
    bl _printf
    b 2f
1:  .align 2
    adrp x0, msg_jump@PAGE
    add x0, x0, msg_jump@PAGEOFF
    adrp x1, vc_str@PAGE
    add x1, x1, vc_str@PAGEOFF
    bl _printf
2:
    // Test HI condition (unsigned higher)
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, hi_str@PAGE
    add x1, x1, hi_str@PAGEOFF
    bl _printf
    
    mov w0, #10
    mov w1, #5
    cmp w0, w1
    .align 2
    b.hi 1f
    adrp x0, msg_nojump@PAGE
    add x0, x0, msg_nojump@PAGEOFF
    adrp x1, hi_str@PAGE
    add x1, x1, hi_str@PAGEOFF
    bl _printf
    b 2f
1:  .align 2
    adrp x0, msg_jump@PAGE
    add x0, x0, msg_jump@PAGEOFF
    adrp x1, hi_str@PAGE
    add x1, x1, hi_str@PAGEOFF
    bl _printf
2:
    // Test LS condition (unsigned lower or same)
    adrp x0, msg_cond@PAGE
    add x0, x0, msg_cond@PAGEOFF
    adrp x1, ls_str@PAGE
    add x1, x1, ls_str@PAGEOFF
    bl _printf
    
    mov w0, #3
    mov w1, #5
    cmp w0, w1
    .align 2
    b.ls 1f
    adrp x0, msg_nojump@PAGE
    add x0, x0, msg_nojump@PAGEOFF
    adrp x1, ls_str@PAGE
    add x1, x1, ls_str@PAGEOFF
    bl _printf
    b 2f
1:  .align 2
    adrp x0, msg_jump@PAGE
    add x0, x0, msg_jump@PAGEOFF
    adrp x1, ls_str@PAGE
    add x1, x1, ls_str@PAGEOFF
    bl _printf
2:
    ldp x29, x30, [sp], 16
    ret