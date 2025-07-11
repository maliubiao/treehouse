import './styles.css';

// Ensure vscode is declared
declare const acquireVsCodeApi: any;
const vscode = acquireVsCodeApi();

function render(services, activeServiceName, systemPrompt, promptRule) {
    const root = document.getElementById('root');
    if (!root) return;

    root.innerHTML = `
        <div class="container">
            <h1>AI Service Configurations</h1>

            <div class="section">
                <h2>Services</h2>
                <div id="service-list" class="service-list"></div>
                <div class="button-group">
                    <button id="new-service">Add New Service</button>
                </div>
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
                    <div class="button-group">
                        <button id="save-system-prompt">Save System Prompt</button>
                    </div>
                </div>
                <div class="form-item" style="margin-top: 15px;">
                    <label for="prompt-rule">Custom Rule (Appended to every request)</label>
                    <textarea id="prompt-rule" rows="3"></textarea>
                    <div class="button-group">
                        <button id="save-prompt-rule">Save Rule</button>
                    </div>
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
                <div class="button-group">
                    <button id="playground-send">Send</button>
                </div>
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
                        <div class="form-item">
                            <label for="name">Service Name</label>
                            <input type="text" id="name">
                        </div>
                        <div class="form-item">
                            <label for="model_name">Model Name</label>
                            <input type="text" id="model_name">
                        </div>
                    </div>
                    <div class="form-item">
                        <label for="base_url">Base URL</label>
                        <input type="text" id="base_url">
                    </div>
                    <div class="form-item">
                        <label for="key">API Key</label>
                        <input type="password" id="key">
                    </div>
                    <div class="form-row">
                        <div class="form-item">
                            <label for="temperature">Temperature</label>
                            <input type="number" id="temperature" step="0.1" min="0" max="2">
                        </div>
                        <div class="form-item">
                            <label for="max_tokens">Max Tokens</label>
                            <input type="number" id="max_tokens" step="1">
                        </div>
                    </div>
                    <div class="form-row">
                        <div class="form-item">
                            <label for="max_context_size">Max Context Size</label>
                            <input type="number" id="max_context_size" step="1">
                        </div>
                         <div class="form-item">
                            <label for="timeout_seconds">Timeout (seconds)</label>
                            <input type="number" id="timeout_seconds" step="1" min="1">
                        </div>
                    </div>
                    <div class="form-row">
                        <div class="form-item">
                            <label for="price_1M_input">Price/1M Input ($)</label>
                            <input type="number" id="price_1M_input" step="0.01">
                        </div>
                        <div class="form-item">
                            <label for="price_1M_output">Price/1M Output ($)</label>
                            <input type="number" id="price_1M_output" step="0.01">
                        </div>
                    </div>
                    <div class="form-row">
                        <div class="form-item" style="flex-direction: row; align-items: center; gap: 10px;">
                            <input type="checkbox" id="supports_json_output" style="width: auto;">
                            <label for="supports_json_output">Supports JSON Output</label>
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
        </div>
    `;

    // Populate Prompts and Rules
    (document.getElementById('system-prompt') as HTMLTextAreaElement).value = systemPrompt;
    (document.getElementById('prompt-rule') as HTMLTextAreaElement).value = promptRule;

    // Populate Service List
    const serviceList = document.getElementById('service-list');
    if (!serviceList) return;
    serviceList.innerHTML = '';
    if (services.length === 0) {
        serviceList.innerHTML = '<p>No services configured. Add a new service or import a configuration.</p>';
    } else {
        services.forEach(service => {
            const item = document.createElement('div');
            item.className = 'service-item' + (service.name === activeServiceName ? ' active' : '');
            
            const nameAndStatus = document.createElement('div');
            nameAndStatus.className = 'service-name-status';
            
            const name = document.createElement('span');
            name.className = 'service-name';
            name.textContent = service.name;
            nameAndStatus.appendChild(name);

            if (service.name === activeServiceName) {
                const status = document.createElement('span');
                status.className = 'active-badge';
                status.textContent = 'Active';
                nameAndStatus.appendChild(status);
            }
            item.appendChild(nameAndStatus);


            const buttons = document.createElement('div');
            buttons.className = 'button-group';

            if (service.name !== activeServiceName) {
                const selectButton = document.createElement('button');
                selectButton.textContent = 'Select';
                selectButton.onclick = () => {
                    vscode.postMessage({ command: 'setActive', name: service.name });
                };
                buttons.appendChild(selectButton);
            }

            const editButton = document.createElement('button');
            editButton.textContent = 'Edit';
            editButton.onclick = () => openModal(service);
            buttons.appendChild(editButton);

            const deleteButton = document.createElement('button');
            deleteButton.textContent = 'Delete';
            deleteButton.onclick = () => {
                vscode.postMessage({ command: 'deleteService', name: service.name });
            };
            buttons.appendChild(deleteButton);

            item.appendChild(buttons);
            serviceList.appendChild(item);
        });
    }

    // Populate Playground Service Selector
    const playgroundSelect = document.getElementById('playground-service-select') as HTMLSelectElement;
    if (playgroundSelect) {
        playgroundSelect.innerHTML = '';
        if(services.length > 0) {
            services.forEach(service => {
                const option = document.createElement('option');
                option.value = service.name;
                option.textContent = service.name;
                if (service.name === activeServiceName) {
                    option.selected = true;
                }
                playgroundSelect.appendChild(option);
            });
        } else {
            const option = document.createElement('option');
            option.textContent = 'No services available';
            option.disabled = true;
            playgroundSelect.appendChild(option);
        }
    }
    
    // Attach event listeners
    attachEventListeners(services);
}

