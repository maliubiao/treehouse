import './styles.css';
import { AiServiceConfig } from '../config/configuration';

// --- TYPE DEFINITIONS ---

/**
 * Defines the interface for the VSCode API object provided by `acquireVsCodeApi`.
 */
interface VSCodeAPI {
    postMessage(message: any): void;
    getState(): any;
    setState(newState: any): void;
}

// --- CONSTANTS ---
const RENDER_PROPS: (keyof Omit<AiServiceConfig, 'is_thinking'>)[] = [
    'name', 'model_name', 'base_url', 'key', 'temperature', 'max_tokens', 
    'max_context_size', 'timeout_seconds', 'price_1M_input', 'price_1M_output', 
    'supports_json_output'
];

// --- MAIN APPLICATION CLASS ---
// Ensure vscode is declared
declare const acquireVsCodeApi: () => VSCodeAPI;
/**
 * Manages the state and interactions of the webview UI.
 */
class ConfigApp {
    private readonly vscode: VSCodeAPI;
    private services: AiServiceConfig[] = [];
    private activeServiceName: string | undefined = undefined;
    private systemPrompt: string = '';
    private promptRule: string = '';

    // A central place to hold all queried DOM elements for easy access and performance.
    private elements: { [key: string]: HTMLElement } = {};

    constructor() {
        this.vscode = acquireVsCodeApi();
    }

    /**
     * Initializes the application, renders the layout, queries elements, and sets up listeners.
     */
    public init(): void {
        this.renderLayout();
        this.queryElements();
        this.bindEventListeners();
        window.addEventListener('message', (event) => this.handleMessage(event));
        this.vscode.postMessage({ command: 'getConfigs' });
    }

    /**
     * Handles incoming messages from the extension.
     */
    private handleMessage(event: MessageEvent): void {
        const message = event.data;
        switch (message.command) {
            case 'loadConfig':
                this.services = message.services;
                this.activeServiceName = message.activeServiceName;
                this.systemPrompt = message.systemPrompt;
                this.promptRule = message.promptRule;
                this.updateUI();
                break;
            case 'testResult':
                this.showTestResult(message.success, message.message);
                break;
            case 'playgroundResponse':
                this.showPlaygroundResponse(message.text, message.success);
                break;
        }
    }

