// 基础函数声明  
function add(a: number, b: number): number {  
  return a + b;  
}  

// 箭头函数表达式  
const multiply = (x: number, y: number): number => x * y;  

// 生成器函数  
function* idGenerator(): Generator<number> {  
  let id = 1;  
  while (true) yield id++;  
}  

// 异步函数  
async function fetchData(url: string): Promise<unknown> {  
  const response = await fetch(url);  
  return response.json();  
}  

// 对象方法简写  
const calculator = {  
  divide(a: number, b: number): number {  
    return a / b;  
  },  
  power: (base: number, exp: number) => Math.pow(base, exp)  
};  

// 类构造函数  
class Person {  
  constructor(public name: string, private age: number) {}  

  // 类方法  
  greet() {  
    return `Hello, I'm ${this.name}`;  
  }  
}  

// 装饰器函数  
function log(target: any, key: string, descriptor: PropertyDescriptor) {  
  const original = descriptor.value;  
  descriptor.value = function (...args: any[]) {  
    console.log(`Calling ${key} with`, args);  
    return original.apply(this, args);  
  };  
  return descriptor;  
}  

// 泛型函数  
function identity<T>(arg: T): T {  
  return arg;  
}  

// 函数重载  
function reverse(str: string): string;  
function reverse<T>(arr: T[]): T[];  
function reverse(value: string | any[]): string | any[] {  
  return typeof value === "string"  
    ? value.split("").reverse().join("")  
    : value.slice().reverse();  
}  

// 可选参数和默认参数  
function createUser(  
  name: string,  
  age?: number,  
  isAdmin: boolean = false  
): { name: string; age?: number } {  
  return { name, age };  
}  

// 剩余参数  
function sum(...numbers: number[]): number {  
  return numbers.reduce((acc, curr) => acc + curr, 0);  
}  

// 类型断言函数  
function assertIsNumber(val: any): asserts val is number {  
  if (typeof val !== "number") throw new Error("Not a number");  
}  

// 解构参数  
function draw({ x = 0, y = 0, color = "black" }: { x?: number; y?: number; color?: string }) {  
  console.log(`Drawing at (${x}, ${y}) with ${color}`);  
}  

// 函数表达式  
const formatDate = function (date: Date): string {  
  return date.toISOString().split("T")[0];  
};  

// 立即调用函数表达式 (IIFE)  
const module = (() => {  
  const privateVar = 42;  
  return {  
    getValue: () => privateVar  
  };  
})();  

// 回调函数类型  
function asyncOperation(callback: (err: Error | null, data?: string) => void) {  
  setTimeout(() => callback(null, "Data received"), 100);  
}  

// 方法装饰器应用  
class TestClass {  
  @log  
  testMethod(msg: string) {  
    console.log(msg);  
  }  
}  

// 函数属性  
interface MemoFunction {  
  (arg: number): number;  
  cache: Map<number, number>;  
}  

// 类型保护函数  
function isString(test: any): test is string {  
  return typeof test === "string";  
}  

// 抽象类方法  
abstract class Animal {  
  abstract makeSound(): void;  
}  

// 函数绑定  
const boundFunction = (function () {  
  return this;  
}).bind(window);  

// 导出函数  
export function exportedFunc() {  
  return "This is exported";  
}  

// 导入类型函数  
import { SomeType } from "./types";  
export function typeUser(user: SomeType): SomeType {  
  return { ...user, id: 1 };  
}  
