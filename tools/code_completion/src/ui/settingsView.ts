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

export function showSettingsView(context: vscode.ExtensionContext): void {
    const panel = vscode.window.createWebviewPanel(
        'treehouseCodeCompleterSettings',
        'Treehouse AI Service Configurations',
        vscode.ViewColumn.One,
        {
            enableScripts: true,
            // Allow the webview to load resources from the 'dist' directory
            localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, 'dist')]
        }
    );

    panelManager.register(panel);

    // Load the pre-built, self-contained HTML file
    const htmlPath = path.join(context.extensionPath, 'dist', 'webview.html');
    const htmlContent = fs.readFileSync(htmlPath, 'utf8');
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
                    showInfoMessage(`Service '${message.service.name}' saved.`);
                    return;
                }
                case 'deleteService': {
                    let currentServices = getAiServiceConfigs();
                    currentServices = currentServices.filter(s => s.name !== message.name);
                    await saveAiServiceConfigs(currentServices);
                    sendConfigsToWebview();
                    showInfoMessage(`Service '${message.name}' deleted.`);
                    return;
                }
                case 'setActive':
                    await setActiveAiService(message.name);
                    sendConfigsToWebview();
                    showInfoMessage(`Service '${message.name}' is now active.`);
                    return;
                case 'importServices':
                    await saveAiServiceConfigs(message.services);
                    sendConfigsToWebview();
                    showInfoMessage(`Imported ${message.services.length} services.`);
                    return;
                case 'testConnection': {
                    const testResult = await testApiConnection(message.service as AiServiceConfig);
                    panel.webview.postMessage({ command: 'testResult', ...testResult });
                    return;
                }
                case 'saveSystemPrompt':
                    await config.update('prompt.systemMessage', message.text, vscode.ConfigurationTarget.Global);
                    showInfoMessage('System prompt saved.');
                    return;
                case 'saveRule':
                    await config.update('prompt.rule', message.text, vscode.ConfigurationTarget.Global);
                    showInfoMessage('Prompt rule saved.');
                    return;
                case 'playgroundRequest': {
                    const allServices = getAiServiceConfigs();
                    const serviceConfig = allServices.find(s => s.name === message.serviceName);

                    if (!serviceConfig) {
                        panel.webview.postMessage({ command: 'playgroundResponse', success: false, text: `Error: Service '${message.serviceName}' not found.` });
                        return;
                    }

                    try {
                        const response = await playgroundChat(message.prompt, serviceConfig);
                        panel.webview.postMessage({ command: 'playgroundResponse', success: true, text: response });
                    } catch (error) {
                        const errorMessage = error instanceof Error ? error.message : String(error);
                        panel.webview.postMessage({ command: 'playgroundResponse', success: false, text: `Error: ${errorMessage}` });
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