    /**
     * Renders the main static layout of the application.
     */
    private renderLayout(): void {
        const root = document.getElementById('root');
        if (!root) return;
        root.innerHTML = `
            <div class="container">
                <h1>Treehouse AI Service Configurations</h1>

                <div class="section">
                    <h2>Services</h2>
                    <div id="service-list" class="service-list"></div>
                    <div class="button-group"><button id="new-service">Add New Service</button></div>
                </div>

                <div class="section">
                    <h2>Import/Export All Services</h2>
                    <textarea id="json-import-export" placeholder="Paste an array of service configs here..."></textarea>
                    <div class="button-group">
                        <button id="import-json">Import All</button>
                        <button id="export-json">Export All</button>
                    </div>
                </div>

                <div class="section">
                    <h2>Prompts & Rules</h2>
                    <div class="form-item">
                        <label for="system-prompt">System Prompt (Master Instruction)</label>
                        <textarea id="system-prompt" rows="5"></textarea>
                        <div class="button-group"><button id="save-system-prompt">Save System Prompt</button></div>
                    </div>
                    <div class="form-item" style="margin-top: 15px;">
                        <label for="prompt-rule">Custom Rule (Appended to every request)</label>
                        <textarea id="prompt-rule" rows="3"></textarea>
                        <div class="button-group"><button id="save-prompt-rule">Save Rule</button></div>
                    </div>
                </div>

                <div class="section">
                    <h2>Playground</h2>
                    <div class="form-item">
                        <label for="playground-service-select">Select Service</label>
                        <select id="playground-service-select"></select>
                    </div>
                    <div class="form-item">
                        <label for="playground-prompt">Prompt</label>
                        <textarea id="playground-prompt" rows="6" placeholder="Enter your prompt here..."></textarea>
                    </div>
                    <div class="button-group"><button id="playground-send">Send</button></div>
                    <div class="form-item">
                        <label>Response</label>
                        <div id="playground-response-area" class="response-area" aria-live="polite"></div>
                    </div>
                </div>
            </div>

            <div id="edit-modal" class="modal">
                <div class="modal-content">
                    <h2 id="modal-title">Edit Service</h2>
                    <div class="modal-form">
                        <input type="hidden" id="original-service-name">
                        <div class="form-item">
                            <label for="json-import-modal">Import from JSON</label>
                            <textarea id="json-import-modal" rows="4" placeholder="Paste a single service JSON config here..."></textarea>
                            <div class="button-group" style="justify-content: flex-start; margin-top: 5px;">
                                <button id="import-from-json-btn">Import and Fill Form</button>
                            </div>
                        </div>
                        <div class="form-row">
                            <div class="form-item"><label for="name">Service Name</label><input type="text" id="name"></div>
                            <div class="form-item"><label for="model_name">Model Name</label><input type="text" id="model_name"></div>
                        </div>
                        <div class="form-item"><label for="base_url">Base URL</label><input type="text" id="base_url"></div>
                        <div class="form-item"><label for="key">API Key</label><input type="password" id="key"></div>
                        <div class="form-row">
                            <div class="form-item"><label for="temperature">Temperature</label><input type="number" id="temperature" step="0.1" min="0" max="2"></div>
                            <div class="form-item"><label for="max_tokens">Max Tokens</label><input type="number" id="max_tokens" step="1"></div>
                        </div>
                        <div class="form-row">
                            <div class="form-item"><label for="max_context_size">Max Context Size</label><input type="number" id="max_context_size" step="1"></div>
                            <div class="form-item"><label for="timeout_seconds">Timeout (seconds)</label><input type="number" id="timeout_seconds" step="1" min="1"></div>
                        </div>
                        <div class="form-row">
                            <div class="form-item"><label for="price_1M_input">Price/1M Input ($)</label><input type="number" id="price_1M_input" step="0.01"></div>
                            <div class="form-item"><label for="price_1M_output">Price/1M Output ($)</label><input type="number" id="price_1M_output" step="0.01"></div>
                        </div>
                        <div class="form-row">
                            <div class="form-item" style="flex-direction: row; align-items: center; gap: 10px;">
                                <input type="checkbox" id="supports_json_output" style="width: auto;"><label for="supports_json_output">Supports JSON Output</label>
                            </div>
                        </div>
                        <div id="test-status-modal" style="height: 20px;"></div>
                        <div class="button-group">
                            <button id="test-connection-modal">Test Connection</button>
                            <button id="save-service-modal">Save</button>
                            <button id="cancel-modal" style="background-color: var(--vscode-button-secondaryBackground);">Cancel</button>
                        </div>
                    </div>
                </div>
            </div>`;
    }

    /**
     * Queries all necessary DOM elements and caches them in `this.elements`.
     */
    private queryElements(): void {
        const ids = [
            'service-list', 'json-import-export', 'system-prompt', 'prompt-rule',
            'playground-service-select', 'playground-prompt', 'playground-response-area',
            'edit-modal', 'modal-title', 'original-service-name', 'json-import-modal',
            'test-status-modal', 'name', 'model_name', 'base_url', 'key',
            'temperature', 'max_tokens', 'max_context_size', 'timeout_seconds',
            'price_1M_input', 'price_1M_output', 'supports_json_output'
        ];
        ids.forEach(id => {
            const el = document.getElementById(id);
            if (el) this.elements[id] = el;
        });
    }

    /**
     * Binds all event listeners to their respective handlers.
     */
    private bindEventListeners(): void {
        // Main page listeners
        document.getElementById('new-service')?.addEventListener('click', () => this.handleNewService());
        document.getElementById('import-json')?.addEventListener('click', () => this.handleImportAll());
        document.getElementById('export-json')?.addEventListener('click', () => this.handleExportAll());
        document.getElementById('save-system-prompt')?.addEventListener('click', () => this.handleSaveSystemPrompt());
        document.getElementById('save-prompt-rule')?.addEventListener('click', () => this.handleSaveRule());
        document.getElementById('playground-send')?.addEventListener('click', () => this.handlePlaygroundSend());

        // Modal listeners
        document.getElementById('cancel-modal')?.addEventListener('click', () => this.closeModal());
        document.getElementById('save-service-modal')?.addEventListener('click', () => this.handleSaveService());
        document.getElementById('test-connection-modal')?.addEventListener('click', () => this.handleTestConnection());
        document.getElementById('import-from-json-btn')?.addEventListener('click', () => this.handleImportSingleService());
    }

