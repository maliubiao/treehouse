interface Account {
  id: string;
  balance: number;
  deposit(amount: number): void;
  withdraw(amount: number): boolean;
}

// 泛型接口
interface Repository<T> {
  getById(id: number): Promise<T>;
  save(entity: T): Promise<void>;
  delete(id: number): Promise<boolean>;
}

// 索引签名
interface StringArray {
  [index: number]: string;
}

// 类型合并
interface ExtendedUser extends User {
  address: string;
  phone?: string;
}

interface ExportedAccount extends Account {
  accountNumber: string;
}

export interface Point {
  x: number;
  y: number;
}

export {
  Account,
  Repository,
  StringArray,
  ExtendedUser,
  ExportedAccount
};