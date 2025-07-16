import * as vscode from 'vscode';
import * as path from 'path';
import { GenerationContext, SmartContext } from '../types';

const MAX_FILE_SIZE_FOR_FULL_CONTEXT = 32 * 1024; // 32KB

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
 */
export async function getGenerationContext(): Promise<GenerationContext | null> {
    const editor = vscode.window.activeTextEditor;
    if (!editor || !editor.document) {
        return null;
    }

    const document = editor.document;
    const fullFileContent = document.getText();
    let selection: vscode.Selection;
    let selectedText: string;

    const symbols = await vscode.commands.executeCommand<vscode.DocumentSymbol[]>(
        'vscode.executeDocumentSymbolProvider',
        document.uri
    );

    // Always try to find an enclosing symbol for context, regardless of selection.
    const enclosingSymbol = (symbols && symbols.length > 0) 
        ? findEnclosingSymbol(symbols, editor.selection.active) 
        : undefined;

    if (editor.selection.isEmpty) {
        // No text selected by user. Treat as an insertion at the cursor.
        selection = editor.selection; // A zero-length range at the cursor
        selectedText = '';
    } else {
        // User has selected text. Treat as replacement.
        selection = editor.selection;
        selectedText = document.getText(selection);
    }
    
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

            // Check bounds before accessing lines
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
    if (!range || range.isEmpty) {
        throw new Error('Invalid range provided');
    }

    const editSuccess = await editor.edit(editBuilder => {
        editBuilder.replace(range, newText);
    });

    if (!editSuccess) {
        throw new Error('Failed to apply changes to the document');
    }
}