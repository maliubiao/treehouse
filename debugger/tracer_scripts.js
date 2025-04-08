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
    },

    // Initialize folding functionality
    initFolding() {
        const { content, expandAllBtn, collapseAllBtn } = this.elements;

        // Toggle folding on click
        content.addEventListener('click', e => {
            if (e.target.classList.contains('foldable')) {
                e.target.classList.toggle('expanded');
                const group = e.target.nextElementSibling;
                if (group) group.classList.toggle('collapsed');
            }
        });

        // Expand all button
        expandAllBtn.addEventListener('click', () => {
            const foldables = content.querySelectorAll('.foldable');
            foldables.forEach(el => {
                el.classList.add('expanded');
                const group = el.nextElementSibling;
                if (group) group.classList.remove('collapsed');
            });
        });

        // Collapse all button
        collapseAllBtn.addEventListener('click', () => {
            const foldables = content.querySelectorAll('.foldable');
            foldables.forEach(el => {
                el.classList.remove('expanded');
                const group = el.nextElementSibling;
                if (group) group.classList.add('collapsed');
            });
        });
    },

    // Initialize search functionality
    initSearch() {
        const { content, search } = this.elements;

        search.addEventListener('input', function() {
            const term = this.value.toLowerCase();
            const elements = content.querySelectorAll('div');

            elements.forEach(el => {
                const text = el.textContent.toLowerCase();
                if (term && text.includes(term)) {
                    el.classList.add('highlight');
                    // Expand parent elements to show matches
                    let parent = el.parentElement;
                    while (parent && parent !== content) {
                        if (parent.classList.contains('foldable')) {
                            parent.classList.add('expanded');
                            const group = parent.nextElementSibling;
                            if (group) group.classList.remove('collapsed');
                        }
                        parent = parent.parentElement;
                    }
                } else {
                    el.classList.remove('highlight');
                }
            });
        });
    },

    // Initialize export functionality
    initExport() {
        const { exportBtn } = this.elements;

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
        document.body.className = theme.includes('dark') ? 'dark-theme' : '';
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
        
        // Hide dialog on page load
        if (sourceDialog) {
            sourceDialog.style.display = 'none';
        }
        
        // Set up close button if it exists
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
        
        // Close on click outside
        document.addEventListener('click', event => {
            if (event.target === sourceDialog) {
                event.stopPropagation();
                sourceDialog.style.display = 'none';
            }
        });
    },

    // Initialize keyboard shortcuts
    initKeyboardShortcuts() {
        document.addEventListener('keydown', event => {
            if (event.key === 'Escape') {
                const sourceDialog = this.elements.sourceDialog;
                if (sourceDialog && sourceDialog.style.display === 'block') {
                    sourceDialog.style.display = 'none';
                }
            }
        });
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
                dialog.style.display = 'block';
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

            // Setup dialog
            this.setupSourceDialog(dialog, titleDiv, sourceContent, filename, lineNumber);
            
            // Create content elements
            const container = this.createSourceContainer(lines, text);
            sourceContent.appendChild(container);
            
            // Add close controls
            this.addDialogCloseControls(dialog);
            
            // Show the dialog
            dialog.style.display = 'block';

            // Process after dialog is visible
            setTimeout(() => {
                this.processSourceCode(
                    container.querySelector('.line-numbers'),
                    container.querySelector('code'),
                    frameLines,
                    lineNumber
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
            codeContent.style.overflow = 'auto';
            codeContent.style.height = 'calc(100% - 20px)';
            
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
        processSourceCode(lineNumbers, code, frameLines, lineNumber) {
            // Highlight executed lines
            if (frameLines) {
                frameLines.all.forEach(line => {
                    const lineElement = lineNumbers.querySelector(`.line-number[data-line="${line}"]`);
                    if (lineElement) {
                        lineElement.classList.add('executed-line');
                    }
                });
            }

            // Highlight and scroll to current line
            const targetLine = lineNumbers.querySelector(`.line-number[data-line="${lineNumber}"]`);
            if (targetLine) {
                targetLine.classList.add('current-line');
                targetLine.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }

            // Syntax highlighting
            Prism.highlightElement(code);

            // Synchronize line heights
            const codeLines = code.querySelectorAll('.token-line, .line');
            if (!codeLines || codeLines.length === 0) {
                this.synchronizeLineHeights(lineNumbers, code.parentElement);
            } else {
                this.synchronizeWithPrismLines(lineNumbers, codeLines);
            }

            // Adjust line numbers container
            lineNumbers.style.overflowY = 'auto';
            lineNumbers.style.height = 'calc(100% - 20px)';
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
            
            // Synchronize scrolling
            const codeContent = lineNumbersContainer.nextElementSibling;
            if (codeContent) {
                codeContent.addEventListener('scroll', function() {
                    lineNumbersContainer.scrollTop = this.scrollTop;
                });
            }
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