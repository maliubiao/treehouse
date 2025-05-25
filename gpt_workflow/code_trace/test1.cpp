#include <iostream>
#include <thread>
#include <vector>

int factorial(int n) {
    if (n <= 1) return 1;
    return n * factorial(n - 1);
}

void print_thread_info(int thread_id) {
    std::cout << "Thread " << thread_id << " started" << std::endl;
    int result = factorial(thread_id);
    std::cout << "Thread " << thread_id << " result: " << result << std::endl;
}

int main() {
    std::vector<std::thread> threads;
    for (int i = 1; i <= 5; ++i) {
        threads.emplace_back(print_thread_info, i);
    }
    for (auto& t : threads) {
        t.join();
    }
    return 0;
}
