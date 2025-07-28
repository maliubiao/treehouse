import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import { 
    getAiServiceConfigs, 
    saveAiServiceConfigs, 
    getActiveAiServiceConfig, 
    setActiveAiService,
    AiServiceConfig
} from '../config/configuration';
import { showInfoMessage, showErrorMessage } from './interactions';
import { panelManager } from './panelManager';
import { testApiConnection, playgroundChat } from '../api/llmClient';
import { t, getI18nConfigForWebview } from '../util/i18n';

export function showSettingsView(context: vscode.ExtensionContext): void {
    const panel = vscode.window.createWebviewPanel(
        'treehouseCodeCompleterSettings',
        t('webview.mainTitle'),
        vscode.ViewColumn.One,
        {
            enableScripts: true,
            localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, 'dist')]
        }
    );

    panelManager.register(panel);

    const htmlPath = path.join(context.extensionPath, 'dist', 'webview.html');
    let htmlContent = fs.readFileSync(htmlPath, 'utf8');

    // Convert the path for the i18next library to a webview-safe URI
    const i18nextScriptPath = vscode.Uri.joinPath(context.extensionUri, 'dist', 'lib', 'i18next', 'i18next.min.js');
    const i18nextScriptUri = panel.webview.asWebviewUri(i18nextScriptPath);

    // Replace the hardcoded relative path with the secure URI to comply with VS Code's CSP
    htmlContent = htmlContent.replace(
        'src="lib/i18next/i18next.min.js"',
        `src="${i18nextScriptUri}"`
    );

    // Inject i18n configuration for Webview
    const i18nConfig = getI18nConfigForWebview();
    htmlContent = htmlContent.replace(
        '<!-- I18N_DATA -->',
        `<script id="i18n-config" type="application/json">${JSON.stringify(i18nConfig)}</script>`
    );

    panel.webview.html = htmlContent;

    const sendConfigsToWebview = (): void => {
        const config = vscode.workspace.getConfiguration('treehouseCodeCompleter');
        panel.webview.postMessage({
            command: 'loadConfig',
            services: getAiServiceConfigs(),
            activeServiceName: getActiveAiServiceConfig()?.name,
            systemPrompt: config.get<string>('prompt.systemMessage'),
            promptRule: config.get<string>('prompt.rule')
        });
    };

    panel.webview.onDidReceiveMessage(
        async (message: any) => {
            const config = vscode.workspace.getConfiguration('treehouseCodeCompleter');
            switch (message.command) {
                case 'getConfigs':
                    sendConfigsToWebview();
                    return;
                case 'saveService': {
                    const services = getAiServiceConfigs();
                    const index = services.findIndex(s => s.name === message.originalName);
                    if (index > -1) {
                        services[index] = message.service;
                    } else {
                        services.push(message.service);
                    }
                    await saveAiServiceConfigs(services);
                    sendConfigsToWebview();
                    showInfoMessage(t("Service '{{name}}' saved.", { name: message.service.name }));
                    return;
                }
                case 'deleteService': {
                    let currentServices = getAiServiceConfigs();
                    currentServices = currentServices.filter(s => s.name !== message.name);
                    await saveAiServiceConfigs(currentServices);
                    sendConfigsToWebview();
                    showInfoMessage(t("Service '{{name}}' deleted.", { name: message.name }));
                    return;
                }
                case 'setActive':
                    await setActiveAiService(message.name);
                    sendConfigsToWebview();
                    showInfoMessage(t("Service '{{name}}' is now active.", { name: message.name }));
                    return;
                case 'importServices':
                    await saveAiServiceConfigs(message.services);
                    sendConfigsToWebview();
                    showInfoMessage(t("Imported {{count}} services.", { count: message.services.length }));
                    return;
                case 'testConnection': {
                    const testResult = await testApiConnection(message.service as AiServiceConfig);
                    panel.webview.postMessage({ command: 'testResult', ...testResult });
                    return;
                }
                case 'saveSystemPrompt':
                    await config.update('prompt.systemMessage', message.text, vscode.ConfigurationTarget.Global);
                    showInfoMessage(t('System prompt saved.'));
                    return;
                case 'saveRule':
                    await config.update('prompt.rule', message.text, vscode.ConfigurationTarget.Global);
                    showInfoMessage(t('Prompt rule saved.'));
                    return;
                case 'playgroundRequest': {
                    const allServices = getAiServiceConfigs();
                    const serviceConfig = allServices.find(s => s.name === message.serviceName);

                    if (!serviceConfig) {
                        panel.webview.postMessage({ command: 'playgroundResponse', success: false, text: t("webview.serviceNotFound", { serviceName: message.serviceName }) });
                        return;
                    }

                    try {
                        const { response, usage } = await playgroundChat(message.prompt, serviceConfig);
                        
                        const isErrorResponse = /^(API Error|Failed to communicate|The request timed out|An unknown error occurred)/i.test(response);
                
                        let responseText = response;
                        if (!isErrorResponse && usage.totalTokens > 0) {
                            const cost = usage.cost ? ` (Cost: $${usage.cost.toFixed(4)})` : '';
                            const tokenInfo = `\n\n---\nModel: ${usage.model}\nTokens: ${usage.totalTokens} (Prompt: ${usage.promptTokens}, Completion: ${usage.completionTokens})${cost}`;
                            responseText += tokenInfo;
                        }
                
                        panel.webview.postMessage({ 
                            command: 'playgroundResponse', 
                            success: !isErrorResponse, 
                            text: responseText
                        });
                    } catch (error) {
                        const errorMessage = error instanceof Error ? error.message : String(error);
                        panel.webview.postMessage({ command: 'playgroundResponse', success: false, text: t("webview.playgroundError", { message: errorMessage }) });
                    }
                    return;
                }
                case 'showError':
                    showErrorMessage(message.text);
                    return;
            }
        },
        undefined,
        context.subscriptions
    );
}