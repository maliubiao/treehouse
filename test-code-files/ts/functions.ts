// 泛型函数
function identity<T>(arg: T): T {
  return arg;
}

// 类型守卫
function isUser(obj: any): obj is User {
  return obj && typeof obj.id === 'number' && typeof obj.name === 'string';
}

// 函数重载
function greet(name: string): string;
function greet(users: User[]): string[];
function greet(input: unknown): unknown {
  if (typeof input === 'string') {
    return `Hello, ${input}`;
  } else if (Array.isArray(input)) {
    return input.map(user => `Hello, ${user.name}`);
  }
  throw new Error('Invalid input');
}

function distance(p1: Point, p2: Point): number {
  return Math.sqrt((p2.x - p1.x) ** 2 + (p2.y - p1.y) ** 2);
}

function area(shape: Shape): number {
  switch (shape.kind) {
    case 'circle': return Math.PI * shape.radius ** 2;
    case 'square': return shape.size ** 2;
    case 'rectangle': return shape.width * shape.height;
  }
}

function basicFunction() {
  const x = 1 + 2;
  console.log(x);
}

// 带参数的箭头函数
const arrowFunctionWithParams = (a: number, b: number): number => {
  return a * b;
};

// 生成器函数
function* numberGenerator(): Generator<number> {
  let index = 0;
  while (true) yield index++;
}

// 异步函数
async function fetchData(url: string): Promise<any> {
  const response = await fetch(url);
  return response.json();
}

// 对象方法简写
const mathOperations = {
  sum(a: number, b: number): number {
    return a + b;
  },
  factorial(n: number): number {
    return n <= 1 ? 1 : n * this.factorial(n - 1);
  },
};

// 立即执行函数表达式 (IIFE)
(function (): void {
  const secret = "IIFE context";
  console.log(secret);
})();

// 带默认参数的函数
function createUser(name: string = "Anonymous", age: number = 0): User {
  return { name, age, id: 0, email: '', createdAt: new Date() };
}

// 剩余参数函数
function sumAll(...numbers: number[]): number {
  return numbers.reduce((acc, curr) => acc + curr, 0);
}

// 解构参数函数
function printCoordinates({ x, y }: { x: number; y: number }): void {
  console.log(`Position: (${x}, ${y})`);
}

// 高阶函数
function createMultiplier(factor: number): (n: number) => number {
  return function (n: number): number {
    return n * factor;
  };
}

// 异步箭头函数表达式
const asyncTimeout = async (ms: number): Promise<void> => {
  await new Promise((resolve) => setTimeout(resolve, ms));
};

// 带标签的函数表达式
const taggedFunction = function namedFunction(): void {
  console.log(namedFunction.name);
};

// 参数解构嵌套
function processConfig({ id, settings: { color = "blue", size } }: {
  id: string;
  settings: { color?: string; size: number }
}): void {
  console.log(`Processing #${id} with ${color} color`);
}

// 生成器异步函数
async function* asyncDataGenerator(): AsyncGenerator<any> {
  let page = 1;
  while (true) {
    const data = await fetchPage(page++);
    yield data;
  }
}

// 回调函数模式
function handleEvent(callback: (event: Event) => void): void {
  document.addEventListener("click", callback);
}

// 函数绑定表达式
const boundHandler = function (this: { message: string }): void {
  console.log(this.message);
}.bind({ message: "Hello from bound function" });

// 递归箭头函数
const factorial = (n: number): number => (n <= 1 ? 1 : n * factorial(n - 1));

// 参数装饰器模式函数
function validateParams(func: (...args: number[]) => any) {
  return function (...args: any[]): any {
    if (args.some((arg) => typeof arg !== "number")) {
      throw new Error("Invalid parameters");
    }
    return func(...args);
  };
}

// 函数属性赋值
function utilityFunction(): void { }
utilityFunction.version = "1.0.0";
utilityFunction.author = "Test Suite";

// 对象属性简写箭头函数
const counter = {
  count: 0,
  increment: (): void => {
    counter.count++;
  },
  reset: function (): void {
    this.count = 0;
  },
};

export {
  identity,
  isUser,
  greet,
  distance,
  area,
  basicFunction,
  arrowFunctionWithParams,
  numberGenerator,
  fetchData,
  mathOperations,
  createUser,
  sumAll,
  printCoordinates,
  createMultiplier,
  asyncTimeout,
  taggedFunction,
  processConfig,
  asyncDataGenerator,
  handleEvent,
  boundHandler,
  factorial,
  validateParams,
  utilityFunction,
  counter
};