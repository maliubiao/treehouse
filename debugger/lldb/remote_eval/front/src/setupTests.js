import '@testing-library/jest-dom';
import { configure } from '@testing-library/react';

// 增加调试信息输出
configure({
  throwSuggestions: true,
  // 显示完整的组件树结构
  showOriginalStackTrace: true
});

// 在测试环境初始化时检查关键依赖版本
beforeAll(() => {
  console.log('React version:', React.version);
  console.log('React-Redux version:', require('react-redux/package.json').version);
});