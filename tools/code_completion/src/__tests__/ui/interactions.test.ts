import * as vscode from 'vscode';
import { getInstruction, showInfoMessage, showErrorMessage } from '../../ui/interactions';

// Mock vscode
jest.mock('vscode', () => ({
  window: {
    showInputBox: jest.fn(),
    showInformationMessage: jest.fn(),
    showErrorMessage: jest.fn()
  }
}));

describe('interactions', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('getInstruction', () => {
    it('should return user input when provided', async () => {
      (vscode.window.showInputBox as jest.Mock).mockResolvedValue('Refactor this function');
      
      const result = await getInstruction();
      
      expect(result).toBe('Refactor this function');
      expect(vscode.window.showInputBox).toHaveBeenCalledWith({
        prompt: 'Enter your instruction for the AI',
        placeHolder: 'e.g., "Refactor this to be more efficient" or "Add JSDoc comments"',
        ignoreFocusOut: true,
      });
    });

    it('should return undefined when user cancels', async () => {
      (vscode.window.showInputBox as jest.Mock).mockResolvedValue(undefined);
      
      const result = await getInstruction();
      
      expect(result).toBeUndefined();
    });
  });

  describe('showInfoMessage', () => {
    it('should show information message with prefix', () => {
      showInfoMessage('Test message');
      
      expect(vscode.window.showInformationMessage).toHaveBeenCalledWith(
        'Treehouse Completer: Test message'
      );
    });
  });

  describe('showErrorMessage', () => {
    it('should show error message without retry option', async () => {
      (vscode.window.showErrorMessage as jest.Mock).mockResolvedValue(undefined);
      
      const result = await showErrorMessage('Test error');
      
      expect(vscode.window.showErrorMessage).toHaveBeenCalledWith(
        'Treehouse Completer Error: Test error'
      );
      expect(result).toBeUndefined();
    });

    it('should show error message with retry option', async () => {
      (vscode.window.showErrorMessage as jest.Mock).mockResolvedValue('Retry');
      
      const retryFn = jest.fn();
      const result = await showErrorMessage('Test error', retryFn);
      
      expect(vscode.window.showErrorMessage).toHaveBeenCalledWith(
        'Treehouse Completer Error: Test error',
        'Retry'
      );
      expect(retryFn).toHaveBeenCalled();
      expect(result).toBe('Retry');
    });

    it('should handle canceling retry', async () => {
      (vscode.window.showErrorMessage as jest.Mock).mockResolvedValue(undefined);
      
      const retryFn = jest.fn();
      const result = await showErrorMessage('Test error', retryFn);
      
      expect(retryFn).not.toHaveBeenCalled();
      expect(result).toBeUndefined();
    });
  });
});