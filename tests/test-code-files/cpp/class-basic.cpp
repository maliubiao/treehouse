class BaseClass {
public:
virtual void display() const {
    std::cout << "Base ID: " << m_id << std::endl;
}
};

class Derived : public BaseClass {
public:
void display() const override {
    std::cout << "Derived display" << std::endl;
}

auto get_name() const -> const std::string& {
    return m_name;
}
};
