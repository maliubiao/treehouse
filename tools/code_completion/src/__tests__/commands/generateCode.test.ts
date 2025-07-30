import { parseLLMResponse, stitchNewFileContent, generateCodeCommand } from '../../commands/generateCode';
import * as vscode from 'vscode';
import { GenerationContext } from '../../types';
import { getInstruction, showInfoMessage, showErrorMessage } from '../../ui/interactions';
import { generateCode as callLLMApi } from '../../api/llmClient';
import { getActiveAiServiceConfig } from '../../config/configuration';

// Mock dependencies
jest.mock('../../utils/logger');
jest.mock('../../ui/interactions');
jest.mock('../../api/llmClient');
jest.mock('../../config/configuration');
jest.mock('../../state/sessionManager');
jest.mock('../../util/i18n', () => ({
  t: (key: string, options?: any) => {
    if (options) {
      // Simple interpolation for testing
      return Object.entries(options).reduce(
        (acc, [k, v]) => acc.replace(`{{${k}}}`, String(v)),
        key
      );
    }
    return key;
  },
}));

// Mock vscode
jest.mock('vscode', () => ({
  Range: jest.fn().mockImplementation((startLine, startChar, endLine, endChar) => ({
    start: { line: startLine, character: startChar },
    end: { line: endLine, character: endChar }
  })),
  Position: jest.fn().mockImplementation((line, char) => ({ line, character: char })),
  Uri: {
    file: jest.fn().mockImplementation((path) => ({ fsPath: path, toString: () => path }))
  },
  ProgressLocation: {
    Notification: 15,
  },
  window: {
      showInformationMessage: jest.fn(),
      showErrorMessage: jest.fn(),
      withProgress: jest.fn((_options, task) => task(
          { report: jest.fn() },
          {
              isCancellationRequested: false,
              onCancellationRequested: jest.fn((_listener: any) => ({ dispose: jest.fn() }))
          }
      )),
      createOutputChannel: jest.fn(() => ({
          appendLine: jest.fn(),
          show: jest.fn()
      }))
  },
  commands: {
      executeCommand: jest.fn()
  }
}));

