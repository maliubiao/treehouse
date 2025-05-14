import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';

export function activate(context: vscode.ExtensionContext) {
    console.log('Code Tracer Viewer 已激活');
    
    const provider = new TraceContentProvider();
    context.subscriptions.push(vscode.workspace.registerTextDocumentContentProvider('trace', provider));
    
    context.subscriptions.push(vscode.commands.registerTextEditorCommand('trace.openReference', (textEditor, edit) => {
        const document = textEditor.document;
        const selection = textEditor.selection;
        
        if (document.languageId !== 'trace') {
            vscode.window.showWarningMessage('只能在.trace文件中使用此功能');
            return;
        }
        
        const line = document.lineAt(selection.active.line).text;
        const reference = parseReference(line);
        
        if (reference) {
            openReference(reference).catch(err => {
                vscode.window.showErrorMessage(`打开文件失败: ${err.message}`);
            });
        }
    }));
    
    context.subscriptions.push(vscode.languages.registerHoverProvider('trace', {
        provideHover(document, position, token) {
            const line = document.lineAt(position.line).text;
            const reference = parseReference(line);
            
            if (reference) {
                const fileExists = fs.existsSync(reference.file);
                const status = fileExists ? '存在' : '不存在';
                return new vscode.Hover([
                    `**文件路径**: ${path.basename(reference.file)}`,
                    `**行号**: ${reference.line || '未知'}`,
                    `**文件状态**: ${status}`,
                    '点击跳转到对应位置'
                ].join('\n\n'));
            }
            
            return undefined;
        }
    }));
    
    context.subscriptions.push(vscode.languages.registerDocumentLinkProvider('trace', {
        provideDocumentLinks(document, token) {
            const links: vscode.DocumentLink[] = [];
            
            for (let i = 0; i < document.lineCount; i++) {
                const line = document.lineAt(i).text;
                const reference = parseReference(line);
                
                if (reference) {
                    const startIndex = line.indexOf(reference.file);
                    const endIndex = startIndex + reference.file.length;
                    const lineNumberPart = reference.line ? `:${reference.line}` : '';
                    
                    const link = new vscode.DocumentLink(
                        new vscode.Range(
                            new vscode.Position(i, startIndex),
                            new vscode.Position(i, endIndex + lineNumberPart.length)
                        ),
                        vscode.Uri.file(reference.file).with({ fragment: `L${reference.line}` })
                    );
                    
                    links.push(link);
                }
            }
            
            return links;
        }
    }));
}

function parseReference(line: string): { file: string; line?: number } | null {
    const regex = / at ((?:[a-zA-Z]:)?(?:\\ |[^:])+?)(?::(\d+))?(?=\s|$)/;
    const match = regex.exec(line);
    
    if (!match) {
        return null;
    }
    
    const rawPath = match[1].replace(/\\ /g, ' ');
    const file = path.normalize(rawPath);
    const lineNum = match[2] ? parseInt(match[2], 10) : undefined;
    
    return { 
        file,
        line: lineNum && lineNum > 0 ? lineNum : undefined 
    };
}

async function openReference(reference: { file: string; line?: number }): Promise<void> {
    const uri = vscode.Uri.file(reference.file);
    
    try {
        await vscode.workspace.fs.stat(uri);
    } catch (error) {
        throw new Error(`文件不存在: ${reference.file}`);
    }

    const doc = await vscode.workspace.openTextDocument(uri);
    
    // 查找已存在的编辑器
    const existingEditor = vscode.window.visibleTextEditors.find(e => 
        e.document.uri.fsPath === uri.fsPath
    );
    
    const viewColumn = existingEditor ? 
        existingEditor.viewColumn : 
        vscode.ViewColumn.Beside;
    
    const editor = await vscode.window.showTextDocument(doc, {
        viewColumn,
        preserveFocus: true,
        preview: false
    });
    
    if (reference.line !== undefined && reference.line > 0) {
        const line = Math.min(reference.line - 1, doc.lineCount - 1);
        const position = new vscode.Position(line, 0);
        const selection = new vscode.Selection(position, position);
        
        editor.revealRange(selection, vscode.TextEditorRevealType.InCenter);
        editor.selection = selection;
    }
}

class TraceContentProvider implements vscode.TextDocumentContentProvider {
    provideTextDocumentContent(uri: vscode.Uri): string {
        return 'Trace content preview not implemented';
    }
}

export function deactivate() {
    console.log('Code Tracer Viewer 已停用');
}