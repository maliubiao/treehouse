import * as vscode from 'vscode';

/**
 * Shows a user input box to get additional instructions.
 * @returns The user's input, or undefined if they cancel.
 */
export function getInstruction(): Promise<string | undefined> {
    return vscode.window.showInputBox({
        prompt: 'Enter your instruction for the AI',
        placeHolder: 'e.g., "Refactor this to be more efficient" or "Add JSDoc comments"',
        ignoreFocusOut: true,
    });
}

/**
 * Shows an information message.
 * @param message - The message to display.
 */
export function showInfoMessage(message: string): void {
    vscode.window.showInformationMessage(`AI Completer: ${message}`);
}

/**
 * Shows an error message with an optional "Retry" button.
 * @param message - The error message to display.
 * @param onRetry - A callback to execute if the user clicks "Retry".
 * @returns A promise that resolves with the user's choice.
 */
export async function showErrorMessage(message: string, onRetry?: () => void): Promise<string | undefined> {
    const options: string[] = [];
    if (onRetry) {
        options.push('Retry');
    }
    const selection = await vscode.window.showErrorMessage(`AI Completer Error: ${message}`, ...options);
    if (selection === 'Retry' && onRetry) {
        onRetry();
    }
    return selection;
}

/**
 * Opens a diff view between two files.
 * @param originalUri - The URI of the original file.
 * @param newUri - The URI of the new (generated) file.
 * @param title - The title for the diff view tab.
 * @returns A promise that resolves when the diff view is shown.
 */
export async function showDiffView(originalUri: vscode.Uri, newUri: vscode.Uri, title: string): Promise<void> {
    await vscode.commands.executeCommand('vscode.diff', originalUri, newUri, title);
}

/**
 * Shows a confirmation prompt to the user.
 * This is now NON-MODAL to allow interaction with the diff view.
 * @param prompt - The main text to show in the confirmation.
 * @param acceptText - The label for the "Accept" button.
 * @param rejectText - The label for the "Reject" button.
 * @returns The user's choice, or undefined if they close the prompt.
 */
export async function getConfirmation(
    prompt: string = 'AI suggestion generated. Review the changes in the diff view.',
    acceptText: string = 'Accept',
    rejectText: string = 'Reject'
): Promise<string | undefined> {
    const choice = await vscode.window.showInformationMessage(
        prompt,
        // By removing { modal: true }, this becomes a non-modal notification.
        acceptText,
        rejectText
    );
    return choice;
}