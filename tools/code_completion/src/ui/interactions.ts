import * as vscode from 'vscode';
import { t } from '../util/i18n';

/**
 * Shows a user input box to get additional instructions.
 * @returns The user's input, or undefined if they cancel.
 */
export async function getInstruction(): Promise<string | undefined> {
    return vscode.window.showInputBox({
        prompt: t('interactions.getInstruction.prompt'),
        placeHolder: t('interactions.getInstruction.placeholder'),
        ignoreFocusOut: true,
    });
}

/**
 * Shows an information message.
 * @param message - The message to display.
 */
export function showInfoMessage(message: string): void {
    vscode.window.showInformationMessage(t('interactions.showInfoMessage_prefix', { message }));
}

/**
 * Shows an error message with an optional "Retry" button.
 * @param message - The error message to display.
 * @param onRetry - A callback to execute if the user clicks "Retry".
 * @returns A promise that resolves with the user's choice.
 */
export async function showErrorMessage(message: string, onRetry?: () => void): Promise<string | undefined> {
    const options: string[] = [];
    const retryOption = t('common.retry');
    if (onRetry) {
        options.push(retryOption);
    }
    const selection = await vscode.window.showErrorMessage(t('interactions.showErrorMessage_prefix', { message }), ...options);
    if (selection === retryOption && onRetry) {
        onRetry();
    }
    return selection;
}