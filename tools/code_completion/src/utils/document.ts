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
 * It determines whether to use the full file content or a "smart" context
 * (surrounding symbols) based on the file size.
 */
export async function getGenerationContext(): Promise<GenerationContext | null> {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        return null;
    }

    const document = editor.document;
    const fullFileContent = document.getText();
    let selection: vscode.Selection;
    let selectedText: string;
    let enclosingSymbol: vscode.DocumentSymbol | undefined;

    const symbols = await vscode.commands.executeCommand<vscode.DocumentSymbol[]>(
        'vscode.executeDocumentSymbolProvider',
        document.uri
    );

    if (editor.selection.isEmpty) {
        if (!symbols || symbols.length === 0) { return null; }
        enclosingSymbol = findEnclosingSymbol(symbols, editor.selection.active);
        if (!enclosingSymbol) { return null; }
        selection = enclosingSymbol.range;
    } else {
        selection = editor.selection;
        if (symbols && symbols.length > 0) {
            enclosingSymbol = findEnclosingSymbol(symbols, selection.start);
        }
    }
    selectedText = document.getText(selection);

    let smartContext: SmartContext | null = null;
    let finalFullFileContent: string | null = fullFileContent;

    if (fullFileContent.length > MAX_FILE_SIZE_FOR_FULL_CONTEXT) {
        finalFullFileContent = null; 
        if (enclosingSymbol && symbols) {
            const { previous, next } = findSymbolNeighbors(enclosingSymbol, symbols);
            smartContext = {
                previousSiblingText: previous ? document.getText(previous.range) : null,
                nextSiblingText: next ? document.getText(next.range) : null,
            };
        } else {
            smartContext = { previousSiblingText: null, nextSiblingText: null };
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
    await editor.edit(editBuilder => {
        editBuilder.replace(range, newText);
    });
}