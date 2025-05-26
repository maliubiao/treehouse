#include <iostream>

int add(int a, int b) {
    return a + b;
}

  
/**  
 * @brief 输出欢迎信息到标准输出  
 * @details  
 * ## 工作原理  
 * 使用std::cout输出固定字符串  
 *  
 * ## 调用关系  
 * 被main函数调用作为程序入口  
 *  
 * ## 副作用  
 * 执行标准输出操作  
 */  
void greet() {  
    fprintf(stderr, "[ENTER] > greet at %s:%d\n", __FILE__, __LINE__);  
    std::cout << "Hello, World!" << std::endl;  
    fprintf(stderr, "[LEAVE] < greet at %s:%d\n", __FILE__, __LINE__);  
}  

  
/**  
 * @brief 程序主入口函数  
 * @return int 返回状态码（0表示成功）  
 * @details  
 * ## 工作原理  
 * 1. 调用greet输出欢迎信息  
 * 2. 调用add进行加法运算  
 * 3. 输出计算结果  
 *  
 * ## 调用关系  
 * [main] -> greet() 输出欢迎信息  
 * [main] -> add() 执行加法运算  
 *  
 * ## 副作用  
 * - 修改标准输出流状态  
 * - 创建临时字符串对象  
 */  
int main() {  
    fprintf(stderr, "[ENTER] > main at %s:%d\n", __FILE__, __LINE__);  
    fprintf(stderr, "[CALL] 将调用 greet [输出欢迎信息] at %s:%d\n", __FILE__, __LINE__);  
    greet();  
    fprintf(stderr, "[CALL] 将调用 add [执行加法运算] at %s:%d\n", __FILE__, __LINE__);  
    std::cout << "2 + 3 = " << add(2, 3) << std::endl;  
    fprintf(stderr, "[LEAVE] < main at %s:%d\n", __FILE__, __LINE__);  
    return 0;  
}  
