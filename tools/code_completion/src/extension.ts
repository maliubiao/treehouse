import * as vscode from 'vscode';
import { generateCodeCommand } from './commands/generateCode';
import { UndoManager } from './state/undoManager';
import { TempFileManager } from './utils/tempFileManager';
import { panelManager } from './ui/panelManager';
import { logger } from './utils/logger';
import { showSettingsView } from './ui/settingsView';
import { sessionManager } from './state/sessionManager';
import { initI18n, t } from './util/i18n';

/**
 * This method is called when your extension is activated.
 * Your extension is activated the very first time the command is executed.
 */
export async function activate(context: vscode.ExtensionContext): Promise<void> {
    await initI18n(context);

    logger.log(t('extension.activated'));

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
                vscode.window.showInformationMessage(t('extension.noActiveWebview'));
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
    const onDidChangeTabs = vscode.window.tabGroups.onDidChangeTabs(async () => {
        // Add a small delay to give VS Code time to update its tab state,
        // which helps prevent race conditions where the tab is not yet in the list.
        await new Promise(resolve => setTimeout(resolve, 150));
        
        if (!sessionManager.isSessionActive()) {
            return;
        }
        const activeUris = sessionManager.getActiveSessionUris();
        if (!activeUris) return;
    
        const isDiffTabOpen = vscode.window.tabGroups.all.some(tg =>
            tg.tabs.some(tab =>
                tab.input instanceof vscode.TabInputTextDiff &&
                tab.input.original.toString() === activeUris.originalUri.toString() &&
                tab.input.modified.toString() === activeUris.newUri.toString()
            )
        );
    
        if (isDiffTabOpen) {
            // We see the tab, so we mark it as seen. This happens when the tab successfully opens.
            if (!sessionManager.getDiffTabHasBeenSeen()) {
                logger.log('Diff tab is now visible and tracked.');
                sessionManager.setDiffTabHasBeenSeen(true);
            }
        } else {
            // The tab is not open. We only end the session if we had previously seen the tab.
            if (sessionManager.getDiffTabHasBeenSeen()) {
                logger.log('Tracked diff tab was closed by user, ending session.');
                // Using a small delay to prevent race conditions with other tab events.
                setTimeout(() => sessionManager.end(), 100);
            } else {
                // This case handles the race condition: a session is active,
                // but its diff tab hasn't been registered in the UI yet. We do nothing and wait.
                logger.log('Diff tab not yet visible, likely still opening. Waiting.');
            }
        }
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