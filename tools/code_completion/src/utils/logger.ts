import * as vscode from 'vscode';

class Logger {
    private static _instance: Logger;
    private readonly _outputChannel: vscode.OutputChannel;

    private constructor() {
        this._outputChannel = vscode.window.createOutputChannel('Treehouse Code Completer');
    }

    public static get instance(): Logger {
        if (!Logger._instance) {
            Logger._instance = new Logger();
        }
        return Logger._instance;
    }

    public log(message: string, data?: object) {
        const logMessage = `[INFO] ${new Date().toISOString()} - ${message}`;
        this._outputChannel.appendLine(logMessage);
        if (data) {
            this._outputChannel.appendLine(JSON.stringify(data, null, 2));
        }
    }

    public warn(message: string, data?: object) {
        const logMessage = `[WARN] ${new Date().toISOString()} - ${message}`;
        this._outputChannel.appendLine(logMessage);
        if (data) {
            this._outputChannel.appendLine(JSON.stringify(data, null, 2));
        }
    }

    public error(message: string, error?: any) {
        const logMessage = `[ERROR] ${new Date().toISOString()} - ${message}`;
        this._outputChannel.appendLine(logMessage);
        if (error) {
            this._outputChannel.appendLine(JSON.stringify(error, Object.getOwnPropertyNames(error), 2));
        }
    }

    public show() {
        this._outputChannel.show();
    }
}

export const logger = Logger.instance;
