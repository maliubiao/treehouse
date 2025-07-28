import './styles.css';
import { AiServiceConfig } from '../config/configuration';
declare const i18next: any;
// --- TYPE DEFINITIONS ---

/**
 * Defines the interface for the VSCode API object provided by `acquireVsCodeApi`.
 */
interface VSCodeAPI {
    postMessage(message: any): void;
    getState(): any;
    setState(newState: any): any;
}

// --- CONSTANTS ---
const RENDER_PROPS: (keyof Omit<AiServiceConfig, 'is_thinking'>)[] = [
    'name', 'model_name', 'base_url', 'key', 'temperature', 'max_tokens', 
    'max_context_size', 'timeout_seconds', 'price_1M_input', 'price_1M_output', 
    'supports_json_output'
];

const I18N_INIT_TIMEOUT = 2000; // 2 seconds timeout for i18n initialization

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
    private i18nInitialized: boolean = false;
    private i18nInitTimeout: ReturnType<typeof setTimeout> | null = null;

    // A central place to hold all queried DOM elements for easy access and performance.
    private elements: { [key: string]: HTMLElement } = {};

    constructor() {
        this.vscode = acquireVsCodeApi();
    }

    /**
     * Initializes the application, renders the layout, queries elements, and sets up listeners.
     */
    public init(): void {
        this.initI18n().then(() => {
            this.renderLayout();
            this.queryElements();
            this.bindEventListeners();
            window.addEventListener('message', (event) => this.handleMessage(event));
            this.vscode.postMessage({ command: 'getConfigs' });
        }).catch(error => {
            console.error('Failed to initialize i18n, falling back to English', error);
            this.fallbackToEnglish();
            this.renderLayout();
            this.queryElements();
            this.bindEventListeners();
            window.addEventListener('message', (event) => this.handleMessage(event));
            this.vscode.postMessage({ command: 'getConfigs' });
        });
    }

    /**
     * Initializes i18next with the configuration provided by the extension.
     */
    private async initI18n(): Promise<void> {
        return new Promise((resolve, reject) => {
            // Set up timeout to prevent hanging if config is never received
            this.i18nInitTimeout = setTimeout(() => {
                if (this.i18nInitTimeout) {
                    clearTimeout(this.i18nInitTimeout);
                    this.i18nInitTimeout = null;
                    reject(new Error('i18n configuration timeout'));
                }
            }, I18N_INIT_TIMEOUT);

            const i18nConfigElement = document.getElementById('i18n-config');
            if (!i18nConfigElement) {
                reject(new Error("i18n-config element not found"));
                return;
            }

            try {
                const config = JSON.parse(i18nConfigElement.textContent || '{}');
                
                if (this.i18nInitTimeout) {
                    clearTimeout(this.i18nInitTimeout);
                    this.i18nInitTimeout = null;
                }
                
                i18next.init({
                    lng: config.language,
                    fallbackLng: 'en',
                    resources: config.resources,
                    ns: config.namespaces,
                    defaultNS: 'common',
                    interpolation: {
                        escapeValue: false
                    }
                }, (err: any) => {
                    if (err) {
                        reject(err);
                        return;
                    }
                    this.i18nInitialized = true;
                    console.log('i18next initialized in Webview');
                    resolve();
                });
            } catch (e) {
                if (this.i18nInitTimeout) {
                    clearTimeout(this.i18nInitTimeout);
                    this.i18nInitTimeout = null;
                }
                reject(new Error(`Failed to parse i18n configuration: ${e instanceof Error ? e.message : String(e)}`));
            }
        });
    }

    /**
     * Fallback to English when i18n initialization fails
     */
    private fallbackToEnglish(): void {
        console.warn('Falling back to English due to i18n initialization failure');
        
        i18next.init({
            lng: 'en',
            fallbackLng: 'en',
            resources: {
                en: {
                    common: {
                        "common": {
                            "retry": "Retry",
                            "saveButton": "Save",
                            "cancelButton": "Cancel",
                            "editButton": "Edit",
                            "deleteButton": "Delete",
                            "selectButton": "Select"
                          },
                          "extension": {
                            "activated": "Treehouse Code Completer is now active.",
                            "noActiveWebview": "No active webview to open developer tools for."
                          },
                          "interactions": {
                            "getInstruction": {
                              "prompt": "Enter your instruction for the AI",
                              "placeholder": "e.g., \"Refactor this to be more efficient\" or \"Add JSDoc comments\""
                            },
                            "showInfoMessage_prefix": "Treehouse Completer: {{message}}",
                            "showErrorMessage_prefix": "Treehouse Completer Error: {{message}}"
                          },
                          "undoManager": {
                            "nothingToUndo": "No AI generation to undo.",
                            "reverted": "Last AI generation has been reverted.",
                            "revertFailed": "Failed to undo last edit: {{error}}"
                          },
                          "sessionManager": {
                            "suggestionReady": "AI suggestion is ready. Accept with {{acceptKey}}, Reject with {{rejectKey}}.",
                            "changesApplied": "Changes have been applied.",
                            "applyFailed": "Failed to apply changes.",
                            "applyFailedError": "Failed to apply changes: {{error}}",
                            "changesRejected": "Changes have been rejected."
                          },
                          "generateCode": {
                            "noActiveService": "No active AI service is configured. Please set one up in the settings.",
                            "openSettings": "Open Settings",
                            "notAvailableInSpecialEditor": "This command is not available in this type of editor (e.g., Terminal, Debug Console).",
                            "noFileSelected": "No active code file selected. Please open a file to use this command.",
                            "timeout": "The code generation request timed out after 120 seconds.",
                            "cancelled": "Operation cancelled by user.",
                            "progress": {
                              "working": "Treehouse AI is working...",
                              "initializing": "Initializing...",
                              "finalizing": "Finalizing..."
                            },
                            "success": "AI generation successful. Tokens used: {{totalTokens}}{{costDisplay}}.",
                            "error": "An error occurred during code generation: {{errorMessage}}",
                            "showDetails": "Show Details",
                            "emptyResponse": "AI response was empty."
                          },
                          "llmClient": {
                            "apiKeyRequired": "API key for the active service is required.",
                            "defaultSystemPrompt": "You are a helpful AI assistant.",
                            "requestTimeout": "The request timed out after {{seconds}} seconds.\nStack: {{stack}}",
                            "apiError": "API Error ({{status}}): {{message}}\nStack: {{stack}}",
                            "communicationError": "Failed to communicate with the API: {{message}}\nStack: {{stack}}",
                            "testConnection": {
                              "prompt": "test",
                              "success": "Connection successful.",
                              "unexpectedResponse": "Received an unexpected response from the API: {{response}}",
                              "timeout": "Connection test timed out after {{seconds}} seconds.\nStack: {{stack}}",
                              "apiError": "API Error ({{status}}): {{name}} - {{message}}\nStack: {{stack}}",
                              "unknownError": "An unknown error occurred during connection test: {{message}}\nStack: {{stack}}"
                            },
                            "playground": {
                              "timeout": "Playground request timed out after {{seconds}} seconds.\nStack: {{stack}}",
                              "apiError": "Playground API Error ({{status}}): {{name}} - {{message}}\nStack: {{stack}}",
                              "communicationError": "Failed to communicate with the API for playground: {{message}}\nStack: {{stack}}"
                            }
                          },
                          "webview": {
                            "mainTitle": "Treehouse AI Settings",
                            "servicesTitle": "AI Services",
                            "addNewService": "Add New Service",
                            "importExportTitle": "Import / Export",
                            "importExportPlaceholder": "Paste JSON array of services to import, or export all services here.",
                            "importAll": "Import All",
                            "exportAll": "Export All",
                            "promptsTitle": "Prompts",
                            "systemPromptLabel": "System Prompt",
                            "saveSystemPrompt": "Save System Prompt",
                            "customRuleLabel": "Custom Rule",
                            "saveCustomRule": "Save Custom Rule",
                            "playgroundTitle": "Playground",
                            "playgroundServiceLabel": "Service to use:",
                            "playgroundPromptLabel": "Prompt:",
                            "playgroundPromptPlaceholder": "Enter your prompt to test a service...",
                            "playgroundSend": "Send",
                            "playgroundResponseLabel": "Response:",
                            "noServicesConfigured": "No AI services configured.",
                            "activeBadge": "ACTIVE",
                            "noServicesAvailable": "No services available",
                            "thinking": "Thinking...",
                            "invalidJsonServices": "Invalid JSON format for services array.",
                            "invalidJsonService": "Invalid JSON format for service object.",
                            "serviceNotFound": "Service '{{serviceName}}' not found.",
                            "playgroundError": "Playground request failed: {{message}}",
                            "editModalTitle": "Edit AI Service",
                            "addModalTitle": "Add New AI Service",
                            "modalImportLabel": "Import Service from JSON",
                            "modalImportPlaceholder": "Paste a single service configuration object here...",
                            "modalImportButton": "Import from JSON",
                            "serviceNameLabel": "Service Name",
                            "modelNameLabel": "Model Name",
                            "baseUrlLabel": "Base URL",
                            "apiKeyLabel": "API Key",
                            "temperatureLabel": "Temperature",
                            "maxTokensLabel": "Max Tokens",
                            "maxContextSizeLabel": "Max Context Size",
                            "timeoutLabel": "Timeout (sec)",
                            "priceInputLabel": "Price/1M Input ($)",
                            "priceOutputLabel": "Price/1M Output ($)",
                            "supportsJsonLabel": "Supports JSON output",
                            "testConnectionButton": "Test Connection",
                            "connectionSuccessful": "Connection successful!",
                            "connectionFailed": "Connection failed: {{message}}"
                          }
                    }
                }
            },
            ns: ['common'],
            defaultNS: 'common',
            interpolation: {
                escapeValue: false
            }
        });
        
        this.i18nInitialized = true;
    }

    /**
     * A translation function that uses i18next.
     * @param key The i18n key (e.g., 'webview.mainTitle' or 'common.retry').
     * @param options An object with placeholder values.
     */
    private t(key: string, options?: { [key: string]: string | number }): string {
        if (!this.i18nInitialized) {
            console.warn(`i18next not initialized, returning key "${key}" as fallback`);
            // Simple interpolation for fallback
            if (options) {
                return Object.entries(options).reduce(
                    (acc, [k, v]) => acc.replace(`{{${k}}}`, String(v)),
                    key
                );
            }
            return key;
        }
        
        return i18next.t(key, options);
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
                <h1>${this.t('webview.mainTitle')}</h1>

                <div class="section">
                    <h2>${this.t('webview.servicesTitle')}</h2>
                    <div id="service-list" class="service-list"></div>
                    <div class="button-group"><button id="new-service">${this.t('webview.addNewService')}</button></div>
                </div>

                <div class="section">
                    <h2>${this.t('webview.importExportTitle')}</h2>
                    <textarea id="json-import-export" placeholder="${this.t('webview.importExportPlaceholder')}"></textarea>
                    <div class="button-group">
                        <button id="import-json">${this.t('webview.importAll')}</button>
                        <button id="export-json">${this.t('webview.exportAll')}</button>
                    </div>
                </div>

                <div class="section">
                    <h2>${this.t('webview.promptsTitle')}</h2>
                    <div class="form-item">
                        <label for="system-prompt">${this.t('webview.systemPromptLabel')}</label>
                        <textarea id="system-prompt" rows="5"></textarea>
                        <div class="button-group"><button id="save-system-prompt">${this.t('webview.saveSystemPrompt')}</button></div>
                    </div>
                    <div class="form-item" style="margin-top: 15px;">
                        <label for="prompt-rule">${this.t('webview.customRuleLabel')}</label>
                        <textarea id="prompt-rule" rows="3"></textarea>
                        <div class="button-group"><button id="save-prompt-rule">${this.t('webview.saveCustomRule')}</button></div>
                    </div>
                </div>

                <div class="section">
                    <h2>${this.t('webview.playgroundTitle')}</h2>
                    <div class="form-item">
                        <label for="playground-service-select">${this.t('webview.playgroundServiceLabel')}</label>
                        <select id="playground-service-select"></select>
                    </div>
                    <div class="form-item">
                        <label for="playground-prompt">${this.t('webview.playgroundPromptLabel')}</label>
                        <textarea id="playground-prompt" rows="6" placeholder="${this.t('webview.playgroundPromptPlaceholder')}"></textarea>
                    </div>
                    <div class="button-group"><button id="playground-send">${this.t('webview.playgroundSend')}</button></div>
                    <div class="form-item">
                        <label>${this.t('webview.playgroundResponseLabel')}</label>
                        <div id="playground-response-area" class="response-area" aria-live="polite"></div>
                    </div>
                </div>
            </div>

            <div id="edit-modal" class="modal">
                <div class="modal-content">
                    <h2 id="modal-title">${this.t('webview.editModalTitle')}</h2>
                    <div class="modal-form">
                        <input type="hidden" id="original-service-name">
                        <div class="form-item">
                            <label for="json-import-modal">${this.t('webview.modalImportLabel')}</label>
                            <textarea id="json-import-modal" rows="4" placeholder="${this.t('webview.modalImportPlaceholder')}"></textarea>
                            <div class="button-group" style="justify-content: flex-start; margin-top: 5px;">
                                <button id="import-from-json-btn">${this.t('webview.modalImportButton')}</button>
                            </div>
                        </div>
                        <div class="form-row">
                            <div class="form-item"><label for="name">${this.t('webview.serviceNameLabel')}</label><input type="text" id="name"></div>
                            <div class="form-item"><label for="model_name">${this.t('webview.modelNameLabel')}</label><input type="text" id="model_name"></div>
                        </div>
                        <div class="form-item"><label for="base_url">${this.t('webview.baseUrlLabel')}</label><input type="text" id="base_url"></div>
                        <div class="form-item"><label for="key">${this.t('webview.apiKeyLabel')}</label><input type="password" id="key"></div>
                        <div class="form-row">
                            <div class="form-item"><label for="temperature">${this.t('webview.temperatureLabel')}</label><input type="number" id="temperature" step="0.1" min="0" max="2"></div>
                            <div class="form-item"><label for="max_tokens">${this.t('webview.maxTokensLabel')}</label><input type="number" id="max_tokens" step="1"></div>
                        </div>
                        <div class="form-row">
                            <div class="form-item"><label for="max_context_size">${this.t('webview.maxContextSizeLabel')}</label><input type="number" id="max_context_size" step="1"></div>
                            <div class="form-item"><label for="timeout_seconds">${this.t('webview.timeoutLabel')}</label><input type="number" id="timeout_seconds" step="1" min="1"></div>
                        </div>
                        <div class="form-row">
                            <div class="form-item"><label for="price_1M_input">${this.t('webview.priceInputLabel')}</label><input type="number" id="price_1M_input" step="0.01"></div>
                            <div class="form-item"><label for="price_1M_output">${this.t('webview.priceOutputLabel')}</label><input type="number" id="price_1M_output" step="0.01"></div>
                        </div>
                        <div class="form-row">
                            <div class="form-item" style="flex-direction: row; align-items: center; gap: 10px;">
                                <input type="checkbox" id="supports_json_output" style="width: auto;"><label for="supports_json_output">${this.t('webview.supportsJsonLabel')}</label>
                            </div>
                        </div>
                        <div id="test-status-modal" style="height: 20px;"></div>
                        <div class="button-group">
                            <button id="test-connection-modal">${this.t('webview.testConnectionButton')}</button>
                            <button id="save-service-modal">${this.t('common.saveButton')}</button>
                            <button id="cancel-modal" style="background-color: var(--vscode-button-secondaryBackground);">${this.t('common.cancelButton')}</button>
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
            list.innerHTML = `<p>${this.t('webview.noServicesConfigured')}</p>`;
            return;
        }
        this.services.forEach(service => {
            const isActive = service.name === this.activeServiceName;
            const item = document.createElement('div');
            item.className = 'service-item' + (isActive ? ' active' : '');
            item.innerHTML = `
                <div class="service-name-status">
                    <span class="service-name">${service.name}</span>
                    ${isActive ? `<span class="active-badge">${this.t('webview.activeBadge')}</span>` : ''}
                </div>
                <div class="button-group">
                    ${!isActive ? `<button class="select-btn">${this.t('common.selectButton')}</button>` : ''}
                    <button class="edit-btn">${this.t('common.editButton')}</button>
                    <button class="delete-btn">${this.t('common.deleteButton')}</button>
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
            select.innerHTML = `<option disabled>${this.t('webview.noServicesAvailable')}</option>`;
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
            this.vscode.postMessage({ command: 'showError', text: this.t('webview.invalidJsonServices') });
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
            responseArea.textContent = this.t('webview.thinking');
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
            this.vscode.postMessage({ command: 'showError', text: this.t('webview.invalidJsonService') });
        }
    }

    // --- Modal Management ---
    private openModal(service: Partial<AiServiceConfig>, isNew: boolean = false): void {
        this.elements['modal-title'].textContent = isNew ? this.t('webview.addModalTitle') : this.t('webview.editModalTitle');
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
                statusEl.innerHTML = `<span class="success-text">${this.t('webview.connectionSuccessful')}</span>`;
            } else {
                statusEl.innerHTML = `<span class="error-text">${this.t('webview.connectionFailed', { message })}</span>`;
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