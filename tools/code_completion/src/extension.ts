import * as vscode from 'vscode';
import { generateCodeCommand } from './commands/generateCode';
import { UndoManager } from './state/undoManager';
import { TempFileManager } from './utils/tempFileManager';
import { panelManager } from './ui/panelManager';
import { logger } from './utils/logger';
import { showSettingsView } from './ui/settingsView';

/**
 * This method is called when your extension is activated.
 * Your extension is activated the very first time the command is executed.
 */
export function activate(context: vscode.ExtensionContext): void {
    logger.log('AI Code Completer is now active.');

    const undoManager = new UndoManager();

    // Register the main command for code generation
    const generateCode = vscode.commands.registerCommand(
        'ai-code-completer.generateCode',
        () => generateCodeCommand(context, undoManager)
    );

    // Register the command to undo the last generation
    const undoLastGeneration = vscode.commands.registerCommand(
        'ai-code-completer.undoLastGeneration',
        () => undoManager.undo()
    );

    // Register the command to open the webview developer tools
    const openWebviewDevTools = vscode.commands.registerCommand(
        'ai-code-completer.openWebviewDeveloperTools',
        () => {
            if (panelManager.getPanel()) {
                vscode.commands.executeCommand('workbench.action.webview.openDeveloperTools');
            } else {
                vscode.window.showInformationMessage('No active AI Code Completer webview to inspect.');
            }
        }
    );

    // Register the command to open settings
    const openSettings = vscode.commands.registerCommand(
        'ai-code-completer.openSettings',
        () => showSettingsView(context)
    );

    context.subscriptions.push(generateCode, undoLastGeneration, openWebviewDevTools, openSettings);
}

/**
 * This method is called when your extension is deactivated.
 * It's used to clean up any resources, like orphaned temporary files.
 */
export function deactivate(): Promise<void> {
    return TempFileManager.cleanupAll();
}
