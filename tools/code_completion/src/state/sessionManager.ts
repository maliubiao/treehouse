
import * as vscode from 'vscode';
import { TempFileManager } from '../utils/tempFileManager';
import { showInfoMessage } from '../ui/interactions';
import { logger } from '../utils/logger';
import { TextDecoder } from 'util';

export interface GenerationSession {
  originalUri: vscode.Uri;
  newUri: vscode.Uri;
  targetEditorUri: vscode.Uri;
  targetSelection: vscode.Range;
  tempFileManager: TempFileManager;
}

/**
 * Returns platform-specific keybinding strings for display.
 * @returns An object with human-readable keybindings for accept and reject.
 */
function getPlatformKeybindings(): { accept: string; reject: string } {
    const isMac = process.platform === 'darwin';
    return {
        accept: isMac ? 'Cmd+Alt+Y' : 'Ctrl+Alt+Y',
        reject: isMac ? 'Cmd+Alt+N' : 'Ctrl+Alt+N',
    };
}

class SessionManager {
  private currentSession: GenerationSession | null = null;
  private static readonly CONTEXT_KEY = 'treehouseCodeCompleter.diffViewActive';
  private endingPromise: Promise<void> | null = null;
  
  public isSessionActive(): boolean {
    const active = !!this.currentSession;
    logger.log(`SessionManager.isSessionActive() -> ${active}`);
    return active;
  }

  public async start(session: GenerationSession): Promise<void> {
    logger.log('SessionManager.start() called', { session });
    
    // Wait for any ongoing end operation to complete
    if (this.endingPromise) {
      logger.log('Waiting for ongoing end operation to complete...');
      await this.endingPromise;
      this.endingPromise = null;
      logger.log('Ongoing end operation completed.');
    }
    this.currentSession = session;
    
    await vscode.commands.executeCommand('setContext', SessionManager.CONTEXT_KEY, true);
    logger.log('Generation session started.', { originalUri: session.originalUri.toString(), newUri: session.newUri.toString() });

    await vscode.commands.executeCommand('vscode.diff', session.originalUri, session.newUri, "Treehouse AI Suggestion (Entire File) vs. Original");

    const keys = getPlatformKeybindings();
    showInfoMessage(
      `AI suggestion ready. Use ${keys.accept} to accept or ${keys.reject} to reject.`
    );
  }

  public async end(): Promise<void> {
    logger.log('SessionManager.end() called');
    if (!this.currentSession) {
      logger.log('No active session to end');
      return;
    }

    const session = this.currentSession;
    logger.log('Ending session', { session });
    this.currentSession = null;

    // Track the end operation to prevent races
    this.endingPromise = this.performEnd(session);
    await this.endingPromise;
    this.endingPromise = null;
  }

  private async performEnd(session: GenerationSession): Promise<void> {
    logger.log('SessionManager.performEnd() starting cleanup', { session });
    try {
      await vscode.commands.executeCommand('setContext', SessionManager.CONTEXT_KEY, false);
      await this.closeDiffTab(session.originalUri, session.newUri, session.targetEditorUri);
      await session.tempFileManager.cleanup();
      logger.log('Generation session ended and cleaned up.');
    } catch (error) {
      logger.error('Error during session cleanup', error);
    }
  }

  public async accept(): Promise<void> {
    logger.log('SessionManager.accept() called');
    if (!this.currentSession) {
      logger.log('No active session to accept');
      return;
    }

    logger.log('Accepting changes (full file)...');
    const { newUri, targetEditorUri, targetSelection } = this.currentSession;

    try {
      logger.log('Reading new content from temp file', { newUri: newUri.toString() });
      const newContentBytes = await vscode.workspace.fs.readFile(newUri);
      const newFullContent = new TextDecoder().decode(newContentBytes);

      logger.log('Showing target editor', { targetEditorUri: targetEditorUri.toString() });
      const editor = await vscode.window.showTextDocument(targetEditorUri);
      const document = editor.document;

      // Create a range for the entire document content
      const firstLine = document.lineAt(0);
      const lastLine = document.lineAt(document.lineCount - 1);
      const fullRange = new vscode.Range(firstLine.range.start, lastLine.range.end);

      logger.log('Applying workspace edit', { 
        targetEditorUri: targetEditorUri.toString(), 
        range: fullRange, 
        contentLength: newFullContent.length 
      });
      const workspaceEdit = new vscode.WorkspaceEdit();
      workspaceEdit.replace(targetEditorUri, fullRange, newFullContent);
      await vscode.workspace.applyEdit(workspaceEdit);

      // After applying, set the selection back to the start of the original
      // modification area for a better user experience.
      const newSelection = new vscode.Selection(targetSelection.start, targetSelection.start);
      editor.selection = newSelection;
      editor.revealRange(newSelection, vscode.TextEditorRevealType.InCenterIfOutsideViewport);

      showInfoMessage('Changes have been applied.');
    } catch (error) {
      logger.error('Failed to apply changes', error);
      vscode.window.showErrorMessage(`Failed to apply changes: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      await this.end();
    }
  }

  public async reject(): Promise<void> {
    logger.log('SessionManager.reject() called');
    if (!this.currentSession) {
      logger.log('No active session to reject');
      return;
    }
    logger.log('Rejecting changes...');
    showInfoMessage('Changes were rejected.');
    await this.end();
  }

  public getActiveSessionUris(): { originalUri: vscode.Uri; newUri: vscode.Uri } | null {
    const uris = this.currentSession ? {
      originalUri: this.currentSession.originalUri,
      newUri: this.currentSession.newUri,
    } : null;
    logger.log('SessionManager.getActiveSessionUris() ->', { uris });
    return uris;
  }

  private async closeDiffTab(originalUri: vscode.Uri, newUri: vscode.Uri, targetEditorUri: vscode.Uri): Promise<void> {
    logger.log('SessionManager.closeDiffTab() called', { 
      originalUri: originalUri.toString(), 
      newUri: newUri.toString(), 
      targetEditorUri: targetEditorUri.toString() 
    });
    
    for (const tabGroup of vscode.window.tabGroups.all) {
      for (const tab of tabGroup.tabs) {
        if (
          tab.input instanceof vscode.TabInputTextDiff &&
          tab.input.original.toString() === originalUri.toString() &&
          tab.input.modified.toString() === newUri.toString()
        ) {
          try {
            await vscode.window.tabGroups.close(tab);
            logger.log('Diff tab closed successfully');
            // Explicitly show the target document to ensure focus returns correctly.
            await vscode.window.showTextDocument(targetEditorUri);
            logger.log('Target editor shown after closing diff tab');
          } catch (e) {
            logger.error("Failed to close diff tab or restore original view.", e);
          }
          return;
        }
      }
    }
    logger.log('No matching diff tab found to close');

  }
}

export const sessionManager = new SessionManager();
