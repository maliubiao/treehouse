// TraceViewer - Core functionality for trace report visualization
// Main namespace to avoid global pollution
const TraceViewer = {
    // Configuration and state
    config: {
        themes: [
            { value: 'prism', label: 'Default (Light)', isDark: false },
            { value: 'prism-dark', label: 'Default Dark', isDark: true },
            { value: 'prism-okaidia', label: 'Okaidia', isDark: true },
            { value: 'prism-tomorrow', label: 'Tomorrow Night', isDark: true },
            { value: 'prism-coy', label: 'Coy', isDark: false },
            { value: 'prism-solarizedlight', label: 'Solarized Light', isDark: false },
            { value: 'prism-twilight', label: 'Twilight', isDark: true },
            { value: 'prism-funky', label: 'Funky', isDark: false },
            { value: 'prism-atom-dark', label: 'Atom Dark', isDark: true },
            { value: 'prism-base16-ateliersulphurpool.light', label: 'Ateliersulphurpool Light', isDark: false },
            { value: 'prism-cb', label: 'CB', isDark: true },
            { value: 'prism-ghcolors', label: 'GitHub', isDark: false },
            { value: 'prism-pojoaque', label: 'Pojoaque', isDark: true },
            { value: 'prism-xonokai', label: 'Xonokai', isDark: true }
        ]
    },

    // Utilities
    utils: {
        debounce(func, delay) {
            let timeoutId;
            return function(...args) {
                clearTimeout(timeoutId);
                timeoutId = setTimeout(() => {
                    func.apply(this, args);
                }, delay);
            };
        }
    },
    
    // DOM elements (populated on init)
    elements: {},

    // Core functionality
    init() {
        // Cache DOM elements
        this.elements = {
            content: document.getElementById('content'),
            search: document.getElementById('search'),
            expandAllBtn: document.getElementById('expandAll'),
            collapseAllBtn: document.getElementById('collapseAll'),
            skeletonViewBtn: document.getElementById('skeletonViewBtn'),
            exportBtn: document.getElementById('exportBtn'),
            themeSelector: document.getElementById('themeSelector'),
            sourceDialog: document.getElementById('sourceDialog'),
            closeSourceBtn: document.getElementById('closeSourceBtn'),
            dialogCloseBtn: document.getElementById('dialogCloseBtn')
        };

        // Initialize components
        this.initFolding();
        this.initSearch();
        this.initExport();
        this.initThemes();
        this.initSourceDialog();
        this.initKeyboardShortcuts();
        this.initCommentToggle();
        this.initCopySubtree();
        this.initFocusSubtree();
        this.initSkeletonView();
        this.initToggleDetails();
        this.initAiExplainer();
    },

    // Initialize folding functionality
    initFolding() {
        const { content, expandAllBtn, collapseAllBtn } = this.elements;

        // Toggle folding on click
        content.addEventListener('click', e => {
            if (e.target.classList.contains('foldable')) {
                e.target.classList.toggle('expanded');
                const group = e.target.nextElementSibling;
                if (group && group.classList.contains('call-group')) {
                    group.classList.toggle('collapsed');
                }
            }
        });

        // Expand all button
        if (expandAllBtn) {
            expandAllBtn.addEventListener('click', () => {
                const foldables = content.querySelectorAll('.foldable');
                foldables.forEach(el => {
                    el.classList.add('expanded');
                    const group = el.nextElementSibling;
                    if (group && group.classList.contains('call-group')) {
                        group.classList.remove('collapsed');
                    }
                });
            });
        }

        // Collapse all button
        if (collapseAllBtn) {
            collapseAllBtn.addEventListener('click', () => {
                const foldables = content.querySelectorAll('.foldable');
                foldables.forEach(el => {
                    el.classList.remove('expanded');
                    const group = el.nextElementSibling;
                    if (group && group.classList.contains('call-group')) {
                        group.classList.add('collapsed');
                    }
                });
            });
        }
    },

    // Initialize search functionality
    initSearch() {
        const { content, search } = this.elements;
        if (!search) return;

        const searchLogic = (event) => {
            const term = event.target.value.toLowerCase();
            const elements = content.querySelectorAll('div[class*="call"], div[class*="return"], div[class*="line"]');

            elements.forEach(el => {
                const text = el.textContent.toLowerCase();
                if (term && text.includes(term)) {
                    el.classList.add('highlight');
                    // Expand parent elements to show matches
                    let parent = el.parentElement;
                    while (parent && parent !== content) {
                        if (parent.classList.contains('call-group')) {
                            parent.classList.remove('collapsed');
                            const foldable = parent.previousElementSibling;
                            if (foldable && foldable.classList.contains('foldable')) {
                                foldable.classList.add('expanded');
                            }
                        }
                        parent = parent.parentElement;
                    }
                } else {
                    el.classList.remove('highlight');
                }
            });
        };
        
        const debouncedSearch = this.utils.debounce(searchLogic, 300);
        search.addEventListener('input', debouncedSearch);
    },

    // Initialize export functionality
    initExport() {
        const { exportBtn } = this.elements;
        if (!exportBtn) return;

        exportBtn.addEventListener('click', () => {
            const html = document.documentElement.outerHTML;
            const blob = new Blob([html], { type: 'text/html' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'trace_report.html';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        });
    },

    // Initialize theme selector
    initThemes() {
        const { themeSelector } = this.elements;
        
        if (themeSelector) {
            // Clear existing options
            themeSelector.innerHTML = '';
            
            // Add theme options
            this.config.themes.forEach(theme => {
                const option = document.createElement('option');
                option.value = theme.value;
                option.textContent = theme.label;
                option.dataset.isDark = theme.isDark;
                themeSelector.appendChild(option);
            });
            
            // Add change event
            themeSelector.addEventListener('change', () => {
                const selectedOption = themeSelector.options[themeSelector.selectedIndex];
                const isDark = selectedOption.dataset.isDark === 'true';
                
                this.changeTheme(themeSelector.value);
                document.body.className = isDark ? 'dark-theme' : '';
            });
        }
    },

    // Handle theme changes
    changeTheme(theme) {
        const themeLink = document.getElementById('prism-theme');
        themeLink.href = `https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/${theme}.min.css`;
        this.updateLineHighlights();
    },

    // Update line highlights based on current theme
    updateLineHighlights() {
        const { themeSelector } = this.elements;
        const executedLines = document.querySelectorAll('.executed-line');
        const currentLines = document.querySelectorAll('.current-line');
        
        const selectedOption = themeSelector.options[themeSelector.selectedIndex];
        const isDark = selectedOption.dataset.isDark === 'true';
        
        executedLines.forEach(el => {
            el.classList.remove('executed-line-light', 'executed-line-dark');
            el.classList.add(isDark ? 'executed-line-dark' : 'executed-line-light');
        });
        
        currentLines.forEach(el => {
            el.classList.remove('current-line-light', 'current-line-dark');
            el.classList.add(isDark ? 'current-line-dark' : 'current-line-light');
        });
    },

    // Initialize source dialog
    initSourceDialog() {
        const { sourceDialog, closeSourceBtn, dialogCloseBtn } = this.elements;
        
        if (closeSourceBtn) {
            closeSourceBtn.addEventListener('click', e => {
                e.stopPropagation();
                sourceDialog.style.display = 'none';
            });
        }
        
        // Dialog close button
        if (dialogCloseBtn) {
            dialogCloseBtn.addEventListener('click', () => {
                sourceDialog.style.display = 'none';
            });
        }
        
    },

    // Initialize keyboard shortcuts
    initKeyboardShortcuts() {
        document.addEventListener('keydown', event => {
            if (event.key === 'Escape') {
                const sourceDialog = this.elements.sourceDialog;
                if (sourceDialog) {
                    sourceDialog.style.display = 'none';
                }
            }
        });
    },
    
    // Initialize "Copy Subtree" functionality
    initCopySubtree() {
        const { content } = this.elements;
        content.addEventListener('click', async (e) => {
            if (!e.target.classList.contains('copy-subtree-btn')) {
                return;
            }

            e.preventDefault();
            e.stopPropagation();

            const copyBtn = e.target;
            const foldable = copyBtn.closest('.foldable.call');
            if (!foldable) return;

            const callGroup = foldable.nextElementSibling;
            if (!callGroup || !callGroup.classList.contains('call-group')) {
                return;
            }

            const lines = [];
            
            // Helper function to process a single node into a clean text line
            const processNodeToText = (node) => {
                const clone = node.cloneNode(true);
                // Remove all UI-only elements
                clone.querySelector('.view-source-btn')?.remove();
                clone.querySelector('.copy-subtree-btn')?.remove();
                clone.querySelector('.focus-subtree-btn')?.remove();
                clone.querySelector('.toggle-details-btn')?.remove();
                clone.querySelector('.comment')?.remove();

                const text = clone.textContent.trim().replace(/\s+/g, ' ');
                const indent = parseInt(node.dataset.indent, 10) || 0;
                
                return ' '.repeat(indent) + text;
            };

            // Process the main foldable 'call' line itself
            lines.push(processNodeToText(foldable));

            // Process all descendant log lines within the call group
            const descendants = callGroup.querySelectorAll('div[data-indent]');
            descendants.forEach(node => {
                lines.push(processNodeToText(node));
            });
            
            // Process the corresponding 'return' line
            let nextElement = callGroup.nextElementSibling;
            while(nextElement) {
                if (nextElement.classList.contains('return')) {
                     const indent = parseInt(nextElement.dataset.indent, 10) || 0;
                     const foldableIndent = parseInt(foldable.dataset.indent, 10) || 0;
                     if(indent === foldableIndent) {
                        lines.push(processNodeToText(nextElement));
                        break;
                     }
                }
                // Stop if we hit another call at the same or higher level
                if (nextElement.classList.contains('foldable')) {
                    break;
                }
                nextElement = nextElement.nextElementSibling;
            }

            const fullText = lines.join('\n');

            try {
                await navigator.clipboard.writeText(fullText);
                const originalContent = copyBtn.textContent;
                copyBtn.textContent = 'Copied!';
                setTimeout(() => {
                    copyBtn.textContent = originalContent;
                }, 1500);
            } catch (err) {
                console.error('Failed to copy text: ', err);
                const originalContent = copyBtn.textContent;
                copyBtn.textContent = 'Error!';
                setTimeout(() => {
                    copyBtn.textContent = originalContent;
                }, 1500);
            }
        });
    },
    
    // Initialize "Focus Subtree" functionality
    initFocusSubtree() {
        this.elements.content.addEventListener('click', e => {
            if (!e.target.classList.contains('focus-subtree-btn')) {
                return;
            }

            e.preventDefault();
            e.stopPropagation();

            const focusBtn = e.target;
            const foldable = focusBtn.closest('.foldable.call');
            if (!foldable) return;

            const callGroup = foldable.nextElementSibling;
            if (!callGroup || !callGroup.classList.contains('call-group')) {
                return;
            }

            // 1. Collect HTML content for the subtree
            const subtreeContainer = document.createElement('div');
            subtreeContainer.appendChild(foldable.cloneNode(true));
            subtreeContainer.appendChild(callGroup.cloneNode(true));
            
            // Find and add the matching return
            let nextElement = callGroup.nextElementSibling;
            while(nextElement) {
                if (nextElement.classList.contains('return')) {
                     const indent = parseInt(nextElement.dataset.indent, 10) || 0;
                     const foldableIndent = parseInt(foldable.dataset.indent, 10) || 0;
                     if(indent === foldableIndent) {
                        subtreeContainer.appendChild(nextElement.cloneNode(true));
                        break;
                     }
                }
                if (nextElement.classList.contains('foldable')) {
                    break;
                }
                nextElement = nextElement.nextElementSibling;
            }
            const subtreeHTML = subtreeContainer.innerHTML;
            
            // 2. Filter required data (executedLines, sourceFiles, commentsData)
            const requiredFiles = new Set();
            const requiredExecutedLines = {};

            const viewSourceButtons = subtreeContainer.querySelectorAll('.view-source-btn');
            viewSourceButtons.forEach(btn => {
                const onclickAttr = btn.getAttribute('onclick');
                // Use a regex to extract arguments: showSource('filename', lineno, frame_id)
                const match = onclickAttr.match(/showSource\('(.+?)',\s*(\d+),\s*(\d+)\)/);
                if (match) {
                    let filename = match[1].replace(/\\\\/g, '\\'); // Un-escape backslashes for JS
                    const frameId = match[3];

                    requiredFiles.add(filename);

                    if (window.executedLines[filename] && window.executedLines[filename][frameId]) {
                        if (!requiredExecutedLines[filename]) {
                            requiredExecutedLines[filename] = {};
                        }
                        requiredExecutedLines[filename][frameId] = window.executedLines[filename][frameId];
                    }
                }
            });

            const filteredSourceFiles = {};
            requiredFiles.forEach(file => {
                if (window.sourceFiles[file]) {
                    filteredSourceFiles[file] = window.sourceFiles[file];
                }
            });

            const filteredCommentsData = {};
            requiredFiles.forEach(file => {
                if(window.commentsData[file]){
                    filteredCommentsData[file] = window.commentsData[file];
                }
            });


            // 3. Construct the new HTML document
            let newHtml = document.documentElement.outerHTML;

            // Replace content
            newHtml = newHtml.replace(
                /<div id="content">[\s\S]*<\/div>/,
                `<div id="content">\n${subtreeHTML}\n</div>`
            );

            // Replace data
            newHtml = newHtml.replace(
                /window\.executedLines = .*?;/,
                `window.executedLines = ${JSON.stringify(requiredExecutedLines)};`
            );
            newHtml = newHtml.replace(
                /window\.sourceFiles = .*?;/,
                `window.sourceFiles = ${JSON.stringify(filteredSourceFiles)};`
            );
            newHtml = newHtml.replace(
                /window\.commentsData = .*?;/,
                `window.commentsData = ${JSON.stringify(filteredCommentsData)};`
            );

            // Update title
            const callText = foldable.textContent.trim().replace(/\s+/g, ' ').substring(0, 50);
            newHtml = newHtml.replace(
                /<title>.*<\/title>/,
                `<title>Focus: ${callText}...</title>`
            );
            newHtml = newHtml.replace(
                /<h1>.*<\/h1>/,
                `<h1>Focus View: ${foldable.textContent.trim().replace(/\s+/g, ' ')}</h1>`
            );

            // 4. Open in new window
            const newWindow = window.open();
            if(newWindow){
                newWindow.document.write(newHtml);
                newWindow.document.close();
            } else {
                alert("Please allow pop-ups for this site to use the focus feature.");
            }
        });
    },

    // Initialize Skeleton View functionality
    initSkeletonView() {
        const { skeletonViewBtn } = this.elements;
        if (!skeletonViewBtn) return;

        skeletonViewBtn.addEventListener('click', () => {
            document.body.classList.toggle('skeleton-mode');

            if (document.body.classList.contains('skeleton-mode')) {
                skeletonViewBtn.textContent = '完整视图';
            } else {
                skeletonViewBtn.textContent = '框架模式';
            }
        });
    },
    
    // Initialize local detail toggle for skeleton mode
    initToggleDetails() {
        this.elements.content.addEventListener('click', e => {
            if (!e.target.classList.contains('toggle-details-btn')) {
                return;
            }

            e.preventDefault();
            e.stopPropagation();

            const toggleBtn = e.target;
            const foldable = toggleBtn.closest('.foldable.call');
            if (!foldable) return;

            const callGroup = foldable.nextElementSibling;
            if (!callGroup || !callGroup.classList.contains('call-group')) {
                return;
            }

            // Toggle the class that overrides skeleton mode locally
            callGroup.classList.toggle('show-details');

            // Update button appearance to reflect state
            if (callGroup.classList.contains('show-details')) {
                toggleBtn.textContent = '📦';
                toggleBtn.title = 'Hide details for this subtree';
            } else {
                toggleBtn.textContent = '👁️';
                toggleBtn.title = 'Show details for this subtree';
            }
        });
    },

    // Initialize AI Explainer functionality
    initAiExplainer() {
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
            currentLogText: '',

            init() {
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
                this.status.textContent = 'Settings saved!';
                setTimeout(() => this.status.textContent = '', 2000);
            },
            
            async fetchModels(savedModel = null) {
                const baseUrl = this.apiUrlInput.value.trim();
                if (!baseUrl) {
                    alert('Please enter the LLM API URL first.');
                    return;
                }
                
                this.status.textContent = 'Fetching models...';
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

                    this.status.textContent = 'Models loaded.';
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
                const lines = [];
                const processNodeToText = (node) => {
                    const clone = node.cloneNode(true);
                    // Minimal cleanup for the prompt, remove UI buttons
                    clone.querySelectorAll('.copy-subtree-btn, .focus-subtree-btn, .explain-ai-btn, .toggle-details-btn, .view-source-btn').forEach(b => b.remove());
                    const text = clone.textContent.trim().replace(/\s+/g, ' ');
                    const indent = parseInt(node.dataset.indent, 10) || 0;
                    return ' '.repeat(indent) + text;
                };

                lines.push(processNodeToText(foldable));
                callGroup.querySelectorAll('div[data-indent]').forEach(node => lines.push(processNodeToText(node)));
                
                let nextElement = callGroup.nextElementSibling;
                while(nextElement) {
                    if (nextElement.classList.contains('return')) {
                        if ((parseInt(nextElement.dataset.indent, 10) || 0) === (parseInt(foldable.dataset.indent, 10) || 0)) {
                            lines.push(processNodeToText(nextElement));
                            break;
                        }
                    }
                    if (nextElement.classList.contains('foldable')) break;
                    nextElement = nextElement.nextElementSibling;
                }
                return lines.join('\n');
            },

            show(logText) {
                this.currentLogText = logText;
                this.body.innerHTML = '';
                this.status.textContent = 'Ready to explain.';
                
                const lines = logText.split('\n');
                lines.forEach((line, index) => {
                    const container = document.createElement('div');
                    container.className = 'ai-log-line-container';
                    
                    const originalLog = document.createElement('div');
                    originalLog.className = 'ai-original-log';
                    originalLog.textContent = line;
                    
                    const explanation = document.createElement('div');
                    explanation.className = 'ai-explanation';
                    explanation.style.display = 'none'; // Initially hidden
                    
                    // Try to extract line number for mapping
                    const match = line.match(/▷\s*(\S+):(\d+)/);
                    if (match) {
                        const file = match[1];
                        const lineNum = match[2];
                        container.dataset.logKey = `${file}:${lineNum}:${index}`; // Add index for uniqueness
                        explanation.id = `explanation-${file.replace(/[:/\\.]/g, '-')}-${lineNum}-${index}`;
                    }

                    container.appendChild(originalLog);
                    container.appendChild(explanation);
                    this.body.appendChild(container);
                });

                this.dialog.style.display = 'flex';
            },

            hide() {
                this.dialog.style.display = 'none';
            },
            
            async startExplanation() {
                const baseUrl = this.apiUrlInput.value.trim();
                const model = this.modelSelect.value;

                if (!baseUrl || !model) {
                    alert('Please configure API URL and select a model.');
                    return;
                }

                // Reset previous explanations
                this.body.querySelectorAll('.ai-explanation').forEach(el => {
                    el.textContent = '';
                    el.style.display = 'none';
                });

                const systemPrompt = `You are a highly specialized code analysis assistant. Your mission is to provide **concrete, data-driven explanations** for a Python trace log. You must explain what the code *actually did* with its runtime data, not just what the code *does* in general.

**Input Log Format:**
Each log entry for a line of code looks like this:
\`▷ path/to/file.py:LINE_NUMBER SOURCE_CODE # Debug: VAR1=VALUE1, VAR2=VALUE2, ...\`

- \`▷ path/to/file.py:LINE_NUMBER SOURCE_CODE\`: The executed line of code.
- \`# Debug: ...\`: The state of relevant variables **after** the line was executed. This data is CRITICAL.

**Your Task & Rules:**

1.  **Analyze \`▷ LINE\` entries ONLY.** Ignore \`CALL\`, \`RETURN\`, etc.
2.  **Focus on the \`# Debug\` data.** Your explanation MUST be based on the variable values provided.
3.  **Be Specific, Not Generic.**
    *   **BAD (Generic):** "Checks if the data is valid."
    *   **GOOD (Specific):** "断言 \`response['status']\` 的值为 'ok'，此断言通过，程序继续执行。"
    *   **BAD (Generic):** "Appends an item to the list."
    *   **GOOD (Specific):** "将字符串 'apple' 添加到 \`my_list\` 中，列表现在变为 \`['orange', 'apple']\`。"
4.  **Explain the Outcome.** Describe the effect of the line's execution. What changed? What was checked? What was the result?
5.  **Use Chinese** for all explanations.

**Output Format:**
You MUST respond with a stream of JSON objects, one per line. Each JSON object must have this exact structure:
{
  "file": "path/to/file.py",
  "lineNumber": 123,
  "explanation": "Your concrete, data-driven explanation in Chinese."
}

**Example Walkthrough:**

**Input Log Snippet:**
▷ /app/main.py:25 data = {'user': 'test', 'items': []} # Debug: data={'user': 'test', 'items': []}
▷ /app/main.py:26 assert data.get('user') == 'test' # Debug: data={'user': 'test', 'items': []}
▷ /app/main.py:27 item_name = "product_a" # Debug: item_name="product_a"
▷ /app/main.py:28 data['items'].append(item_name) # Debug: data={'user': 'test', 'items': ['product_a']}, item_name="product_a"

**Your Required JSON Output Stream:**
{"file": "/app/main.py", "lineNumber": 25, "explanation": "创建一个名为 'data' 的字典，包含 'user' 和 'items' 两个键。"}
{"file": "/app/main.py", "lineNumber": 26, "explanation": "断言 'data' 字典中的 'user' 键对应的值是 'test'。断言成功。"}
{"file": "/app/main.py", "lineNumber": 27, "explanation": "将字符串 'product_a' 赋值给变量 'item_name'。"}
{"file": "/app/main.py", "lineNumber": 28, "explanation": "将 'item_name' 的值 ('product_a') 添加到 'data' 字典的 'items' 列表中。列表更新为 ['product_a']。"}
`;

                const userPrompt = `Please analyze the following trace log:\n\n${this.currentLogText}`;
                const fullPrompt = `${systemPrompt}\n\n${userPrompt}`;

                this.status.textContent = 'Sending request to LLM...';
                this.startBtn.disabled = true;

                try {
                    const response = await fetch(`${baseUrl}/ask?model=${encodeURIComponent(model)}`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ prompt: fullPrompt })
                    });
                    
                    if (!response.ok || !response.body) throw new Error(`HTTP error! Status: ${response.status}`);
                    
                    this.status.textContent = 'Receiving explanation stream...';
                    let receivedChars = 0;

                    const reader = response.body.getReader();
                    const decoder = new TextDecoder();
                    let sseLineBuffer = '';
                    let jsonContentBuffer = ''; // Buffer for the actual LLM content

                    while (true) {
                        const { value, done } = await reader.read();
                        if (done) {
                            // After stream ends, try to process any remaining content in the buffer
                            if (jsonContentBuffer.trim()) {
                                try {
                                    const explanationData = JSON.parse(jsonContentBuffer);
                                    this.renderExplanation(explanationData);
                                } catch (e) {
                                    console.warn('Failed to parse final LLM-generated JSON object:', jsonContentBuffer, e);
                                }
                            }
                            break;
                        }

                        // 1. Process the raw stream for SSE lines (NDJSON in our case)
                        sseLineBuffer += decoder.decode(value, { stream: true });
                        const sseLines = sseLineBuffer.split('\n');
                        sseLineBuffer = sseLines.pop(); // Keep the last, possibly incomplete, line

                        for (const sseLine of sseLines) {
                            if (sseLine.trim() === '') continue;
                            try {
                                const ssePayload = JSON.parse(sseLine); // e.g., {event: 'content', data: '...'}

                                if (ssePayload.event === "content" || ssePayload.event === "thinking") {
                                    if (typeof ssePayload.data === 'string') {
                                        receivedChars += ssePayload.data.length;
                                        this.status.textContent = `Receiving explanation stream... (${receivedChars} chars)`;
                                    }
                                    
                                    if (ssePayload.event === "content" && typeof ssePayload.data === 'string') {
                                        // 2. Append LLM's raw data to our content buffer
                                        jsonContentBuffer += ssePayload.data;

                                        // 3. Try to extract complete JSON objects (delimited by newline)
                                        const jsonObjectsRaw = jsonContentBuffer.split('\n');
                                        jsonContentBuffer = jsonObjectsRaw.pop(); // Keep incomplete part for the next chunk

                                        for (const jsonObjStr of jsonObjectsRaw) {
                                            if (jsonObjStr.trim() === '') continue;
                                            try {
                                                const explanationData = JSON.parse(jsonObjStr);
                                                this.renderExplanation(explanationData);
                                            } catch (jsonError) {
                                                console.warn('Failed to parse LLM-generated JSON object:', jsonObjStr, jsonError);
                                            }
                                        }
                                    }
                                } else if (ssePayload.event === "error") {
                                    throw new Error(ssePayload.data);
                                } else if (ssePayload.event === "end") {
                                    this.status.textContent = `Explanation finished. (Total ${receivedChars} chars)`;
                                }
                            } catch (e) {
                                console.warn('Failed to parse SSE line envelope:', sseLine, e);
                            }
                        }
                    }

                } catch (error) {
                    this.status.textContent = `Error: ${error.message}`;
                    console.error('AI Explanation failed:', error);
                } finally {
                    this.startBtn.disabled = false;
                }
            },
            
            renderExplanation(data) {
                if (!data.file || !data.lineNumber || !data.explanation) return;
                
                // Find all potential containers matching file and line number
                const potentialContainers = this.body.querySelectorAll(`[data-log-key^="${data.file}:${data.lineNumber}:"]`);
                
                potentialContainers.forEach(container => {
                    const explanationEl = container.querySelector('.ai-explanation');
                    if (explanationEl && explanationEl.textContent === '') { // Render only if empty
                        explanationEl.textContent = data.explanation;
                        explanationEl.style.display = 'block';
                        return; // Assume we found the right one for this pass
                    }
                });
            }
        };

        // Initialize the module
        aiExplainer.init();
        // Attach to the main viewer object for debugging/scoping
        TraceViewer.aiExplainer = aiExplainer;
    },

    // Adjust line number styles based on theme
    adjustLineNumberStyles(isDark) {
        const lineNumbers = document.querySelectorAll('.line-number');
        if (isDark) {
            lineNumbers.forEach(el => {
                el.style.color = '#aaa';
                el.style.borderRightColor = '#444';
            });
        } else {
            lineNumbers.forEach(el => {
                el.style.color = '#999';
                el.style.borderRightColor = '#eee';
            });
        }
    },

    // Initialize comment toggle functionality
    initCommentToggle() {
        const content = this.elements.content;
        
        // 使用事件委托模式，但增加更精确的判断
        content.addEventListener('click', e => {
            // 检查是否点击了评论或其子元素
            let target = e.target;
            let isComment = target.classList.contains('comment') || 
                             target.classList.contains('comment-preview') ||
                             target.classList.contains('comment-full') ||
                             target.closest('.comment');
            
            if (!isComment) return;
            
            // 找到评论根元素
            const commentElement = target.classList.contains('comment') ? 
                                  target : target.closest('.comment');
            
            if (!commentElement) return;
            
            // 阻止事件冒泡
            e.stopPropagation();
            e.preventDefault();
            
            // 切换展开状态
            commentElement.classList.toggle('expanded');
            
            // 如果展开，滚动到可见区域
            if (commentElement.classList.contains('expanded')) {
                setTimeout(() => {
                    commentElement.scrollIntoView({behavior: 'smooth', block: 'nearest'});
                }, 10);
            }
        });
    },

    // Source code viewer functionality
    sourceViewer: {
        // Get executed lines for a specific frame
        getFrameLines(filename, frameId) {
            if (!window.executedLines || !window.executedLines[filename] || !window.executedLines[filename][frameId]) {
                return null;
            }
            const rawLines = window.executedLines[filename][frameId];
            // Extract just the line numbers from the [lineno, comment] pairs
            const lines = rawLines.map(pair => Array.isArray(pair) ? pair[0] : pair);
            return {
                min: Math.min(...lines),
                max: Math.max(...lines),
                all: [...new Set(lines)]
            };
        },

        // Show source code dialog
        showSource(filename, lineNumber, frameId) {
            const sourceContent = document.getElementById('sourceContent');
            const titleDiv = document.getElementById('sourceTitle');
            const dialog = document.getElementById('sourceDialog');

            if (!window.sourceFiles || !window.sourceFiles[filename]) {
                titleDiv.textContent = `${filename} (Source not available)`;
                sourceContent.innerHTML = '<div>Source file not available</div>';
                dialog.style.display = 'flex';
                return;
            }
            // Get source code, decode if it's Base64-encoded
            let text = window.sourceFiles[filename];
        
            // Attempt to decode Base64 with UTF-8 support
            const raw = atob(text);
            const bytes = new Uint8Array(raw.length);
            for (let i = 0; i < raw.length; i++) {
                bytes[i] = raw.charCodeAt(i);
            }
            text = new TextDecoder('utf-8').decode(bytes);
            
            const lines = text.split('\n');

            const frameLines = frameId ? this.getFrameLines(filename, frameId) : null;
            for(let lineNumber of frameLines.all) {
                line_debug_comment = window.lineComment[`${frameId}-${filename}-${lineNumber}`]
                if(line_debug_comment) {
                  lines[lineNumber-1] += line_debug_comment;
                }
            }
            text = lines.join("\n")

            // Setup dialog
            this.setupSourceDialog(dialog, titleDiv, sourceContent, filename, lineNumber);
            
            // Create content elements
            const container = this.createSourceContainer(lines, text);
            sourceContent.appendChild(container);
            
            // Add close controls
            this.addDialogCloseControls(dialog);
            
            // Show the dialog
            dialog.style.display = 'flex';

            // Process after dialog is visible
            setTimeout(() => {
                this.processSourceCode(
                    container.querySelector('.line-numbers'),
                    container.querySelector('code'),
                    frameLines,
                    lineNumber,
                    frameId,
                    filename,
                );
            }, 100);
        },
        
        // Setup dialog header
        setupSourceDialog(dialog, titleDiv, sourceContent, filename, lineNumber) {
            titleDiv.textContent = `${filename} (Line ${lineNumber})`;
            sourceContent.innerHTML = '';

            // Clean up any existing controls
            const existingCloseBtn = dialog.querySelector('.floating-close-btn');
            if (existingCloseBtn) {
                dialog.removeChild(existingCloseBtn);
            }

            const existingOverlay = dialog.querySelector('.close-overlay');
            if (existingOverlay) {
                dialog.removeChild(existingOverlay);
            }
        },
        
        // Create source container with line numbers and code
        createSourceContainer(lines, text) {
            const container = document.createElement('div');
            container.className = 'source-container';
            
            const lineNumbers = document.createElement('div');
            lineNumbers.className = 'line-numbers';
            
            const codeContent = document.createElement('div');
            codeContent.className = 'code-content';
            
            const pre = document.createElement('pre');
            const code = document.createElement('code');
            code.className = 'language-python';
            code.textContent = text;
            pre.appendChild(code);
            codeContent.appendChild(pre);
            
            // Generate line numbers
            for (let i = 1; i <= lines.length; i++) {
                const lineNum = document.createElement('div');
                lineNum.className = 'line-number';
                lineNum.textContent = i;
                lineNum.setAttribute('data-line', i);
                lineNumbers.appendChild(lineNum);
            }
            
            container.appendChild(lineNumbers);
            container.appendChild(codeContent);
            
            return container;
        },
        
        // Add close button and overlay
        addDialogCloseControls(dialog) {
            const closeBtn = document.createElement('div');
            closeBtn.className = 'floating-close-btn';
            closeBtn.innerHTML = '&times;';
            closeBtn.title = "Close (Esc)";
            closeBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                dialog.style.display = 'none';
            });
            dialog.appendChild(closeBtn);

            const closeOverlay = document.createElement('div');
            closeOverlay.className = 'close-overlay';
            closeOverlay.addEventListener('click', (e) => {
                e.stopPropagation();
                dialog.style.display = 'none';
            });
            dialog.appendChild(closeOverlay);
        },
        
        // Process source code after rendering
        processSourceCode(lineNumbers, code, frameLines, lineNumber, frameId, filename) {
            // Add loading indicator
            const loadingIndicator = document.createElement('div');
            loadingIndicator.style.position = 'absolute';
            loadingIndicator.style.top = '50%';
            loadingIndicator.style.left = '50%';
            loadingIndicator.style.transform = 'translate(-50%, -50%)';
            loadingIndicator.style.padding = '10px';
            loadingIndicator.style.background = 'rgba(0,0,0,0.7)';
            loadingIndicator.style.color = 'white';
            loadingIndicator.style.borderRadius = '4px';
            loadingIndicator.textContent = 'Loading syntax highlighting...';
            lineNumbers.parentElement.appendChild(loadingIndicator);

            const doHighlight = () => {
                // 1. Syntax highlighting must be done first to create the final DOM for the code.
                Prism.highlightElement(code);

                // 2. Synchronize line heights based on the now-highlighted code.
                const codeLines = code.querySelectorAll('.token-line, .line');
                if (!codeLines || codeLines.length === 0) {
                    this.synchronizeLineHeights(lineNumbers, code.parentElement);
                } else {
                    this.synchronizeWithPrismLines(lineNumbers, codeLines);
                }

                // 3. Highlight all lines that were executed in this frame.
                if (frameLines) {
                    frameLines.all.forEach(line => {
                        const lineElement = lineNumbers.querySelector(`.line-number[data-line="${line}"]`);
                        if (lineElement) {
                            lineElement.classList.add('executed-line');
                        }
                    });
                }

                // 4. Highlight the specific line that triggered the 'view source' action.
                const targetLine = lineNumbers.querySelector(`.line-number[data-line="${lineNumber}"]`);
                if (targetLine) {
                    targetLine.classList.add('current-line');
                    
                    // 5. Scroll the single parent container to the target line.
                    // This is robust because there is only one scrollable container.
                    targetLine.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
                
                // Remove loading indicator
                loadingIndicator.remove();
            };
            
            // Check if Prism is loaded
            if (typeof Prism !== 'undefined') {
                doHighlight();
            } else {
                // Poll until Prism is available
                const prismCheckInterval = setInterval(() => {
                    if (typeof Prism !== 'undefined') {
                        clearInterval(prismCheckInterval);
                        doHighlight();
                    }
                }, 100);
            }
        },
        
        // Synchronize line number heights with code
        synchronizeLineHeights(lineNumbersContainer, codeContainer) {
            const computedStyle = window.getComputedStyle(codeContainer);
            const lineHeight = computedStyle.lineHeight;
            const fontSize = computedStyle.fontSize;
            
            const lineNumberElements = lineNumbersContainer.querySelectorAll('.line-number');
            
            lineNumberElements.forEach(el => {
                el.style.height = lineHeight;
                el.style.lineHeight = lineHeight;
                el.style.fontSize = fontSize;
            });
        },

        // Synchronize with Prism-generated line elements
        synchronizeWithPrismLines(lineNumbersContainer, codeLines) {
            const lineNumberElements = lineNumbersContainer.querySelectorAll('.line-number');
            const count = Math.min(lineNumberElements.length, codeLines.length);
            
            // Get current theme info
            const themeSelector = document.getElementById('themeSelector');
            const selectedOption = themeSelector.options[themeSelector.selectedIndex];
            const isDark = selectedOption.dataset.isDark === 'true';
            
            // Set background color based on theme
            lineNumbersContainer.style.backgroundColor = isDark ? '#2d2d2d' : '#f5f5f5';
            
            // Adjust line heights to match
            for (let i = 0; i < count; i++) {
                const codeLineHeight = codeLines[i].offsetHeight;
                
                if (lineNumberElements[i]) {
                    lineNumberElements[i].style.height = `${codeLineHeight}px`;
                    lineNumberElements[i].style.lineHeight = `${codeLineHeight}px`;
                }
            }
            
            // Apply theme styles
            TraceViewer.adjustLineNumberStyles(isDark);
        }
    }
};

// Initialize the application
document.addEventListener('DOMContentLoaded', () => {
    TraceViewer.init();
});

// Make source viewer methods available globally to be used by inline event handlers
function showSource(filename, lineNumber, frameId) {
    TraceViewer.sourceViewer.showSource(filename, lineNumber, frameId);
}

function getFrameLines(filename, frameId) {
    return TraceViewer.sourceViewer.getFrameLines(filename, frameId);
}

// 全局函数
function toggleCommentExpand(commentId, event) {
    if (event) {
        event.stopPropagation();
        event.preventDefault();
    }
    
    const commentEl = document.getElementById(commentId);
    if (commentEl) {
        commentEl.classList.toggle('expanded');
        
        // 如果展开，滚动到可见区域
        if (commentEl.classList.contains('expanded')) {
            setTimeout(() => {
                commentEl.scrollIntoView({behavior: 'smooth', block: 'nearest'});
            }, 10);
        }
    }
}