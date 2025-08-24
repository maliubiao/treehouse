/**
 * AI Explainer Module for TraceViewer.
 * This module encapsulates all functionality related to fetching AI-based explanations
 * for code trace subtrees.
 */
function initializeAiExplainer(TraceViewer) {
    const aiExplainer = {
        dialog: document.getElementById('aiExplainDialog'),
        closeBtn: document.querySelector('.ai-explain-close-btn'),
        apiUrlInput: document.getElementById('llmApiUrl'),
        modelSelect: document.getElementById('llmModelSelect'),
        saveBtn: document.getElementById('llmSettingsSaveBtn'),
        fetchModelsBtn: document.getElementById('llmFetchModelsBtn'),
        startBtn: document.getElementById('startAiExplainBtn'),
        body: document.getElementById('aiExplainBody'),
        status: document.getElementById('aiExplainStatus'),

        // Raw response elements (removed - now integrated into chat UI)

        currentLogText: '',
        abortController: null,

        init() {
            this.abortController = null;
            // Event listener for the main "Explain AI" button (delegated)
            TraceViewer.elements.content.addEventListener('click', e => {
                if (e.target.classList.contains('explain-ai-btn')) {
                    e.preventDefault();
                    e.stopPropagation();
                    this.handleExplainClick(e.target);
                }
            });

            // Dialog-specific event listeners
            this.closeBtn.addEventListener('click', () => this.hide());
            this.dialog.addEventListener('click', (e) => {
                if (e.target === this.dialog) {
                    this.hide();
                }
            });
            this.saveBtn.addEventListener('click', () => this.saveSettings());
            this.fetchModelsBtn.addEventListener('click', () => this.fetchModels());
            this.startBtn.addEventListener('click', () => this.startExplanation());

            // Raw response toggle removed - now integrated into chat UI

            this.loadSettings();
        },

        loadSettings() {
            const apiUrl = localStorage.getItem('llmApiUrl');
            const model = localStorage.getItem('llmModel');
            if (apiUrl) {
                this.apiUrlInput.value = apiUrl;
                this.fetchModels(model); // Fetch models and select the saved one
            }
        },

        saveSettings() {
            const apiUrl = this.apiUrlInput.value;
            const model = this.modelSelect.value;
            localStorage.setItem('llmApiUrl', apiUrl);
            localStorage.setItem('llmModel', model);
            this.status.textContent = TraceViewer.i18n.t('aiStatusSaved');
            setTimeout(() => this.status.textContent = '', 2000);
        },

        async fetchModels(savedModel = null) {
            const baseUrl = this.apiUrlInput.value.trim();
            if (!baseUrl) {
                alert(TraceViewer.i18n.t('aiApiUrlAlert'));
                return;
            }

            this.status.textContent = TraceViewer.i18n.t('aiStatusFetching');
            try {
                const response = await fetch(`${baseUrl}/models`);
                if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
                const data = await response.json();

                if (data.error) throw new Error(data.error);

                this.modelSelect.innerHTML = '';
                (data.models || []).forEach(model => {
                    const option = document.createElement('option');
                    option.value = option.textContent = model;
                    this.modelSelect.appendChild(option);
                });

                if (savedModel) {
                    this.modelSelect.value = savedModel;
                }

                this.status.textContent = TraceViewer.i18n.t('aiStatusLoaded');
            } catch (error) {
                this.status.textContent = `Error: ${error.message}`;
                console.error('Failed to fetch models:', error);
            }
        },

        handleExplainClick(button) {
            const foldable = button.closest('.foldable.call');
            if (!foldable) return;

            const callGroup = foldable.nextElementSibling;
            if (!callGroup || !callGroup.classList.contains('call-group')) return;

            // Use the same logic as copy subtree to get the text
            const logText = this.getSubtreeText(foldable, callGroup);
            this.show(logText);
        },

        getSubtreeText(foldable, callGroup) {
            // Reuse the existing _nodeToTextLines method from TraceViewer
            let allLines = [];

            // Process the main foldable 'call' line itself
            allLines.push(...TraceViewer._nodeToTextLines(foldable));

            // Process all descendant log lines within the call group
            const descendants = callGroup.querySelectorAll('div[data-indent]');
            descendants.forEach(node => {
                allLines.push(...TraceViewer._nodeToTextLines(node));
            });
            
            // Find and process the corresponding 'return' or 'exception' line
            let nextElement = callGroup.nextElementSibling;
            const foldableIndent = parseInt(foldable.dataset.indent, 10) || 0;
            while(nextElement) {
                const nextIndent = parseInt(nextElement.dataset.indent, 10) || 0;
                if (nextElement.classList.contains('foldable') && nextIndent <= foldableIndent) {
                    break; // Stop if we hit another call at the same or higher level
                }
                if ((nextElement.classList.contains('return') || nextElement.classList.contains('error')) && nextIndent === foldableIndent) {
                    allLines.push(...TraceViewer._nodeToTextLines(nextElement));
                    break;
                }
                nextElement = nextElement.nextElementSibling;
            }

            return allLines.join('\n');
        },

        show(logText) {
            this.currentLogText = logText;
            this.body.innerHTML = '';
            this.status.textContent = TraceViewer.i18n.t('aiStatusReady');

            // Create new UI layout
            const container = document.createElement('div');
            container.className = 'ai-explain-container';
            
            // Compact header with minimal footprint
            const compactHeader = document.createElement('div');
            compactHeader.className = 'ai-compact-header';
            compactHeader.innerHTML = `
                <button class="ai-subtree-toggle" data-i18n-title="aiToggleSubtreeTitle">
                    <span class="toggle-icon">◀</span>
                    <span class="toggle-text">${TraceViewer.i18n.t('aiSubtreeTitle')}</span>
                </button>
            `;
            
            // Code subtree (always visible)
            const subtreeSection = document.createElement('div');
            subtreeSection.className = 'ai-subtree-section';
            subtreeSection.innerHTML = `<pre class="ai-subtree-content">${logText}</pre>`;
            
            // Toggle functionality
            compactHeader.querySelector('.ai-subtree-toggle').addEventListener('click', () => {
                subtreeSection.classList.toggle('collapsed');
                const icon = compactHeader.querySelector('.toggle-icon');
                icon.textContent = subtreeSection.classList.contains('collapsed') ? '▶' : '▼';
            });
            
            // User input section (more prominent)
            const inputSection = document.createElement('div');
            inputSection.className = 'ai-input-section';
            inputSection.innerHTML = `
                <div class="ai-input-wrapper">
                    <textarea 
                        id="aiUserQuestion" 
                        class="ai-user-question" 
                        placeholder="${TraceViewer.i18n.t('aiUserQuestionPlaceholder')}"
                        rows="4"
                    ></textarea>
                    <button id="aiAskQuestionBtn" class="ai-ask-btn" data-i18n="aiAskButton">
                        ${TraceViewer.i18n.t('aiAskButton')}
                    </button>
                </div>
            `;
            
            // Response section
            const responseSection = document.createElement('div');
            responseSection.className = 'ai-response-section';
            responseSection.innerHTML = `
                <div class="ai-response-header">
                    <span class="ai-response-title">${TraceViewer.i18n.t('aiResponseTitle')}</span>
                </div>
                <div class="ai-response-content">
                    <div class="ai-chat-container">
                        <div class="ai-chat-messages" id="aiChatMessages">
                            <div class="ai-empty-state">${TraceViewer.i18n.t('aiEmptyState')}</div>
                        </div>
                    </div>
                </div>
            `;
            
            container.appendChild(compactHeader);
            container.appendChild(subtreeSection);
            container.appendChild(inputSection);
            container.appendChild(responseSection);
            this.body.appendChild(container);
            
            // Add event listener for ask button
            document.getElementById('aiAskQuestionBtn').addEventListener('click', () => {
                this.startExplanation();
            });
            
            // Add enter key support for textarea
            const textarea = document.getElementById('aiUserQuestion');
            textarea.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault();
                    this.startExplanation();
                }
            });

            this.dialog.style.display = 'flex';
        },

        hide() {
            if (this.abortController) {
                this.abortController.abort();
            }
            this.dialog.style.display = 'none';
            this.body.innerHTML = '';
            this.status.textContent = TraceViewer.i18n.t('aiStatusReady');
            this.startBtn.disabled = false;
        },

        async startExplanation() {
            const baseUrl = this.apiUrlInput.value.trim();
            const model = this.modelSelect.value;
            const userQuestion = document.getElementById('aiUserQuestion').value.trim();

            if (!baseUrl || !model) {
                alert(TraceViewer.i18n.t('aiApiUrlAlert'));
                return;
            }

            if (!userQuestion) {
                alert(TraceViewer.i18n.t('aiQuestionRequiredAlert'));
                return;
            }

            // Clear previous responses and show loading state
            const chatMessages = document.getElementById('aiChatMessages');
            chatMessages.innerHTML = '';

            // Add user message
            const userMsgDiv = document.createElement('div');
            userMsgDiv.className = 'ai-chat-message user-message';
            userMsgDiv.innerHTML = `<div class="ai-message-content">${userQuestion}</div>`;
            chatMessages.appendChild(userMsgDiv);

            // Add AI message with structured sections
            const aiMsgDiv = document.createElement('div');
            aiMsgDiv.className = 'ai-chat-message ai-message';
            aiMsgDiv.innerHTML = `
                <div class="ai-message-header">
                    <span class="ai-message-sender">🤖 AI Assistant</span>
                </div>
                <div class="ai-message-content">
                    <div class="ai-thinking-section" style="display: none;">
                        <div class="ai-section-label">💭 思考过程</div>
                        <div class="ai-thinking-content"><pre></pre></div>
                    </div>
                    <div class="ai-response-section" style="display: none;">
                        <div class="ai-section-label">📝 回答</div>
                        <div class="ai-response-content"></div>
                    </div>
                </div>
            `;
            chatMessages.appendChild(aiMsgDiv);
            chatMessages.scrollTop = chatMessages.scrollHeight;

            const systemPrompt = `You are an expert Python code analysis assistant. Analyze the provided trace log subtree and answer the user's question.

**Trace Log Context:**
The following is a subtree from a Python execution trace, showing function calls, returns, and line executions with debug variables:

\`\`\`
${this.currentLogText}
\`\`\`

**Your Task:**
1. Understand the entire code execution flow shown in the trace
2. Pay special attention to the debug variable values (# Debug: ...)
3. Answer the user's question specifically based on what actually happened in the code
4. Use Chinese for your response
5. Be concrete and reference actual values from the trace

**Response Format:**
Provide a clear, well-structured response that directly answers the user's question based on the trace data.`;

            const userPrompt = `User Question: ${userQuestion}\n\nPlease analyze the trace log above and answer my question.`;
            const fullPrompt = `${systemPrompt}\n\n${userPrompt}`;

            this.abortController = new AbortController();
            this.status.textContent = TraceViewer.i18n.t('aiStatusSending');
            document.getElementById('aiAskQuestionBtn').disabled = true;

            try {
                const response = await fetch(`${baseUrl}/ask?model=${encodeURIComponent(model)}`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ prompt: fullPrompt }),
                    signal: this.abortController.signal
                });

                if (!response.ok || !response.body) throw new Error(`HTTP error! Status: ${response.status}`);

                this.status.textContent = TraceViewer.i18n.t('aiStatusReceiving');
                let receivedChars = 0;

                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let sseLineBuffer = '';
                let currentAiMessage = null;
                let thinkingContent = '';
                let responseContent = '';

                // Find the AI message element
                const aiMessages = chatMessages.querySelectorAll('.ai-message');
                currentAiMessage = aiMessages[aiMessages.length - 1];
                
                // Get the content sections
                const thinkingSection = currentAiMessage.querySelector('.ai-thinking-section');
                const thinkingPre = thinkingSection.querySelector('pre');
                const responseSection = currentAiMessage.querySelector('.ai-response-section');
                const responseContentDiv = responseSection.querySelector('.ai-response-content');

                while (true) {
                    const { value, done } = await reader.read();
                    if (done) break;

                    sseLineBuffer += decoder.decode(value, { stream: true });
                    const sseLines = sseLineBuffer.split('\n');
                    sseLineBuffer = sseLines.pop();

                    for (const sseLine of sseLines) {
                        if (sseLine.trim() === '') continue;
                        try {
                            const ssePayload = JSON.parse(sseLine);

                            if (ssePayload.event === "thinking") {
                                if (typeof ssePayload.data === 'string') {
                                    thinkingContent += ssePayload.data;
                                    receivedChars += ssePayload.data.length;
                                    this.status.textContent = `${TraceViewer.i18n.t('aiStatusReceiving')} (${receivedChars} chars)`;
                                    
                                    // Real-time update thinking content
                                    thinkingSection.style.display = 'block';
                                    thinkingPre.textContent = thinkingContent;
                                    chatMessages.scrollTop = chatMessages.scrollHeight;
                                }
                            } else if (ssePayload.event === "content") {
                                if (typeof ssePayload.data === 'string') {
                                    responseContent += ssePayload.data;
                                    receivedChars += ssePayload.data.length;
                                    this.status.textContent = `${TraceViewer.i18n.t('aiStatusReceiving')} (${receivedChars} chars)`;
                                    
                                    // Real-time update response content with markdown rendering
                                    responseSection.style.display = 'block';
                                    responseContentDiv.innerHTML = this.formatResponse(responseContent);
                                    chatMessages.scrollTop = chatMessages.scrollHeight;
                                }
                            } else if (ssePayload.event === "error") {
                                throw new Error(ssePayload.data);
                            }
                        } catch (e) {
                            console.warn('Failed to parse SSE line:', sseLine, e);
                        }
                    }
                }

            } catch (error) {
                if (error.name === 'AbortError') {
                    console.log('Fetch aborted by user.');
                } else {
                    this.status.textContent = `${TraceViewer.i18n.t('errorMessagePrefix')}${error.message}`;
                    console.error('AI Explanation failed:', error);
                    
                    // Show error in chat
                    if (currentAiMessage) {
                        currentAiMessage.querySelector('.ai-message-content').innerHTML = 
                            `<div class="ai-error">❌ ${error.message}</div>`;
                    }
                }
            } finally {
                // Handle stream completion (even without explicit end event)
                if (currentAiMessage) {
                    // Show completion status
                    if (thinkingContent || responseContent) {
                        this.status.textContent = `${TraceViewer.i18n.t('aiStatusFinished')} (Total ${receivedChars} chars)`;
                    }
                    
                    // Ensure at least one section is visible
                    if (!thinkingSection.style.display || thinkingSection.style.display === 'none') {
                        if (thinkingContent) {
                            thinkingSection.style.display = 'block';
                            thinkingPre.textContent = thinkingContent;
                        }
                    }
                    
                    if (!responseSection.style.display || responseSection.style.display === 'none') {
                        if (responseContent) {
                            responseSection.style.display = 'block';
                            responseContentDiv.innerHTML = this.formatResponse(responseContent);
                        }
                    }
                }
                
                document.getElementById('aiAskQuestionBtn').disabled = false;
                this.abortController = null;
            }
        },

        
    formatResponse(content) {
        // Use marked.js for proper Markdown rendering
        try {
            return marked.parse(content);
        } catch (error) {
            console.error('Markdown parsing error:', error);
            // Fallback to simple HTML escaping
            return content
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/\n/g, '<br>');
        }
    }
    };

    // Initialize the module and attach to the main viewer object
    aiExplainer.init();
    TraceViewer.aiExplainer = aiExplainer;
}