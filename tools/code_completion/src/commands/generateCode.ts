import * as vscode from 'vscode';
import { getGenerationContext } from '../utils/document';
import { getInstruction, showInfoMessage } from '../ui/interactions';
import { generateCode as callLLMApi, TokenUsage } from '../api/llmClient';
import { UndoManager } from '../state/undoManager';
import { TempFileManager } from '../utils/tempFileManager';
import { getActiveAiServiceConfig } from '../config/configuration';
import { showSettingsView } from '../ui/settingsView';
import { logger } from '../utils/logger';
import { GenerationContext } from '../types';

/**
 * Parses the raw LLM response to extract code and imports from tagged sections.
 *
 * This function uses a single-pass, stack-based parser to robustly handle
 * potentially nested or malformed tags. It operates with the following rules:
 *
 * 1.  **Error Handling:** Throws an error for empty or whitespace-only input.
 * 2.  **Fallback:** If no `UPDATED_*` tags are found, the entire response is
 *     treated as the new code.
 * 3.  **Parsing:**
 *     - It captures the content of the **first** complete, outermost block for
 *       each tag type (`<UPDATED_CODE>`, `<UPDATED_IMPORTS>`).
 *     - It correctly handles nested tags, ignoring inner blocks.
 *     - It does NOT trim whitespace from the extracted content, preserving formatting.
 *     - For malformed tags (e.g., unclosed tags, or an end tag without a start tag),
 *       it logs a warning and ignores the content, ensuring predictable output.
 *
 * @param responseText The full string response from the LLM.
 * @returns An object with the new code and optionally new imports.
 * @throws {Error} If the response is empty.
 */
export function parseLLMResponse(responseText: string): { newCode: string; newImports: string | null } {
    if (!responseText || !responseText.trim()) {
        throw new Error('AI response was empty.');
    }

    const CODE_TAG = 'UPDATED_CODE';
    const IMPORTS_TAG = 'UPDATED_IMPORTS';

    // Fallback for responses without any tags. Using a simpler regex for the check.
    if (!/<UPDATED_(CODE|IMPORTS)>/.test(responseText)) {
        return { newCode: responseText, newImports: null };
    }

    const tagRegex = /<(\/?)(UPDATED_CODE|UPDATED_IMPORTS)>/g;
    let match;

    const codeStack: number[] = [];
    const importsStack: number[] = [];

    let codeContent: string | null = null;
    let importsContent: string | null = null;

    while ((match = tagRegex.exec(responseText)) !== null) {
        const [fullMatch, slash, tagName] = match;
        const isEndTag = slash === '/';

        const stack = tagName === CODE_TAG ? codeStack : importsStack;
        
        if (isEndTag) {
            if (stack.length > 0) {
                const startIndex = stack.pop()!;
                if (stack.length === 0) { // Closing an outermost tag
                    const content = responseText.substring(startIndex, match.index);
                    if (tagName === CODE_TAG) {
                        if (codeContent === null) codeContent = content; // Capture first one
                    } else {
                        if (importsContent === null) importsContent = content; // Capture first one
                    }
                }
            } else {
                logger.warn(`Found end tag </${tagName}> without matching start tag.`);
            }
        } else { // Start Tag
            stack.push(match.index + fullMatch.length);
        }
    }

    if (codeStack.length > 0 || importsStack.length > 0) {
        const unclosed = [
            ...(codeStack.length > 0 ? [`<${CODE_TAG}>`] : []),
            ...(importsStack.length > 0 ? [`<${IMPORTS_TAG}>`] : [])
        ];
        logger.warn('Unclosed tags found in LLM response:', unclosed);
    }
    
    return {
        newCode: codeContent ?? '',
        newImports: importsContent
    };
}


/**
 * Constructs the new full content of the file by replacing the import and code blocks.
 * This is a robust way to handle edits, as it avoids issues with shifting ranges.
 * @param originalContent The original full text of the document.
 * @param context The generation context containing ranges for imports and selection.
 * @param newCode The new code to insert.
 * @param newImports The new import block text (or null if unchanged).
 * @returns The complete new string for the file.
 */
