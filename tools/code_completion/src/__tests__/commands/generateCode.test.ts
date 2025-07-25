import { parseLLMResponse } from '../../commands/generateCode';

// Mock logger
jest.mock('../../utils/logger', () => ({
  logger: {
    log: jest.fn(),
    warn: jest.fn(),
    error: jest.fn()
  }
}));

// Mock vscode
jest.mock('vscode', () => ({
  Range: jest.fn().mockImplementation((startLine, startChar, endLine, endChar) => ({
    start: { line: startLine, character: startChar },
    end: { line: endLine, character: endChar }
  })),
  Position: jest.fn().mockImplementation((line, char) => ({ line, character: char })),
  Uri: {
    file: jest.fn().mockImplementation((path) => ({ fsPath: path }))
  }
}));

describe('generateCode', () => {
  describe('parseLLMResponse', () => {
    
    // --- Test Fallback Behavior (No Tags) ---

    it('should treat the entire response as code when no tags are present', () => {
      const response = `const x = 1;\nconsole.log(x);`;
      const result = parseLLMResponse(response);
      expect(result.newCode).toBe('const x = 1;\nconsole.log(x);');
      expect(result.newImports).toBeNull();
    });

    it('should throw an error for an empty response', () => {
        expect(() => parseLLMResponse('')).toThrow('AI response was empty.');
    });
    
    // --- Test Standard Tag Parsing ---

    it('should parse response with only an UPDATED_CODE block', () => {
      const response = `Some preceding text.\n<UPDATED_CODE>\nconst x = 1;\nconsole.log(x);\n</UPDATED_CODE>\nSome trailing text.`;
      const result = parseLLMResponse(response);
      expect(result.newCode).toBe('\nconst x = 1;\nconsole.log(x);\n');
      expect(result.newImports).toBeNull();
    });

    it('should parse response with only an UPDATED_IMPORTS block', () => {
      const response = `<UPDATED_IMPORTS>\nimport React from 'react';\n</UPDATED_IMPORTS>`;
      const result = parseLLMResponse(response);
      expect(result.newCode).toBe(''); // No code block found
      expect(result.newImports).toBe("\nimport React from 'react';\n");
    });
    
    it('should parse response with both imports and code blocks in correct order', () => {
      const response = `Thinking...\n<UPDATED_IMPORTS>\nimport { useState } from 'react';\n</UPDATED_IMPORTS>\nHere is the code:\n<UPDATED_CODE>\nconst [count, setCount] = useState(0);\n</UPDATED_CODE>`;
      const result = parseLLMResponse(response);
      expect(result.newCode).toBe('\nconst [count, setCount] = useState(0);\n');
      expect(result.newImports).toBe("\nimport { useState } from 'react';\n");
    });

    // --- Test Robustness and Edge Cases ---

    it('should handle nested tags correctly, extracting the outermost block', () => {
      const response = `<UPDATED_CODE>
function outer() {
  // <UPDATED_CODE>inner content</UPDATED_CODE>
  return "outer";
}
</UPDATED_CODE>`;
      const result = parseLLMResponse(response);
      expect(result.newCode).toBe(`
function outer() {
  // <UPDATED_CODE>inner content</UPDATED_CODE>
  return "outer";
}
`);
    });

    it('should extract the first outermost block if multiple exist', () => {
      const response = `<UPDATED_CODE>const first = 1;</UPDATED_CODE>\nSome text\n<UPDATED_CODE>const second = 2;</UPDATED_CODE>`;
      const result = parseLLMResponse(response);
      expect(result.newCode).toBe('const first = 1;');
    });

    it('should return empty string for a block with unclosed tags', () => {
      const response = `<UPDATED_CODE>\nconst x = 1;`;
      const result = parseLLMResponse(response);
      expect(result.newCode).toBe('');
      expect(result.newImports).toBeNull();
    });
  });
});