/**
 * @file test.cpp
 * @brief Comprehensive C++ test file for tree-sitter parser validation
 * Contains multiple language constructs with nested namespaces and classes
 */

// Preprocessor directives
#include <iostream>
#include <vector>
#include <string>
#include <type_traits>
#include <memory>
#define MAX_COUNT 100
#ifdef DEBUG_MODE
    #define DEBUG_LOG(msg) std::cout << "[DEBUG] " << msg << std::endl
#else
    #define DEBUG_LOG(msg)
#endif

// Global declarations
int global_counter = 0;
const double PI = 3.1415926535;

// Type aliases
using StringVector = std::vector<std::string>;
typedef unsigned long ulong;

// Nested namespace definitions
namespace Outer {
    namespace Inner {
        namespace Math {
            template<typename T>
            T add(T a, T b) {
                return a + b;
            }
        }
    }
}

// Class hierarchy with various access modifiers
class BaseClass {
public:
    explicit BaseClass(int id) : m_id(id) {}
    virtual ~BaseClass() = default;
    
    virtual void display() const {
        std::cout << "Base ID: " << m_id << std::endl;
    }

    // Pure virtual function
    virtual void pure_virtual() = 0;

protected:
    int m_id;

    // Friend function declaration
    friend void friend_function(BaseClass& obj);
};

// Friend function definition
void friend_function(BaseClass& obj) {
    obj.m_id += 100;
    DEBUG_LOG("Friend function modified ID");
}

// Derived class with inheritance
class Derived : public BaseClass {
public:
    Derived(int id, const std::string& name) 
        : BaseClass(id), m_name(name) {}

    // Delegating constructor
    Derived() : Derived(0, "Default") {}

    // Move constructor
    Derived(Derived&& other) noexcept 
        : BaseClass(std::move(other.m_id)), m_name(std::move(other.m_name)) {
        DEBUG_LOG("Move constructor called");
    }

    void display() const override {
        std::cout << "Derived ID: " << m_id 
                  << ", Name: " << m_name << std::endl;
    }

    void pure_virtual() override {
        std::cout << "Implemented pure virtual" << std::endl;
    }

    // Static member and method
    static int instance_count;
    static void printCount() {
        std::cout << "Instances: " << instance_count << std::endl;
    }

    // Const method with trailing return type
    auto get_name() const -> const std::string& {
        return m_name;
    }

    // noexcept method
    void unsafe_operation() noexcept {
        // May throw but marked noexcept
        DEBUG_LOG("This method is noexcept");
    }

private:
    std::string m_name;
};

int Derived::instance_count = 0;

// Structure with methods
struct Point {
    int x;
    int y;
    
    void move(int dx, int dy) {
        x += dx;
        y += dy;
        DEBUG_LOG("Point moved");
    }
    
    // Operator overload
    Point operator+(const Point& other) const {
        return {x + other.x, y + other.y};
    }
};

// Function template with documentation
/**
 * @brief Calculates the square of a number
 * @tparam T Numeric type
 * @param value Input value
 * @return Square of the input value
 */
template<typename T>
T square(T value) {
    return value * value;
}

// Template specialization
template<>
float square(float value) {
    return value * value;
}

// Variadic template function
template<typename... Args>
void printAll(Args&&... args) {
    (std::cout << ... << args) << std::endl;
}

// constexpr function with if constexpr
template<typename T>
constexpr auto type_info() {
    if constexpr (std::is_integral_v<T>) {
        return "integral";
    } else {
        return "non-integral";
    }
}

// [[nodiscard]] attribute
[[nodiscard]] int must_use_function() {
    return 42;
}

// Function with exception specification
void risky_function() throw(std::bad_alloc) {
    new int[1000000000000];
}

// Function try block
TestClass::TestClass() try : m_value(new int(5)) {
} catch(...) {
    std::cout << "Constructor exception caught" << std::endl;
}

// Enum class with attributes
enum class Color : char {
    RED = 1,
    GREEN = 2,
    BLUE = 4
};

// Test class with various special members
class TestClass {
public:
    // Default constructor
    TestClass() = default;
    
    // Explicit constructor
    explicit TestClass(int v) : m_value(v) {}
    
    // Copy constructor
    TestClass(const TestClass& other) : m_value(other.m_value) {}
    
    // Move assignment operator
    TestClass& operator=(TestClass&& other) noexcept {
        m_value = std::exchange(other.m_value, 0);
        return *this;
    }
    
    // Destructor with logging
    ~TestClass() {
        DEBUG_LOG("TestClass destroyed");
    }
    
    // Const method
    void const_method() const {
        std::cout << "Const method called" << std::endl;
    }
    
    // Volatile method
    void volatile_method() volatile {
        std::cout << "Volatile method called" << std::endl;
    }
    
    // Final method
    void final_method() final {
        std::cout << "Final method" << std::endl;
    }

private:
    int m_value = 0;
};

// Concept and constrained template
template<typename T>
concept Arithmetic = std::is_arithmetic_v<T>;

template<Arithmetic T>
T add(T a, T b) {
    return a + b;
}

// New namespace with scope resolution operators
namespace ScopeResolution {
    class ScopeTest {
    public:
        static void static_method() {
            std::cout << "Static method called" << std::endl;
        }
        
