import * as vscode from 'vscode';
import { getGenerationContext } from '../utils/document';
import { getInstruction, showInfoMessage, showErrorMessage } from '../ui/interactions';
import { generateCode as callLLMApi, TokenUsage } from '../api/llmClient';
import { UndoManager } from '../state/undoManager';
import { TempFileManager } from '../utils/tempFileManager';
import { getActiveAiServiceConfig } from '../config/configuration';
import { showSettingsView } from '../ui/settingsView';
import { logger } from '../utils/logger';
import { GenerationContext } from '../types';
import { t } from '../util/i18n';
import { sessionManager } from '../state/sessionManager';

/**
 * Trims leading and trailing blank lines from a string.
 * A line is considered blank if it contains only whitespace.
 * This function preserves indentation of the first and last non-blank lines.
 * Returns null if the input is null.
 * Returns an empty string if the input is empty or contains only whitespace.
 */
function trimBlankLines(str: string | null): string | null {
    if (str === null) {
        return null;
    }
    if (str.trim() === '') {
        return '';
    }

    const lines = str.split('\n');
    let start = 0;
    while (start < lines.length && lines[start].trim() === '') {
        start++;
    }

    let end = lines.length - 1;
    while (end >= start && lines[end].trim() === '') {
        end--;
    }

    return lines.slice(start, end + 1).join('\n');
}


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
 *     - For malformed tags (e.g., unclosed tags, or an end tag without a start tag),
 *       it logs a warning and ignores the content, ensuring predictable output.
 * 4.  **Cleaning:** All extracted content and fallback responses are cleaned of
 *     leading/trailing blank lines using `trimBlankLines`.
 *
 * @param responseText The full string response from the LLM.
 * @returns An object with the new code and optionally new imports.
 * @throws {Error} If the response is empty.
 */
