// Import removed - using global jest
import { parseLLMResponse } from '../../commands/generateCode';
import { logger } from '../../utils/logger';

// Mock logger
jest.mock('../../utils/logger', () => ({
  logger: {
    log: jest.fn(),
    warn: jest.fn(),
    error: jest.fn()
  }
}));

// Mock i18n to provide the expected error message
jest.mock('../../util/i18n', () => ({
  t: jest.fn((key: string) => {
    if (key === 'generateCode.emptyResponse') {
      return 'AI response was empty.';
    }
    return key; // Return the key for other translations
  }),
}));

describe('parseLLMResponse', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('正常情况', () => {
    it('应该正确解析包含新代码的响应', () => {
      const response = `
<UPDATED_CODE>
function hello() {
  console.log("Hello, world!");
}
</UPDATED_CODE>
`;
      const result = parseLLMResponse(response);
      expect(result.newCode).toBe(`function hello() {\n  console.log("Hello, world!");\n}`);
      expect(result.newImports).toBeNull();
    });

    it('应该正确解析包含新导入和新代码的响应', () => {
      const response = `
<UPDATED_IMPORTS>
import React from 'react';
import { useState } from 'react';
</UPDATED_IMPORTS>
<UPDATED_CODE>
const Component = () => {
  const [count, setCount] = useState(0);
  return <div>{count}</div>;
};
</UPDATED_CODE>
`;
      const result = parseLLMResponse(response);
      expect(result.newCode).toBe(`const Component = () => {\n  const [count, setCount] = useState(0);\n  return <div>{count}</div>;\n};`);
      expect(result.newImports).toBe(`import React from 'react';\nimport { useState } from 'react';`);
    });

    it('应该正确处理标签周围有额外空格的情况', () => {
      const response = `
  <UPDATED_CODE>
    const x = 1;
  </UPDATED_CODE>  
`;
      const result = parseLLMResponse(response);
      expect(result.newCode).toBe('    const x = 1;');
    });

    it('应该正确处理代码中包含标签字符串的情况', () => {
      const response = `
<UPDATED_CODE>
const html = '<UPDATED_CODE>test</UPDATED_CODE>';
console.log(html);
</UPDATED_CODE>
`;
      const result = parseLLMResponse(response);
      expect(result.newCode).toBe(`const html = '<UPDATED_CODE>test</UPDATED_CODE>';\nconsole.log(html);`);
    });
  });

  describe('嵌套标签处理', () => {
    it('应该正确处理嵌套的相同标签', () => {
      const response = `
<UPDATED_CODE>
function outer() {
  <UPDATED_CODE>
  function inner() {
    return "nested";
  }
  </UPDATED_CODE>
  return inner();
}
</UPDATED_CODE>
`;
      const result = parseLLMResponse(response);
      expect(result.newCode).toBe(`function outer() {\n  <UPDATED_CODE>\n  function inner() {\n    return "nested";\n  }\n  </UPDATED_CODE>\n  return inner();\n}`);
    });

    it('应该正确处理多个嵌套层级', () => {
      const response = `
<UPDATED_IMPORTS>
import { a } from 'a';
<UPDATED_IMPORTS>
import { b } from 'b';
</UPDATED_IMPORTS>
</UPDATED_IMPORTS>
<UPDATED_CODE>
function test() {
  <UPDATED_CODE>
  return true;
  </UPDATED_CODE>
}
</UPDATED_CODE>
`;
      const result = parseLLMResponse(response);
      expect(result.newCode).toBe(`function test() {\n  <UPDATED_CODE>\n  return true;\n  </UPDATED_CODE>\n}`);
      expect(result.newImports).toBe(`import { a } from 'a';\n<UPDATED_IMPORTS>\nimport { b } from 'b';\n</UPDATED_IMPORTS>`);
    });
  });

  describe('边界与清理情况', () => {
    it('应该处理空的代码块', () => {
      const response = `<UPDATED_CODE></UPDATED_CODE>`;
      const result = parseLLMResponse(response);
      expect(result.newCode).toBe('');
    });

    it('应该处理只包含空白字符的代码块并返回空字符串', () => {
      const response = `
<UPDATED_CODE>
  
  
</UPDATED_CODE>
`;
      const result = parseLLMResponse(response);
      expect(result.newCode).toBe('');
    });

    it('应该处理没有换行的单行代码', () => {
      const response = `<UPDATED_CODE>const x = 1;</UPDATED_CODE>`;
      const result = parseLLMResponse(response);
      expect(result.newCode).toBe('const x = 1;');
    });

    it('应该处理代码块中的特殊字符', () => {
      const response = `
<UPDATED_CODE>
const special = '测试字符 \n \t "quoted" \\escaped\\';
</UPDATED_CODE>
`;
      const result = parseLLMResponse(response);
      expect(result.newCode).toBe(`const special = '测试字符 \n \t "quoted" \\escaped\\';`);
    });
    
    it('应该当没有标签时，将整个响应作为代码并修剪', () => {
      const response = `

function untagged() {
  return "hello";
}

`;
      const result = parseLLMResponse(response);
      expect(result.newCode).toBe('function untagged() {\n  return "hello";\n}');
      expect(result.newImports).toBeNull();
    });

    it('应该返回一个空字符串对于只包含空白的响应', () => {
      const response = ' \n \t \n ';
      // The initial check for empty/whitespace response will catch this
      expect(() => parseLLMResponse(response)).toThrow('AI response was empty.');
    });
    
    it('应该返回一个空字符串对于只包含空白的响应 (带标签)', () => {
        const response = '<UPDATED_CODE> \n \t \n </UPDATED_CODE>';
        const result = parseLLMResponse(response);
        expect(result.newCode).toBe('');
        expect(result.newImports).toBeNull();
    });

    it('应该在只有 imports 标签时正常解析并修剪', () => {
      const response = `
<UPDATED_IMPORTS>

import a from 'a';

</UPDATED_IMPORTS>
`;
      const result = parseLLMResponse(response);
      expect(result.newCode).toBe('');
      expect(result.newImports).toBe("import a from 'a';");
    });
  });

  describe('标签顺序', () => {
    it('应该正确处理 imports 在 code 之前的顺序', () => {
      const response = `
<UPDATED_IMPORTS>
import a from 'a';
</UPDATED_IMPORTS>
<UPDATED_CODE>
const b = 1;
</UPDATED_CODE>
`;
      const result = parseLLMResponse(response);
      expect(result.newImports).toBe(`import a from 'a';`);
      expect(result.newCode).toBe(`const b = 1;`);
    });

    it('应该正确处理 code 在 imports 之前的顺序', () => {
      const response = `
<UPDATED_CODE>
const b = 1;
</UPDATED_CODE>
<UPDATED_IMPORTS>
import a from 'a';
</UPDATED_IMPORTS>
`;
      const result = parseLLMResponse(response);
      expect(result.newImports).toBe(`import a from 'a';`);
      expect(result.newCode).toBe(`const b = 1;`);
    });
  });

  describe('错误处理', () => {
    it('应该在空响应时抛出错误', () => {
      expect(() => parseLLMResponse('')).toThrow('AI response was empty.');
    });

    it('应该在 null 响应时抛出错误', () => {
      expect(() => parseLLMResponse(null as any)).toThrow('AI response was empty.');
    });

    it('应该在 undefined 响应时抛出错误', () => {
      expect(() => parseLLMResponse(undefined as any)).toThrow('AI response was empty.');
    });

    it('应该在缺少结束标签时记录警告但继续处理', () => {
      const response = `
<UPDATED_CODE>
const x = 1;
<UPDATED_IMPORTS>
import a from 'a';
</UPDATED_IMPORTS>
`;
      const result = parseLLMResponse(response);
      // newCode should be empty because its tag is unclosed
      expect(result.newCode).toBe('');
      // newImports should be parsed correctly as it is a complete block
      expect(result.newImports).toBe(`import a from 'a';`);
      expect(logger.warn).toHaveBeenCalledWith(
        'Unclosed tags found in LLM response:',
        expect.arrayContaining(['<UPDATED_CODE>'])
      );
    });

    it('应该在有多余结束标签时记录警告但继续处理', () => {
      const response = `
<UPDATED_CODE>
const x = 1;
</UPDATED_CODE>
</UPDATED_CODE>
`;
      const result = parseLLMResponse(response);
      expect(result.newCode).toBe(`const x = 1;`);
      expect(logger.warn).toHaveBeenCalledWith(
        'Found end tag </UPDATED_CODE> without matching start tag.'
      );
    });

    it('应该在结束标签不匹配时记录警告', () => {
      const response = `
<UPDATED_CODE>
const x = 1;
</UPDATED_IMPORTS>
`;

      const result = parseLLMResponse(response);
      // newCode is empty because its tag is not closed by a matching end tag
      expect(result.newCode).toBe('');
      expect(logger.warn).toHaveBeenCalledWith(
        'Found end tag </UPDATED_IMPORTS> without matching start tag.'
      );
    });
  });

  describe('复杂场景', () => {
    it('应该处理多个相同标签只取最外层一对', () => {
      const response = `
<UPDATED_CODE>
function outer() {
  <UPDATED_CODE>inner content</UPDATED_CODE>
  return "outer";
}
</UPDATED_CODE>
<UPDATED_CODE>
this should be ignored
</UPDATED_CODE>
`;
      const result = parseLLMResponse(response);
      expect(result.newCode).toBe(`function outer() {\n  <UPDATED_CODE>inner content</UPDATED_CODE>\n  return "outer";\n}`);
    });

    it('应该处理标签内包含其他XML标签', () => {
      const response = `
<UPDATED_CODE>
const xml = \`<root>
  <item id="1">First</item>
  <item id="2">Second</item>
</root>\`;
</UPDATED_CODE>
`;
      const result = parseLLMResponse(response);
      expect(result.newCode).toBe(`const xml = \`<root>\n  <item id="1">First</item>\n  <item id="2">Second</item>\n</root>\`;`);
    });


//     it('应该处理包含注释的代码', () => {
//       const response = `
// <UPDATED_CODE>
// // This is a comment with <UPDATED_CODE> in it
// function test() {
//   /* Multi-line comment
//      with <UPDATED_IMPORTS> tag */
//   return true;
// }
// </UPDATED_CODE>
// `;
//       const result = parseLLMResponse(response);
//       expect(result.newCode).toBe(`
// // This is a comment with <UPDATED_CODE> in it
// function test() {
//   /* Multi-line comment
//      with <UPDATED_IMPORTS> tag */
//   return true;
// }
// `);
//     });
  });
});