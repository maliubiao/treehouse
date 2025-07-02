import time

# [NEW] 为了更清晰的API，我们通常会创建一个 presets.py 文件来存放快捷装饰器。
# 此处为了演示，我们直接从主模块导入别名。
from debugger.unit_test_generator_decorator import generate_unit_tests


def faulty_sub_function(x):
    """
    一个简单的子函数，其行为依赖于输入值。
    - 当输入大于150时，它会抛出ValueError。
    - 否则，它返回输入值的10倍。
    这是测试生成器需要处理的两种独特执行路径：正常返回和异常退出。
    """
    if x > 150:
        # 路径 1: 异常退出
        raise ValueError("输入值不能大于 150")
    # 路径 2: 正常返回
    return x * 10


def complex_sub_function(a, b):
    """
    一个包含业务逻辑、循环和异常处理的复杂函数。
    它调用了另一个可能失败的函数(faulty_sub_function)，并对异常进行了捕获和处理。
    这同样会产生两种主要的执行路径。
    """
    total = a
    for idx in range(b):
        total += idx + 1
        time.sleep(0.01)  # 模拟耗时操作

    try:
        # 调用 faulty_sub_function。
        # CallAnalyzer 需要能正确跟踪到这次调用，并记录其是正常返回还是异常退出。
        result = faulty_sub_function(total)
    except ValueError:
        # 路径 A: 内部调用失败，函数通过异常处理块返回。
        result = -1

    # 路径 B: 内部调用成功，函数正常返回。
    return result


# [REFACTORED] 使用更智能的装饰器。
# - 我们不再需要手动指定 `target_files`。装饰器会自动将被装饰函数所在的文件加入追踪列表。
# - 我们仍然可以覆盖默认参数，比如 `target_functions`, `auto_confirm` 等。
# - `target_functions` 指定了我们关心的具体函数。新版装饰器会自动把被装饰的
#   入口函数 'main_entrypoint' 也加入到生成列表中，如果提供了该列表。
@generate_unit_tests(
    target_functions=["complex_sub_function", "faulty_sub_function"],
    output_dir="generated_tests",
    report_dir="call_reports",
    auto_confirm=True,
    trace_llm=True,
    num_workers=2,
)
def main_entrypoint(val1, val2):
    """
    演示的主入口函数。
    它的执行将触发对目标函数的多次调用，覆盖正常和异常路径，
    从而为单元测试生成提供丰富的运行时数据。
    """
    print("--- 开始执行主函数 ---")

    # 场景 1: 触发目标函数的“异常/失败”路径。
    # - complex_sub_function(10, 20) 被调用 -> total = 220。
    # - faulty_sub_function(220) 被调用 -> 触发 ValueError。
    # - complex_sub_function 捕获异常，返回 -1。
    # [预期测试 1]: faulty_sub_function(220) -> raises ValueError。
    # [预期测试 2]: complex_sub_function(10, 20) -> returns -1。
    print("\n[场景 1] 测试目标函数的“失败”路径...")
    intermediate_result = complex_sub_function(val1, val2)
    print(f"第一次调用 complex_sub_function 的结果: {intermediate_result}")

    # 场景 2: 触发目标函数的“正常/成功”路径。
    # - complex_sub_function(-1, 0) 被调用 -> total = -1。
    # - faulty_sub_function(-1) 被调用 -> 返回 -10。
    # - complex_sub_function 正常返回 -10。
    # [预期测试 3]: faulty_sub_function(-1) -> returns -10。
    # [预期测试 4]: complex_sub_function(-1, 0) -> returns -10。
    print("\n[场景 2] 测试目标函数的“成功”路径...")
    final_result = complex_sub_function(intermediate_result, 0)
    print(f"第二次调用 complex_sub_function 的结果: {final_result}")

    # 注意：即使我们再次以相同的参数调用，新的去重逻辑也不会生成重复的测试用例。
    print("\n[场景 3] 重复调用，预期不会产生新的测试用例...")
    complex_sub_function(val1, val2)
    print("第三次调用 complex_sub_function 完成。")

    # 由于入口函数 'main_entrypoint' 被自动加入测试目标，也会为其生成测试。
    # [预期测试 5]: main_entrypoint(10, 20) -> returns final_result。
    print("\n--- 主函数执行完毕 ---")
    return final_result


if __name__ == "__main__":
    # 运行此脚本将执行 main_entrypoint。
    # 程序正常退出时，注册的 atexit 回调函数将被触发，
    # 自动开始对 `target_functions` 列表中的函数（以及main_entrypoint自身）生成单元测试。
    # UnitTestGenerator 现在将根据 `num_workers` 参数在内部管理并行生成。
    main_entrypoint(10, 20)
