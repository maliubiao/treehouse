import * as vscode from 'vscode';
import { getGenerationContext } from '../utils/document';
import { getInstruction, showDiffView, showErrorMessage, showInfoMessage, getConfirmation } from '../ui/interactions';
import { generateCode as callLLMApi } from '../api/llmClient';
import { UndoManager } from '../state/undoManager';
import { TempFileManager } from '../utils/tempFileManager';
import { getActiveAiServiceConfig } from '../config/configuration';
import { showSettingsView } from '../ui/settingsView';
import { TextDecoder } from 'util';

/**
 * The main command logic for generating code.
 * Orchestrates the entire workflow from user input to applying changes.
 * @param context - The extension context.
 * @param undoManager - The manager for handling undo operations.
 */
export async function generateCodeCommand(context: vscode.ExtensionContext, undoManager: UndoManager): Promise<void> {
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
        // Step 1: Run the long-running task with a progress indicator.
        // This block handles the API call and temp file creation.
        const result = await vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: 'Treehouse AI is working...',
            cancellable: false
        }, async (progress) => {
            progress.report({ message: 'Generating code...' });
            
            const { editor, selection, selectedText, fileExtension } = generationContext;
            const generatedCode = await callLLMApi(instruction, generationContext);
            
            undoManager.remember(editor.document.uri, selection, selectedText);
            
            const tempFiles = await tempFileManager.createTempFilesForDiff(
                selectedText,
                generatedCode,
                fileExtension
            );

            // Return all necessary data for the next, interactive step.
            return {
                ...tempFiles, // originalUri and newUri
                editor,
                selection
            };
        });

        // The progress notification is now gone.
        // Step 2: Handle user interaction (diff view and confirmation).
        const { originalUri, newUri } = result;

        await showDiffView(originalUri, newUri, "Treehouse AI Suggestion vs. Original");
        
        const userChoice = await getConfirmation();

        // Helper to close the diff tab cleanly
        const closeDiffTab = async (): Promise<void> => {
            for (const tab of vscode.window.tabGroups.all.flatMap(tg => tg.tabs)) {
                if (tab.input instanceof vscode.TabInputTextDiff &&
                    originalUri && newUri &&
                    tab.input.original.toString() === originalUri.toString() &&
                    tab.input.modified.toString() === newUri.toString()) {
                    try {
                        await vscode.window.tabGroups.close(tab);
                    } catch (e) {
                        console.error("Treehouse Code Completer: Failed to close diff tab.", e);
                    }
                    return;
                }
            }
        };
        
        if (userChoice === 'Accept') {
            const newContentBytes = await vscode.workspace.fs.readFile(newUri);
            const finalContent = new TextDecoder().decode(newContentBytes);

            const workspaceEdit = new vscode.WorkspaceEdit();
            workspaceEdit.replace(result.editor.document.uri, result.selection, finalContent);
            await vscode.workspace.applyEdit(workspaceEdit);
            
            const lines = finalContent.split('\n');
            const newEndLine = result.selection.start.line + lines.length - 1;
            const newEndChar = lines.length === 1
                ? result.selection.start.character + finalContent.length
                : lines[lines.length - 1].length;
            const newEndPosition = new vscode.Position(newEndLine, newEndChar);
            const newSelection = new vscode.Selection(result.selection.start, newEndPosition);

            result.editor.selection = newSelection;
            result.editor.revealRange(newSelection, vscode.TextEditorRevealType.Default);

            await closeDiffTab();
            await vscode.window.showTextDocument(result.editor.document.uri, { viewColumn: result.editor.viewColumn });
            showInfoMessage('Changes have been applied.');
            await tempFileManager.cleanup();
        } else if (userChoice === 'Reject') {
            await closeDiffTab();
            showInfoMessage('Changes were rejected.');
            await tempFileManager.cleanup();
        }
        // If userChoice is undefined (i.e., the notification was dismissed), we do nothing.
        // The diff view remains open for the user to review at their own pace.
        // The temp files will be cleaned up on extension deactivation.
    } catch (error) {
        // In case of an error during the process, ensure temp files are cleaned up.
        await tempFileManager.cleanup();

        const errorMessage = error instanceof Error ? error.message : String(error);
        const selection = await vscode.window.showErrorMessage(`Treehouse Completer Error: ${errorMessage}`, 'Retry');
        if (selection === 'Retry') {
            vscode.commands.executeCommand('treehouse-code-completer.generateCode');
        }
    }
}