import * as vscode from 'vscode';
import * as path from 'path';
import { GenerationContext, SmartContext, ImportBlock } from '../types';

const MAX_FILE_SIZE_FOR_FULL_CONTEXT = 32 * 1024; // 32KB

/**
 * Extracts the contiguous block of import/require statements from the top of a document.
 * It allows for empty lines within the import block and skips shebang lines.
 * @param document - The VS Code text document.
 * @returns An object containing the import text and its range, or null if no imports are found.
 */
export function extractImportBlock(document: vscode.TextDocument): ImportBlock | null {
    let importText = '';
    let endLine = -1;
    let inBlock = false;
    let startLine = -1;

    // Skip shebang line if present
    let currentLine = 0;
    if (document.lineCount > 0 && document.lineAt(0).text.startsWith('#!')) {
        currentLine = 1;
    }

    // Skip doc comments at the top of the file
    while (currentLine < document.lineCount) {
        const line = document.lineAt(currentLine);
        if (line.isEmptyOrWhitespace) {
            currentLine++;
            continue;
        }
        // Check for doc comments (single line or multi-line)
        if (line.text.match(/^\s*\/\*\*/)) {
            // Multi-line doc comment - skip until we find the closing */
            while (currentLine < document.lineCount) {
                const docLine = document.lineAt(currentLine);
                if (docLine.text.includes('*/')) {
                    currentLine++;
                    break;
                }
                currentLine++;
            }
            continue;
        }
        // Single line comment
        if (line.text.match(/^\s*\/\//)) {
            currentLine++;
            continue;
        }
        break;
    }

    for (let i = currentLine; i < document.lineCount; i++) {
        const line = document.lineAt(i);

        if (line.isEmptyOrWhitespace) {
            if (inBlock) {
                importText += line.text + '\n'; // Preserve empty lines within the block
            }
            continue;
        }

        // A common pattern for imports/requires
        if (line.text.match(/^\s*(import|from|const .* = require|require)/)) {
            importText += line.text + '\n';
            endLine = i;
            if (startLine === -1) {
                startLine = i; // Mark the start of the import block
            }
            inBlock = true;
        } else {
            // The first non-import line signifies the end of the block
            if (inBlock) {
                break;
            }
        }
    }

    if (endLine > -1 && startLine > -1) {
        // Create a range for the import block
        const range = new vscode.Range(
            new vscode.Position(startLine, 0),
            document.lineAt(endLine).range.end
        );

        return { text: importText, range };
    }

    return null;
}
/**
 * Recursively searches for the most specific (innermost) document symbol that contains the given position.
 * @param symbols - The list of symbols to search through.
 * @param position - The cursor position.
 * @returns The most specific symbol containing the position, or undefined if none is found.
 */
function findEnclosingSymbol(symbols: vscode.DocumentSymbol[], position: vscode.Position): vscode.DocumentSymbol | undefined {
    for (const symbol of symbols) {
        if (symbol.range.contains(position)) {
            const childSymbol = findEnclosingSymbol(symbol.children, position);
            return childSymbol || symbol;
        }
    }
    return undefined;
}

/**
 * Finds the parent symbol and the immediate siblings (previous and next) of a given symbol.
 */
function findSymbolNeighbors(
    targetSymbol: vscode.DocumentSymbol,
    allSymbols: vscode.DocumentSymbol[]
): { parent: vscode.DocumentSymbol | null; previous: vscode.DocumentSymbol | null; next: vscode.DocumentSymbol | null } {
    
    const search = (
        symbols: vscode.DocumentSymbol[],
        parent: vscode.DocumentSymbol | null
    ): { parent: vscode.DocumentSymbol | null; previous: vscode.DocumentSymbol | null; next: vscode.DocumentSymbol | null; found: boolean } | null => {
        const index = symbols.findIndex(s => s === targetSymbol);

        if (index !== -1) {
            return {
                parent,
                previous: index > 0 ? symbols[index - 1] : null,
                next: index < symbols.length - 1 ? symbols[index + 1] : null,
                found: true,
            };
        }

        for (const symbol of symbols) {
            const result = search(symbol.children, symbol);
            if (result?.found) {
                return result;
            }
        }
        return null;
    };

    const result = search(allSymbols, null);
    return { parent: result?.parent || null, previous: result?.previous || null, next: result?.next || null };
}

/**
 * Gathers all necessary context for an AI code generation task.
 * It now clearly distinguishes between replacement (user has a selection) and
 * insertion (user has a cursor but no selection).
 * It always attempts to find an enclosing symbol for smart context, regardless of selection.
 * 
 * This function also validates that the active editor is a proper code file,
 * excluding special editors like terminal or debug console.
 */
export async function getGenerationContext(): Promise<GenerationContext | null> {
    const editor = vscode.window.activeTextEditor;
    if (!editor || !editor.document) {
        return null;
    }

    // Check if the editor is a special type that shouldn't trigger code generation
    const specialEditors = ['terminal', 'debug-console', 'output'];
    if (specialEditors.includes(editor.document.languageId)) {
        // Not returning an error here but simply returning null
        // The command handler will show an appropriate message
        return null;
    }

    const document = editor.document;
    const fullFileContent = document.getText();
    let selection: vscode.Selection;
    let selectedText: string;
    let range: vscode.Range;

    const symbols = await vscode.commands.executeCommand<vscode.DocumentSymbol[]>(
        'vscode.executeDocumentSymbolProvider',
        document.uri
    );

    // Always try to find an enclosing symbol for context, regardless of selection.
    const enclosingSymbol = (symbols && symbols.length > 0) 
        ? findEnclosingSymbol(symbols, editor.selection.active) 
        : undefined;

    if (editor.selection.isEmpty) {
        // If no selection, and we found a symbol, select the whole symbol.
        // Otherwise, it's an insertion at the cursor.
        if (enclosingSymbol) {
            range = enclosingSymbol.range;
            selection = new vscode.Selection(range.start, range.end);
            selectedText = document.getText(range);
        } else {
            selection = editor.selection; // A zero-length range at the cursor
            range = new vscode.Range(selection.start, selection.end);
            selectedText = '';
        }
    } else {
        // User has selected text. Treat as replacement.
        selection = editor.selection;
        range = new vscode.Range(selection.start, selection.end);
        selectedText = document.getText(range);
    }
    
    const importBlock = extractImportBlock(document);

    let smartContext: SmartContext | null = null;
    let finalFullFileContent: string | null = fullFileContent;

    if (fullFileContent.length > MAX_FILE_SIZE_FOR_FULL_CONTEXT) {
        finalFullFileContent = null; 
        if (enclosingSymbol && symbols) {
            // If we have a symbol, use its siblings for smart context.
            const { previous, next } = findSymbolNeighbors(enclosingSymbol, symbols);
            smartContext = {
                previousSiblingText: previous ? document.getText(previous.range) : null,
                nextSiblingText: next ? document.getText(next.range) : null,
            };
        } else {
            // Fallback for smart context: use adjacent lines if no symbol is available.
            const startLineNum = selection.start.line;
            const endLineNum = selection.end.line;

            const prevLineText = (startLineNum > 0 && startLineNum - 1 < document.lineCount) 
                ? document.lineAt(startLineNum - 1).text 
                : null;
            const nextLineText = (endLineNum + 1 < document.lineCount) 
                ? document.lineAt(endLineNum + 1).text 
                : null;
            
            smartContext = {
                previousSiblingText: prevLineText,
                nextSiblingText: nextLineText,
            };
        }
    }

    return {
        editor,
        selection,
        selectedText,
        filePath: document.uri.fsPath,
        fileExtension: path.extname(document.fileName),
        fullFileContent: finalFullFileContent,
        smartContext,
        importBlock,
    };
}

/**
 * Applies the generated code to the document.
 * @param editor - The text editor to modify.
 * @param range - The range to replace.
 * @param newText - The new text to insert.
 */
export async function applyChanges(editor: vscode.TextEditor, range: vscode.Range, newText: string): Promise<void> {
    // Validate editor and document before attempting edit
    if (!editor || !editor.document) {
        throw new Error('Invalid editor or document state');
    }

    // Ensure the document is still open and valid
    if (editor.document.isClosed) {
        throw new Error('Document has been closed');
    }

    // Validate range
    if (!range) {
        throw new Error('Invalid range provided');
    }

    const editSuccess = await editor.edit(editBuilder => {
        editBuilder.replace(range, newText);
    });

    if (!editSuccess) {
        throw new Error('Failed to apply changes to the document');
    }
}