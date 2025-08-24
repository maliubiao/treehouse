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
        body: document.getElementById('aiExplainBody'),
        status: document.getElementById('aiExplainStatus'),

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
            this.body.innerHTML = ''; // Clear previous content
            this.status.textContent = TraceViewer.i18n.t('aiStatusReady');

            // 1. Main container
            const container = document.createElement('div');
            container.className = 'ai-explain-container';

            // 2. Collapsible code subtree section
            const subtreeSection = document.createElement('div');
            subtreeSection.className = 'ai-subtree-section collapsed';
            
            const subtreeHeader = document.createElement('div');
            subtreeHeader.className = 'ai-subtree-header';
            subtreeHeader.innerHTML = `
                <span class="ai-subtree-title">${TraceViewer.i18n.t('aiSubtreeTitle')}</span>
                <button class="ai-toggle-subtree-btn" title="${TraceViewer.i18n.t('aiToggleSubtreeTitle')}">
                    <i class="fas fa-chevron-down"></i>
                </button>
            `;

            const subtreeContent = document.createElement('div');
            subtreeContent.className = 'ai-subtree-content';
            const pre = document.createElement('pre');
            pre.textContent = logText;
            subtreeContent.appendChild(pre);

            subtreeSection.appendChild(subtreeHeader);
            subtreeSection.appendChild(subtreeContent);
            
            // Toggle functionality for subtree
            subtreeHeader.addEventListener('click', () => {
                subtreeSection.classList.toggle('collapsed');
                const icon = subtreeHeader.querySelector('i');
                icon.className = subtreeSection.classList.contains('collapsed') ? 'fas fa-chevron-down' : 'fas fa-chevron-up';
            });


            // 3. Chat messages area
            const chatMessages = document.createElement('div');
            chatMessages.id = 'aiChatMessages';
            chatMessages.className = 'ai-chat-messages';
            chatMessages.innerHTML = `<div class="ai-empty-state">${TraceViewer.i18n.t('aiEmptyState')}</div>`;
            
            // 4. User input section
            const inputSection = document.createElement('div');
            inputSection.className = 'ai-input-section';
            inputSection.innerHTML = `
                <div class="ai-input-wrapper">
                    <textarea id="aiUserQuestion" class="ai-user-question" placeholder="${TraceViewer.i18n.t('aiUserQuestionPlaceholder')}" rows="3"></textarea>
                    <button id="aiAskQuestionBtn" class="ai-ask-btn" title="Ctrl+Enter">
                        <i class="fas fa-paper-plane"></i>
                    </button>
                </div>
            `;

            // Append all parts to the main container
            container.appendChild(subtreeSection);
            container.appendChild(chatMessages);
            container.appendChild(inputSection);
            this.body.appendChild(container);

            // Add event listeners for the new elements
            const askBtn = document.getElementById('aiAskQuestionBtn');
            const questionTextarea = document.getElementById('aiUserQuestion');

            askBtn.addEventListener('click', () => this.startExplanation());
            questionTextarea.addEventListener('keydown', (e) => {
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
            this.status.textContent = '';
        },

        async startExplanation() {
            const baseUrl = this.apiUrlInput.value.trim();
            const model = this.modelSelect.value;
            const userQuestionInput = document.getElementById('aiUserQuestion');
            const userQuestion = userQuestionInput.value.trim();
            const askBtn = document.getElementById('aiAskQuestionBtn');

            if (!baseUrl || !model) {
                alert(TraceViewer.i18n.t('aiApiUrlAlert'));
                return;
            }

            if (!userQuestion) {
                alert(TraceViewer.i18n.t('aiQuestionRequiredAlert'));
                return;
            }

            // Collapse subtree if not already collapsed
            const subtreeSection = this.body.querySelector('.ai-subtree-section');
            if (subtreeSection && !subtreeSection.classList.contains('collapsed')) {
                subtreeSection.classList.add('collapsed');
                const icon = subtreeSection.querySelector('.ai-subtree-header i');
                if (icon) icon.className = 'fas fa-chevron-down';
            }

            const chatMessages = document.getElementById('aiChatMessages');
            // Clear empty state if it exists
            const emptyState = chatMessages.querySelector('.ai-empty-state');
            if (emptyState) {
                emptyState.remove();
            }

            // Add user message to chat
            const userMsgDiv = document.createElement('div');
            userMsgDiv.className = 'ai-chat-message user-message';
            userMsgDiv.innerHTML = `<div class="ai-message-content">${this.escapeHtml(userQuestion)}</div>`;
            chatMessages.appendChild(userMsgDiv);
            chatMessages.scrollTop = chatMessages.scrollHeight;

            // Clear input and disable it
            userQuestionInput.value = '';
            userQuestionInput.disabled = true;
            askBtn.disabled = true;

            // Prepare and add AI message container
            const aiMsgDiv = document.createElement('div');
            aiMsgDiv.className = 'ai-chat-message ai-message';
            aiMsgDiv.innerHTML = `
                <div class="ai-message-header">
                    <span class="ai-message-sender">🤖 AI Assistant</span>
                </div>
                <div class="ai-message-content">
                    <div class="ai-thinking-section" style="display: none;">
                        <div class="ai-section-label">
                            <i class="fas fa-brain"></i> ${TraceViewer.i18n.t('aiThinkingProcess')}
                        </div>
                        <div class="ai-thinking-content"><pre></pre></div>
                    </div>
                    <div class="ai-response-section">
                         <div class="ai-section-label">
                            <i class="fas fa-comment-dots"></i> ${TraceViewer.i18n.t('aiAnswer')}
                         </div>
                        <div class="ai-response-content-body"></div>
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
1. Understand the entire code execution flow shown in the trace.
2. Pay special attention to the debug variable values (# Debug: ...).
3. Answer the user's question specifically based on what actually happened in the code.
4. Use Chinese for your response.
5. Be concrete and reference actual values from the trace.

**Response Format:**
Provide a clear, well-structured response that directly answers the user's question based on the trace data.`;

            const userPrompt = `User Question: ${userQuestion}\n\nPlease analyze the trace log above and answer my question.`;
            const fullPrompt = `${systemPrompt}\n\n${userPrompt}`;

            this.abortController = new AbortController();
            this.status.textContent = TraceViewer.i18n.t('aiStatusSending');

            try {
                const response = await fetch(`${baseUrl}/ask?model=${encodeURIComponent(model)}`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ prompt: fullPrompt }),
                    signal: this.abortController.signal
                });

                if (!response.ok || !response.body) throw new Error(`HTTP error! Status: ${response.status}`);

                this.status.textContent = TraceViewer.i18n.t('aiStatusReceiving');
                
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let sseLineBuffer = '';
                
                let thinkingContent = '';
                let responseContent = '';
                let receivedChars = 0;

                const thinkingSection = aiMsgDiv.querySelector('.ai-thinking-section');
                const thinkingPre = thinkingSection.querySelector('pre');
                const responseContentDiv = aiMsgDiv.querySelector('.ai-response-content-body');
                
                // Show thinking section from the start to stream content into it
                thinkingSection.style.display = 'block';

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
                            
                            receivedChars += (ssePayload.data || '').length;
                            this.status.textContent = `${TraceViewer.i18n.t('aiStatusReceiving')} (${receivedChars} chars)`;

                            if (ssePayload.event === "thinking") {
                                if (typeof ssePayload.data === 'string') {
                                    thinkingContent += ssePayload.data;
                                    thinkingPre.textContent = thinkingContent;
                                    chatMessages.scrollTop = chatMessages.scrollHeight;
                                }
                            } else if (ssePayload.event === "content") {
                                if (typeof ssePayload.data === 'string') {
                                    responseContent += ssePayload.data;
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

                // Final update after stream ends
                responseContentDiv.innerHTML = this.formatResponse(responseContent);
                this.status.textContent = `${TraceViewer.i18n.t('aiStatusFinished')} (Total ${receivedChars} chars)`;


            } catch (error) {
                const errorMessage = error.name === 'AbortError' 
                    ? 'Request aborted by user.' 
                    : `${TraceViewer.i18n.t('errorMessagePrefix')}${error.message}`;
                
                this.status.textContent = errorMessage;
                console.error('AI Explanation failed:', error);
                
                aiMsgDiv.querySelector('.ai-message-content').innerHTML = 
                    `<div class="ai-error">❌ ${errorMessage}</div>`;

            } finally {
                // Re-enable input
                userQuestionInput.disabled = false;
                askBtn.disabled = false;
                this.abortController = null;
                setTimeout(() => this.status.textContent = '', 5000);
            }
        },

        escapeHtml(unsafe) {
            if (!unsafe) return '';
            return unsafe
                 .replace(/&/g, "&amp;")
                 .replace(/</g, "&lt;")
                 .replace(/>/g, "&gt;")
                 .replace(/"/g, "&quot;")
                 .replace(/'/g, "&#039;");
        },

        formatResponse(content) {
            // Use marked.js for proper Markdown rendering
            try {
                // Configure marked to handle line breaks correctly
                return marked.parse(content, { breaks: true });
            } catch (error) {
                console.error('Markdown parsing error:', error);
                // Fallback to simple HTML escaping and line breaks
                return this.escapeHtml(content).replace(/\n/g, '<br>');
            }
        }
    };

    // Initialize the module and attach to the main viewer object
    aiExplainer.init();
    TraceViewer.aiExplainer = aiExplainer;
}