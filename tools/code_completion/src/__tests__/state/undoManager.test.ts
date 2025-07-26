import * as vscode from 'vscode';
import { UndoManager } from '../../state/undoManager';
import { showInfoMessage } from '../../ui/interactions';

// Mock vscode
jest.mock('vscode', () => ({
  window: {
    showTextDocument: jest.fn(),
    showErrorMessage: jest.fn(),
    showInformationMessage: jest.fn()
  },
  ViewColumn: {
    Active: 1,
  },
  Range: jest.fn(),
  Position: jest.fn()
}));

// Mock interactions and i18n
jest.mock('../../ui/interactions');
jest.mock('../../util/i18n', () => ({ t: (key: string) => key }));

describe('UndoManager', () => {
  let undoManager: UndoManager;
  
  beforeEach(() => {
    jest.clearAllMocks();
    undoManager = new UndoManager();
  });

  describe('undo', () => {
    it('should show message when no edit to undo', async () => {
      await undoManager.undo();
      
      expect(showInfoMessage).toHaveBeenCalledWith('undoManager.nothingToUndo');
    });

    it('should successfully undo last edit', async () => {
      const mockUri = { path: '/test.ts' } as any;
      const mockRange = { start: { line: 0, character: 0 }, end: { line: 0, character: 5 } } as any;
      const originalText = 'const x = 1;';
      
      undoManager.remember(mockUri, mockRange, originalText);
      
      const mockEditor = {
        document: {
          positionAt: jest.fn().mockReturnValue({ line: 0, character: 0 }),
          getText: jest.fn().mockReturnValue('some new text')
        },
        selection: {},
        edit: jest.fn(callback => {
            const builder = { replace: jest.fn() };
            callback(builder);
            expect(builder.replace).toHaveBeenCalledWith(expect.any(Object), originalText);
            return Promise.resolve(true);
        })
      };
      (vscode.window.showTextDocument as jest.Mock).mockResolvedValue(mockEditor);
      
      await undoManager.undo();
      
      expect(vscode.window.showTextDocument).toHaveBeenCalledWith(mockUri, { viewColumn: vscode.ViewColumn.Active });
      expect(showInfoMessage).toHaveBeenCalledWith('undoManager.reverted');
    });

    it('should handle undo failure', async () => {
      const mockUri = { path: '/test.ts' } as any;
      const mockRange = { start: { line: 0, character: 0 }, end: { line: 0, character: 5 } } as any;
      const originalText = 'const x = 1;';
      
      undoManager.remember(mockUri, mockRange, originalText);
      
      (vscode.window.showTextDocument as jest.Mock).mockRejectedValue(new Error('Test error'));
      
      await undoManager.undo();
      
      expect(vscode.window.showErrorMessage).toHaveBeenCalledWith('undoManager.revertFailed');
    });
  });
});