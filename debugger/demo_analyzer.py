import time

from debugger.unit_test_generator_decorator import generate_unit_tests


def faulty_sub_function(x):
    """一个会抛出异常的子函数"""
    if x > 150:
        raise ValueError("输入值不能大于 150")
    return x * 10


def complex_sub_function(a, b):
    """一个包含循环和变量变化的子函数"""
    total = a
    for idx in range(b):
        total += idx + 1
        time.sleep(0.01)

    try:
        result = faulty_sub_function(total)
    except ValueError:
        result = -1

    return result


# 使用装饰器自动生成单元测试
@generate_unit_tests(
    target_functions=["complex_sub_function", "faulty_sub_function"], output_dir="generated_tests", auto_confirm=True
)
def main_entrypoint(val1, val2):
    """演示的主入口函数"""
    print("--- 开始执行主函数 ---")
    intermediate_result = complex_sub_function(val1, val2)
    final_result = complex_sub_function(intermediate_result, 0)
    print(f"最终结果: {final_result}")
    print("--- 主函数执行完毕 ---")
    return final_result


if __name__ == "__main__":
    main_entrypoint(10, 20)
