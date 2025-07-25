import * as vscode from 'vscode';

/**
 * Shows a user input box to get additional instructions.
 * @returns The user's input, or undefined if they cancel.
 */
export async function getInstruction(): Promise<string | undefined> {
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
    vscode.window.showInformationMessage(`Treehouse Completer: ${message}`);
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
    const selection = await vscode.window.showErrorMessage(`Treehouse Completer Error: ${message}`, ...options);
    if (selection === 'Retry' && onRetry) {
        onRetry();
    }
    return selection;
}