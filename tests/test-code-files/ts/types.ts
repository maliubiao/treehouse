// 类型定义
type User = {
  id: number;
  name: string;
  email: string;
  age?: number;
  readonly createdAt: Date;
};

// 映射类型
type PartialUser = Partial<User>;
type ReadonlyUser = Readonly<User>;
type UserWithoutEmail = Omit<User, 'email'>;

// 条件类型
type NonNullableUser = NonNullable<User | null | undefined>;
type UserKeys = keyof User;

// 元组类型
type StringNumberPair = [string, number];

// 可辨识联合
type Shape =
  | { kind: 'circle'; radius: number }
  | { kind: 'square'; size: number }
  | { kind: 'rectangle'; width: number; height: number };

// 模板字面量类型
type Email = `${string}@${string}.${string}`;

// 类型别名中的泛型
type Response<T> = {
  data: T;
  status: number;
  message?: string;
};

// 类型参数默认值
type PaginatedResponse<T = any> = {
  items: T[];
  total: number;
  page: number;
};

export type {
  User,
  PartialUser,
  ReadonlyUser,
  UserWithoutEmail,
  NonNullableUser,
  UserKeys,
  StringNumberPair,
  Shape,
  Email,
  Response,
  PaginatedResponse
};