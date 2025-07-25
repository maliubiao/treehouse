// Import removed - using global jest
import { sessionManager } from '../../state/sessionManager';
import { TempFileManager } from '../../utils/tempFileManager';

// Mock all dependencies
jest.mock('../../utils/logger');
jest.mock('../../utils/tempFileManager');
jest.mock('../../ui/interactions');
// Simple vscode mock
jest.mock('vscode', () => ({
    window: {
        createOutputChannel: jest.fn(),
        showInformationMessage: jest.fn(),
        showTextDocument: jest.fn(),
        tabGroups: {
            close: jest.fn()
        }
    },
    workspace: {
        getConfiguration: jest.fn(() => ({
            get: jest.fn()
        })),
        applyEdit: jest.fn(),
        fs: {
            readFile: jest.fn(),
        }
    },
    commands: {
        executeCommand: jest.fn()
    },
    Uri: {
        file: (path: string) => ({
            path: path,
            toString: () => `file://${path}`
        })
    }
}));

describe('SessionManager', () => {
  let mockTempFileManager: jest.Mocked<TempFileManager>;
  
  beforeEach(() => {
    jest.clearAllMocks();
    
    // Mock TempFileManager
    mockTempFileManager = {
      cleanup: jest.fn().mockResolvedValue(undefined),
    } as any;
    
    // Reset sessionManager state
    (sessionManager as any).currentSession = null;
    (sessionManager as any).endingPromise = null;
  });

  describe('isSessionActive', () => {
    it('should return false initially', () => {
      expect(sessionManager.isSessionActive()).toBe(false);
    });

    it('should return true when session is active', async () => {
      await sessionManager.start({
        originalUri: { toString: () => 'test' } as any,
        newUri: { toString: () => 'test' } as any,
        targetEditorUri: { fsPath: '/test' } as any,
        targetSelection: {
          start: { line: 0, character: 0 },
          end: { line: 1, character: 0 }
        } as any,
        tempFileManager: mockTempFileManager
      });
      
      expect(sessionManager.isSessionActive()).toBe(true);
    });
  });

  describe('start', () => {
    it('should start a new session', async () => {
      const sessionData = {
        originalUri: { toString: () => 'test' } as any,
        newUri: { toString: () => 'test' } as any,
        targetEditorUri: { resourceUri: 'test' } as any,
        targetSelection: {
          start: { line: 0, character: 0 },
          end: { line: 1, character: 0 }
        } as any,
        tempFileManager: mockTempFileManager
      };

      await sessionManager.start(sessionData);
      
      expect(sessionManager.isSessionActive()).toBe(true);
      expect((sessionManager as any).currentSession).toEqual(sessionData);
    });

    it('should end previous session before starting new one', async () => {
      const sessionData1 = {
        originalUri: { toString: () => 'test1' } as any,
        newUri: { toString: () => 'test1' } as any,
        targetEditorUri: { resourceUri: 'test1' } as any,
        targetSelection: {
          start: { line: 0, character: 0 },
          end: { line: 1, character: 0 }
        } as any,
        tempFileManager: mockTempFileManager
      };

      const sessionData2 = {
        originalUri: { toString: () => 'test2' } as any,
        newUri: { toString: () => 'test2' } as any,
        targetEditorUri: { resourceUri: 'test2' } as any,
        targetSelection: {
          start: { line: 0, character: 0 },
          end: { line: 1, character: 0 }
        } as any,
        tempFileManager: mockTempFileManager
      };

      await sessionManager.start(sessionData1);
      await sessionManager.start(sessionData2);
      
      expect((sessionManager as any).currentSession).toEqual(sessionData2);
    });
  });

  describe('end', () => {
    it('should do nothing when no session active', async () => {
      await sessionManager.end();
      
      // Should not throw
      expect((sessionManager as any).currentSession).toBe(null);
    });

    it('should end active session', async () => {
      const sessionData = {
        originalUri: { toString: () => 'test' } as any,
        newUri: { toString: () => 'test' } as any,
        targetEditorUri: { resourceUri: 'test' } as any,
        targetSelection: {
          start: { line: 0, character: 0 },
          end: { line: 1, character: 0 }
        } as any,
        tempFileManager: mockTempFileManager
      };

      await sessionManager.start(sessionData);
      await sessionManager.end();
      
      expect(sessionManager.isSessionActive()).toBe(false);
    });
  });

  describe('accept', () => {
    it('should do nothing when no session active', async () => {
      await sessionManager.accept();
      
      // Should not throw
      expect(mockTempFileManager.cleanup).not.toHaveBeenCalled();
    });

    // Note: Full accept testing requires complex VS Code mocking
    // Simplified for now - would need document/workspace mocking
  });

  describe('reject', () => {
    it('should do nothing when no session active', async () => {
      await sessionManager.reject();
      
      // Should not throw
      expect(mockTempFileManager.cleanup).not.toHaveBeenCalled();
    });

    it('should end session when active', async () => {
      const sessionData = {
        originalUri: { toString: () => 'test' } as any,
        newUri: { toString: () => 'test' } as any,
        targetEditorUri: { resourceUri: 'test' } as any,
        targetSelection: {
          start: { line: 0, character: 0 },
          end: { line: 1, character: 0 }
        } as any,
        tempFileManager: mockTempFileManager
      };

      await sessionManager.start(sessionData);
      await sessionManager.reject();
      
      expect(sessionManager.isSessionActive()).toBe(false);
    });
  });

  describe('getActiveSessionUris', () => {
    it('should return null when no session active', () => {
      expect(sessionManager.getActiveSessionUris()).toBe(null);
    });

    it('should return URIs when session is active', async () => {
      const sessionData = {
        originalUri: { toString: () => 'original' } as any,
        newUri: { toString: () => 'new' } as any,
        targetEditorUri: { resourceUri: 'test' } as any,
        targetSelection: {
          start: { line: 0, character: 0 },
          end: { line: 1, character: 0 }
        } as any,
        tempFileManager: mockTempFileManager
      };

      await sessionManager.start(sessionData);
      const uris = sessionManager.getActiveSessionUris();
      
      expect(uris).toEqual({
        originalUri: expect.any(Object),
        newUri: expect.any(Object),
      });
    });
  });
});