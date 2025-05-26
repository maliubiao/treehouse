#include <iostream>

int add(int a, int b) {
    return a + b;
}

void greet() {
    std::cout << "Hello, World!" << std::endl;
}

int main() {
    greet();
    std::cout << "2 + 3 = " << add(2, 3) << std::endl;
    return 0;
}
