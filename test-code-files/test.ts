// 基础函数声明
// 各种import样式
import { foo } from 'module';
import * as bar from 'module2';
import baz, { qux } from 'module3';
import('dynamic-module').then(m => m.init());
const lazyImport = await import('lazy-module');
import type { SomeType } from 'types-module';
import { reallyLongNamedExport as shortName } from 'very-long-module-name';
import defaultExport, { namedExport } from 'mixed-export-module';
import { nested: { deepImport } } from 'nested-module';
import './side-effects-only';
import {
  multiLineImport1,
  multiLineImport2,
  multiLineImport3
} from 'multi-line-module';

// 类型定义
type User = {
  id: number;
  name: string;
  email: string;
  age?: number;
  readonly createdAt: Date;
};

interface Account {
  id: string;
  balance: number;
  deposit(amount: number): void;
  withdraw(amount: number): boolean;
}

// 泛型函数
function identity<T>(arg: T): T {
  return arg;
}

// 泛型接口
interface Repository<T> {
  getById(id: number): Promise<T>;
  save(entity: T): Promise<void>;
  delete(id: number): Promise<boolean>;
}

// 枚举类型
enum Color {
  Red = 'RED',
  Green = 'GREEN',
  Blue = 'BLUE'
}

// 类型守卫
function isUser(obj: any): obj is User {
  return obj && typeof obj.id === 'number' && typeof obj.name === 'string';
}

// 映射类型
type PartialUser = Partial<User>;
type ReadonlyUser = Readonly<User>;
type UserWithoutEmail = Omit<User, 'email'>;

// 条件类型
type NonNullableUser = NonNullable<User | null | undefined>;
type UserKeys = keyof User;

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

// 装饰器
function log(target: any, key: string, descriptor: PropertyDescriptor) {
  const originalMethod = descriptor.value;
  descriptor.value = function (...args: any[]) {
    console.log(`Calling ${key} with args:`, args);
    const result = originalMethod.apply(this, args);
    console.log(`Result:`, result);
    return result;
  };
  return descriptor;
}

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

// 类型断言
const unknownValue: unknown = 'hello';
const strLength = (unknownValue as string).length;

// 元组类型
type StringNumberPair = [string, number];
const pair: StringNumberPair = ['age', 30];

// 可辨识联合
type Shape =
  | { kind: 'circle'; radius: number }
  | { kind: 'square'; size: number }
  | { kind: 'rectangle'; width: number; height: number };

function area(shape: Shape): number {
  switch (shape.kind) {
    case 'circle': return Math.PI * shape.radius ** 2;
    case 'square': return shape.size ** 2;
    case 'rectangle': return shape.width * shape.height;
  }
}

// 命名空间
namespace Geometry {
  export interface Point {
    x: number;
    y: number;
  }

  export function distance(p1: Point, p2: Point): number {
    return Math.sqrt((p2.x - p1.x) ** 2 + (p2.y - p1.y) ** 2);
  }
}

// 类型推断
const inferredString = 'This is a string'; // type is string
const inferredNumber = 42; // type is number

// 常量断言
const colors = ['red', 'green', 'blue'] as const;

// 模板字面量类型
type Email = `${string}@${string}.${string}`;
const validEmail: Email = 'test@example.com';

// 索引签名
interface StringArray {
  [index: number]: string;
}

// 类型谓词
function isStringArray(arr: any[]): arr is string[] {
  return arr.every(item => typeof item === 'string');
}

// 类型合并
interface ExtendedUser extends User {
  address: string;
  phone?: string;
}

// 类型别名中的泛型
type Response<T> = {
  data: T;
  status: number;
  message?: string;
};

// 类型参数默认值
interface PaginatedResponse<T = any> {
  items: T[];
  total: number;
  page: number;
}

// 类型导入导出
export type { User };
export interface ExportedAccount extends Account {
  accountNumber: string;
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