function attachEventListeners(services: any[]): void {
    document.getElementById('new-service')?.addEventListener('click', () => {
        openModal({
            name: "New Service", model_name: "", base_url: "", key: "",
            temperature: 0.1, max_tokens: 8192, max_context_size: 131072,
            timeout_seconds: 60,
            is_thinking: true, price_1M_input: 0.0, price_1M_output: 0.0,
            supports_json_output: false
        }, true);
    });

    document.getElementById('import-json')?.addEventListener('click', () => {
        try {
            const importText = (document.getElementById('json-import-export') as HTMLTextAreaElement).value;
            const importedServices = JSON.parse(importText);
            vscode.postMessage({ command: 'importServices', services: importedServices });
            (document.getElementById('json-import-export') as HTMLTextAreaElement).value = '';
        } catch (e) {
            vscode.postMessage({ command: 'showError', text: 'Invalid JSON format.' });
        }
    });

    document.getElementById('export-json')?.addEventListener('click', () => {
        (document.getElementById('json-import-export') as HTMLTextAreaElement).value = JSON.stringify(services, null, 2);
    });

    document.getElementById('save-system-prompt')?.addEventListener('click', () => {
        const text = (document.getElementById('system-prompt') as HTMLTextAreaElement).value;
        vscode.postMessage({ command: 'saveSystemPrompt', text });
    });

    document.getElementById('save-prompt-rule')?.addEventListener('click', () => {
        const text = (document.getElementById('prompt-rule') as HTMLTextAreaElement).value;
        vscode.postMessage({ command: 'saveRule', text });
    });

    // Modal listeners
    const modal = document.getElementById('edit-modal');
    if (!modal) return;
    document.getElementById('cancel-modal')?.addEventListener('click', () => modal.style.display = 'none');
    document.getElementById('save-service-modal')?.addEventListener('click', () => {
        const service = {
            name: (document.getElementById('name') as HTMLInputElement).value,
            model_name: (document.getElementById('model_name') as HTMLInputElement).value,
            base_url: (document.getElementById('base_url') as HTMLInputElement).value,
            key: (document.getElementById('key') as HTMLInputElement).value,
            temperature: parseFloat((document.getElementById('temperature') as HTMLInputElement).value),
            max_tokens: parseInt((document.getElementById('max_tokens') as HTMLInputElement).value, 10),
            max_context_size: parseInt((document.getElementById('max_context_size') as HTMLInputElement).value, 10),
            timeout_seconds: parseInt((document.getElementById('timeout_seconds') as HTMLInputElement).value, 10),
            price_1M_input: parseFloat((document.getElementById('price_1M_input') as HTMLInputElement).value),
            price_1M_output: parseFloat((document.getElementById('price_1M_output') as HTMLInputElement).value),
            supports_json_output: (document.getElementById('supports_json_output') as HTMLInputElement).checked,
            is_thinking: true,
        };
        const originalName = (document.getElementById('original-service-name') as HTMLInputElement).value;
        vscode.postMessage({ command: 'saveService', service, originalName });
        modal.style.display = 'none';
    });

    document.getElementById('test-connection-modal')?.addEventListener('click', () => {
        const service = {
            name: (document.getElementById('name') as HTMLInputElement).value,
            model_name: (document.getElementById('model_name') as HTMLInputElement).value,
            base_url: (document.getElementById('base_url') as HTMLInputElement).value,
            key: (document.getElementById('key') as HTMLInputElement).value,
            timeout_seconds: parseInt((document.getElementById('timeout_seconds') as HTMLInputElement).value, 10),
        };
        vscode.postMessage({ command: 'testConnection', service });
    });

    document.getElementById('import-from-json-btn')?.addEventListener('click', () => {
        try {
            const service = JSON.parse((document.getElementById('json-import-modal') as HTMLTextAreaElement).value);
            (document.getElementById('name') as HTMLInputElement).value = service.name || '';
            (document.getElementById('model_name') as HTMLInputElement).value = service.model_name || '';
            (document.getElementById('base_url') as HTMLInputElement).value = service.base_url || '';
            (document.getElementById('key') as HTMLInputElement).value = service.key || '';
            (document.getElementById('temperature') as HTMLInputElement).value = service.temperature ?? 0.1;
            (document.getElementById('max_tokens') as HTMLInputElement).value = service.max_tokens ?? 8192;
            (document.getElementById('max_context_size') as HTMLInputElement).value = service.max_context_size ?? 0;
            (document.getElementById('timeout_seconds') as HTMLInputElement).value = service.timeout_seconds ?? 60;
            (document.getElementById('price_1M_input') as HTMLInputElement).value = service.price_1M_input ?? 0;
            (document.getElementById('price_1M_output') as HTMLInputElement).value = service.price_1M_output ?? 0;
            (document.getElementById('supports_json_output') as HTMLInputElement).checked = service.supports_json_output ?? false;
            (document.getElementById('json-import-modal') as HTMLTextAreaElement).value = '';
        } catch (e) {
            vscode.postMessage({ command: 'showError', text: 'Invalid JSON format for single service.' });
        }
    });

    // Playground listener
    document.getElementById('playground-send')?.addEventListener('click', () => {
        const serviceSelect = document.getElementById('playground-service-select') as HTMLSelectElement;
        const promptText = document.getElementById('playground-prompt') as HTMLTextAreaElement;
        const responseArea = document.getElementById('playground-response-area');
        
        if (serviceSelect.value && promptText.value && responseArea) {
            responseArea.className = 'response-area';
            responseArea.textContent = 'Thinking...';
            vscode.postMessage({
                command: 'playgroundRequest',
                serviceName: serviceSelect.value,
                prompt: promptText.value
            });
        }
    });
}

