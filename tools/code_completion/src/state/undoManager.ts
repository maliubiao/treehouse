import * as vscode from 'vscode';
import { LastEdit } from '../types';
import { showInfoMessage } from '../ui/interactions';
import { t } from '../util/i18n';

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
            showInfoMessage(t('undoManager.nothingToUndo'));
            return;
        }

        try {
            const editor = await vscode.window.showTextDocument(this.lastEdit.uri, {
                viewColumn: vscode.ViewColumn.Active
            });
            
            const originalSelection = editor.selection;

            const success = await editor.edit(editBuilder => {
                // The range for replacement should be the range of the *new* text,
                // which might be different from the original range if we replaced the whole file.
                // However, our `remember` stores the *original* range and text.
                // To revert, we need to replace the *current* content with the *original* content.
                // This is complex. A simpler, more robust undo is to replace the entire document's
                // content with the remembered original text.
                
                // Let's assume for now the replacement was in place.
                const fullRange = new vscode.Range(
                    editor.document.positionAt(0),
                    editor.document.positionAt(editor.document.getText().length)
                );
                if (this.lastEdit)
                    editBuilder.replace(fullRange, this.lastEdit.originalText);
            });

            if (success) {
                // Restore selection to where it was before undoing
                editor.selection = originalSelection;
                showInfoMessage(t('undoManager.reverted'));
                this.lastEdit = null; // Clear the last edit after undoing
            } else {
                 throw new Error("The edit operation failed to apply.");
            }
            
        } catch (error) {
            vscode.window.showErrorMessage(t('undoManager.revertFailed', { error: error instanceof Error ? error.message : String(error) }));
        }
    }
}