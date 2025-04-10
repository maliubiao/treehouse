static PyGetSetDef CodeObject_getsetters[] = {
    {"co_name", CodeObject_get_name, nullptr, "Code object name", nullptr},
    {"co_filename", CodeObject_get_filename, nullptr, "Code object filename", nullptr},
    {"co_firstlineno", CodeObject_get_firstlineno, nullptr, "First line number", nullptr},
    {nullptr, nullptr, nullptr, nullptr, nullptr}
};
int global_array[] = {1, 2, 3};

class Container {
public:
static char buffer[1024];
int member_array[5];
};

char Container::buffer[1024] = {0};

void process_data(int data[], size_t size) {}
