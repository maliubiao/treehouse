template<typename T>
class TemplateScope {
public:
static void template_method() {}

class Inner {
public:
    static void template_inner_method() {}
};
};
