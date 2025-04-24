// 抽象类
abstract class Animal {
  abstract makeSound(): void;

  move(): void {
    console.log('Moving...');
  }
}

class Dog extends Animal {
  makeSound(): void {
    console.log('Woof!');
  }
}

// 类方法
class Calculator {
  private value: number;

  constructor() {
    this.value = 0;
  }

  add(n: number): void {
    this.value += n;
  }

  static create(): Calculator {
    return new Calculator();
  }
}

// 带可选链的类方法
class ModernClass {
  private nested: {
    data: {
      value?: string;
    } | null;
  };

  constructor() {
    this.nested = {
      data: null,
    };
  }

  safeAccess(): string {
    return this.nested?.data?.value ?? "default";
  }
}

export { Animal, Dog, Calculator, ModernClass };