    /**
     * Updates the entire UI based on the current state.
     */
    private updateUI(): void {
        this.updateServiceList();
        this.updatePromptsAndRules();
        this.updatePlaygroundSelector();
    }

    private updateServiceList(): void {
        const list = this.elements['service-list'];
        if (!list) return;
        list.innerHTML = '';
        if (this.services.length === 0) {
            list.innerHTML = '<p>No services configured. Add a new service or import a configuration.</p>';
            return;
        }
        this.services.forEach(service => {
            const isActive = service.name === this.activeServiceName;
            const item = document.createElement('div');
            item.className = 'service-item' + (isActive ? ' active' : '');
            item.innerHTML = `
                <div class="service-name-status">
                    <span class="service-name">${service.name}</span>
                    ${isActive ? '<span class="active-badge">Active</span>' : ''}
                </div>
                <div class="button-group">
                    ${!isActive ? '<button class="select-btn">Select</button>' : ''}
                    <button class="edit-btn">Edit</button>
                    <button class="delete-btn">Delete</button>
                </div>`;
            
            if (!isActive) {
                item.querySelector('.select-btn')?.addEventListener('click', () => {
                    this.vscode.postMessage({ command: 'setActive', name: service.name });
                });
            }
            item.querySelector('.edit-btn')?.addEventListener('click', () => this.openModal(service));
            item.querySelector('.delete-btn')?.addEventListener('click', () => {
                this.vscode.postMessage({ command: 'deleteService', name: service.name });
            });
            list.appendChild(item);
        });
    }

    private updatePromptsAndRules(): void {
        (this.elements['system-prompt'] as HTMLTextAreaElement).value = this.systemPrompt;
        (this.elements['prompt-rule'] as HTMLTextAreaElement).value = this.promptRule;
    }

    private updatePlaygroundSelector(): void {
        const select = this.elements['playground-service-select'] as HTMLSelectElement;
        if (!select) return;
        select.innerHTML = '';
        if (this.services.length > 0) {
            this.services.forEach(service => {
                const option = document.createElement('option');
                option.value = service.name;
                option.textContent = service.name;
                option.selected = service.name === this.activeServiceName;
                select.appendChild(option);
            });
        } else {
            select.innerHTML = '<option disabled>No services available</option>';
        }
    }

    // --- Event Handlers ---
    private handleNewService(): void {
        const newServiceTemplate: Partial<AiServiceConfig> = {
            name: "New Service", model_name: "", base_url: "", key: "",
            temperature: 0.1, max_tokens: 8192, max_context_size: 131072,
            timeout_seconds: 60, price_1M_input: 0.0, price_1M_output: 0.0,
            supports_json_output: false
        };
        this.openModal(newServiceTemplate, true);
    }
    
    private handleImportAll(): void {
        const importText = (this.elements['json-import-export'] as HTMLTextAreaElement).value;
        try {
            const importedServices = JSON.parse(importText);
            this.vscode.postMessage({ command: 'importServices', services: importedServices });
            (this.elements['json-import-export'] as HTMLTextAreaElement).value = '';
        } catch (e) {
            this.vscode.postMessage({ command: 'showError', text: 'Invalid JSON format for services array.' });
        }
    }

    private handleExportAll(): void {
        (this.elements['json-import-export'] as HTMLTextAreaElement).value = JSON.stringify(this.services, null, 2);
    }

    private handleSaveSystemPrompt(): void {
        const text = (this.elements['system-prompt'] as HTMLTextAreaElement).value;
        this.vscode.postMessage({ command: 'saveSystemPrompt', text });
    }

    private handleSaveRule(): void {
        const text = (this.elements['prompt-rule'] as HTMLTextAreaElement).value;
        this.vscode.postMessage({ command: 'saveRule', text });
    }

