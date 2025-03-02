// 基础函数声明
function basicFunction() {
  const x = 1 + 2;
  console.log(x);
}

// 带参数的箭头函数
const arrowFunctionWithParams = (a, b) => {
  return a * b;
};

// 生成器函数
function* numberGenerator() {
  let index = 0;
  while (true) yield index++;
}

// 异步函数
async function fetchData(url) {
  const response = await fetch(url);
  return response.json();
}

// 对象方法简写
const mathOperations = {
  sum(a, b) {
    return a + b;
  },
  factorial(n) {
    return n <= 1 ? 1 : n * this.factorial(n - 1);
  },
};

// 类方法
class Calculator {
  constructor() {
    this.value = 0;
  }

  add(n) {
    this.value += n;
  }

  static create() {
    return new Calculator();
  }
}

// 立即执行函数表达式 (IIFE)
(function () {
  const secret = "IIFE context";
  console.log(secret);
})();

// 带默认参数的函数
function createUser(name = "Anonymous", age = 0) {
  return { name, age };
}

// 剩余参数函数
function sumAll(...numbers) {
  return numbers.reduce((acc, curr) => acc + curr, 0);
}

// 解构参数函数
function printCoordinates({ x, y }) {
  console.log(`Position: (${x}, ${y})`);
}

// 高阶函数
function createMultiplier(factor) {
  return function (n) {
    return n * factor;
  };
}

// 异步箭头函数表达式
const asyncTimeout = async (ms) => {
  await new Promise((resolve) => setTimeout(resolve, ms));
};

// 带标签的函数表达式
const taggedFunction = function namedFunction() {
  console.log(namedFunction.name);
};

// 参数解构嵌套
function processConfig({ id, settings: { color = "blue", size } }) {
  console.log(`Processing #${id} with ${color} color`);
}

// 生成器异步函数
async function* asyncDataGenerator() {
  let page = 1;
  while (true) {
    const data = await fetchPage(page++);
    yield data;
  }
}

// 回调函数模式
function handleEvent(callback) {
  document.addEventListener("click", callback);
}

// 函数绑定表达式
const boundHandler = function () {
  console.log(this.message);
}.bind({ message: "Hello from bound function" });

// 递归箭头函数
const factorial = (n) => (n <= 1 ? 1 : n * factorial(n - 1));

// 带可选链的类方法
class ModernClass {
  constructor() {
    this.nested = {
      data: null,
    };
  }

  safeAccess() {
    return this.nested?.data?.value ?? "default";
  }
}

// 参数装饰器模式函数
function validateParams(func) {
  return function (...args) {
    if (args.some((arg) => typeof arg !== "number")) {
      throw new Error("Invalid parameters");
    }
    return func(...args);
  };
}

// 函数属性赋值
function utilityFunction() {}
utilityFunction.version = "1.0.0";
utilityFunction.author = "Test Suite";

// 对象属性简写箭头函数
const counter = {
  count: 0,
  increment: () => {
    // 注意箭头函数的this绑定问题
    counter.count++;
  },
  reset: function () {
    this.count = 0;
  },
};
