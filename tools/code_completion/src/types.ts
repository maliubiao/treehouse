import * as vscode from 'vscode';

export interface LastEdit {
    uri: vscode.Uri;
    originalText: string;
    range: vscode.Range;
}

export interface SmartContext {
    previousSiblingText: string | null;
    nextSiblingText: string | null;
}

export interface ImportBlock {
    text: string;
    range: vscode.Range;
}

export interface GenerationContext {
    editor: vscode.TextEditor;
    selection: vscode.Selection;
    selectedText: string;
    filePath: string;
    fileExtension: string;
    fullFileContent: string | null; // Null if smart context is used
    smartContext: SmartContext | null; // Null if full file content is used
    importBlock: ImportBlock | null;
}


export interface LastEdit {
    uri: vscode.Uri;
    originalText: string;
    range: vscode.Range;
}

export interface SmartContext {
    previousSiblingText: string | null;
    nextSiblingText: string | null;
}