export function parseLLMResponse(responseText: string): { newCode: string; newImports: string | null } {
    if (!responseText || !responseText.trim()) {
        throw new Error(t('generateCode.emptyResponse'));
    }

    const CODE_TAG = 'UPDATED_CODE';
    const IMPORTS_TAG = 'UPDATED_IMPORTS';

    if (!/<UPDATED_(CODE|IMPORTS)>/.test(responseText)) {
        // No tags found, treat the whole response as code and trim it.
        return { newCode: trimBlankLines(responseText) ?? '', newImports: null };
    }
    
    const tagRegex = /<(\/)?(UPDATED_CODE|UPDATED_IMPORTS)>/g;
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
                        if (codeContent === null) codeContent = content;
                    } else {
                        if (importsContent === null) importsContent = content;
                    }
                }
            } else {
                logger.warn(`Found end tag </${tagName}> without matching start tag.`);
            }
        } else {
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
    
    // Apply trimming to the extracted content
    const finalCode = trimBlankLines(codeContent);
    const finalImports = trimBlankLines(importsContent);
    
    return {
        newCode: finalCode ?? '',
        newImports: finalImports
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
    
    if (!importBlock) {
        return originalContent.slice(0, selectionStartOffset) + newCode + originalContent.slice(selectionEndOffset);
    }
    
    const importStartOffset = document.offsetAt(importBlock.range.start);
    const importEndOffset = document.offsetAt(importBlock.range.end);
    
    if (importEndOffset >= selectionStartOffset) {
        logger.warn('Selection is within or before the import block. Performing a simple replacement.');
        return originalContent.slice(0, selectionStartOffset) + newCode + originalContent.slice(selectionEndOffset);
    }
    
    let finalImportText = importBlock.text;
    if (newImports !== null) {
        finalImportText = newImports;
    }
    
    const beforeImports = originalContent.slice(0, importStartOffset);
    let betweenImportsAndCode = originalContent.slice(importEndOffset, selectionStartOffset);
    const afterCode = originalContent.slice(selectionEndOffset);
    
    if (finalImportText.trim().length > 0 && !finalImportText.endsWith('\n') && !finalImportText.endsWith('\r\n')) {
        finalImportText += '\n';
    }

    if (finalImportText.endsWith('\n') || finalImportText.endsWith('\r\n')) {
        if (betweenImportsAndCode.startsWith('\r\n')) {
            betweenImportsAndCode = betweenImportsAndCode.substring(2);
        } else if (betweenImportsAndCode.startsWith('\n')) {
            betweenImportsAndCode = betweenImportsAndCode.substring(1);
        }
    }
    
    return beforeImports + finalImportText + betweenImportsAndCode + newCode + afterCode;
}

async function callLLMWithTimeout(
    instruction: string,
    generationContext: GenerationContext,
    cancellationToken: vscode.CancellationToken,
): Promise<{ code: string; usage: TokenUsage }> {
    const activeService = getActiveAiServiceConfig();
    const timeoutSeconds = activeService?.timeout_seconds ?? 120;
    const timeoutMs = timeoutSeconds * 1000;

    return new Promise((resolve, reject) => {
        const timeout = setTimeout(() => {
            cancellationRegistration.dispose();
            reject(new Error(t('generateCode.timeout')));
        }, timeoutMs);

        const cancellationRegistration = cancellationToken.onCancellationRequested(() => {
            clearTimeout(timeout);
            cancellationRegistration.dispose();
            // The rejection is handled inside callLLMApi, which will throw an AbortError
        });

        callLLMApi(instruction, generationContext, undefined, cancellationToken)
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
    _sessionManager: typeof sessionManager
): Promise<void> {
    const activeService = getActiveAiServiceConfig();
    if (!activeService) {
        const selection = await vscode.window.showInformationMessage(
            t('generateCode.noActiveService'),
            t('generateCode.openSettings')
        );
        if (selection === t('generateCode.openSettings')) {
            showSettingsView(context);
        }
        return;
    }

    const generationContext = await getGenerationContext();
    if (!generationContext) {
        const editor = vscode.window.activeTextEditor;
        if (editor?.document) {
            const specialEditors = ['terminal', 'debug-console', 'output'];
            if (specialEditors.includes(editor.document.languageId)) {
                showInfoMessage(t('generateCode.notAvailableInSpecialEditor'));
                return;
            }
        }
        
        showInfoMessage(t('generateCode.noFileSelected'));
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
            title: t('generateCode.progress.working'),
            cancellable: true
        }, async (progress, token) => {
            progress.report({ message: t('generateCode.progress.initializing') });
            
            result = await callLLMWithTimeout(instruction, generationContext, token);
            
            progress.report({ message: t('generateCode.progress.finalizing') });
        });
        
        const { code: rawResponse, usage } = result!;
        const { newCode, newImports } = parseLLMResponse(rawResponse);
        
        const costDisplay = (usage.cost ?? 0) > 0 ? ` ($${usage.cost!.toFixed(4)})` : '';
        showInfoMessage(t('generateCode.success', { totalTokens: usage.totalTokens, costDisplay }));
        
        logger.log('Token usage details:', usage);
        
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

        await sessionManager.start({
            originalUri,
            newUri,
            targetEditorUri: editor.document.uri,
            targetSelection: generationContext.selection,
            tempFileManager
        });

    } catch (error) {
        await tempFileManager.cleanup();
        const errorMessage = error instanceof Error ? error.message : String(error);
        
        logger.error('Command Execution Error:', {
            error: {
                message: errorMessage,
                stack: error instanceof Error ? error.stack : undefined,
            },
        });

        if (errorMessage === t('generateCode.cancelled')) {
            showInfoMessage(t('generateCode.cancelled'));
            return;
        }

        const retryOption = t('ui.retry');
        const selection = await showErrorMessage(errorMessage, () => {
             vscode.commands.executeCommand('treehouse-code-completer.generateCode');
        });

        if (selection !== retryOption) {
            const showDetailsOption = t('generateCode.showDetails');
            const userChoice = await vscode.window.showErrorMessage(
                t('generateCode.error', { errorMessage }),
                showDetailsOption
            );
            if (userChoice === showDetailsOption) {
                logger.show();
            }
        }
    }
}