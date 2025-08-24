/**
 * AI Explainer Module for TraceViewer.
 * This module encapsulates all functionality related to fetching AI-based explanations
 * for code trace subtrees, supporting multi-turn conversations.
 */
function initializeAiExplainer(TraceViewer) {
    const aiExplainer = {
        // Main Dialog UI Elements
        dialog: document.getElementById('aiExplainDialog'),
        closeBtn: document.querySelector('.ai-explain-close-btn'),
        body: document.getElementById('aiExplainBody'),
        status: document.getElementById('aiExplainStatus'),
        settingsBtn: document.getElementById('aiSettingsBtn'),
        clearChatBtn: null, // Will be initialized in init()
        currentModelDisplay: document.getElementById('aiCurrentModel'),

        // Settings Dialog UI Elements
        settingsDialog: document.getElementById('aiSettingsDialog'),
        settingsCloseBtn: document.getElementById('aiSettingsCloseBtn'),
        apiUrlInput: document.getElementById('llmApiUrl'),
        modelSelect: document.getElementById('llmModelSelect'),
        saveBtn: document.getElementById('llmSettingsSaveBtn'),
        fetchModelsBtn: document.getElementById('llmFetchModelsBtn'),
        
        // State Management
        currentLogText: '',
        conversationHistory: [],
        abortController: null,

        // References to dynamic UI parts for easy access
        currentChatMessagesDiv: null,
        currentThinkingSection: null,
        currentResponseSection: null,

        init() {
            // Event listeners for main dialog actions (delegated where possible)
            TraceViewer.elements.content.addEventListener('click', e => {
                if (e.target.classList.contains('explain-ai-btn')) {
                    e.preventDefault();
                    e.stopPropagation();
                    this.handleExplainClick(e.target);
                }
            });

            this.closeBtn.addEventListener('click', () => this.hide());
            this.dialog.addEventListener('click', (e) => {
                if (e.target === this.dialog) this.hide();
            });
            this.settingsBtn.addEventListener('click', () => this.showSettings());
            
            // This button is added dynamically, so we need to get it after the DOM is ready
            this.clearChatBtn = document.getElementById('aiClearChatBtn');
            if (this.clearChatBtn) {
                this.clearChatBtn.addEventListener('click', () => this.clearConversation());
            }

            // Settings dialog event listeners
            this.settingsCloseBtn.addEventListener('click', () => this.hideSettings());
            this.settingsDialog.addEventListener('click', (e) => {
                if (e.target === this.settingsDialog) this.hideSettings();
            });
            this.saveBtn.addEventListener('click', () => this.saveSettings());
            this.fetchModelsBtn.addEventListener('click', () => this.fetchModels());

            this.loadSettings();
        },

        updateCurrentModelDisplay() {
            const model = localStorage.getItem('llmModel');
            if(model) {
                this.currentModelDisplay.textContent = model.length > 25 ? `${model.substring(0, 25)}...` : model;
            } else {
                this.currentModelDisplay.textContent = TraceViewer.i18n.t('aiModelNotSet');
            }
        },

        loadSettings() {
            const apiUrl = localStorage.getItem('llmApiUrl');
            const model = localStorage.getItem('llmModel');
            if (apiUrl) {
                this.apiUrlInput.value = apiUrl;
                this.fetchModels(model);
            }
            this.updateCurrentModelDisplay();
        },

        saveSettings() {
            const apiUrl = this.apiUrlInput.value;
            const model = this.modelSelect.value;
            localStorage.setItem('llmApiUrl', apiUrl);
            localStorage.setItem('llmModel', model);
            this.updateCurrentModelDisplay();
            alert(TraceViewer.i18n.t('aiSettingsSaved'));
            this.hideSettings();
        },

        async fetchModels(savedModel = null) {
            const baseUrl = this.apiUrlInput.value.trim();
            if (!baseUrl) {
                alert(TraceViewer.i18n.t('aiApiUrlAlert'));
                return;
            }
            
            const originalBtnContent = this.fetchModelsBtn.innerHTML;
            this.fetchModelsBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
            this.fetchModelsBtn.disabled = true;

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

                const currentSavedModel = savedModel || localStorage.getItem('llmModel');
                if (currentSavedModel) {
                    this.modelSelect.value = currentSavedModel;
                }
            } catch (error) {
                alert(`${TraceViewer.i18n.t('aiFetchModelsError')}: ${error.message}`);
                console.error('Failed to fetch models:', error);
            } finally {
                this.fetchModelsBtn.innerHTML = originalBtnContent;
                this.fetchModelsBtn.disabled = false;
            }
        },

        handleExplainClick(button) {
            const foldable = button.closest('.foldable.call');
            if (!foldable) return;

            const callGroup = foldable.nextElementSibling;
            if (!callGroup || !callGroup.classList.contains('call-group')) return;

            const logText = this.getSubtreeText(foldable, callGroup);
            this.show(logText);
        },

        getSubtreeText(foldable, callGroup) {
            let allLines = [...TraceViewer._nodeToTextLines(foldable)];
            const descendants = callGroup.querySelectorAll('div[data-indent]');
            descendants.forEach(node => allLines.push(...TraceViewer._nodeToTextLines(node)));
            
            let nextElement = callGroup.nextElementSibling;
            const foldableIndent = parseInt(foldable.dataset.indent, 10) || 0;
            while(nextElement) {
                const nextIndent = parseInt(nextElement.dataset.indent, 10) || 0;
                if (nextElement.classList.contains('foldable') && nextIndent <= foldableIndent) break;
                if ((nextElement.classList.contains('return') || nextElement.classList.contains('error')) && nextIndent === foldableIndent) {
                    allLines.push(...TraceViewer._nodeToTextLines(nextElement));
                    break;
                }
                nextElement = nextElement.nextElementSibling;
            }
            return allLines.join('\n');
        },
        
        _buildInitialSystemPrompt(logText) {
            const systemContent = `You are an expert Python code analysis assistant. Analyze the provided trace log subtree and answer the user's question.

**Trace Log Context:**
The following is a subtree from a Python execution trace, showing function calls, returns, and line executions with debug variables:

\`\`\`
${logText}
\`\`\`

**Your Task:**
1. Understand the entire code execution flow shown in the trace.
2. Pay special attention to the debug variable values (# Debug: ...).
3. Answer the user's question specifically based on what actually happened in the code.
4. Use Chinese for your response.
5. Be concrete and reference actual values from the trace.
6. Format your response using Markdown. Use code blocks for code snippets.

**Response Format:**
Provide a clear, well-structured response that directly answers the user's question based on the trace data.`;
            return { role: 'system', content: systemContent };
        },
        
        show(logText) {
            this.currentLogText = logText;
            this.conversationHistory = [this._buildInitialSystemPrompt(logText)];
            this.updateCurrentModelDisplay();
            this.renderFullUI();
            this.dialog.style.display = 'flex';
        },
        
        clearConversation() {
            this.conversationHistory = [this._buildInitialSystemPrompt(this.currentLogText)];
            this.renderFullUI();
            if (this.currentChatMessagesDiv) {
                this.currentChatMessagesDiv.innerHTML = `<div class="ai-empty-state">${TraceViewer.i18n.t('aiEmptyState')}</div>`;
            }
            this.status.textContent = "对话已重置。";
            setTimeout(() => this.status.textContent = '', 3000);
        },

        renderFullUI() {
            this.resetDialogState();
            this.body.innerHTML = ''; // Clear previous UI
            
            const container = document.createElement('div');
            container.className = 'ai-explain-container';

            // Subtree Section
            const subtreeSection = document.createElement('div');
            subtreeSection.className = 'ai-subtree-section ai-subtree-collapsed';
            subtreeSection.innerHTML = `
                <div class="ai-subtree-header">
                    <span class="ai-subtree-title">${TraceViewer.i18n.t('aiSubtreeTitle')}</span>
                    <button class="ai-toggle-subtree-btn" title="${TraceViewer.i18n.t('aiToggleSubtreeTitle')}">
                        <i class="fas fa-chevron-down"></i>
                    </button>
                </div>
                <div class="ai-subtree-content"><pre></pre></div>`;
            subtreeSection.querySelector('pre').textContent = this.currentLogText;
            subtreeSection.querySelector('.ai-subtree-header').addEventListener('click', () => {
                subtreeSection.classList.toggle('ai-subtree-collapsed');
                const icon = subtreeSection.querySelector('i');
                icon.className = subtreeSection.classList.contains('ai-subtree-collapsed') ? 'fas fa-chevron-down' : 'fas fa-chevron-up';
            });
            
            // Chat Messages Area
            const chatMessages = document.createElement('div');
            chatMessages.id = 'aiChatMessages';
            chatMessages.className = 'ai-chat-messages';
            chatMessages.innerHTML = `<div class="ai-empty-state">${TraceViewer.i18n.t('aiEmptyState')}</div>`;
            this.currentChatMessagesDiv = chatMessages;

            // Input Section
            const inputSection = document.createElement('div');
            inputSection.className = 'ai-input-section';
            inputSection.innerHTML = `
                <div class="ai-input-wrapper">
                    <textarea id="aiUserQuestion" class="ai-user-question" placeholder="${TraceViewer.i18n.t('aiUserQuestionPlaceholder')}" rows="1"></textarea>
                    <button id="aiAskQuestionBtn" class="ai-ask-btn" title="Send (Enter)">
                        <i class="fas fa-paper-plane"></i>
                    </button>
                </div>`;
            
            container.appendChild(subtreeSection);
            container.appendChild(chatMessages);
            container.appendChild(inputSection);
            this.body.appendChild(container);

            const askBtn = document.getElementById('aiAskQuestionBtn');
            const questionTextarea = document.getElementById('aiUserQuestion');

            askBtn.addEventListener('click', () => this.startExplanation());
            questionTextarea.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this.startExplanation();
                }
            });
            questionTextarea.addEventListener('input', () => {
                questionTextarea.style.height = 'auto';
                questionTextarea.style.height = `${questionTextarea.scrollHeight}px`;
            });
        },

        resetDialogState() {
            this.status.textContent = '';
            this.currentChatMessagesDiv = null;
            this.currentThinkingSection = null;
            this.currentResponseSection = null;
            if (this.abortController) {
                this.abortController.abort();
                this.abortController = null;
            }
        },

        hide() {
            this.resetDialogState();
            this.dialog.style.display = 'none';
            this.hideSettings();
        },

        showSettings() {
            this.settingsDialog.style.display = 'flex';
        },

        hideSettings() {
            this.settingsDialog.style.display = 'none';
        },

        async startExplanation() {
            const baseUrl = localStorage.getItem('llmApiUrl');
            const model = localStorage.getItem('llmModel');
            const userQuestionInput = document.getElementById('aiUserQuestion');
            const userQuestion = userQuestionInput.value.trim();
            const askBtn = document.getElementById('aiAskQuestionBtn');

            if (!baseUrl || !model) {
                alert(TraceViewer.i18n.t('aiApiUrlAlert'));
                this.showSettings(); return;
            }
            if (!userQuestion) {
                alert(TraceViewer.i18n.t('aiQuestionRequiredAlert')); return;
            }
            
            // Add user message to history and UI
            this.conversationHistory.push({ role: 'user', content: userQuestion });
            this.renderUserMessage(userQuestion);

            userQuestionInput.value = '';
            userQuestionInput.style.height = 'auto';
            userQuestionInput.disabled = true;
            askBtn.disabled = true;
            
            this.abortController = new AbortController();
            this.status.textContent = TraceViewer.i18n.t('aiStatusSending');
            
            try {
                const response = await fetch(`${baseUrl}/ask`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ messages: this.conversationHistory, model: model }),
                    signal: this.abortController.signal
                });

                if (!response.ok || !response.body) throw new Error(`HTTP error! Status: ${response.status}`);

                this.status.textContent = TraceViewer.i18n.t('aiStatusReceiving');
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let sseLineBuffer = '';
                let fullResponseText = '';

                this.renderAssistantMessageShell();

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
                            
                            this.status.textContent = `${TraceViewer.i18n.t('aiStatusReceiving')} (${(fullResponseText.length / 1024).toFixed(1)} KB)`;
                            
                            if (ssePayload.event === "thinking" && ssePayload.data) {
                                this.updateThinkingSection(ssePayload.data, true);
                            } else if (ssePayload.event === "content" && ssePayload.data) {
                                fullResponseText += ssePayload.data;
                                this.updateResponseSection(fullResponseText);
                            } else if (ssePayload.event === "error") {
                                throw new Error(ssePayload.data);
                            }
                        } catch (e) { console.warn('Failed to parse SSE line:', sseLine, e); }
                    }
                }
                
                // Add final assistant message to history
                this.conversationHistory.push({ role: 'assistant', content: fullResponseText });
                
                this.status.textContent = `${TraceViewer.i18n.t('aiStatusFinished')} (Total ${(fullResponseText.length / 1024).toFixed(1)} KB)`;

            } catch (error) {
                const errorMessage = error.name === 'AbortError' ? 'Request aborted.' : `${TraceViewer.i18n.t('errorMessagePrefix')}${error.message}`;
                this.status.textContent = errorMessage;
                this.updateResponseSection(errorMessage, true);
                this.conversationHistory.push({ role: 'assistant', content: `Error: ${errorMessage}` });
            } finally {
                userQuestionInput.disabled = false;
                askBtn.disabled = false;
                this.abortController = null;
                setTimeout(() => this.status.textContent = '', 5000);
            }
        },

        renderUserMessage(content) {
            const emptyState = this.currentChatMessagesDiv.querySelector('.ai-empty-state');
            if (emptyState) emptyState.remove();
            
            const userMsgDiv = document.createElement('div');
            userMsgDiv.className = 'ai-chat-message user-message';
            const userMsgContent = document.createElement('div');
            userMsgContent.className = 'ai-message-content';
            userMsgContent.textContent = content;
            userMsgDiv.appendChild(userMsgContent);
            this.currentChatMessagesDiv.appendChild(userMsgDiv);
            this.currentChatMessagesDiv.scrollTop = this.currentChatMessagesDiv.scrollHeight;
        },

        renderAssistantMessageShell() {
            const aiMsgDiv = document.createElement('div');
            aiMsgDiv.className = 'ai-chat-message ai-message';
            
            // Thinking section (initially hidden)
            const thinkingSection = document.createElement('div');
            thinkingSection.className = 'ai-thinking-section';
            thinkingSection.style.display = 'none';
            thinkingSection.innerHTML = `
                <div class="ai-section-label">
                    <i class="fas fa-brain"></i> ${TraceViewer.i18n.t('aiThinkingProcess')}
                </div>
                <div class="ai-thinking-content"><pre></pre></div>`;
            this.currentThinkingSection = thinkingSection;

            // Response section
            const responseSection = document.createElement('div');
            responseSection.className = 'ai-response-section ai-message-content';
            responseSection.innerHTML = `<div class="ai-response-content-body"><span class="ai-cursor"></span></div>`;
            this.currentResponseSection = responseSection;

            aiMsgDiv.appendChild(thinkingSection);
            aiMsgDiv.appendChild(responseSection);
            this.currentChatMessagesDiv.appendChild(aiMsgDiv);
            this.currentChatMessagesDiv.scrollTop = this.currentChatMessagesDiv.scrollHeight;
        },

        updateThinkingSection(contentChunk, append = false) {
            if (!this.currentThinkingSection) return;
            this.currentThinkingSection.style.display = 'block';
            const pre = this.currentThinkingSection.querySelector('pre');
            if (append) pre.textContent += contentChunk;
            else pre.textContent = contentChunk;
            this.currentChatMessagesDiv.scrollTop = this.currentChatMessagesDiv.scrollHeight;
        },
        
        updateResponseSection(fullContent, isError = false) {
            if (!this.currentResponseSection) return;
            const contentBody = this.currentResponseSection.querySelector('.ai-response-content-body');
            
            if (isError) {
                contentBody.innerHTML = `<div class="ai-error">❌ ${fullContent}</div>`;
            } else {
                contentBody.innerHTML = this.formatResponse(fullContent);
                contentBody.querySelectorAll('pre code:not(.language-processed)').forEach((block) => {
                    Prism.highlightElement(block, false, () => block.classList.add('language-processed'));
                });
            }
            this.currentChatMessagesDiv.scrollTop = this.currentChatMessagesDiv.scrollHeight;
        },

        formatResponse(content) {
            try {
                return marked.parse(content, { breaks: true, gfm: true });
            } catch (error) {
                const pre = document.createElement('pre');
                pre.textContent = content;
                return pre.outerHTML;
            }
        }
    };

    aiExplainer.init();
    TraceViewer.aiExplainer = aiExplainer;
}