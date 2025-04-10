template<typename T>
concept Arithmetic = std::is_arithmetic_v<T>;

template<Arithmetic T>
T add(T a, T b) {
return a + b;
}

template<typename T>
constexpr auto type_info() {
if constexpr (std::is_integral_v<T>) {
    return "integral";
} else {
    return "non-integral";
}
}