        void member_method() {
            std::cout << "Member method called" << std::endl;
        }
    };
    
    void free_function() {
        std::cout << "Free function called" << std::endl;
    }
    
    namespace Nested {
        void nested_function() {
            std::cout << "Nested function called" << std::endl;
        }
    }
}

// Class with qualified name resolution
class QualifiedNameTest {
public:
    class InnerClass {
    public:
        static void inner_static_method() {
            std::cout << "Inner static method" << std::endl;
        }
    };
    
    void outer_method() {
        std::cout << "Outer method" << std::endl;
    }
};

// Template class with scope resolution
template<typename T>
class TemplateScope {
public:
    class Inner {
    public:
        static void template_inner_method() {
            std::cout << "Template inner method" << std::endl;
        }
    };
    
    static void template_method() {
        std::cout << "Template method" << std::endl;
    }
};

// New implementations for tree-sitter testing
namespace ImplementationTests {
    class ComplexClass {
    public:
        ComplexClass() = default;
        
        // Out-of-line constructor implementation
        ComplexClass(int value);
        
        // Out-of-line method implementation
        void complex_method();
        
        // Static out-of-line implementation
        static void static_complex_method();
    };
    
    // Out-of-line constructor implementation
    ComplexClass::ComplexClass(int value) {
        std::cout << "ComplexClass constructed with " << value << std::endl;
    }
    
    // Out-of-line method implementation
    void ComplexClass::complex_method() {
        std::cout << "Complex method called" << std::endl;
    }
    
    // Out-of-line static method implementation
    void ComplexClass::static_complex_method() {
        std::cout << "Static complex method called" << std::endl;
    }
    
    // Template class with out-of-line implementations
    template<typename T>
    class TemplateClass {
    public:
        TemplateClass();
        void template_method();
    };
    
    // Out-of-line template class constructor
    template<typename T>
    TemplateClass<T>::TemplateClass() {
        std::cout << "TemplateClass constructed" << std::endl;
    }
    
    // Out-of-line template class method
    template<typename T>
    void TemplateClass<T>::template_method() {
        std::cout << "Template method called with type: " 
                  << typeid(T).name() << std::endl;
    }
    
    // Namespace with out-of-line implementations
    namespace NestedImpl {
        class NestedClass {
        public:
            void nested_method();
        };
        
        void free_function();
    }
    
    // Out-of-line nested class method
    void NestedImpl::NestedClass::nested_method() {
        std::cout << "Nested method called" << std::endl;
    }
    
    // Out-of-line free function
    void NestedImpl::free_function() {
        std::cout << "Free function in nested namespace" << std::endl;
    }
}

// Main function demonstrating various features
int main() {
    // Lambda expressions
    auto multiplier = [](int x) { return x * MAX_COUNT; };
    auto complex_lambda = [](auto&&... args) -> decltype(auto) {
        return (args + ...);
    };
    
    // Nested namespace usage
    std::cout << "5 + 3 = " 
              << Outer::Inner::Math::add(5, 3) << std::endl;

    // Class instantiation
    Derived d1(1, "Test");
    d1.display();
    Derived::printCount();

    // Structure usage
    Point p1{10, 20};
    p1.move(5, -3);
    Point p2 = p1 + Point{2, 4};

    // Template function call
    std::cout << "Square of 5.5: " << square(5.5) << std::endl;

    // Range-based for loop
    StringVector fruits{"apple", "banana", "cherry"};
    for (const auto& fruit : fruits) {
        std::cout << fruit << std::endl;
    }

    // New test cases
    [[maybe_unused]] auto result = must_use_function();
    
    // Structured bindings
    auto [x, y] = p1;
    std::cout << "X: " << x << ", Y: " << y << std::endl;
    
    // Constexpr if usage
    std::cout << "int is " << type_info<int>() << std::endl;
    
    // Variadic template usage
    printAll("Hello", " ", 42, " ", 3.14);
    
    // Concept-constrained template
    static_assert(Arithmetic<int>, "int should be arithmetic");
    
    // Move constructor test
    Derived d2 = std::move(d1);
    
    // Friend function test
    friend_function(d2);
    
    // Lambda with capture
    int capture_value = 10;
    auto capturing_lambda = [capture_value](int x) { return x + capture_value; };
    
    // Function try block
    try {
        risky_function();
    } catch(const std::exception& e) {
        std::cout << "Exception caught: " << e.what() << std::endl;
    }
    
    // New scope resolution tests
    ScopeResolution::ScopeTest::static_method();
    ScopeResolution::ScopeTest obj;
    obj.member_method();
    ScopeResolution::free_function();
    ScopeResolution::Nested::nested_function();
    
    QualifiedNameTest::InnerClass::inner_static_method();
    QualifiedNameTest qn_obj;
    qn_obj.outer_method();
    
    TemplateScope<int>::template_method();
    TemplateScope<double>::Inner::template_inner_method();
    
    // New implementation tests
    ImplementationTests::ComplexClass cc(42);
    cc.complex_method();
    ImplementationTests::ComplexClass::static_complex_method();
    
    ImplementationTests::TemplateClass<int> tc;
    tc.template_method();
    
    ImplementationTests::NestedImpl::NestedClass nc;
    nc.nested_method();
    ImplementationTests::NestedImpl::free_function();

    return 0;
}