    private handlePlaygroundSend(): void {
        const serviceSelect = this.elements['playground-service-select'] as HTMLSelectElement;
        const promptText = this.elements['playground-prompt'] as HTMLTextAreaElement;
        const responseArea = this.elements['playground-response-area'];
        
        if (serviceSelect.value && promptText.value && responseArea) {
            responseArea.className = 'response-area';
            responseArea.textContent = 'Thinking...';
            this.vscode.postMessage({
                command: 'playgroundRequest',
                serviceName: serviceSelect.value,
                prompt: promptText.value
            });
        }
    }
    
    private handleSaveService(): void {
        const service = this.getServiceFromModal();
        const originalName = (this.elements['original-service-name'] as HTMLInputElement).value;
        this.vscode.postMessage({ command: 'saveService', service, originalName });
        this.closeModal();
    }

    private handleTestConnection(): void {
        const service = this.getServiceFromModal();
        this.vscode.postMessage({ command: 'testConnection', service });
    }

    private handleImportSingleService(): void {
        const jsonInput = (this.elements['json-import-modal'] as HTMLTextAreaElement).value;
        try {
            const service = JSON.parse(jsonInput);
            this.populateModal(service);
            (this.elements['json-import-modal'] as HTMLTextAreaElement).value = '';
        } catch (e) {
            this.vscode.postMessage({ command: 'showError', text: 'Invalid JSON format for single service.' });
        }
    }

    // --- Modal Management ---
    private openModal(service: Partial<AiServiceConfig>, isNew: boolean = false): void {
        this.elements['modal-title'].textContent = isNew ? 'Add New Service' : 'Edit Service';
        (this.elements['original-service-name'] as HTMLInputElement).value = isNew ? '' : service.name || '';
        this.populateModal(service);
        (this.elements['json-import-modal'] as HTMLTextAreaElement).value = '';
        this.elements['test-status-modal'].innerHTML = '';
        this.elements['edit-modal'].style.display = 'block';
    }
    
    private closeModal(): void {
        this.elements['edit-modal'].style.display = 'none';
    }

    /**
     * Populates the modal form from a service object.
     */
    private populateModal(service: Partial<AiServiceConfig>): void {
        const defaults: Omit<AiServiceConfig, 'name' | 'model_name' | 'base_url' | 'key' | 'is_thinking'> = {
            temperature: 0.1, max_tokens: 8192, max_context_size: 0,
            timeout_seconds: 60, price_1M_input: 0, price_1M_output: 0,
            supports_json_output: false
        };

        RENDER_PROPS.forEach(key => {
            const element = this.elements[key] as HTMLInputElement;
            if (!element) return;

            const value = service[key] ?? (defaults as any)[key];

            if (element.type === 'checkbox') {
                element.checked = value as boolean;
            } else {
                element.value = value?.toString() ?? '';
            }
        });
    }

    /**
     * Reads all values from the modal form and returns a service object.
     */
    private getServiceFromModal(): Partial<AiServiceConfig> {
        const service: Partial<AiServiceConfig> = { is_thinking: true };
        RENDER_PROPS.forEach(key => {
            const element = this.elements[key] as HTMLInputElement;
            if (!element) return;
            
            if (element.type === 'checkbox') {
                (service as any)[key] = element.checked;
            } else if (element.type === 'number') {
                (service as any)[key] = parseFloat(element.value);
            } else {
                (service as any)[key] = element.value;
            }
        });
        return service;
    }
    
    // --- UI Feedback ---
    private showTestResult(success: boolean, message: string): void {
        const statusEl = this.elements['test-status-modal'];
        if (statusEl) {
            if (success) {
                statusEl.innerHTML = '<span class="success-text">✔️ Connection successful!</span>';
            } else {
                statusEl.innerHTML = `<span class="error-text">❌ ${message}</span>`;
            }
        }
    }

    private showPlaygroundResponse(text: string, success: boolean): void {
        const responseArea = this.elements['playground-response-area'];
        if (responseArea) {
            responseArea.textContent = text;
            responseArea.className = `response-area ${success ? '' : 'error-text'}`;
        }
    }
}

// --- Application Entry Point ---
document.addEventListener('DOMContentLoaded', () => {
    const app = new ConfigApp();
    app.init();
});