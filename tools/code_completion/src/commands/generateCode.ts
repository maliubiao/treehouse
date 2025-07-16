import * as vscode from 'vscode';
import { getGenerationContext } from '../utils/document';
import { getInstruction, showInfoMessage } from '../ui/interactions';
import { generateCode as callLLMApi, TokenUsage } from '../api/llmClient';
import { UndoManager } from '../state/undoManager';
import { TempFileManager } from '../utils/tempFileManager';
import { getActiveAiServiceConfig } from '../config/configuration';
import { showSettingsView } from '../ui/settingsView';
import { SessionManager } from '../state/sessionManager';
import { logger } from '../utils/logger';
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
        showInfoMessage('Place your cursor or select code in a file to generate code.');
        return;
    }

    const instruction = await getInstruction();
    if (instruction === undefined) { // User cancelled the input box
        return;
    }

    const tempFileManager = new TempFileManager();

    try {
        const { editor, selection, fileExtension } = generationContext;
        
        let result: { code: string; usage: TokenUsage };
        let progressMessage = '';
        
        await vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: 'Treehouse AI is working...',
            cancellable: false
        }, async (progress) => {
            progress.report({ message: 'Initializing...' });
            
            result = await callLLMApi(instruction, generationContext, (tokenCount, currentText) => {
                progressMessage = `Generated ${tokenCount} tokens...`;
                progress.report({ message: progressMessage });
            });
            
            progress.report({ message: 'Finalizing response...' });
        });
        
        const { code: generatedCode, usage } = result!;
        
        const costDisplay = usage.cost ? ` ($${usage.cost.toFixed(4)})` : '';
        showInfoMessage(`✅ Code generation completed | ${usage.totalTokens} tokens${costDisplay}`);
        
        logger.log('Token usage details:', {
            model: usage.model,
            promptTokens: usage.promptTokens,
            completionTokens: usage.completionTokens,
            totalTokens: usage.totalTokens,
            cost: usage.cost
        });
        
        const originalFullContent = editor.document.getText();
        
        // Use offsets for accurate string manipulation, works for both replacement and insertion.
        const offsetStart = editor.document.offsetAt(selection.start);
        const offsetEnd = editor.document.offsetAt(selection.end);
        const newFullContent = originalFullContent.slice(0, offsetStart) + generatedCode + originalFullContent.slice(offsetEnd);

        // For undo, remember the state of the entire file.
        const fullRange = new vscode.Range(
            editor.document.positionAt(0),
            editor.document.positionAt(originalFullContent.length)
        );
        undoManager.remember(editor.document.uri, fullRange, originalFullContent);
        
        const { originalUri, newUri } = await tempFileManager.createTempFilesForDiff(
            originalFullContent,
            newFullContent,
            fileExtension
        );

        const sessionData = {
            originalUri,
            newUri,
            targetEditorUri: editor.document.uri,
            targetSelection: selection, // Pass original selection for cursor positioning on accept
            tempFileManager
        };

        // Start the session, which will show the diff view and handle all subsequent user actions.
        await sessionManager.start(sessionData);

    } catch (error) {
        // In case of an error during the API call or file creation, ensure temp files are cleaned up.
        await tempFileManager.cleanup();

        const errorDetails = {
            message: error instanceof Error ? error.message : String(error),
            stack: error instanceof Error ? error.stack : new Error().stack,
            type: error?.constructor?.name || 'Unknown'
        };

        const errorMessage = error instanceof Error ? error.message : String(error);
        
        logger.error('Command Execution Error:', {
            error: errorDetails,
            context: 'generateCodeCommand',
            timestamp: new Date().toISOString()
        });

        const selection = await vscode.window.showErrorMessage(
            `Treehouse Completer Error: ${errorMessage}`, 
            'Show Details', 
            'Retry'
        );
        
        if (selection === 'Show Details') {
            logger.show();
        } else if (selection === 'Retry') {
            vscode.commands.executeCommand('treehouse-code-completer.generateCode');
        }
    }
}