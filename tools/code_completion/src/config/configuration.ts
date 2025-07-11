import * as vscode from 'vscode';

const CONFIG_SECTION = 'aiCodeCompleter';

export interface AiServiceConfig {
    name: string;
    max_context_size: number;
    max_tokens: number;
    is_thinking: boolean;
    temperature: number;
    key: string;
    base_url: string;
    model_name: string;
    price_1M_input: number;
    price_1M_output: number;
    supports_json_output: boolean;
    timeout_seconds: number;
}

/**
 * Retrieves all AI service configurations from VS Code settings.
 */
export function getAiServiceConfigs(): AiServiceConfig[] {
    const config = vscode.workspace.getConfiguration(CONFIG_SECTION);
    return config.get<AiServiceConfig[]>('services', []);
}

/**
 * Saves the entire list of AI service configurations.
 */
export async function saveAiServiceConfigs(services: AiServiceConfig[]): Promise<void> {
    const config = vscode.workspace.getConfiguration(CONFIG_SECTION);
    await config.update('services', services, vscode.ConfigurationTarget.Global);
}

/**
 * Retrieves the currently active AI service configuration.
 */
export function getActiveAiServiceConfig(): AiServiceConfig | undefined {
    const services = getAiServiceConfigs();
    const activeServiceName = vscode.workspace.getConfiguration(CONFIG_SECTION).get<string>('activeService');
    return services.find(s => s.name === activeServiceName);
}

/**
 * Sets the active AI service configuration.
 */
export async function setActiveAiService(serviceName: string): Promise<void> {
    const config = vscode.workspace.getConfiguration(CONFIG_SECTION);
    await config.update('activeService', serviceName, vscode.ConfigurationTarget.Global);
}