
import * as vscode from 'vscode';
import { TempFileManager } from '../utils/tempFileManager';
import { showInfoMessage } from '../ui/interactions';
import { logger } from '../utils/logger';
import { TextDecoder } from 'util';
import { t } from '../util/i18n';
import {showErrorMessage} from '../ui/interactions'

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
    return active;
  }

  public async start(session: GenerationSession): Promise<void> {
    if (this.endingPromise) {
      await this.endingPromise;
      this.endingPromise = null;
    }
    this.currentSession = session;
    
    await vscode.commands.executeCommand('setContext', SessionManager.CONTEXT_KEY, true);
    logger.log('Generation session started.', { originalUri: session.originalUri.toString(), newUri: session.newUri.toString() });

    await vscode.commands.executeCommand('vscode.diff', session.originalUri, session.newUri, "Treehouse AI Suggestion (Entire File) vs. Original");

    const keys = getPlatformKeybindings();
    showInfoMessage(
      t('sessionManager.suggestionReady', { acceptKey: keys.accept, rejectKey: keys.reject })
    );
  }

  public async end(): Promise<void> {
    if (!this.currentSession) {
      return;
    }

    const session = this.currentSession;
    this.currentSession = null;

    this.endingPromise = this.performEnd(session);
    await this.endingPromise;
    this.endingPromise = null;
  }

  private async performEnd(session: GenerationSession): Promise<void> {
    try {
      await vscode.commands.executeCommand('setContext', SessionManager.CONTEXT_KEY, false);
      await this.closeDiffTab(session.originalUri, session.newUri);
      await session.tempFileManager.cleanup();
      await vscode.window.showTextDocument(session.targetEditorUri);
      logger.log('Generation session ended and cleaned up.');
    } catch (error) {
      logger.error('Error during session cleanup', error);
    }
  }

  public async accept(): Promise<void> {
    if (!this.currentSession) {
      return;
    }

    const { newUri, targetEditorUri, targetSelection } = this.currentSession;

    try {
      const newContentBytes = await vscode.workspace.fs.readFile(newUri);
      const newFullContent = new TextDecoder().decode(newContentBytes);

      const editor = await vscode.window.showTextDocument(targetEditorUri);
      const document = editor.document;

      const fullRange = new vscode.Range(
        document.lineAt(0).range.start,
        document.lineAt(document.lineCount - 1).range.end
      );

      const workspaceEdit = new vscode.WorkspaceEdit();
      workspaceEdit.replace(targetEditorUri, fullRange, newFullContent);
      const success = await vscode.workspace.applyEdit(workspaceEdit);

      if (success) {
          const newSelection = new vscode.Selection(targetSelection.start, targetSelection.start);
          editor.selection = newSelection;
          editor.revealRange(newSelection, vscode.TextEditorRevealType.InCenterIfOutsideViewport);
          showInfoMessage(t('sessionManager.changesApplied'));
      } else {
          throw new Error(t('sessionManager.applyFailed'));
      }

    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      logger.error(t('sessionManager.applyFailedError', {error: errorMessage}), error);
      showErrorMessage(t('sessionManager.applyFailedError', { error: errorMessage}));
    } finally {
      await this.end();
    }
  }

  public async reject(): Promise<void> {
    if (!this.currentSession) {
      return;
    }
    logger.log('Rejecting changes...');
    showInfoMessage(t('sessionManager.changesRejected'));
    await this.end();
  }

  public getActiveSessionUris(): { originalUri: vscode.Uri; newUri: vscode.Uri } | null {
    return this.currentSession ? {
      originalUri: this.currentSession.originalUri,
      newUri: this.currentSession.newUri,
    } : null;
  }

  private async closeDiffTab(originalUri: vscode.Uri, newUri: vscode.Uri): Promise<void> {
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
          } catch (e) {
            logger.error("Failed to close diff tab.", e);
          }
          return;
        }
      }
    }
    logger.log('No matching diff tab found to close');
  }
}

export const sessionManager = new SessionManager();