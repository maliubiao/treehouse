#include <iostream>
#include <thread>
#include <vector>


/**
 * @brief 计算整数的阶乘
 * @param n 输入整数（n >= 0）
 * @return int 返回n的阶乘结果
 * @details
 * ## 工作原理
 * 使用递归算法计算阶乘：
 * 1. 基线条件：n <= 1时返回1
 * 2. 递归步骤：返回n乘以(n-1)的阶乘
 *
 * ## 调用关系
 * [factorial] -> [factorial] 递归调用自身
 * [factorial] <- [print_thread_info] 被线程函数调用
 *
 * ## 异常处理
 * 当n为负数时可能产生错误结果（未做参数校验）
 */
int factorial(int n) {
    fprintf(stderr, "[ENTER] > factorial at %s:%d\n", __FILE__, __LINE__);
    if (n <= 1) {
        fprintf(stderr, "[LEAVE] < factorial at %s:%d\n", __FILE__, __LINE__);
        return 1;
    }
    fprintf(stderr, "[CALL] 将调用 factorial [计算整数的阶乘] at %s:%d\n", __FILE__, __LINE__);
    int result = n * factorial(n - 1);
    fprintf(stderr, "[LEAVE] < factorial at %s:%d\n", __FILE__, __LINE__);
    return result;
}


/**
 * @brief 打印线程信息并计算阶乘
 * @param thread_id 线程标识号（1-5）
 * @details
 * ## 工作原理
 * 1. 输出线程启动信息
 * 2. 调用factorial计算当前线程ID的阶乘
 * 3. 输出计算结果
 *
 * ## 调用关系
 * [print_thread_info] -> [factorial] 进行阶乘计算
 * [print_thread_info] <- [main] 被主函数创建的线程调用
 *
 * ## 副作用
 * - 向标准输出写入数据
 * - 可能产生控制台输出延迟
 */
void print_thread_info(int thread_id) {
    fprintf(stderr, "[ENTER] > print_thread_info at %s:%d\n", __FILE__, __LINE__);
    std::cout << "Thread " << thread_id << " started" << std::endl;
    fprintf(stderr, "[CALL] 将调用 factorial [计算整数的阶乘] at %s:%d\n", __FILE__, __LINE__);
    int result = factorial(thread_id);
    std::cout << "Thread " << thread_id << " result: " << result << std::endl;
    fprintf(stderr, "[LEAVE] < print_thread_info at %s:%d\n", __FILE__, __LINE__);
}


/**
 * @brief 主函数创建并管理线程
 * @return int 程序退出状态码（0表示正常退出）
 * @details
 * ## 工作原理
 * 1. 创建5个工作线程
 * 2. 使用emplace_back初始化线程对象
 * 3. 等待所有线程执行完毕
 *
 * ## 调用关系
 * [main] -> [print_thread_info] 启动工作线程
 *
 * ## 副作用
 * - 创建系统线程资源
 * - 可能产生线程调度竞争
 */
int main() {
    fprintf(stderr, "[ENTER] > main at %s:%d\n", __FILE__, __LINE__);
    std::vector<std::thread> threads;
    for (int i = 1; i <= 5; ++i) {
        fprintf(stderr, "[CALL] 将调用 print_thread_info [打印线程信息并计算阶乘] at %s:%d\n", __FILE__, __LINE__);
        threads.emplace_back(print_thread_info, i);
    }
    
    for (auto& t : threads) {
        t.join();
    }
    
    fprintf(stderr, "[LEAVE] < main at %s:%d\n", __FILE__, __LINE__);
    return 0;
}