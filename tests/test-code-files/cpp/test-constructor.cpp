class Derived {
public:
Derived(Derived&& other) noexcept {}
};

class TestClass {
public:
TestClass& operator=(TestClass&& other) noexcept {
    return *this;
}
};
