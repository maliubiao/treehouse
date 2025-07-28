import * as vscode from 'vscode';
import { getInstruction, showInfoMessage, showErrorMessage } from '../../ui/interactions';
import { t } from '../../util/i18n';

// Mock vscode
jest.mock('vscode', () => ({
  window: {
    showInputBox: jest.fn(),
    showInformationMessage: jest.fn(),
    showErrorMessage: jest.fn()
  }
}));

// Mock i18n
jest.mock('../../util/i18n', () => ({
  t: jest.fn((key, options) => {
    // A simple mock that returns the key, or interpolates for testing purposes.
    if (key === 'interactions.showInfoMessage_prefix' && options?.message) {
      return `Treehouse Completer: ${options.message}`;
    }
    if (key === 'interactions.showErrorMessage_prefix' && options?.message) {
      return `Treehouse Completer Error: ${options.message}`;
    }
    if (key === 'ui.retry') {
        return 'Retry';
    }
    return key;
  })
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
        prompt: 'interactions.getInstruction.prompt',
        placeHolder: 'interactions.getInstruction.placeholder',
        ignoreFocusOut: true,
      });
      expect(t).toHaveBeenCalledWith('interactions.getInstruction.prompt');
      expect(t).toHaveBeenCalledWith('interactions.getInstruction.placeholder');
    });

    it('should return undefined when user cancels', async () => {
      (vscode.window.showInputBox as jest.Mock).mockResolvedValue(undefined);
      const result = await getInstruction();
      expect(result).toBeUndefined();
    });
  });

  describe('showInfoMessage', () => {
    it('should show information message with translated prefix', () => {
      showInfoMessage('Test message');
      
      expect(t).toHaveBeenCalledWith('interactions.showInfoMessage_prefix', { message: 'Test message' });
      expect(vscode.window.showInformationMessage).toHaveBeenCalledWith(
        'Treehouse Completer: Test message'
      );
    });
  });

  describe('showErrorMessage', () => {
    it('should show error message without retry option', async () => {
      (vscode.window.showErrorMessage as jest.Mock).mockResolvedValue(undefined);
      
      await showErrorMessage('Test error');
      
      expect(t).toHaveBeenCalledWith('interactions.showErrorMessage_prefix', { message: 'Test error' });
      expect(vscode.window.showErrorMessage).toHaveBeenCalledWith(
        'Treehouse Completer Error: Test error'
      );
    });

    it('should show error message with retry option', async () => {
      (vscode.window.showErrorMessage as jest.Mock).mockResolvedValue('Retry');
      const retryFn = jest.fn();

      await showErrorMessage('Test error', retryFn);
      
      expect(t).toHaveBeenCalledWith('common.retry');
      expect(vscode.window.showErrorMessage).toHaveBeenCalledWith(
        'Treehouse Completer Error: Test error',
        'Retry'
      );
      expect(retryFn).toHaveBeenCalled();
    });

    it('should handle canceling retry', async () => {
      (vscode.window.showErrorMessage as jest.Mock).mockResolvedValue(undefined);
      const retryFn = jest.fn();
      await showErrorMessage('Test error', retryFn);
      expect(retryFn).not.toHaveBeenCalled();
    });
  });
});