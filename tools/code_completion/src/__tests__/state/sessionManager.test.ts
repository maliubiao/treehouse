import { sessionManager, GenerationSession } from '../../state/sessionManager';
import { TempFileManager } from '../../utils/tempFileManager';
import * as vscode from 'vscode';
import { showInfoMessage } from '../../ui/interactions';
import { TextEncoder } from 'util';

// Mock dependencies
jest.mock('../../utils/logger');
jest.mock('../../utils/tempFileManager');
jest.mock('../../ui/interactions');
jest.mock('../../util/i18n', () => ({ t: (key: string) => key }));

// Simple vscode mock
jest.mock('vscode', () => ({
    window: {
        showInformationMessage: jest.fn(),
        showTextDocument: jest.fn().mockResolvedValue({
            document: {
                lineAt: (i: number) => ({ range: { start: { line: i, character: 0 }, end: { line: i, character: 10 } } }),
                lineCount: 2,
            },
            selection: {},
            revealRange: jest.fn(),
        }),
        tabGroups: {
            close: jest.fn(),
            all: [],
        },
        createOutputChannel: jest.fn(() => ({
            appendLine: jest.fn(),
            show: jest.fn(),
        })),
    },
    workspace: {
        applyEdit: jest.fn().mockResolvedValue(true),
        fs: {
            readFile: jest.fn(),
        }
    },
    commands: {
        executeCommand: jest.fn().mockResolvedValue(undefined)
    },
    Uri: {
        file: (path: string) => ({
            path: path,
            fsPath: path,
            toString: () => `file://${path}`
        })
    },
    Position: jest.fn((line, character) => ({ line, character })),
    Range: jest.fn((start, end) => ({ start, end })),
    Selection: jest.fn((start, end) => ({ start, end })),
    TabInputTextDiff: class {},
    TextEditorRevealType: { InCenterIfOutsideViewport: 2 },
    WorkspaceEdit: class {
        replace = jest.fn();
    }
}));

describe('SessionManager', () => {
  let mockTempFileManager: jest.Mocked<TempFileManager>;
  
  beforeEach(() => {
    jest.clearAllMocks();
    
    mockTempFileManager = new TempFileManager() as jest.Mocked<TempFileManager>;
    mockTempFileManager.cleanup = jest.fn().mockResolvedValue(undefined);
    
    (sessionManager as any).currentSession = null;
    (sessionManager as any).endingPromise = null;
  });

  const createMockSession = (): GenerationSession => ({
    originalUri: vscode.Uri.file('/tmp/original.ts'),
    newUri: vscode.Uri.file('/tmp/new.ts'),
    targetEditorUri: vscode.Uri.file('/project/file.ts'),
    targetSelection: new vscode.Range(new (vscode.Position as any)(5, 0), new (vscode.Position as any)(10, 0)),
    tempFileManager: mockTempFileManager,
  });

  describe('start', () => {
    it('should start a session and show diff view', async () => {
      const session = createMockSession();
      await sessionManager.start(session);

      expect((sessionManager as any).currentSession).toBe(session);
      expect(vscode.commands.executeCommand).toHaveBeenCalledWith('setContext', 'treehouseCodeCompleter.diffViewActive', true);
      expect(vscode.commands.executeCommand).toHaveBeenCalledWith('vscode.diff', session.originalUri, session.newUri, expect.any(String));
      expect(showInfoMessage).toHaveBeenCalledWith('sessionManager.suggestionReady');
    });
  });

  describe('end', () => {
    it('should end an active session and clean up', async () => {
      const session = createMockSession();
      (sessionManager as any).currentSession = session;
      
      await sessionManager.end();

      expect((sessionManager as any).currentSession).toBeNull();
      expect(vscode.commands.executeCommand).toHaveBeenCalledWith('setContext', 'treehouseCodeCompleter.diffViewActive', false);
      expect(mockTempFileManager.cleanup).toHaveBeenCalled();
    });
  });

  describe('accept', () => {
    it('should apply changes and end the session', async () => {
      const session = createMockSession();
      (sessionManager as any).currentSession = session;
      
      const newContent = 'const newCode = "accepted";';
      const newContentBytes = new TextEncoder().encode(newContent);
      (vscode.workspace.fs.readFile as jest.Mock).mockResolvedValue(newContentBytes);

      await sessionManager.accept();

      expect(vscode.workspace.fs.readFile).toHaveBeenCalledWith(session.newUri);
      expect(vscode.workspace.applyEdit).toHaveBeenCalled();
      expect(showInfoMessage).toHaveBeenCalledWith('sessionManager.changesApplied');
      expect(sessionManager.isSessionActive()).toBe(false);
    });
  });

  describe('reject', () => {
    it('should reject changes and end the session', async () => {
      const session = createMockSession();
      (sessionManager as any).currentSession = session;
      
      await sessionManager.reject();

      expect(vscode.workspace.applyEdit).not.toHaveBeenCalled();
      expect(showInfoMessage).toHaveBeenCalledWith('sessionManager.changesRejected');
      expect(sessionManager.isSessionActive()).toBe(false);
    });
  });
});