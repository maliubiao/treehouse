document.addEventListener('DOMContentLoaded', function () {
    const content = document.getElementById('content');
    const searchInput = document.getElementById('search');
    const expandAllBtn = document.getElementById('expandAll');
    const collapseAllBtn = document.getElementById('collapseAll');
    const exportBtn = document.getElementById('exportBtn');
    const themeSelector = document.getElementById('themeSelector');

    searchInput.addEventListener('input', function () {
        const term = this.value.toLowerCase();
        const elements = content.querySelectorAll('div');

        elements.forEach(el => {
            const text = el.textContent.toLowerCase();
            if (term && text.includes(term)) {
                el.classList.add('highlight');
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

    content.addEventListener('click', function (e) {
        if (e.target.classList.contains('foldable')) {
            e.target.classList.toggle('expanded');
            const group = e.target.nextElementSibling;
            if (group) group.classList.toggle('collapsed');
        }
    });

    expandAllBtn.addEventListener('click', function () {
        const foldables = content.querySelectorAll('.foldable');
        foldables.forEach(el => {
            el.classList.add('expanded');
            const group = el.nextElementSibling;
            if (group) group.classList.remove('collapsed');
        });
    });

    collapseAllBtn.addEventListener('click', function () {
        const foldables = content.querySelectorAll('.foldable');
        foldables.forEach(el => {
            el.classList.remove('expanded');
            const group = el.nextElementSibling;
            if (group) group.classList.add('collapsed');
        });
    });

    exportBtn.addEventListener('click', function () {
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

    if (themeSelector) {
        themeSelector.addEventListener('change', function() {
            changeTheme(this.value);
        });
    }

    // Make sure source dialog is hidden on page load
    const sourceDialog = document.getElementById('sourceDialog');
    if (sourceDialog) {
        sourceDialog.style.display = 'none';
    }
    
    // Fix for closeSourceBtn if it exists when the page loads
    const closeSourceBtn = document.getElementById('closeSourceBtn');
    if (closeSourceBtn) {
        closeSourceBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            document.getElementById('sourceDialog').style.display = 'none';
        });
    }
});

function getFrameLines(filename, frameId) {
    if (!window.executedLines || !window.executedLines[filename] || !window.executedLines[filename][frameId]) {
        return null;
    }
    const lines = window.executedLines[filename][frameId];
    return {
        min: Math.min(...lines),
        max: Math.max(...lines),
        all: [...new Set(lines)]
    };
}

function showSource(filename, lineNumber, frameId) {
    const sourceContent = document.getElementById('sourceContent');
    const titleDiv = document.getElementById('sourceTitle');
    const dialog = document.getElementById('sourceDialog');

    if (!window.sourceFiles || !window.sourceFiles[filename]) {
        titleDiv.textContent = `${filename} (Source not available)`;
        sourceContent.innerHTML = '<div>Source file not available</div>';
        dialog.style.display = 'block';
        return;
    }

    const text = window.sourceFiles[filename];
    const lines = text.split('\n');
    const frameLines = frameId ? getFrameLines(filename, frameId) : null;

    titleDiv.textContent = `${filename} (Line ${lineNumber})`;
    sourceContent.innerHTML = '';

    const existingCloseBtn = dialog.querySelector('.floating-close-btn');
    if (existingCloseBtn) {
        dialog.removeChild(existingCloseBtn);
    }

    const existingOverlay = dialog.querySelector('.close-overlay');
    if (existingOverlay) {
        dialog.removeChild(existingOverlay);
    }

    const container = document.createElement('div');
    container.className = 'source-container';

    const lineNumbers = document.createElement('div');
    lineNumbers.className = 'line-numbers';

    const codeContent = document.createElement('div');
    codeContent.className = 'code-content';
    codeContent.style.overflow = 'auto';
    codeContent.style.height = 'calc(100% - 20px)';  // 新增高度限制

    const pre = document.createElement('pre');
    const code = document.createElement('code');
    code.className = 'language-python';
    code.textContent = text;
    pre.appendChild(code);
    codeContent.appendChild(pre);

    for (let i = 1; i <= lines.length; i++) {
        const lineNum = document.createElement('div');
        lineNum.className = 'line-number';
        lineNum.textContent = i;
        lineNum.setAttribute('data-line', i);
        lineNumbers.appendChild(lineNum);
    }

    container.appendChild(lineNumbers);
    container.appendChild(codeContent);
    sourceContent.appendChild(container);

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

    dialog.style.display = 'block';

    setTimeout(() => {
        if (frameLines) {
            frameLines.all.forEach(line => {
                const lineElement = lineNumbers.querySelector(`.line-number[data-line="${line}"]`);
                if (lineElement) {
                    lineElement.classList.add('executed-line');
                }
            });
        }

        const targetLine = lineNumbers.querySelector(`.line-number[data-line="${lineNumber}"]`);
        if (targetLine) {
            targetLine.classList.add('current-line');
            targetLine.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }

        Prism.highlightElement(code);

        const codeLines = code.querySelectorAll('.token-line, .line');
        if (!codeLines || codeLines.length === 0) {
            synchronizeLineHeights(lineNumbers, pre);
        } else {
            synchronizeWithPrismLines(lineNumbers, codeLines);
        }

        lineNumbers.style.overflowY = 'auto';
        lineNumbers.style.height = 'calc(100% - 20px)';  // 新增高度同步
    }, 100);
}

function synchronizeLineHeights(lineNumbersContainer, codeContainer) {
    const computedStyle = window.getComputedStyle(codeContainer);
    const lineHeight = computedStyle.lineHeight;
    const fontSize = computedStyle.fontSize;
    
    const lineNumberElements = lineNumbersContainer.querySelectorAll('.line-number');
    
    lineNumberElements.forEach(el => {
        el.style.height = lineHeight;
        el.style.lineHeight = lineHeight;
        el.style.fontSize = fontSize;
    });
}

function synchronizeWithPrismLines(lineNumbersContainer, codeLines) {
    const lineNumberElements = lineNumbersContainer.querySelectorAll('.line-number');
    
    const count = Math.min(lineNumberElements.length, codeLines.length);
    
    const themeSelector = document.getElementById('themeSelector');
    const selectedOption = themeSelector.options[themeSelector.selectedIndex];
    const isDark = selectedOption.dataset.isDark === 'true';
    
    lineNumbersContainer.style.backgroundColor = isDark ? '#2d2d2d' : '#f5f5f5';
    
    for (let i = 0; i < count; i++) {
        const codeLineHeight = codeLines[i].offsetHeight;
        
        if (lineNumberElements[i]) {
            lineNumberElements[i].style.height = `${codeLineHeight}px`;
            lineNumberElements[i].style.lineHeight = `${codeLineHeight}px`;
        }
    }
    
    adjustLineNumberStyles(isDark);
    
    const codeContent = lineNumbersContainer.nextElementSibling;
    if (codeContent) {
        codeContent.addEventListener('scroll', function() {
            lineNumbersContainer.scrollTop = this.scrollTop;
        });
    }
}

function updateLineHighlights(theme) {
    const executedLines = document.querySelectorAll('.executed-line');
    const currentLines = document.querySelectorAll('.current-line');
    
    executedLines.forEach(el => {
        el.classList.remove('executed-line-light', 'executed-line-dark');
        el.classList.add(theme.includes('dark') ? 'executed-line-dark' : 'executed-line-light');
    });
    
    currentLines.forEach(el => {
        el.classList.remove('current-line-light', 'current-line-dark');
        el.classList.add(theme.includes('dark') ? 'current-line-dark' : 'current-line-light');
    });
}

document.getElementById('dialogCloseBtn').addEventListener('click', function () {
    document.getElementById('sourceDialog').style.display = 'none';
});

document.addEventListener('click', function (event) {
    const dialog = document.getElementById('sourceDialog');
    if (event.target === dialog) {
        event.stopPropagation();
        dialog.style.display = 'none';
    }
});

document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
        document.getElementById('sourceDialog').style.display = 'none';
    }
});

function changeTheme(theme) {
    const themeLink = document.getElementById('prism-theme');
    themeLink.href = `https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/${theme}.min.css`;
    document.body.className = theme.includes('dark') ? 'dark-theme' : '';
    updateLineHighlights(theme);
}

document.addEventListener('DOMContentLoaded', function() {
    const content = document.getElementById('content');
    const searchInput = document.getElementById('search');
    const expandAllBtn = document.getElementById('expandAll');
    const collapseAllBtn = document.getElementById('collapseAll');
    const exportBtn = document.getElementById('exportBtn');
    const themeSelector = document.getElementById('themeSelector');
    
    if (themeSelector) {
        themeSelector.innerHTML = '';
        
        const themes = [
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
        ];
        
        themes.forEach(theme => {
            const option = document.createElement('option');
            option.value = theme.value;
            option.textContent = theme.label;
            option.dataset.isDark = theme.isDark;
            themeSelector.appendChild(option);
        });
        
        themeSelector.addEventListener('change', function() {
            const selectedOption = this.options[this.selectedIndex];
            const isDark = selectedOption.dataset.isDark === 'true';
            
            changeTheme(this.value);
            
            document.body.className = isDark ? 'dark-theme' : '';
        });
    }
});

function updateLineHighlights(theme) {
    const executedLines = document.querySelectorAll('.executed-line');
    const currentLines = document.querySelectorAll('.current-line');
    
    const themeSelector = document.getElementById('themeSelector');
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
}

function adjustLineNumberStyles(isDark) {
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
}