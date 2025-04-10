class BaseClass {
friend void friend_function(BaseClass& obj);
};

void friend_function(BaseClass& obj) {}

[[nodiscard]] int must_use_function() {
	return 42;
}

