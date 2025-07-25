module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'node',
  // 明确指定模块文件扩展名
  moduleFileExtensions: ['ts', 'js'],
  // 定义 Jest 应该查找测试和源文件的根目录
  roots: ['<rootDir>/src', '<rootDir>/tests'],
  // 定义测试文件的匹配模式
  testMatch: [
    '**/__tests__/**/*.test.ts',
    '**/__tests__/**/*.spec.ts',
    '**/tests/**/*.test.ts',
    '**/tests/**/*.spec.ts'
  ],
  // 配置转换器以处理 TypeScript 文件
  transform: {
    '^.+\\.ts$': 'ts-jest',
  },
  // 配置代码覆盖率收集
  collectCoverageFrom: [
    'src/**/*.ts',
    '!src/**/*.d.ts',
    '!src/test/**/*.ts',
    '!src/webview/**/*.ts',
    '!src/extension.ts',
  ],
  coverageThreshold: {
    global: {
      branches: 80,
      functions: 80,
      lines: 80,
      statements: 80,
    },
  },
  coverageReporters: ['text', 'lcov', 'html'],
  // 配置模块名称映射，用于 mock 或别名
  // 注意：如果 tsconfig.json 中没有对应的 paths 配置，
  // 或者项目中未使用 '@/...' 这样的导入方式，则应移除 '@/*' 的映射以避免混淆。
  // 这里保留 'vscode' 的 mock 映射是必要的。
  moduleNameMapper: {
    // 如果项目代码中确实使用了 @/alias，请确保 tsconfig.json 中有对应的 paths 配置
    // 并且这里的映射是正确的。否则，请注释或删除下面这一行。
    // '^@/(.*)$': '<rootDir>/src/$1',
    // Mock VS Code API module
    '^vscode$': '<rootDir>/tests/__mocks__/vscode.ts',
  },
  // 设置测试环境初始化文件
  setupFilesAfterEnv: ['<rootDir>/tests/setup.ts'],
};