function openModal(service, isNew = false) {
    const modal = document.getElementById('edit-modal');
    if (!modal) return;
    (document.getElementById('modal-title') as HTMLElement).textContent = isNew ? 'Add New Service' : 'Edit Service';
    (document.getElementById('original-service-name') as HTMLInputElement).value = isNew ? '' : service.name;
    (document.getElementById('name') as HTMLInputElement).value = service.name || '';
    (document.getElementById('model_name') as HTMLInputElement).value = service.model_name || '';
    (document.getElementById('base_url') as HTMLInputElement).value = service.base_url || '';
    (document.getElementById('key') as HTMLInputElement).value = service.key || '';
    (document.getElementById('temperature') as HTMLInputElement).value = service.temperature ?? 0.1;
    (document.getElementById('max_tokens') as HTMLInputElement).value = service.max_tokens ?? 8192;
    (document.getElementById('max_context_size') as HTMLInputElement).value = service.max_context_size ?? 0;
    (document.getElementById('timeout_seconds') as HTMLInputElement).value = service.timeout_seconds ?? 60;
    (document.getElementById('price_1M_input') as HTMLInputElement).value = service.price_1M_input ?? 0;
    (document.getElementById('price_1M_output') as HTMLInputElement).value = service.price_1M_output ?? 0;
    (document.getElementById('supports_json_output') as HTMLInputElement).checked = service.supports_json_output ?? false;
    (document.getElementById('test-status-modal') as HTMLElement).innerHTML = '';
    (document.getElementById('json-import-modal') as HTMLTextAreaElement).value = '';
    modal.style.display = 'block';
}

window.addEventListener('message', event => {
    const message = event.data;
    switch (message.command) {
        case 'loadConfig':
            render(message.services, message.activeServiceName, message.systemPrompt, message.promptRule);
            break;
        case 'testResult': {
            const statusEl = document.getElementById('test-status-modal');
            if (statusEl) {
                if (message.success) {
                    statusEl.innerHTML = '<span class="success-text">✔️ Connection successful!</span>';
                } else {
                    statusEl.innerHTML = `<span class="error-text">❌ ${message.message}</span>`;
                }
            }
            break;
        }
        case 'playgroundResponse': {
            const responseArea = document.getElementById('playground-response-area');
            if (responseArea) {
                responseArea.textContent = message.text;
                if (message.success) {
                    responseArea.className = 'response-area';
                } else {
                    responseArea.className = 'response-area error-text';
                }
            }
            break;
        }
    }
});

vscode.postMessage({ command: 'getConfigs' });