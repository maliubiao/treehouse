import * as vscode from 'vscode';
import { LastEdit } from '../types';
import { showInfoMessage } from '../ui/interactions';

/**
 * Manages the state for the last AI-generated edit, allowing it to be undone.
 */
export class UndoManager {
    private lastEdit: LastEdit | null = null;

    /**
     * Stores the details of an edit before it is applied.
     * @param uri - The document URI.
     * @param range - The range of the original text.
     * @param originalText - The text that is about to be replaced.
     */
    public remember(uri: vscode.Uri, range: vscode.Range, originalText: string): void {
        this.lastEdit = { uri, range, originalText };
    }

    /**
     * Reverts the last stored edit.
     */
    public async undo(): Promise<void> {
        if (!this.lastEdit) {
            showInfoMessage('No AI generation to undo.');
            return;
        }

        try {
            const editor = await vscode.window.showTextDocument(this.lastEdit.uri, {
                viewColumn: vscode.ViewColumn.Active
            });
            
            await editor.edit(editBuilder => {
                editBuilder.replace(this.lastEdit!.range, this.lastEdit!.originalText);
            });

            showInfoMessage('Last AI generation has been reverted.');
            this.lastEdit = null; // Clear the last edit after undoing
        } catch (error) {
            vscode.window.showErrorMessage(`Failed to undo last edit: ${error instanceof Error ? error.message : String(error)}`);
        }
    }
}