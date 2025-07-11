import * as vscode from 'vscode';

export const panelManager = {
    currentPanel: undefined as vscode.WebviewPanel | undefined,

    register(panel: vscode.WebviewPanel) {
        this.currentPanel = panel;
        panel.onDidDispose(() => {
            this.currentPanel = undefined;
        }, null);
    },

    getPanel() {
        return this.currentPanel;
    }
};
