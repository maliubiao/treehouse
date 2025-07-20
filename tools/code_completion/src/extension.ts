import * as vscode from 'vscode';
import { generateCodeCommand } from './commands/generateCode';
import { UndoManager } from './state/undoManager';
import { TempFileManager } from './utils/tempFileManager';
import { panelManager } from './ui/panelManager';
import { logger } from './utils/logger';
import { showSettingsView } from './ui/settingsView';
import { sessionManager } from './state/sessionManager';

/**
 * This method is called when your extension is activated.
 * Your extension is activated the very first time the command is executed.
 */
export function activate(context: vscode.ExtensionContext): void {
    logger.log('Treehouse Code Completer is now active.');

    const undoManager = new UndoManager();

    // Register the main command for code generation
    const generateCode = vscode.commands.registerCommand(
        'treehouse-code-completer.generateCode',
        () => generateCodeCommand(context, undoManager, sessionManager)
    );

    // Register the command to undo the last generation
    const undoLastGeneration = vscode.commands.registerCommand(
        'treehouse-code-completer.undoLastGeneration',
        () => undoManager.undo()
    );

    // Register the command to open the webview developer tools
    const openWebviewDevTools = vscode.commands.registerCommand(
        'treehouse-code-completer.openWebviewDeveloperTools',
        () => {
            if (panelManager.getPanel()) {
                vscode.commands.executeCommand('workbench.action.webview.openDeveloperTools');
            } else {
                vscode.window.showInformationMessage('No active Treehouse Code Completer webview to inspect.');
            }
        }
    );

    // Register the command to open settings
    const openSettings = vscode.commands.registerCommand(
        'treehouse-code-completer.openSettings',
        () => showSettingsView(context)
    );

    // Register session commands for accepting/rejecting changes
    const acceptChanges = vscode.commands.registerCommand(
        'treehouse-code-completer.acceptChanges',
        () => sessionManager.accept()
    );
    
    const rejectChanges = vscode.commands.registerCommand(
        'treehouse-code-completer.rejectChanges',
        () => sessionManager.reject()
    );

    // Listener to clean up session if diff tab is closed manually
    const onDidChangeTabs = vscode.window.tabGroups.onDidChangeTabs(() => {
        if (!sessionManager.isSessionActive()) {
            return;
        }
        // const activeUris = sessionManager.getActiveSessionUris();
        // if (!activeUris) return;

        // const isDiffTabOpen = vscode.window.tabGroups.all.some(tg =>
        //     tg.tabs.some(tab =>
        //         tab.input instanceof vscode.TabInputTextDiff &&
        //         tab.input.original.toString() === activeUris.originalUri.toString() &&
        //         tab.input.modified.toString() === activeUris.newUri.toString()
        //     )
        // );
        
        // if (!isDiffTabOpen) {
        //     logger.log('Diff tab closed by user, ending session.');
        //     sessionManager.end();
        // }
    });

    context.subscriptions.push(
        generateCode, 
        undoLastGeneration, 
        openWebviewDevTools, 
        openSettings,
        acceptChanges,
        rejectChanges,
        onDidChangeTabs
    );
}

/**
 * This method is called when your extension is deactivated.
 * It's used to clean up any resources, like orphaned temporary files.
 */
export function deactivate(): Promise<void> {
    sessionManager.end(); // End any active session
    return TempFileManager.cleanupAll();
}