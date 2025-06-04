import traceback

import lldb


class BasicStepThreadPlan:
    def __init__(self, thread_plan, step_dict):
        self.thread_plan = thread_plan
        self.thread = thread_plan.GetThread()
        self.steps_taken = 0

        # Handle SBStructuredData properly
        if step_dict.IsValid() and step_dict.GetType() == lldb.eStructuredDataTypeDictionary:
            max_steps_value = step_dict.GetValueForKey("max_steps")
            if max_steps_value.IsValid() and max_steps_value.GetType() == lldb.eStructuredDataTypeInteger:
                self.max_steps = int(max_steps_value.GetIntegerValue())
            else:
                self.max_steps = 10
        else:
            self.max_steps = 10

        self.current_addr = self._get_current_pc()
        self.should_step_counter = 0  # 跟踪should_step调用次数

        # 结构化初始化日志
        self._log_init_info()

    def _log_init_info(self):
        """记录初始化信息"""
        print("\n[BasicStepThreadPlan] Initialized")
        print(f"Thread ID: {self.thread.GetThreadID()}")
        print(f"Initial PC: 0x{self.current_addr:x}")
        print(f"Max steps: {self.max_steps}")
        print("=========================================\n")

    def _get_current_pc(self):
        """安全获取当前PC地址"""
        if not self.thread.IsValid():
            return 0
        frame = self.thread.GetFrameAtIndex(0)
        return frame.GetPC() if frame.IsValid() else 0

    def explains_stop(self, _event):
        """决定是否解释停止事件"""
        return self.steps_taken < self.max_steps

    def is_stale(self):
        """检查计划是否已完成"""
        return self.steps_taken >= self.max_steps

    def should_step(self):
        """是否应该单步执行"""
        return True

    def should_stop(self, _event):
        """决定是否应该停止执行"""
        try:
            self.steps_taken += 1
            current_pc = self._get_current_pc()

            self._log_step_info(current_pc)

            if self.steps_taken >= self.max_steps:
                self._log_completion()
                self.thread_plan.SetPlanComplete(True)
                return True

            return False
        except RuntimeError as e:
            traceback.print_exc()
            print(f"[ERROR] Execution error in should_stop: {str(e)}")
            return True

    def _log_step_info(self, current_pc):
        """记录步骤信息"""
        print("\n=== Step Information ===")
        print(f"Step: {self.steps_taken}/{self.max_steps}")
        print(f"Program Counter: 0x{current_pc:x}")

        process = self.thread.process.target.GetProcess()
        if process.IsValid():
            target = self.thread.process.target
            addr = lldb.SBAddress(current_pc, target)
            instructions = target.ReadInstructions(addr, 1)
            if instructions and len(instructions) > 0:
                print(f"Instruction: {instructions[0]}")
            else:
                print("Instruction: [unreadable]")
        else:
            print("Instruction: [invalid process]")

        print("=======================\n")

    def _log_completion(self):
        """记录计划完成信息"""
        print("\n=== Plan Completed ===")
        print(f"Executed {self.max_steps} steps")
        print("=======================\n")
