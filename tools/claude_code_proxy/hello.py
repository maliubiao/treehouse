def greet(name="World"):
    message = f"Hello, {name}!"
    return message


def main():
    result = greet("终端")
    print(result)
    return result


if __name__ == "__main__":
    main()