export function stitchNewFileContent(
    originalContent: string,
    context: GenerationContext,
    newCode: string,
    newImports: string | null,
): string {
    const { document } = context.editor;
    const { selection, importBlock } = context;

    const selectionStartOffset = document.offsetAt(selection.start);
    const selectionEndOffset = document.offsetAt(selection.end);
    
    const importStartOffset = importBlock ? document.offsetAt(importBlock.range.start) : 0;
    const importEndOffset = importBlock ? document.offsetAt(importBlock.range.end) : 0;
    
    let finalImportText = newImports ?? (importBlock?.text ?? null);

    if (newImports && !importBlock) {
        finalImportText = `${newImports.trim()}`;
    } else if (newImports) {
        finalImportText = newImports.trim();
    }


    if (importEndOffset > selectionStartOffset) {
        logger.warn('Selection is within or before the import block. Performing a simple replacement.');
        return originalContent.slice(0, selectionStartOffset) + newCode + originalContent.slice(selectionEndOffset);
    }

    const beforeImports = originalContent.slice(0, importStartOffset);
    const betweenImportsAndCode = originalContent.slice(importEndOffset, selectionStartOffset);
    const afterCode = originalContent.slice(selectionEndOffset);
    
    const stitched = beforeImports + (finalImportText ?? '') + betweenImportsAndCode + newCode + afterCode;
    return stitched;
}

/**
 * Wraps the LLM API call with a timeout and cancellation logic.
 */
async function callLLMWithTimeout(
    instruction: string,
    generationContext: GenerationContext,
    cancellationToken: vscode.CancellationToken,
): Promise<{ code: string; usage: TokenUsage }> {
    const timeoutMs = 120000; // 2 minutes timeout

    return new Promise((resolve, reject) => {
        const timeout = setTimeout(() => {
            reject(new Error('AI generation request timed out after 2 minutes.'));
        }, timeoutMs);

        const cancellationRegistration = cancellationToken.onCancellationRequested(() => {
            clearTimeout(timeout);
            reject(new Error('Operation cancelled by user.'));
        });

        const onProgress = (_tokenCount: number, _currentText: string) => {
            // This function can be passed to callLLMApi if progress updates are needed.
        };

        callLLMApi(instruction, generationContext, onProgress, cancellationToken)
            .then(result => {
                clearTimeout(timeout);
                cancellationRegistration.dispose();
                resolve(result);
            })
            .catch(err => {
                clearTimeout(timeout);
                cancellationRegistration.dispose();
                reject(err);
            });
    });
}

export async function generateCodeCommand(
    context: vscode.ExtensionContext, 
    undoManager: UndoManager,
    sessionManager: any
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
    if (instruction === undefined) { 
        return;
    }

    const tempFileManager = new TempFileManager();

    try {
        const { editor, fileExtension } = generationContext;
        
        let result: { code: string; usage: TokenUsage };
        
        await vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: 'Treehouse AI is working...',
            cancellable: true
        }, async (progress, token) => {
            progress.report({ message: 'Initializing...' });
            
            result = await callLLMWithTimeout(instruction, generationContext, token);
            
            progress.report({ message: 'Finalizing response...' });
        });
        
        const { code: rawResponse, usage } = result!;
        const { newCode, newImports } = parseLLMResponse(rawResponse);
        
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
        
        const newFullContent = stitchNewFileContent(originalFullContent, generationContext, newCode, newImports);

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
            targetSelection: generationContext.selection,
            tempFileManager
        };

        await sessionManager.start(sessionData);

    } catch (error) {
        await tempFileManager.cleanup();
        const errorMessage = error instanceof Error ? error.message : String(error);
        
        logger.error('Command Execution Error:', {
            error: {
                message: errorMessage,
                stack: error instanceof Error ? error.stack : undefined,
            },
            context: 'generateCodeCommand',
        });

        if (errorMessage.includes('Operation cancelled')) {
            showInfoMessage('Operation cancelled.');
            return;
        }

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