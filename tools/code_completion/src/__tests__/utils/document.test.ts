import * as vscode from 'vscode';
import { extractImportBlock, applyChanges, getGenerationContext } from '../../utils/document';

// Mock vscode
jest.mock('vscode', () => ({
  window: {
    activeTextEditor: null,
  },
  commands: {
    executeCommand: jest.fn()
  },
  Range: jest.fn((start, end) => ({ start, end, contains: jest.fn()})),
  Position: jest.fn((line, char) => ({ line, character: char })),
  Uri: {
    file: jest.fn().mockImplementation((path) => ({ fsPath: path, toString: () => path }))
  },
  Selection: jest.fn((start, end) => ({ start, end, isEmpty: start === end }))
}));

describe('document utilities', () => {
  describe('extractImportBlock', () => {
    it('should extract simple import statements', () => {
      const mockDocument = {
        lineCount: 3,
        lineAt: jest.fn().mockImplementation((i) => {
          const lines = [
            { text: 'import React from "react";', isEmptyOrWhitespace: false, range: { end: 20 } },
            { text: 'import { useState } from "react";', isEmptyOrWhitespace: false, range: { end: 20 } },
            { text: '', isEmptyOrWhitespace: true, range: { end: 0 } }
          ];
          return lines[i];
        })
      } as any;
      (vscode.Range as jest.Mock).mockImplementation((start, end) => ({ start, end }));

      const result = extractImportBlock(mockDocument);
      expect(result).not.toBeNull();
      expect(result?.text).toContain('import React from "react";');
      expect(result?.text).toContain('import { useState } from "react";');
    });

    it('should handle empty documents', () => {
      const mockDocument = {
        lineCount: 0,
        lineAt: jest.fn()
      } as any;

      const result = extractImportBlock(mockDocument);
      expect(result).toBeNull();
    });

    it('should handle documents without imports', () => {
      const mockDocument = {
        lineCount: 2,
        lineAt: jest.fn().mockImplementation((i) => {
          const lines = [
            { text: 'const x = 1;', isEmptyOrWhitespace: false },
            { text: 'console.log(x);', isEmptyOrWhitespace: false }
          ];
          return lines[i];
        })
      } as any;

      const result = extractImportBlock(mockDocument);
      expect(result).toBeNull();
    });

    it('should preserve empty lines within import blocks', () => {
      const mockDocument = {
        lineCount: 4,
        lineAt: jest.fn().mockImplementation((i) => {
          const lines = [
            { text: 'import React from "react";', isEmptyOrWhitespace: false, range: { end: 20 } },
            { text: '', isEmptyOrWhitespace: true, range: { end: 0 } },
            { text: 'import { useState } from "react";', isEmptyOrWhitespace: false, range: { end: 20 } },
            { text: 'console.log("test");', isEmptyOrWhitespace: false, range: { end: 20 } }
          ];
          return lines[i];
        })
      } as any;

      const result = extractImportBlock(mockDocument);
      expect(result).not.toBeNull();
      expect(result?.text).toContain('import React from "react";\n\nimport { useState } from "react";');
    });

    it('should handle Python multi-line imports with parentheses', () => {
      const mockDocument = {
        lineCount: 6,
        lineAt: jest.fn().mockImplementation((i) => {
          const lines = [
            { text: 'from typing import (', isEmptyOrWhitespace: false, range: { end: 20 } },
            { text: '    List,', isEmptyOrWhitespace: false, range: { end: 10 } },
            { text: '    Dict,', isEmptyOrWhitespace: false, range: { end: 10 } },
            { text: '    Optional,', isEmptyOrWhitespace: false, range: { end: 15 } },
            { text: ')', isEmptyOrWhitespace: false, range: { end: 1 } },
            { text: '', isEmptyOrWhitespace: true, range: { end: 0 } }
          ];
          return lines[i];
        })
      } as any;

      const result = extractImportBlock(mockDocument);
      expect(result).not.toBeNull();
      expect(result?.text).toContain('from typing import (');
      expect(result?.text).toContain('    List,');
      expect(result?.text).toContain('    Dict,');
      expect(result?.text).toContain('    Optional,');
      expect(result?.text).toContain(')');
    });

    it('should handle JavaScript multi-line imports with curly braces', () => {
      const mockDocument = {
        lineCount: 7,
        lineAt: jest.fn().mockImplementation((i) => {
          const lines = [
            { text: 'import {', isEmptyOrWhitespace: false, range: { end: 8 } },
            { text: '  useState,', isEmptyOrWhitespace: false, range: { end: 10 } },
            { text: '  useEffect,', isEmptyOrWhitespace: false, range: { end: 12 } },
            { text: '  createContext,', isEmptyOrWhitespace: false, range: { end: 15 } },
            { text: '} from "react";', isEmptyOrWhitespace: false, range: { end: 17 } },
            { text: '', isEmptyOrWhitespace: true, range: { end: 0 } },
            { text: 'const App = () => {};', isEmptyOrWhitespace: false, range: { end: 20 } }
          ];
          return lines[i];
        })
      } as any;

      const result = extractImportBlock(mockDocument);
      expect(result).not.toBeNull();
      expect(result?.text).toContain('import {');
      expect(result?.text).toContain('  useState,');
      expect(result?.text).toContain('  useEffect,');
      expect(result?.text).toContain('  createContext,');
      expect(result?.text).toContain('} from "react";');
    });

    it('should handle Python imports with trailing commas and line continuations', () => {
      const mockDocument = {
        lineCount: 5,
        lineAt: jest.fn().mockImplementation((i) => {
          const lines = [
            { text: 'import pandas as pd,', isEmptyOrWhitespace: false, range: { end: 20 } },
            { text: '    numpy as np,', isEmptyOrWhitespace: false, range: { end: 20 } },
            { text: '    matplotlib.pyplot as plt', isEmptyOrWhitespace: false, range: { end: 30 } },
            { text: '', isEmptyOrWhitespace: true, range: { end: 0 } },
            { text: 'df = pd.DataFrame()', isEmptyOrWhitespace: false, range: { end: 20 } }
          ];
          return lines[i];
        })
      } as any;

      const result = extractImportBlock(mockDocument);
      expect(result).not.toBeNull();
      expect(result?.text).toContain('import pandas as pd,');
      expect(result?.text).toContain('    numpy as np,');
      expect(result?.text).toContain('    matplotlib.pyplot as plt');
    });

    it('should handle mixed single and multi-line imports', () => {
      const mockDocument = {
        lineCount: 10,
        lineAt: jest.fn().mockImplementation((i) => {
          const lines = [
            { text: 'import React from "react";', isEmptyOrWhitespace: false, range: { end: 20 } },
            { text: 'import {', isEmptyOrWhitespace: false, range: { end: 8 } },
            { text: '  Button,', isEmptyOrWhitespace: false, range: { end: 10 } },
            { text: '  Card,', isEmptyOrWhitespace: false, range: { end: 8 } },
            { text: '} from "antd";', isEmptyOrWhitespace: false, range: { end: 15 } },
            { text: '', isEmptyOrWhitespace: true, range: { end: 0 } },
            { text: 'from typing import (', isEmptyOrWhitespace: false, range: { end: 17 } },
            { text: '    List, Dict', isEmptyOrWhitespace: false, range: { end: 15 } },
            { text: ')', isEmptyOrWhitespace: false, range: { end: 1 } },
            { text: 'const App = () => {};', isEmptyOrWhitespace: false, range: { end: 20 } }
          ];
          return lines[i];
        })
      } as any;

      const result = extractImportBlock(mockDocument);
      expect(result).not.toBeNull();
      expect(result?.text).toContain('import React from "react";');
      expect(result?.text).toContain('import {');
      expect(result?.text).toContain('  Button,');
      expect(result?.text).toContain('  Card,');
      expect(result?.text).toContain('} from "antd";');
      expect(result?.text).toContain('from typing import');
      expect(result?.text).toContain('    List, Dict');
    });

    it('should handle nested parentheses in import statements', () => {
      const mockDocument = {
        lineCount: 6,
        lineAt: jest.fn().mockImplementation((i) => {
          const lines = [
            { text: 'from mymodule import (', isEmptyOrWhitespace: false, range: { end: 20 } },
            { text: '    func1, func2,', isEmptyOrWhitespace: false, range: { end: 20 } },
            { text: '    TuppleType,  # Tuple[int, str]', isEmptyOrWhitespace: false, range: { end: 30 } },
            { text: '    DictType,  # Dict[str, Any]', isEmptyOrWhitespace: false, range: { end: 30 } },
            { text: ')', isEmptyOrWhitespace: false, range: { end: 1 } },
            { text: '', isEmptyOrWhitespace: true, range: { end: 0 } }
          ];
          return lines[i];
        })
      } as any;

      const result = extractImportBlock(mockDocument);
      expect(result).not.toBeNull();
      expect(result?.text).toContain('from mymodule import (');
      expect(result?.text).toContain('    func1, func2,');
      expect(result?.text).toContain('    TuppleType,  # Tuple[int, str]');
      expect(result?.text).toContain('    DictType,  # Dict[str, Any]');
      expect(result?.text).toContain(')');
    });
  });

  describe('getGenerationContext', () => {
    beforeEach(() => {
      jest.clearAllMocks();
    });

    it('should return null when no active editor', async () => {
      (vscode.window.activeTextEditor as any) = null;
      
      const result = await getGenerationContext();
      expect(result).toBeNull();
    });

    it('should return null when in terminal editor', async () => {
      const mockEditor = {
        document: {
          languageId: 'terminal',
          getText: jest.fn().mockReturnValue(''),
          uri: { fsPath: '/test/file.js', toString: () => 'file:///test/file.js' },
          fileName: 'file.js'
        },
        selection: {
          isEmpty: true,
          active: { line: 0, character: 0 },
          start: { line: 0, character: 0 },
          end: { line: 0, character: 0 }
        }
      };
      
      (vscode.window.activeTextEditor as any) = mockEditor;
      (vscode.commands.executeCommand as jest.Mock).mockResolvedValue([]);

      const result = await getGenerationContext();
      expect(result).toBeNull();
    });

    it('should return null when in debug console editor', async () => {
      const mockEditor = {
        document: {
          languageId: 'debug-console',
          getText: jest.fn().mockReturnValue(''),
          uri: { fsPath: '/test/file.js', toString: () => 'file:///test/file.js' },
          fileName: 'file.js'
        },
        selection: {
          isEmpty: true,
          active: { line: 0, character: 0 },
          start: { line: 0, character: 0 },
          end: { line: 0, character: 0 }
        }
      };
      
      (vscode.window.activeTextEditor as any) = mockEditor;
      (vscode.commands.executeCommand as jest.Mock).mockResolvedValue([]);

      const result = await getGenerationContext();
      expect(result).toBeNull();
    });

    it('should return null when in output panel editor', async () => {
      const mockEditor = {
        document: {
          languageId: 'output',
          getText: jest.fn().mockReturnValue(''),
          uri: { fsPath: '/test/file.js', toString: () => 'file:///test/file.js' },
          fileName: 'file.js'
        },
        selection: {
          isEmpty: true,
          active: { line: 0, character: 0 },
          start: { line: 0, character: 0 },
          end: { line: 0, character: 0 }
        }
      };
      
      (vscode.window.activeTextEditor as any) = mockEditor;
      (vscode.commands.executeCommand as jest.Mock).mockResolvedValue([]);

      const result = await getGenerationContext();
      expect(result).toBeNull();
    });

    it('should handle empty selection with no enclosing symbol', async () => {
      const mockEditor = {
        document: {
          languageId: 'javascript',
          getText: jest.fn().mockReturnValue('const x = 1;\nconsole.log(x);'),
          uri: { fsPath: '/test/file.js', toString: () => 'file:///test/file.js' },
          fileName: 'file.js'
        },
        selection: {
          isEmpty: true,
          active: { line: 0, character: 0 },
          start: { line: 0, character: 0 },
          end: { line: 0, character: 0 }
        }
      };
      
      (vscode.window.activeTextEditor as any) = mockEditor;
      (vscode.commands.executeCommand as jest.Mock).mockResolvedValue([]);

      const result = await getGenerationContext();
      expect(result).not.toBeNull();
      expect(result?.selectedText).toBe('');
      expect(result?.filePath).toBe('/test/file.js');
      expect(result?.fileExtension).toBe('.js');
    });

    it('should handle text selection', async () => {
      const mockEditor = {
        document: {
          languageId: 'javascript',
          getText: jest.fn().mockImplementation((range?: any) => {
            if (!range) return 'const x = 1;\nconsole.log(x);';
            return 'const x = 1;';
          }),
          uri: { fsPath: '/test/file.js', toString: () => 'file:///test/file.js' },
          fileName: 'file.js',
          lineCount: 2,
          lineAt: jest.fn().mockImplementation((i) => ({
            text: i === 0 ? 'const x = 1;' : 'console.log(x);'
          }))
        },
        selection: {
          isEmpty: false,
          active: { line: 0, character: 0 },
          start: { line: 0, character: 0 },
          end: { line: 0, character: 12 }
        }
      };
      
      (vscode.window.activeTextEditor as any) = mockEditor;
      (vscode.commands.executeCommand as jest.Mock).mockResolvedValue([]);

      const result = await getGenerationContext();
      expect(result).not.toBeNull();
      expect(result?.selectedText).toBe('const x = 1;');
      expect(result?.filePath).toBe('/test/file.js');
    });
  });

  describe('applyChanges', () => {
    it('should throw error when editor is invalid', async () => {
      await expect(applyChanges(null as any, null as any, 'test'))
        .rejects
        .toThrow('Invalid editor or document state');
    });

    it('should throw error when document is closed', async () => {
      const mockEditor = {
        document: {
          isClosed: true
        }
      };
      
      await expect(applyChanges(mockEditor as any, new (vscode.Range as any)(0, 0, 0, 0), 'test'))
        .rejects
        .toThrow('Document has been closed');
    });

    it('should throw error when range is invalid', async () => {
      const mockEditor = {
        document: {
          isClosed: false
        },
        edit: jest.fn()
      };
      
      await expect(applyChanges(mockEditor as any, null as any, 'test'))
        .rejects
        .toThrow('Invalid range provided');
    });

    it('should apply changes successfully', async () => {
      const mockEdit = jest.fn(callback => {
        const builder = { replace: jest.fn() };
        callback(builder);
        return Promise.resolve(true);
      });
      const mockEditor = {
        document: {
          isClosed: false
        },
        edit: mockEdit
      };
      
      await expect(applyChanges(mockEditor as any, new (vscode.Range as any)(0, 0, 0, 0), 'test'))
        .resolves
        .toBeUndefined();
      
      expect(mockEditor.edit).toHaveBeenCalled();
    });

    it('should throw error when edit fails', async () => {
      const mockEditor = {
        document: {
          isClosed: false
        },
        edit: jest.fn().mockResolvedValue(false)
      };
      
      await expect(applyChanges(mockEditor as any, new (vscode.Range as any)(0, 0, 0, 0), 'test'))
        .rejects
        .toThrow('Failed to apply changes to the document');
    });
  });
});