import * as vscode from 'vscode';
import { getGenerationContext } from '../utils/document';
import { getInstruction, showInfoMessage } from '../ui/interactions';
import { generateCode as callLLMApi } from '../api/llmClient';
import { UndoManager } from '../state/undoManager';
import { TempFileManager } from '../utils/tempFileManager';
import { getActiveAiServiceConfig } from '../config/configuration';
import { showSettingsView } from '../ui/settingsView';
import { SessionManager } from '../state/sessionManager';

/**
 * The main command logic for generating code.
 * Orchestrates the workflow up to starting a diff session.
 * @param context - The extension context.
 * @param undoManager - The manager for handling undo operations.
 * @param sessionManager - The manager for the active generation session.
 */
export async function generateCodeCommand(
    context: vscode.ExtensionContext, 
    undoManager: UndoManager,
    sessionManager: SessionManager
): Promise<void> {
    const activeService = getActiveAiServiceConfig();
    if (!activeService) {
        const selection = await vscode.window.showInformationMessage(
            'No active Treehouse AI service is configured. Please set up a service to continue.',
            'Open Settings'
        );
        if (selection === 'Open Settings') {
            showSettingsView(context);
        }
        return;
    }

    const generationContext = await getGenerationContext();
    if (!generationContext) {
        showInfoMessage('Please select a block of code, or place your cursor inside a function/class to refactor.');
        return;
    }

    const instruction = await getInstruction();
    if (instruction === undefined) { // User cancelled the input box
        return;
    }

    const tempFileManager = new TempFileManager();

    try {
        const sessionData = await vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: 'Treehouse AI is working...',
            cancellable: false
        }, async (progress) => {
            progress.report({ message: 'Generating code...' });
            
            const { editor, selection, selectedText, fileExtension } = generationContext;
            const generatedCode = await callLLMApi(instruction, generationContext);
            
            undoManager.remember(editor.document.uri, selection, selectedText);
            
            const { originalUri, newUri } = await tempFileManager.createTempFilesForDiff(
                selectedText,
                generatedCode,
                fileExtension
            );

            return {
                originalUri,
                newUri,
                targetEditorUri: editor.document.uri,
                targetSelection: selection,
                tempFileManager
            };
        });

        // Start the session, which will show the diff view and handle all subsequent user actions.
        await sessionManager.start(sessionData);

    } catch (error) {
        // In case of an error during the API call or file creation, ensure temp files are cleaned up.
        await tempFileManager.cleanup();

        const errorMessage = error instanceof Error ? error.message : String(error);
        const selection = await vscode.window.showErrorMessage(`Treehouse Completer Error: ${errorMessage}`, 'Retry');
        if (selection === 'Retry') {
            vscode.commands.executeCommand('treehouse-code-completer.generateCode');
        }
    }
}