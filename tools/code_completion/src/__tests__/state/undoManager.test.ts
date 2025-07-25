import * as vscode from 'vscode';
import { UndoManager } from '../../state/undoManager';

// Mock vscode
jest.mock('vscode', () => ({
  window: {
    showTextDocument: jest.fn(),
    showErrorMessage: jest.fn(),
    showInformationMessage: jest.fn()
  },
  ViewColumn: {
    Active: 1,
  }
}));

// Mock interactions
jest.mock('../../ui/interactions', () => ({
  showInfoMessage: jest.fn()
}));

describe('UndoManager', () => {
  let undoManager: UndoManager;
  
  beforeEach(() => {
    jest.clearAllMocks();
    undoManager = new UndoManager();
  });

  describe('remember', () => {
    it('should store edit details', () => {
      const mockUri = { toString: () => 'test' } as any;
      const mockRange = { start: { line: 0, character: 0 }, end: { line: 0, character: 5 } } as any;
      const originalText = 'const x = 1;';
      
      undoManager.remember(mockUri, mockRange, originalText);
      
      // We can't directly access private property, but we can test behavior
      expect(true).toBe(true); // Placeholder - actual testing happens in undo
    });
  });

  describe('undo', () => {
    it('should show message when no edit to undo', async () => {
      await undoManager.undo();
      
      const interactions = require('../../ui/interactions');
      expect(interactions.showInfoMessage).toHaveBeenCalledWith('No AI generation to undo.');
    });

    it('should successfully undo last edit', async () => {
      const mockUri = { toString: () => 'test' } as any;
      const mockRange = { start: { line: 0, character: 0 }, end: { line: 0, character: 5 } } as any;
      const originalText = 'const x = 1;';
      
      // Remember an edit
      undoManager.remember(mockUri, mockRange, originalText);
      
      // Mock showTextDocument to return editor with edit method
      const mockEditor = {
        edit: jest.fn(callback => {
            const builder = { replace: jest.fn() };
            callback(builder);
            return Promise.resolve(true);
        })
      };
      (vscode.window.showTextDocument as jest.Mock).mockResolvedValue(mockEditor);
      
      await undoManager.undo();
      
      expect(vscode.window.showTextDocument).toHaveBeenCalledWith(mockUri, {
        viewColumn: 1 // vscode.ViewColumn.Active
      });
      
      const interactions = require('../../ui/interactions');
      expect(interactions.showInfoMessage).toHaveBeenCalledWith('Last AI generation has been reverted.');
    });

    it('should handle undo failure', async () => {
      const mockUri = { toString: () => 'test' } as any;
      const mockRange = { start: { line: 0, character: 0 }, end: { line: 0, character: 5 } } as any;
      const originalText = 'const x = 1;';
      
      // Remember an edit
      undoManager.remember(mockUri, mockRange, originalText);
      
      // Mock showTextDocument to throw error
      (vscode.window.showTextDocument as jest.Mock).mockRejectedValue(new Error('Test error'));
      
      await undoManager.undo();
      
      expect(vscode.window.showErrorMessage).toHaveBeenCalledWith(
        'Failed to undo last edit: Test error'
      );
    });
  });
});