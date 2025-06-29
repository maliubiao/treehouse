import time

from debugger.analyzable_tracer import analyzable_trace
from debugger.call_analyzer import CallAnalyzer

# 1. 创建一个 CallAnalyzer 实例来收集数据
analyzer = CallAnalyzer()


def faulty_sub_function(x):
    """一个会抛出异常的子函数"""
    # 修改了判断条件，以便在第二次调用时触发异常
    if x > 150:
        raise ValueError("输入值不能大于 150")
    return x * 10


def complex_sub_function(a, b):
    """一个包含循环和变量变化的子函数"""
    total = a
    for i in range(b):
        total += i + 1
        time.sleep(0.01)  # 模拟耗时操作

    # 调用另一个子函数
    try:
        result = faulty_sub_function(total)
    except ValueError as e:
        result = -1  # 捕获异常并返回一个默认值

    return result


# 2. 使用新的 @analyzable_trace 装饰器，并传入 analyzer 实例
#    我们启用 enable_var_trace 来捕获行级变量变化
@analyzable_trace(analyzer=analyzer, enable_var_trace=True, report_name="demo_analyzer_report.html")
def main_entrypoint(val1, val2):
    """演示的主入口函数"""
    print("--- 开始执行主函数 ---")
    # 第一次调用，正常执行
    # total = 10 + 1 + 2 + 3 = 16. faulty_sub_function(16) -> 160
    intermediate_result = complex_sub_function(val1, 3)

    # 第二次调用，这次会触发并捕获异常
    # total = 160. faulty_sub_function(160) -> raises ValueError
    # complex_sub_function catches it and returns -1
    final_result = complex_sub_function(intermediate_result, 0)

    print(f"最终结果: {final_result}")
    print("--- 主函数执行完毕 ---")
    return final_result


if __name__ == "__main__":
    # 3. 运行被装饰的函数
    main_entrypoint(10, 20)  # val2 is not used in main_entrypoint, but passed to demonstrate arg capture

    print("\n" + "=" * 50)
    print("          函数调用分析结果")
    print("=" * 50 + "\n")

    # 4. 从 analyzer 中查询特定函数的调用记录
    # 注意：tracer 格式化后的文件名可能与原始路径不同
    # 我们需要从 analyzer 的数据中找到正确的文件名
    filename = ""

    if analyzer.call_trees:
        # 获取第一个记录的文件名作为示例
        filename = next(iter(analyzer.call_trees))

    func_name = "main_entrypoint"
    main_calls = analyzer.get_calls_by_function(filename, func_name)

    if not main_calls:
        print(f"未找到函数 {func_name} 在 {filename} 中的调用记录。")
    else:
        # 5. 打印调用树，展示捕获到的详细信息
        for i, call_record in enumerate(main_calls):
            print(f"--- 第 {i + 1} 次调用 '{func_name}' 的详细记录 ---\n")
            print(analyzer.pretty_print_call(call_record))
            print("\n" + "-" * 50 + "\n")

    # 6. 演示如何利用这些数据生成单元测试
    print("\n" + "=" * 50)
    print("          单元测试生成思路")
    print("=" * 50 + "\n")

    # 假设我们想为 complex_sub_function 生成测试
    complex_func_calls = analyzer.get_calls_by_function(filename, "complex_sub_function")
    if complex_func_calls:
        # 获取第一次调用
        first_call = complex_func_calls[0]
        args = first_call["args"]
        retval = first_call["return_value"]

        print("💡 根据第一次调用 complex_sub_function(a=10, b=3)，可以生成以下测试：")
        print(f"   - 输入: a={args['a']}, b={args['b']}")
        print(f"  - 期望输出: {retval}")
        print("   - 子调用 'faulty_sub_function' 被调用，且其行为也被记录，可以用于 Mock。")
        print("\n   示例测试代码 (需要手动导入 unittest.mock):")
        print("   def test_complex_sub_function_first_case(self):")
        print("       # 模拟其子调用")
        print("       # from unittest.mock import patch, MagicMock")
        print("       # import your_module")
        print("       mock_faulty_sub = MagicMock(return_value=160)")
        print("       with patch('your_module.faulty_sub_function', mock_faulty_sub):")
        # 注意：这里的参数值是字符串，在生成代码时可能需要类型转换
        print(f"          self.assertEqual(your_module.complex_sub_function({args['a']}, {args['b']}), {retval})")
        print(f"          mock_faulty_sub.assert_called_once_with(16)")

        # 获取第二次调用，这次内部捕获了异常
        second_call = complex_func_calls[1]
        args2 = second_call["args"]
        retval2 = second_call["return_value"]

        print("\n💡 根据第二次调用 complex_sub_function(a=160, b=0)，可以生成另一个测试用例：")
        print(f"   - 输入: a={args2['a']}, b={args2['b']}")
        print(f"   - 期望输出: {retval2} (因为内部捕获了异常)")
        print("   - 子调用 'faulty_sub_function' 抛出了 ValueError，这也可以被验证。")
        print("\n   示例测试代码:")
        print("   def test_complex_sub_function_exception_case(self):")
        print("       # 模拟子调用抛出异常")
        print("       mock_faulty_sub = MagicMock(side_effect=ValueError('输入值不能大于 150'))")
        print("       with patch('your_module.faulty_sub_function', mock_faulty_sub):")
        print(f"          self.assertEqual(your_module.complex_sub_function({args2['a']}, {args2['b']}), {retval2})")
        print(f"          mock_faulty_sub.assert_called_once_with(160)")

    # 7. 将完整的分析报告保存到文件
    analyzer.generate_report("call_analysis_report.json")
