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