describe('generateCode command and helpers', () => {
  
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('parseLLMResponse', () => {
    it('should treat the entire response as code when no tags are present', () => {
      const response = `const x = 1;\nconsole.log(x);`;
      const result = parseLLMResponse(response);
      expect(result.newCode).toBe('const x = 1;\nconsole.log(x);');
      expect(result.newImports).toBeNull();
    });

    it('should throw an error for an empty response', () => {
        expect(() => parseLLMResponse('')).toThrow('generateCode.emptyResponse');
    });
    
    it('should parse response with both imports and code blocks', () => {
      const response = `<UPDATED_IMPORTS>\nimport { useState } from 'react';\n</UPDATED_IMPORTS>\n<UPDATED_CODE>\nconst [count, setCount] = useState(0);\n</UPDATED_CODE>`;
      const result = parseLLMResponse(response);
      expect(result.newCode).toBe('const [count, setCount] = useState(0);');
      expect(result.newImports).toBe("import { useState } from 'react';");
    });

    it('should return null for imports when UPDATED_IMPORTS contains only whitespace', () => {
      const response = `<UPDATED_IMPORTS>\n\n</UPDATED_IMPORTS>\n<UPDATED_CODE>\nconst [count, setCount] = useState(0);\n</UPDATED_CODE>`;
      const result = parseLLMResponse(response);
      expect(result.newCode).toBe('const [count, setCount] = useState(0);');
      expect(result.newImports).toBeNull();
    });

    it('should return null for imports when UPDATED_IMPORTS is empty', () => {
      const response = `<UPDATED_IMPORTS></UPDATED_IMPORTS>\n<UPDATED_CODE>\nconst [count, setCount] = useState(0);\n</UPDATED_CODE>`;
      const result = parseLLMResponse(response);
      expect(result.newCode).toBe('const [count, setCount] = useState(0);');
      expect(result.newImports).toBeNull();
    });

  });

  describe('stitchNewFileContent', () => {
    const createMockDocument = (content: string) => ({
        offsetAt: jest.fn((position: vscode.Position): number => {
            const lines = content.split('\n');
            let offset = 0;
            for (let i = 0; i < position.line; i++) {
                if (lines[i] !== undefined) offset += lines[i].length + 1;
            }
            offset += position.character;
            return Math.min(offset, content.length);
        }),
        positionAt: jest.fn((offset: number): vscode.Position => {
            offset = Math.max(0, Math.min(offset, content.length));
            const textUpToOffset = content.substring(0, offset);
            const lines = textUpToOffset.split('\n');
            const line = lines.length - 1;
            const character = lines[line].length;
            return new (vscode.Position as any)(line, character);
        }),
    });

    const getRangeFromSubstring = (doc: any, fulltext: string, substring: string) => {
        const startOffset = fulltext.indexOf(substring);
        if (startOffset === -1) throw new Error(`Substring not found: "${substring}"`);
        const endOffset = startOffset + substring.length;
        const startPos = doc.positionAt(startOffset);
        const endPos = doc.positionAt(endOffset);
        return new (vscode.Range as any)(startPos.line, startPos.character, endPos.line, endPos.character);
    };

    it('should replace selected content correctly', () => {
        const originalContent = `const a = 1;\nconst b = 2;\nconsole.log(a + b);`;
        const mockDocument = createMockDocument(originalContent);
        const selectedText = 'const b = 2;';
        const context: GenerationContext = {
            editor: { document: mockDocument } as any,
            selection: getRangeFromSubstring(mockDocument, originalContent, selectedText),
            fullFileContent: originalContent,
            importBlock: null
        } as any;
        const newCode = 'const b = 3;';
        const result = stitchNewFileContent(originalContent, context, newCode, null);
        expect(result).toBe(`const a = 1;\nconst b = 3;\nconsole.log(a + b);`);
    });

    it('should not modify import block when newImports is null', () => {
        const originalContent = `import { useState } from 'react';\n\nconst App = () => {\n  return <div>Hello</div>;\n};`;
        const mockDocument = createMockDocument(originalContent);
        const importText = `import { useState } from 'react';\n`;
        const selectedText = `const App = () => {\n  return <div>Hello</div>;\n};`;
        const context: GenerationContext = {
            editor: { document: mockDocument } as any,
            selection: getRangeFromSubstring(mockDocument, originalContent, selectedText),
            fullFileContent: originalContent,
            importBlock: {
                text: importText,
                range: getRangeFromSubstring(mockDocument, originalContent, importText)
            }
        } as any;
        const newCode = `const App = () => {\n  return <div>Updated Hello</div>;\n};`;
        const result = stitchNewFileContent(originalContent, context, newCode, null);
        expect(result).toBe(`import { useState } from 'react';\nconst App = () => {\n  return <div>Updated Hello</div>;\n};`);
    });

    it('should replace import block when newImports is not null', () => {
        const originalContent = `import { useState } from 'react';\n\nconst App = () => {\n  return <div>Hello</div>;\n};`;
        const mockDocument = createMockDocument(originalContent);
        const importText = `import { useState } from 'react';\n`;
        const selectedText = `const App = () => {\n  return <div>Hello</div>;\n};`;
        const context: GenerationContext = {
            editor: { document: mockDocument } as any,
            selection: getRangeFromSubstring(mockDocument, originalContent, selectedText),
            fullFileContent: originalContent,
            importBlock: {
                text: importText,
                range: getRangeFromSubstring(mockDocument, originalContent, importText)
            }
        } as any;
        const newCode = `const App = () => {\n  return <div>Updated Hello</div>;\n};`;
        const newImports = `import { useState, useEffect } from 'react';\n`;
        const result = stitchNewFileContent(originalContent, context, newCode, newImports);
        expect(result).toBe(`import { useState, useEffect } from 'react';\nconst App = () => {\n  return <div>Updated Hello</div>;\n};`);
    });
  });

  describe('generateCodeCommand main logic', () => {
    it('should show settings prompt if no active service', async () => {
      (getActiveAiServiceConfig as jest.Mock).mockReturnValue(undefined);
      await generateCodeCommand({} as any, {} as any, {} as any);
      expect(vscode.window.showInformationMessage).toHaveBeenCalledWith(
        'generateCode.noActiveService', 'generateCode.openSettings'
      );
    });

    it('should exit if user provides no instruction', async () => {
      (getActiveAiServiceConfig as jest.Mock).mockReturnValue({ name: 'test-service' });
      (getInstruction as jest.Mock).mockResolvedValue(undefined);
      
      // A simplified mock context
      const mockGetGenerationContext = jest.spyOn(require('../../utils/document'), 'getGenerationContext')
        .mockResolvedValue({ editor: { document: { getText: () => 'foo' } } });
      
      await generateCodeCommand({} as any, {} as any, {} as any);
      
      expect(callLLMApi).not.toHaveBeenCalled();
      mockGetGenerationContext.mockRestore();
    });

    it('should handle API errors gracefully', async () => {
        (getActiveAiServiceConfig as jest.Mock).mockReturnValue({ name: 'test-service' });
        (getInstruction as jest.Mock).mockResolvedValue('test instruction');
        
        const mockGetGenerationContext = jest.spyOn(require('../../utils/document'), 'getGenerationContext')
          .mockResolvedValue({ 
            editor: { document: { getText: () => 'foo', uri: 'file://test.ts', positionAt: () => ({line:0, character:0}) } },
            fileExtension: '.ts',
            selection: new (vscode.Range as any)(0,0,0,0)
          });

        (callLLMApi as jest.Mock).mockRejectedValue(new Error("Test API Error"));

        await generateCodeCommand({} as any, { remember: jest.fn() } as any, {} as any);

        expect(showErrorMessage).toHaveBeenCalledWith("Test API Error", expect.any(Function));

        mockGetGenerationContext.mockRestore();
    });

    it('should show cancellation message when cancelled', async () => {
        (getActiveAiServiceConfig as jest.Mock).mockReturnValue({ name: 'test-service' });
        (getInstruction as jest.Mock).mockResolvedValue('test instruction');
        
        const mockGetGenerationContext = jest.spyOn(require('../../utils/document'), 'getGenerationContext')
          .mockResolvedValue({ 
            editor: { document: { getText: () => 'foo', uri: 'file://test.ts', positionAt: () => ({line:0, character:0}) } },
            fileExtension: '.ts',
            selection: new (vscode.Range as any)(0,0,0,0)
          });
        
        // Mock the cancellation error
        (callLLMApi as jest.Mock).mockRejectedValue(new Error("generateCode.cancelled"));

        await generateCodeCommand({} as any, { remember: jest.fn() } as any, {} as any);

        expect(showInfoMessage).toHaveBeenCalledWith("generateCode.cancelled");
        expect(showErrorMessage).not.toHaveBeenCalled();

        mockGetGenerationContext.mockRestore();
    });
  });
});