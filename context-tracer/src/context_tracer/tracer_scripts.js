// Search Database - Advanced search functionality for trace events
class SearchDatabase {
    constructor() {
        this.events = [];
        this.index = {
            byFilename: new Map(),
            byFunction: new Map(),
            byLine: new Map(),
            byFrame: new Map(),
            byType: new Map(),
            byThread: new Map()
        };
    }
    
    // Initialize database from window.eventMetadata
    initializeFromMetadata() {
        if (!window.eventMetadata) return;
        
        if ('requestIdleCallback' in window) {
            requestIdleCallback(() => this._initializeFromMetadataImpl());
        } else {
            // Fallback to immediate execution if requestIdleCallback is not supported
            setTimeout(() => this._initializeFromMetadataImpl(), 0);
        }
    }
    
    _initializeFromMetadataImpl() {
        const allElements = document.querySelectorAll('[data-event-id]');
        const elementMap = new Map();
        allElements.forEach(el => {
            const eventId = el.getAttribute('data-event-id');
            if (eventId) {
                elementMap.set(eventId, el);
            }
        });
        
        Object.entries(window.eventMetadata).forEach(([eventId, metadata]) => {
            const element = elementMap.get(eventId);
            if (element) {
                this.addEvent({
                    id: parseInt(eventId),
                    ...metadata,
                    element: element
                });
            } else {
                console.warn(`Element with data-event-id="${eventId}" not found.`);
            }
        });
    }
    
    addEvent(eventData) {
        const event = {
            id: eventData.id,
            type: eventData.type,
            filename: eventData.filename,
            lineno: eventData.lineno,
            func: eventData.func,
            frameId: eventData.frame_id,
            threadId: eventData.thread_id,
            args: this._parseArgs(eventData.args),
            returnValue: eventData.return_value,
            variables: eventData.tracked_vars,
            element: eventData.element
        };
        
        this.events.push(event);
        this._indexEvent(event);
    }
    
    _indexEvent(event) {
        // Index by filename
        if (event.filename) {
            if (!this.index.byFilename.has(event.filename)) {
                this.index.byFilename.set(event.filename, []);
            }
            this.index.byFilename.get(event.filename).push(event);
        }
        
        // Index by function name
        if (event.func) {
            if (!this.index.byFunction.has(event.func)) {
                this.index.byFunction.set(event.func, []);
            }
            this.index.byFunction.get(event.func).push(event);
        }
        
        // Index by line number
        if (event.lineno) {
            const lineKey = `${event.filename}:${event.lineno}`;
            if (!this.index.byLine.has(lineKey)) {
                this.index.byLine.set(lineKey, []);
            }
            this.index.byLine.get(lineKey).push(event);
        }
        
        // Index by frame ID
        if (event.frameId) {
            if (!this.index.byFrame.has(event.frameId)) {
                this.index.byFrame.set(event.frameId, []);
            }
            this.index.byFrame.get(event.frameId).push(event);
        }
        
        // Index by event type
        if (event.type) {
            if (!this.index.byType.has(event.type)) {
                this.index.byType.set(event.type, []);
            }
            this.index.byType.get(event.type).push(event);
        }
        
        // Index by thread ID
        if (event.threadId) {
            if (!this.index.byThread.has(event.threadId)) {
                this.index.byThread.set(event.threadId, []);
            }
            this.index.byThread.get(event.threadId).push(event);
        }
    }
    
    _parseArgs(argsString) {
        if (!argsString) return {};
        
        const args = {};
        // Simple parsing of "arg1=value1, arg2=value2" format
        const pairs = argsString.split(',').map(pair => pair.trim());
        
        pairs.forEach(pair => {
            const [key, value] = pair.split('=').map(part => part.trim());
            if (key && value) {
                args[key] = value;
            }
        });
        
        return args;
    }
    
    // Basic search functionality
    search(query) {
        if (!query || query.trim() === '') return [];
        
        const lowerQuery = query.toLowerCase();
        const terms = lowerQuery.split(/\s+/).filter(term => term.length > 0);
        
        // Simple text search across all fields
        return this.events.filter(event => {
            // If multiple terms, all must match
            if (terms.length > 1) {
                return terms.every(term => 
                    (event.filename && event.filename.toLowerCase().includes(term)) ||
                    (event.func && event.func.toLowerCase().includes(term)) ||
                    (event.lineno && event.lineno.toString().includes(term)) ||
                    (event.args && Object.values(event.args).some(val => 
                        val && val.toString().toLowerCase().includes(term))) ||
                    (event.returnValue && event.returnValue.toLowerCase().includes(term)) ||
                    (event.variables && Object.entries(event.variables).some(([key, val]) => 
                        key.toLowerCase().includes(term) || 
                        (val && val.toLowerCase().includes(term))))
                );
            }
            
            // Single term search
            return (
                (event.filename && event.filename.toLowerCase().includes(lowerQuery)) ||
                (event.func && event.func.toLowerCase().includes(lowerQuery)) ||
                (event.lineno && event.lineno.toString().includes(query)) ||
                (event.args && Object.values(event.args).some(val => 
                    val && val.toString().toLowerCase().includes(lowerQuery))) ||
                (event.returnValue && event.returnValue.toLowerCase().includes(lowerQuery)) ||
                (event.variables && Object.entries(event.variables).some(([key, val]) => 
                    key.toLowerCase().includes(lowerQuery) || 
                    (val && val.toLowerCase().includes(lowerQuery))))
            );
        });
    }
    
    // Advanced query parsing (to be implemented)
    parseQuery(query) {
        // TODO: Implement advanced query parser with field-specific searching
        return { type: 'TEXT', value: query };
    }
    
    // Get event by ID
    getEvent(eventId) {
        return this.events.find(event => event.id === eventId);
    }
    
    // Get all events for a specific file
    getEventsByFilename(filename) {
        return this.index.byFilename.get(filename) || [];
    }
    
    // Get all events for a specific function
    getEventsByFunction(funcName) {
        return this.index.byFunction.get(funcName) || [];
    }
    
    // Get all events for a specific line
    getEventsByLine(filename, lineno) {
        const lineKey = `${filename}:${lineno}`;
        return this.index.byLine.get(lineKey) || [];
    }
}

// Search Modal Component
class SearchModal {
    constructor(database) {
        this.database = database;
        this.currentPage = 1;
        this.resultsPerPage = 20;
        this.currentResults = [];
        this.modal = null;
    }
    
    show() {
        if (!this.modal) {
            this.modal = this._createModal();
            document.body.appendChild(this.modal);
        }
        this.modal.style.display = 'flex';
        this.modal.querySelector('.search-input').focus();
    }
    
    hide() {
        if (this.modal) {
            this.modal.style.display = 'none';
        }
    }
    
    _createModal() {
        const modal = document.createElement('div');
        modal.className = 'search-modal';
        modal.innerHTML = `
            <div class="search-modal-content">
                <div class="search-header">
                    <h3 data-i18n="searchModalTitle">Advanced Search</h3>
                    <button class="search-close-btn">&times;</button>
                </div>
                <div class="search-input-container">
                    <input type="text" class="search-input" placeholder="Enter search query..." data-i18n-placeholder="searchQueryPlaceholder">
                    <button class="search-button" data-i18n="searchButton">Search</button>
                </div>
                <div class="search-help">
                    <p data-i18n="searchHelpText">Search examples: file:"*.py", func:"calculate", line:10-50, param:"user_id=123"</p>
                </div>
                <div class="results-container">
                    <div class="results-info">
                        <span class="results-count" data-i18n="resultsCount">0 results</span>
                    </div>
                    <div class="results-list"></div>
                    <div class="pagination-controls">
                        <button class="pagination-btn prev-btn" disabled data-i18n="prevPage">Previous</button>
                        <span class="page-info" data-i18n="pageInfo">Page 1 of 1</span>
                        <button class="pagination-btn next-btn" disabled data-i18n="nextPage">Next</button>
                    </div>
                </div>
            </div>
        `;
        
        // Add event listeners
        const searchInput = modal.querySelector('.search-input');
        const searchBtn = modal.querySelector('.search-button');
        const closeBtn = modal.querySelector('.search-close-btn');
        const prevBtn = modal.querySelector('.prev-btn');
        const nextBtn = modal.querySelector('.next-btn');
        
        searchBtn.addEventListener('click', () => this._performSearch());
        searchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this._performSearch();
        });
        closeBtn.addEventListener('click', () => this.hide());
        prevBtn.addEventListener('click', () => this._prevPage());
        nextBtn.addEventListener('click', () => this._nextPage());
        
        // Close modal when clicking outside
        modal.addEventListener('click', (e) => {
            if (e.target === modal) this.hide();
        });
        
        return modal;
    }
    
    _performSearch() {
        const query = this.modal.querySelector('.search-input').value.trim();
        if (!query) return;
        
        this.currentResults = this.database.search(query);
        this.currentPage = 1;
        this._renderResults();
    }
    
    _renderResults() {
        const resultsList = this.modal.querySelector('.results-list');
        const resultsCount = this.modal.querySelector('.results-count');
        const pageInfo = this.modal.querySelector('.page-info');
        const prevBtn = this.modal.querySelector('.prev-btn');
        const nextBtn = this.modal.querySelector('.next-btn');
        
        // Update results count
        resultsCount.textContent = `${this.currentResults.length} results`;
        
        // Calculate pagination
        const totalPages = Math.ceil(this.currentResults.length / this.resultsPerPage);
        const start = (this.currentPage - 1) * this.resultsPerPage;
        const end = start + this.resultsPerPage;
        const pageResults = this.currentResults.slice(start, end);
        
        // Update pagination controls
        pageInfo.textContent = TraceViewer.i18n.t('pageInfo', { 
            page: this.currentPage, 
            total: totalPages 
        });
        prevBtn.disabled = this.currentPage <= 1;
        nextBtn.disabled = this.currentPage >= totalPages;
        
        // Render results
        resultsList.innerHTML = pageResults.map(result => 
            this._createResultItem(result)
        ).join('');
        
        // Add click handlers to result items
        resultsList.querySelectorAll('.result-item').forEach(item => {
            item.addEventListener('click', () => this._jumpToResult(item.dataset.eventId));
        });
    }
    
    _createResultItem(result) {
        const preview = this._formatEventPreview(result);
        return `
            <div class="result-item" data-event-id="${result.id}">
                <div class="result-preview">${preview}</div>
                <div class="result-meta">
                    <span class="result-type">${result.type}</span>
                    <span class="result-location">${result.filename}:${result.lineno}</span>
                </div>
            </div>
        `;
    }
    
    _formatEventPreview(event) {
        let preview = '';
        switch (event.type) {
            case 'call':
                preview = `↘ CALL ${event.func || 'unknown'}(${JSON.stringify(event.args)})`;
                break;
            case 'return':
                preview = `↗ RETURN ${event.returnValue || 'None'}`;
                break;
            case 'line':
                preview = `▷ LINE ${event.filename}:${event.lineno}`;
                if (event.variables) {
                    preview += ` # Debug: ${Object.entries(event.variables).map(([k, v]) => `${k}=${v}`).join(', ')}`;
                }
                break;
            case 'exception':
                preview = `⚠ EXCEPTION ${event.returnValue || 'Unknown error'}`;
                break;
            default:
                preview = `${event.type.toUpperCase()} ${event.filename}:${event.lineno}`;
        }
        return preview;
    }
    
    _jumpToResult(eventId) {
        const event = this.database.getEvent(parseInt(eventId));
        if (event && event.element) {
            // Scroll to element
            event.element.scrollIntoView({ behavior: 'smooth', block: 'center' });
            
            // Highlight the element temporarily
            event.element.classList.add('search-highlight');
            setTimeout(() => {
                event.element.classList.remove('search-highlight');
            }, 2000);
            
            // Expand parent call groups if needed
            let parent = event.element.parentElement;
            while (parent && parent !== document.getElementById('content')) {
                if (parent.classList.contains('call-group')) {
                    parent.classList.remove('collapsed');
                    const foldable = parent.previousElementSibling;
                    if (foldable && foldable.classList.contains('foldable')) {
                        foldable.classList.add('expanded');
                    }
                }
                parent = parent.parentElement;
            }
            
            this.hide();
        }
    }
    
    _prevPage() {
        if (this.currentPage > 1) {
            this.currentPage--;
            this._renderResults();
        }
    }
    
    _nextPage() {
        const totalPages = Math.ceil(this.currentResults.length / this.resultsPerPage);
        if (this.currentPage < totalPages) {
            this.currentPage++;
            this._renderResults();
        }
    }
}

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
        ],
        INITIAL_LOAD_MAX_LINES: 2000, // Max lines to show on smart "Expand All"
        SMART_EXPAND_THRESHOLD: 1000,  // Subtrees smaller than this will be fully expanded on click
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
        },
        escapeHTML(str) {
            const p = document.createElement('p');
            p.textContent = str;
            return p.innerHTML;
        }
    },
    
    // DOM elements (populated on init)
    elements: {},

    // Core functionality
    init() {
        // Cache DOM elements
        this.elements = {
            content: document.getElementById('content'),
            search: document.getElementById('sidebarSearch') || document.getElementById('search'),
            expandAllBtn: document.getElementById('expandAll'),
            collapseAllBtn: document.getElementById('collapseAll'),
            skeletonViewBtn: document.getElementById('skeletonViewBtn'),
            exportBtn: document.getElementById('exportBtn'),
            sourceDialog: document.getElementById('sourceDialog'),
            dialogCloseBtn: document.getElementById('dialogCloseBtn'),
            summaryBtn: document.getElementById('summaryBtn'),
            summaryDropdown: document.getElementById('summaryDropdown'),
            settingsBtn: document.getElementById('settingsBtn'),
            settingsDialog: document.getElementById('settingsDialog'),
            sidebar: document.getElementById('sidebar'),
            sidebarOverlay: document.getElementById('sidebarOverlay'),
            toggleSidebar: document.getElementById('toggleSidebar'),
            filterCall: document.getElementById('filterCall'),
            filterReturn: document.getElementById('filterReturn'),
            filterLine: document.getElementById('filterLine'),
            filterException: document.getElementById('filterException'),
            searchBtn: document.getElementById('searchBtn')
        };

        // Initialize components
        this.i18n.init();
        this.calculateSubtreeSizes(); // Must run before initFolding
        this.initFolding();
        this.initSearch();
        this.initExport();
        this.initSettingsDialog(); // Replaces theme and help init
        this.initSourceDialog();
        this.initKeyboardShortcuts();
        this.initCommentToggle();
        this.initDebugVarsToggle();
        this.initMultiLineToggle();
        this.initCopySubtree();
        this.initFocusSubtree();
        this.initSkeletonView();
        this.initToggleDetails();
        this.initAiExplainer();
        this.initClipboardInterceptor();
        this.initSummaryDropdown();
        
        // New sidebar and filter functionality
        this.initSidebar();
        this.initFilters();
        
        // Initialize search database if metadata is available
        if (window.eventMetadata) {
            this.searchDatabase = new SearchDatabase();
            this.searchDatabase.initializeFromMetadata();
        }
        
        // Initialize search functionality
        this.initSearchModal();
    },
    
    // Initialize search modal functionality
    initSearchModal() {
        const { searchBtn } = this.elements;
        if (!searchBtn) return;
        
        // Create search modal instance
        this.searchModal = new SearchModal(this.searchDatabase);
        
        // Add event listener to search button
        searchBtn.addEventListener('click', () => {
            this.searchModal.show();
        });
        
        // Add keyboard shortcut (Ctrl+F)
        document.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
                e.preventDefault();
                this.searchModal.show();
            }
        });
    },

    // Pre-calculates the size of each foldable section for smart expansion
    calculateSubtreeSizes() {
        const foldables = this.elements.content.querySelectorAll('.foldable.call');
        foldables.forEach(foldable => {
            // Look for call group as next sibling or first child
            let callGroup = foldable.nextElementSibling;
            if (!callGroup || !callGroup.classList.contains('call-group')) {
                callGroup = foldable.querySelector('.call-group');
            }
            
            if (callGroup && callGroup.classList.contains('call-group')) {
                // Count only direct children, excluding nested foldable elements
                const directDescendants = callGroup.querySelectorAll(':scope > div[data-indent]:not(.foldable.call)');
                foldable.dataset.subtreeSize = directDescendants.length;
            } else {
                foldable.dataset.subtreeSize = 0;
            }
        });
    },

    // Initialize folding functionality
    initFolding() {
        const { content, expandAllBtn, collapseAllBtn } = this.elements;

        // Toggle folding on click
        content.addEventListener('click', e => {
            if (e.target.classList.contains('foldable')) {
                console.log('[+] Foldable element clicked:', e.target.textContent.trim());
                this.toggleFoldable(e.target);
            }
        });

        // Smart expand all button
        if (expandAllBtn) {
            expandAllBtn.addEventListener('click', () => this.smartExpandAll());
        }

        // Collapse all button
        if (collapseAllBtn) {
            collapseAllBtn.addEventListener('click', () => {
                const foldables = content.querySelectorAll('.foldable.expanded');
                foldables.forEach(el => this.collapseSubtree(el));
            });
        }
    },

    // Toggles a single foldable element's state
    toggleFoldable(foldable) {
        if (foldable.classList.contains('expanded')) {
            console.log('Action: Collapsing subtree for', foldable.textContent.trim());
            this.collapseSubtree(foldable);
        } else {
            console.log('Action: Expanding subtree for', foldable.textContent.trim());
            this.expandSubtree(foldable);
        }
    },

    // Expands a subtree, intelligently deciding between full and partial expansion
    expandSubtree(foldable) {
        const label = `expandSubtree: ${foldable.textContent.trim().substring(0, 100)}`;
        console.group(label);

        const callGroup = foldable.nextElementSibling;
        if (!callGroup || !callGroup.classList.contains('call-group')) {
            console.warn('Could not find call-group for foldable:', foldable);
            console.groupEnd();
            return;
        }

        foldable.classList.add('expanded');
        callGroup.classList.remove('collapsed');

        const subtreeSize = parseInt(foldable.dataset.subtreeSize, 10) || 0;
        console.log(`Subtree size: ${subtreeSize}. Smart expand threshold: ${this.config.SMART_EXPAND_THRESHOLD}`);

        // If the subtree is small enough, perform a full recursive expansion for convenience
        if (subtreeSize > 0 && subtreeSize < this.config.SMART_EXPAND_THRESHOLD) {
            console.log('Performing smart recursive expansion.');
            const query = '.foldable.call';
            const timerLabel = `SmartExpand querySelectorAll for "${label}"`;
            
            console.time(timerLabel);
            const children = callGroup.querySelectorAll(query);
            console.timeEnd(timerLabel);
            console.log(`Found ${children.length} descendant foldable elements to expand.`);
            
            children.forEach(child => {
                // The recursive call will create its own console group
                this.expandSubtree(child);
            });
        } else {
            console.log('Subtree is large, expanding only the first level.');
        }
        // For large subtrees, only the first level is expanded by the lines above.
        console.groupEnd();
    },

    // Recursively collapses a subtree
    collapseSubtree(foldable) {
        const label = `collapseSubtree: ${foldable.textContent.trim().substring(0, 100)}`;
        console.group(label);

        foldable.classList.remove('expanded');
        const callGroup = foldable.nextElementSibling;
        if (!callGroup || !callGroup.classList.contains('call-group')) {
            console.warn('Could not find call-group for foldable during collapse:', foldable);
            console.groupEnd();
            return;
        }

        callGroup.classList.add('collapsed');
        
        // Also recursively collapse any children that were open
        const children = callGroup.querySelectorAll('.foldable.call.expanded');
        if(children.length > 0) {
            console.log(`Recursively collapsing ${children.length} expanded children.`);
            children.forEach(child => this.collapseSubtree(child));
        }
        
        console.groupEnd();
    },

    // Expands top-level items level by level until a line threshold is met
    smartExpandAll() {
        let visibleCount = 0;
        // Get only top-level nodes to start the breadth-first expansion
        const queue = Array.from(this.elements.content.children)
                           .filter(el => el.classList.contains('foldable'));

        // Start with a clean slate
        this.elements.content.querySelectorAll('.foldable.expanded').forEach(f => this.collapseSubtree(f));

        while (queue.length > 0 && visibleCount < this.config.INITIAL_LOAD_MAX_LINES) {
            const current = queue.shift();
            if (current.classList.contains('expanded')) continue;

            current.classList.add('expanded');
            const callGroup = current.nextElementSibling;
            
            if (callGroup && callGroup.classList.contains('call-group')) {
                callGroup.classList.remove('collapsed');
                
                // Add the number of newly visible lines to the count
                visibleCount += callGroup.children.length;

                // Add direct children to the end of the queue for breadth-first processing
                const directChildren = Array.from(callGroup.children)
                                          .filter(el => el.classList.contains('foldable'));
                queue.push(...directChildren);
            }
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

    // Initialize themes functionality (part of settings dialog now)
    initThemes(themeSelector) {
        if (!themeSelector) return;
        
        themeSelector.innerHTML = '';
        this.config.themes.forEach(theme => {
            const option = document.createElement('option');
            option.value = theme.value;
            option.textContent = theme.label;
            option.dataset.isDark = theme.isDark;
            themeSelector.appendChild(option);
        });
        
        themeSelector.addEventListener('change', () => {
            this.handleThemeChange(themeSelector);
        });
        
        // Set initial theme
        this.handleThemeChange(themeSelector);
    },

    // Handle theme changes
    handleThemeChange(themeSelector) {
        const selectedOption = themeSelector.options[themeSelector.selectedIndex];
        if (!selectedOption) return;

        const theme = selectedOption.value;
        const isDark = selectedOption.dataset.isDark === 'true';
        
        document.getElementById('prism-theme').href = `static/css/${theme}.min.css`;
        document.body.className = isDark ? 'dark-theme' : '';
        this.updateLineHighlights();
    },

    // Update line highlights based on current theme
    updateLineHighlights() {
        const isDark = document.body.classList.contains('dark-theme');
        document.querySelectorAll('.executed-line').forEach(el => {
            el.classList.remove('executed-line-light', 'executed-line-dark');
            el.classList.add(isDark ? 'executed-line-dark' : 'executed-line-light');
        });
        
        document.querySelectorAll('.current-line').forEach(el => {
            el.classList.remove('current-line-light', 'current-line-dark');
            el.classList.add(isDark ? 'current-line-dark' : 'current-line-light');
        });
    },

    initSummaryDropdown() {
        const { summaryBtn, summaryDropdown } = this.elements;
        if (!summaryBtn || !summaryDropdown) return;

        summaryBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            summaryDropdown.classList.toggle('show');
        });

        window.addEventListener('click', (e) => {
            if (!summaryBtn.contains(e.target) && !summaryDropdown.contains(e.target)) {
                summaryDropdown.classList.remove('show');
            }
        });
    },

    // NEW: Initialize Settings Dialog
    initSettingsDialog() {
        const { settingsBtn, settingsDialog } = this.elements;
        if (!settingsBtn || !settingsDialog) return;

        const closeBtn = settingsDialog.querySelector('.modal-close-btn');
        const tabLinks = settingsDialog.querySelectorAll('.tab-link');
        const tabContents = settingsDialog.querySelectorAll('.tab-content');
        const themeSelector = document.getElementById('themeSelector');
        
        // Init themes inside the dialog
        this.initThemes(themeSelector);

        settingsBtn.addEventListener('click', () => {
            settingsDialog.style.display = 'flex';
        });

        closeBtn.addEventListener('click', () => {
            settingsDialog.style.display = 'none';
        });
        
        settingsDialog.addEventListener('click', (e) => {
            if (e.target === settingsDialog) {
                settingsDialog.style.display = 'none';
            }
        });

        // Tab switching logic
        tabLinks.forEach(link => {
            link.addEventListener('click', () => {
                const tabId = link.dataset.tab;

                tabLinks.forEach(l => l.classList.remove('active'));
                tabContents.forEach(c => c.classList.remove('active'));

                link.classList.add('active');
                document.getElementById(tabId).classList.add('active');
            });
        });
    },

    // Initialize source dialog
    initSourceDialog() {
        const { sourceDialog, dialogCloseBtn } = this.elements;
        
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
                if (this.elements.sourceDialog) {
                    this.elements.sourceDialog.style.display = 'none';
                }
                if (this.elements.settingsDialog) {
                    this.elements.settingsDialog.style.display = 'none';
                }
            }
        });
    },

    _nodeToTextLines(node) {
        if (!node || node.nodeType !== Node.ELEMENT_NODE || !node.hasAttribute('data-indent')) {
            return [];
        }
    
        const clone = node.cloneNode(true);
    
        // Remove all UI-only elements
        clone.querySelectorAll('.view-source-btn, .copy-subtree-btn, .focus-subtree-btn, .toggle-details-btn, .explain-ai-btn, .expand-code-btn').forEach(el => el.remove());
    
        // Handle new debug vars UI
        let debugCommentText = '';
        const debugVarsEl = clone.querySelector('.debug-vars');
        if (debugVarsEl) {
            const vars = [];
            debugVarsEl.querySelectorAll('.list-view .var-entry').forEach(entry => {
                const name = entry.querySelector('.var-name')?.textContent?.trim() || '';
                const value = entry.querySelector('.var-value')?.innerText?.trim() || '';
                if (name && value) {
                    vars.push(`${name}=${value}`);
                }
            });
            if (vars.length > 0) {
                debugCommentText = ` # Debug: ${vars.join(', ')}`;
            }
            debugVarsEl.remove();
        }
    
        // Handle legacy comments
        clone.querySelectorAll('.comment').forEach(commentEl => {
            const fullTextEl = commentEl.querySelector('.comment-full');
            const content = (fullTextEl || commentEl).textContent.trim();
            commentEl.replaceWith(document.createTextNode(` # ${content}`));
        });
    
        let text;
        const multiLineContainer = clone.querySelector('.multi-line-container');
        if (multiLineContainer) {
            const prefixEl = multiLineContainer.querySelector('.multi-line-prefix');
            const codeEl = multiLineContainer.querySelector('.code-full code');
            const prefix = prefixEl ? prefixEl.textContent.replace(/[\s\u00A0]+/g, ' ').trim() : '';
            const code = codeEl ? codeEl.textContent : '';
            // Reconstruct the line without collapsing whitespace from the code part itself
            text = prefix + (prefix ? ' ' : '') + code;
        } else {
            // Use innerText to get a text representation that respects some whitespace,
            // then trim only the outer edges.
            text = clone.innerText ? clone.innerText.trim() : '';
        }
    
        const indent = parseInt(node.dataset.indent, 10) || 0;
        const indentation = ' '.repeat(indent);
    
        // Handle multi-line text from the source code itself
        const lines = text.split('\n').map(line => indentation + line);
        
        // Append debug comment to the last line
        if (lines.length > 0 && debugCommentText) {
            lines[lines.length - 1] += debugCommentText;
        }
    
        return lines;
    },

    // Initialize "Copy Subtree" functionality
    initCopySubtree() {
        this.elements.content.addEventListener('click', async (e) => {
            if (!e.target.classList.contains('copy-subtree-btn')) return;
            e.preventDefault();
            e.stopPropagation();
    
            const copyBtn = e.target;
            const foldable = copyBtn.closest('.foldable.call');
            if (!foldable) return;
    
            const callGroup = foldable.nextElementSibling;
            if (!callGroup || !callGroup.classList.contains('call-group')) return;
    
            let allLines = [];
    
            // Process the main foldable 'call' line itself
            allLines.push(...this._nodeToTextLines(foldable));
    
            // Process all descendant log lines within the call group
            const descendants = callGroup.querySelectorAll('div[data-indent]');
            descendants.forEach(node => {
                allLines.push(...this._nodeToTextLines(node));
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
                    allLines.push(...this._nodeToTextLines(nextElement));
                    break;
                }
                nextElement = nextElement.nextElementSibling;
            }
    
            const fullText = allLines.join('\n');
    
            try {
                await navigator.clipboard.writeText(fullText);
                const originalContent = copyBtn.textContent;
                copyBtn.textContent = TraceViewer.i18n.t('copiedText');
                setTimeout(() => { copyBtn.textContent = originalContent; }, 1500);
            } catch (err) {
                console.error('Failed to copy text: ', err);
                const originalContent = copyBtn.textContent;
                copyBtn.textContent = 'Error!';
                setTimeout(() => { copyBtn.textContent = originalContent; }, 1500);
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
            
            // Find and add the matching return or exception
            let nextElement = callGroup.nextElementSibling;
            while(nextElement) {
                if (nextElement.classList.contains('return') || nextElement.classList.contains('error')) {
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
            this.i18n.apply(); // Re-apply translations to update button text
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
                toggleBtn.title = TraceViewer.i18n.t('toggleDetailsHideTitle');
            } else {
                toggleBtn.textContent = '👁️';
                toggleBtn.title = TraceViewer.i18n.t('toggleDetailsTitle');
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
            
            // Raw response elements
            rawResponseToggleBtn: document.getElementById('llmRawResponseToggleBtn'),
            rawResponseContent: document.getElementById('llmRawResponseContent'),
            thinkingOutput: document.getElementById('llmThinkingOutput'),
            contentOutput: document.getElementById('llmContentOutput'),

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
                
                // Raw response toggle
                if (this.rawResponseToggleBtn) {
                    this.rawResponseToggleBtn.addEventListener('click', () => {
                        const isHidden = this.rawResponseContent.style.display === 'none';
                        this.rawResponseContent.style.display = isHidden ? 'flex' : 'none';
                        this.rawResponseToggleBtn.textContent = isHidden ? TraceViewer.i18n.t('aiHideBtn') : TraceViewer.i18n.t('aiShowBtn');
                    });
                }
                
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
                this.status.textContent = TraceViewer.i18n.t('aiStatusReady');
                
                // Reset raw response viewer
                this.thinkingOutput.textContent = '';
                this.contentOutput.textContent = '';
                this.rawResponseContent.style.display = 'none';
                this.rawResponseToggleBtn.textContent = TraceViewer.i18n.t('aiShowBtn');

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

                if (!baseUrl || !model) {
                    alert(TraceViewer.i18n.t('aiApiUrlAlert'));
                    return;
                }

                // Reset previous explanations and raw outputs
                this.body.querySelectorAll('.ai-explanation').forEach(el => {
                    el.textContent = '';
                    el.style.display = 'none';
                });
                this.thinkingOutput.textContent = '';
                this.contentOutput.textContent = '';


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

                this.abortController = new AbortController();
                this.status.textContent = TraceViewer.i18n.t('aiStatusSending');
                this.startBtn.disabled = true;

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
                                
                                if (ssePayload.event === "thinking") {
                                    if (typeof ssePayload.data === 'string') {
                                        this.thinkingOutput.textContent += ssePayload.data;
                                        this.thinkingOutput.scrollTop = this.thinkingOutput.scrollHeight;
                                    }
                                } else if (ssePayload.event === "content" || ssePayload.event === "thinking") {
                                    if (typeof ssePayload.data === 'string') {
                                        receivedChars += ssePayload.data.length;
                                        this.status.textContent = `${TraceViewer.i18n.t('aiStatusReceiving')} (${receivedChars} chars)`;
                                    }
                                    
                                    if (ssePayload.event === "content" && typeof ssePayload.data === 'string') {
                                        this.contentOutput.textContent += ssePayload.data;
                                        this.contentOutput.scrollTop = this.contentOutput.scrollHeight;
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
                                    this.status.textContent = `${TraceViewer.i18n.t('aiStatusFinished')} (Total ${receivedChars} chars)`;
                                }
                            } catch (e) {
                                console.warn('Failed to parse SSE line envelope:', sseLine, e);
                            }
                        }
                    }

                } catch (error) {
                    if (error.name === 'AbortError') {
                        console.log('Fetch aborted by user.');
                        // UI state is reset by hide()
                    } else {
                        this.status.textContent = `${TraceViewer.i18n.t('errorMessagePrefix')}${error.message}`;
                        console.error('AI Explanation failed:', error);
                    }
                } finally {
                    this.startBtn.disabled = false;
                    this.abortController = null;
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

    // Intercept native copy events for better text representation
    initClipboardInterceptor() {
        document.addEventListener('copy', (event) => {
            const selection = document.getSelection();
            if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
                return;
            }
    
            const contentEl = this.elements.content;
            const range = selection.getRangeAt(0);
            if (!contentEl || !contentEl.contains(range.commonAncestorContainer)) {
                return; // Selection is outside our scope
            }
    
            const plainText = this.extractTextFromSelection(selection);
            event.clipboardData.setData('text/plain', plainText);
            event.preventDefault();
        });
    },
    
    // Helper to generate clean text from a selection fragment
    extractTextFromSelection(selection) {
        const range = selection.getRangeAt(0);
        const ancestor = range.commonAncestorContainer;
    
        // Find all log entry elements within the common ancestor
        const allDivs = (ancestor && ancestor.nodeType === Node.ELEMENT_NODE ? ancestor : ancestor?.parentElement)?.querySelectorAll('div[data-indent]') || [];
        
        // Filter for divs that are actually within the selection range
        const selectedDivs = Array.from(allDivs).filter(div => 
            (selection && selection.containsNode ? selection.containsNode(div, true) : false) || 
            (range && range.intersectsNode ? range.intersectsNode(div) : false)
        );
    
        if (selectedDivs.length === 0) {
            // Fallback for simple text selection inside a single line
            return selection.toString();
        }

        const allLines = selectedDivs.flatMap(div => this._nodeToTextLines(div));
        return allLines.join('\n');
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

    // Initialize comment toggle functionality (for legacy comments on call/return)
    initCommentToggle() {
        const content = this.elements.content;
        
        content.addEventListener('click', e => {
            const commentElement = e.target.closest('.comment');
            if (!commentElement) return;
            
            e.stopPropagation();
            e.preventDefault();
            
            commentElement.classList.toggle('expanded');
            
            if (commentElement.classList.contains('expanded')) {
                setTimeout(() => {
                    commentElement.scrollIntoView({behavior: 'smooth', block: 'nearest'});
                }, 10);
            }
        });
    },

    // Initialize new debug vars UI toggle functionality
    initDebugVarsToggle() {
        this.elements.content.addEventListener('click', e => {
            const debugVars = e.target.closest('.debug-vars');
            if (debugVars) {
                e.stopPropagation();
                debugVars.classList.toggle('expanded');
            }
        });
    },

    // Initialize multi-line statement toggle functionality
    initMultiLineToggle() {
        this.elements.content.addEventListener('click', e => {
            const toggleBtn = e.target.closest('.expand-code-btn');
            if (!toggleBtn) return;
    
            e.stopPropagation();
            const container = toggleBtn.closest('.multi-line-container');
            if (!container) return;
    
            container.classList.toggle('expanded');
            const isExpanded = container.classList.contains('expanded');
            toggleBtn.textContent = isExpanded ? '[-]' : '[+]';

            if (isExpanded) {
                // If Prism is available, highlight the full code block
                const codeBlock = container.querySelector('.code-full pre code');
                if (codeBlock && typeof Prism !== 'undefined') {
                    Prism.highlightElement(codeBlock);
                }
            }
        });
    },

    // Internationalization (i18n) Module
    i18n: {
        currentLang: 'en',
        translations: {},

        init() {
            // Load translations from the global window object injected by Python
            this.translations = window.translations || {};
            
            // The initial language is set by the `lang` attribute on the <html> tag
            this.currentLang = document.documentElement.lang || 'en';

            const langSelector = document.getElementById('languageSelector');
            if (langSelector) {
                langSelector.value = this.currentLang;
                langSelector.addEventListener('change', (e) => this.setLang(e.target.value));
            }
            // NO initial apply() call, to prevent flashing. The HTML is pre-rendered.
        },

        setLang(lang) {
            this.currentLang = lang;
            localStorage.setItem('traceViewerLang', lang);
            document.documentElement.lang = lang;
            this.apply();
        },

        apply() {
            document.querySelectorAll('[data-i18n]').forEach(el => {
                const key = el.dataset.i18n;
                const translation = this.translations[key]?.[this.currentLang];
                if (translation) {
                    // Special handling for the skeleton view button text
                    if (key === 'skeletonView' && document.body.classList.contains('skeleton-mode')) {
                        el.innerHTML = this.translations['skeletonViewActive'][this.currentLang] || translation;
                    } else {
                        el.innerHTML = translation;
                    }
                }
            });
            document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
                const key = el.dataset.i18nPlaceholder;
                const translation = this.translations[key]?.[this.currentLang];
                if (translation) el.placeholder = translation;
            });
            document.querySelectorAll('[data-i18n-title]').forEach(el => {
                const key = el.dataset.i18nTitle;
                const translation = this.translations[key]?.[this.currentLang];
                if (translation) el.title = translation;
            });
            
            // Translate dynamic content that might have been generated by Python
            this.translateDynamicContent();
        },

        t(key, params = {}) {
            let translation = this.translations[key]?.[this.currentLang] || key;
            Object.entries(params).forEach(([param, value]) => {
                translation = translation.replace(`{${param}}`, value);
            });
            return translation;
        },
        
        translateDynamicContent() {
            const errorElements = document.querySelectorAll('.error, .exception');
            errorElements.forEach(element => {
                if (!element.dataset.originalContent) {
                    element.dataset.originalContent = element.textContent;
                }
                const originalText = element.dataset.originalContent;

                const sizeMatch = originalText.match(/⚠ HTML报告大小已超过(\d+\.?\d*)MB限制，后续内容将被忽略/);
                if (sizeMatch) {
                    const sizeLimitMb = sizeMatch[1];
                    element.textContent = this.t('htmlSizeExceeded', {size_limit_mb: sizeLimitMb});
                    return;
                }
            });
        }
    },

    // Source code viewer functionality
    sourceViewer: {
        getFrameLines(filename, frameId) {
            if (!window.executedLines || !window.executedLines[filename] || !window.executedLines[filename][frameId]) {
                return null;
            }
            const rawLines = window.executedLines[filename][frameId];
            const lines = rawLines.map(pair => Array.isArray(pair) ? pair[0] : pair);
            return {
                min: Math.min(...lines),
                max: Math.max(...lines),
                all: [...new Set(lines)]
            };
        },

        createDebugVarsElementForSourceView(variables) {
            if (!variables || Object.keys(variables).length === 0) return null;
        
            const container = document.createElement('div');
            container.className = 'debug-vars';
            container.title = TraceViewer.i18n.t('debugVarsTitle');
            container.addEventListener('click', e => {
                e.stopPropagation();
                container.classList.toggle('expanded');
            });
        
            const compactView = document.createElement('div');
            compactView.className = 'compact-view';
            const compactItems = [];
            for (const [name, value] of Object.entries(variables)) {
                const escapedName = TraceViewer.utils.escapeHTML(name);
                const escapedValue = TraceViewer.utils.escapeHTML(value);
                compactItems.push(`<span class="var-name">${escapedName}</span>=<span class="var-value">${escapedValue}</span>`);
            }
            compactView.innerHTML = compactItems.join(' ');
            container.appendChild(compactView);
        
            const listView = document.createElement('div');
            listView.className = 'list-view';
            const listItems = [];
            for (const [name, value] of Object.entries(variables)) {
                const escapedName = TraceViewer.utils.escapeHTML(name);
                const escapedValue = TraceViewer.utils.escapeHTML(value);
                listItems.push(`<div class="var-entry"><span class="var-name">${escapedName}</span>: <span class="var-value"><pre>${escapedValue}</pre></span></div>`);
            }
            listView.innerHTML = listItems.join('');
            container.appendChild(listView);
        
            return container;
        },

        showSource(filename, lineNumber, frameId) {
            const sourceContent = document.getElementById('sourceContent');
            const titleDiv = document.getElementById('sourceTitle');
            const dialog = document.getElementById('sourceDialog');

            if (!window.sourceFiles || !window.sourceFiles[filename]) {
                titleDiv.textContent = `${filename} (${TraceViewer.i18n.t('sourceNotAvailable')})`;
                sourceContent.innerHTML = `<div>${TraceViewer.i18n.t('sourceNotAvailable')}</div>`;
                dialog.style.display = 'flex';
                return;
            }
            let originalText = window.sourceFiles[filename];
            const raw = atob(originalText);
            const bytes = new Uint8Array(raw.length);
            for (let i = 0; i < raw.length; i++) {
                bytes[i] = raw.charCodeAt(i);
            }
            let text = new TextDecoder('utf-8').decode(bytes);

            const frameLines = this.getFrameLines(filename, frameId);
            const lines = text.split('\n');
            if (frameLines) {
                frameLines.all.forEach(lineNum => {
                    const lineIdx = lineNum - 1;
                    if (lineIdx < lines.length) {
                        const key = `${frameId}-${filename}-${lineNum}`;
                        const commentData = window.lineComment[key];
                        if (commentData) {
                            try {
                                const jsonData = JSON.stringify(commentData);
                                const encodedData = btoa(unescape(encodeURIComponent(jsonData)));
                                lines[lineIdx] += ` # __CTX_DEBUG_PLACEHOLDER__${encodedData}`;
                            } catch (e) {
                                console.error(`Failed to encode debug data for line ${lineNum}:`, e);
                            }
                        }
                    }
                });
                text = lines.join('\n');
            }

            this.setupSourceDialog(dialog, titleDiv, sourceContent, filename, lineNumber);
            const container = this.createSourceContainer(lines, text);
            sourceContent.appendChild(container);
            this.addDialogCloseControls(dialog);
            
            setTimeout(() => {
                this.processSourceCode(
                    container.querySelector('.line-numbers'),
                    container.querySelector('code'),
                    frameLines,
                    lineNumber,
                    frameId,
                    filename,
                    dialog
                );
            }, 10);
        },
        
        setupSourceDialog(dialog, titleDiv, sourceContent, filename, lineNumber) {
            titleDiv.textContent = `${filename} (Line ${lineNumber})`;
            sourceContent.innerHTML = '';
            const existingCloseBtn = dialog.querySelector('.floating-close-btn');
            if (existingCloseBtn) dialog.removeChild(existingCloseBtn);
            const existingOverlay = dialog.querySelector('.close-overlay');
            if (existingOverlay) dialog.removeChild(existingOverlay);
        },
        
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
        
        addDialogCloseControls(dialog) {
            const closeBtn = document.createElement('div');
            closeBtn.className = 'floating-close-btn';
            closeBtn.innerHTML = '&times;';
            closeBtn.title = TraceViewer.i18n.t('closeEsc');
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
        
        processSourceCode(lineNumbers, code, frameLines, lineNumber, frameId, filename, dialog) {
            const loadingIndicator = document.createElement('div');
            loadingIndicator.style.position = 'absolute';
            loadingIndicator.style.top = '50%';
            loadingIndicator.style.left = '50%';
            loadingIndicator.style.transform = 'translate(-50%, -50%)';
            loadingIndicator.style.padding = '10px';
            loadingIndicator.style.background = 'rgba(0,0,0,0.7)';
            loadingIndicator.style.color = 'white';
            loadingIndicator.style.borderRadius = '4px';
            loadingIndicator.textContent = TraceViewer.i18n.t('loadingSyntax');
            lineNumbers.parentElement.appendChild(loadingIndicator);

            const doHighlight = () => {
                Prism.highlightElement(code);
                const codeLines = code.querySelectorAll('.token-line, .line');
                if (!codeLines || codeLines.length === 0) {
                    this.synchronizeLineHeights(lineNumbers, code.parentElement);
                } else {
                    this.synchronizeWithPrismLines(lineNumbers, codeLines);
                }

                const placeholderPrefix = '# __CTX_DEBUG_PLACEHOLDER__';
                const comments = code.querySelectorAll('.token.comment');
                comments.forEach(comment => {
                    const text = comment.textContent || '';
                    if (text.startsWith(placeholderPrefix)) {
                        const encodedData = text.substring(placeholderPrefix.length);
                        try {
                            const jsonData = decodeURIComponent(escape(atob(encodedData)));
                            const data = JSON.parse(jsonData);
                            const debugEl = this.createDebugVarsElementForSourceView(data);
                            if (debugEl && comment.parentNode) {
                                comment.parentNode.replaceChild(debugEl, comment);
                            }
                        } catch (e) {
                            console.error('Failed to decode or render debug placeholder:', e);
                            comment.style.display = 'none';
                        }
                    }
                });

                if (frameLines) {
                    frameLines.all.forEach(line => {
                        const lineElement = lineNumbers.querySelector(`.line-number[data-line="${line}"]`);
                        if (lineElement) lineElement.classList.add('executed-line');
                    });
                }
                
                loadingIndicator.remove();
                dialog.style.display = 'flex';

                const targetLine = lineNumbers.querySelector(`.line-number[data-line="${lineNumber}"]`);
                if (targetLine) {
                    targetLine.classList.add('current-line');
                    setTimeout(() => {
                        targetLine.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    }, 0);
                }
            };
            
            if (typeof Prism !== 'undefined') {
                doHighlight();
            } else {
                const prismCheckInterval = setInterval(() => {
                    if (typeof Prism !== 'undefined') {
                        clearInterval(prismCheckInterval);
                        doHighlight();
                    }
                }, 100);
            }
        },
        
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

        synchronizeWithPrismLines(lineNumbersContainer, codeLines) {
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
            TraceViewer.adjustLineNumberStyles(isDark);
        }
    }
};

document.addEventListener('DOMContentLoaded', () => {
    TraceViewer.init();
    if (window.eventMetadata) {
        TraceViewer.searchDatabase = new SearchDatabase();
        TraceViewer.searchDatabase.initializeFromMetadata();
    }
});

TraceViewer.initSidebar = function() {
    const { toggleSidebar, sidebar, sidebarOverlay } = this.elements;
    if (toggleSidebar) {
        toggleSidebar.addEventListener('click', () => {
            sidebar.classList.toggle('open');
            sidebarOverlay.classList.toggle('show');
        });
    }
    if (sidebarOverlay) {
        sidebarOverlay.addEventListener('click', () => {
            sidebar.classList.remove('open');
            sidebarOverlay.classList.remove('show');
        });
    }
};

TraceViewer.initFilters = function() {
    const { filterCall, filterReturn, filterLine, filterException } = this.elements;
    const filters = { call: filterCall, return: filterReturn, line: filterLine, exception: filterException };
    Object.values(filters).forEach(filter => {
        if (filter) filter.addEventListener('change', () => this.applyFilters());
    });
    this.applyFilters();
};

TraceViewer.applyFilters = function() {
    const { filterCall, filterReturn, filterLine, filterException, content } = this.elements;
    const filterStates = {
        call: filterCall ? filterCall.checked : true,
        return: filterReturn ? filterReturn.checked : true,
        line: filterLine ? filterLine.checked : true,
        exception: filterException ? filterException.checked : true
    };
    const elements = content.querySelectorAll('div[class*="call"], div[class*="return"], div[class*="line"], div[class*="error"]');
    elements.forEach(el => {
        let show = true;
        if (el.classList.contains('call') && !filterStates.call) show = false;
        else if (el.classList.contains('return') && !filterStates.return) show = false;
        else if (el.classList.contains('line') && !filterStates.line) show = false;
        else if ((el.classList.contains('error') || el.classList.contains('exception')) && !filterStates.exception) show = false;
        el.style.display = show ? '' : 'none';
    });
    const callGroups = content.querySelectorAll('.call-group');
    callGroups.forEach(group => {
        group.style.display = Array.from(group.children).some(child => child.style.display !== 'none') ? '' : 'none';
    });
};

function showSource(filename, lineNumber, frameId) {
    TraceViewer.sourceViewer.showSource(filename, lineNumber, frameId);
}
function getFrameLines(filename, frameId) {
    return TraceViewer.sourceViewer.getFrameLines(filename, frameId);
}
function toggleCommentExpand(commentId, event) {
    if (event) {
        event.stopPropagation();
        event.preventDefault();
    }
    const commentEl = document.getElementById(commentId);
    if (commentEl) {
        commentEl.classList.toggle('expanded');
        if (commentEl.classList.contains('expanded')) {
            setTimeout(() => {
                commentEl.scrollIntoView({behavior: 'smooth', block: 'nearest'});
            }, 10);
        }
    }
}
TraceViewer.SearchModal = SearchModal;
TraceViewer.SearchDatabase = SearchDatabase;

// ===== Navigation Bar Functionality (Refactored for Performance with Web Worker) =====

TraceViewer._updateNavIndicators = function(navViewport, navPosition, content, navigationBar) {
    const contentHeight = content.scrollHeight;
    const viewportHeight = content.clientHeight;
    const scrollTop = content.scrollTop;

    if (contentHeight <= viewportHeight + 2) {
        navViewport.style.display = 'none';
        navPosition.style.display = 'none';
        return;
    }
    
    navViewport.style.display = 'block';
    navPosition.style.display = 'block';
    
    const navHeight = navigationBar.getBoundingClientRect().height;
    if (navHeight === 0) return;

    const viewportRatio = viewportHeight / contentHeight;
    const scrollRatio = scrollTop / contentHeight;
    
    const viewportTop = scrollRatio * navHeight;
    const viewportHeightPx = viewportRatio * navHeight;
    
    navViewport.style.top = viewportTop + 'px';
    navViewport.style.height = Math.max(viewportHeightPx, 8) + 'px';
    
    navPosition.style.top = viewportTop + 'px';
};

TraceViewer._redrawNavThumbnail = function(canvas, content, navigationBar) {
    if (!this.navWorker) return; // Worker not initialized

    const navHeight = navigationBar.getBoundingClientRect().height;
    if (navHeight === 0) return;

    const contentHeight = content.scrollHeight;
    const isDark = document.body.classList.contains('dark-theme');
    
    // This part still runs on the main thread, but it's just data collection.
    const elementsData = [];
    const elements = content.querySelectorAll('.foldable, .line, .return, .error');
    const sampleCount = Math.min(elements.length, 500); // Increased sample count for better fidelity
    const contentRect = content.getBoundingClientRect();

    for (let i = 0; i < sampleCount; i++) {
        const index = Math.floor(i * elements.length / sampleCount);
        const element = elements[index];
        const rect = element.getBoundingClientRect();
        
        let type = 'line'; // default
        if (element.classList.contains('call')) type = 'call';
        else if (element.classList.contains('return')) type = 'return';
        else if (element.classList.contains('error')) type = 'error';

        elementsData.push({
            type: type,
            top: rect.top - contentRect.top + content.scrollTop,
            height: rect.height
        });
    }

    // Post data to the worker for rendering
    this.navWorker.postMessage({
        type: 'render',
        canvasWidth: canvas.width,
        canvasHeight: canvas.height,
        navHeight: navHeight,
        contentHeight: contentHeight,
        isDark: isDark,
        elements: elementsData
    });
};

TraceViewer.initNavigationBar = function() {
    const navigationBar = document.getElementById('navigationBar');
    const navThumbnail = document.getElementById('navThumbnail');
    const navViewport = document.getElementById('navViewport');
    const navPosition = document.getElementById('navPosition');
    const content = this.elements.content;

    if (!navigationBar || !content) return;

    const canvas = document.createElement('canvas');
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    navThumbnail.appendChild(canvas);
    const ctx = canvas.getContext('2d');

    // Initialize Web Worker for background rendering
    try {
        const workerScriptElement = document.getElementById('nav-worker-script');
        if (!workerScriptElement || !workerScriptElement.textContent.trim()) {
            throw new Error("Worker script element not found or is empty.");
        }
        const workerScriptContent = workerScriptElement.textContent;
        const blob = new Blob([workerScriptContent], { type: 'application/javascript' });
        const workerUrl = URL.createObjectURL(blob);
        this.navWorker = new Worker(workerUrl);

        this.navWorker.onmessage = (event) => {
            if (event.data.type === 'rendered' && event.data.imageBitmap) {
                const bitmap = event.data.imageBitmap;
                // Ensure canvas is still valid before drawing
                if (canvas && canvas.parentElement) {
                    ctx.clearRect(0, 0, canvas.width, canvas.height);
                    ctx.drawImage(bitmap, 0, 0);
                }
                bitmap.close(); // Release memory
            }
        };
    } catch (e) {
        console.error("Failed to create navigation bar worker. Thumbnail will not be rendered.", e);
        navigationBar.style.display = 'none';
        return;
    }

    // Fast, non-debounced function for smooth scroll feedback
    const updateIndicators = () => {
        this._updateNavIndicators(navViewport, navPosition, content, navigationBar);
    };

    // Debounced function for triggering an asynchronous redraw
    const debouncedRedraw = this.utils.debounce(() => {
        this._redrawNavThumbnail(canvas, content, navigationBar);
    }, 250);

    // Initial setup
    this.setupCanvasSize(canvas);
    setTimeout(() => {
        debouncedRedraw();
        updateIndicators();
    }, 100);

    // --- Event Listeners ---
    content.addEventListener('scroll', updateIndicators);
    navigationBar.addEventListener('click', (e) => this.handleNavigationClick(e, content));

    // Drag-to-scroll functionality
    let isDragging = false, startY, startScrollTop;
    const onMouseDown = (e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        e.stopPropagation();
        isDragging = true;
        startY = e.clientY;
        startScrollTop = content.scrollTop;
        document.body.style.cursor = 'grabbing';
        document.body.style.userSelect = 'none';
        navViewport.style.transition = 'none';
        navPosition.style.transition = 'none';
        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
    };
    const onMouseMove = (e) => {
        if (!isDragging) return;
        const deltaY = e.clientY - startY;
        const navHeight = navigationBar.clientHeight;
        const contentHeight = content.scrollHeight;
        if (navHeight > 0) {
            content.scrollTop = startScrollTop + (deltaY * (contentHeight / navHeight));
        }
    };
    const onMouseUp = () => {
        if (!isDragging) return;
        isDragging = false;
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        navViewport.style.transition = '';
        navPosition.style.transition = '';
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
    };
    navViewport.addEventListener('mousedown', onMouseDown);

    window.addEventListener('resize', () => {
        this.setupCanvasSize(canvas);
        debouncedRedraw();
        updateIndicators();
    });

    // Observe content changes to trigger redraw
    let lastScrollHeight = content.scrollHeight;
    const observer = new MutationObserver(this.utils.debounce(() => {
        if (content.scrollHeight !== lastScrollHeight) {
            lastScrollHeight = content.scrollHeight;
            debouncedRedraw();
            updateIndicators();
        }
    }, 100));
    observer.observe(content, { childList: true, subtree: true, attributes: true, attributeFilter: ['style', 'class'] });
    
    // Explicit redraw on user interactions that change content height
    content.addEventListener('click', (e) => {
        if (e.target.classList.contains('foldable') || e.target.classList.contains('expand-code-btn')) {
            setTimeout(debouncedRedraw, 300); // Delay to allow for animations
        }
    });
};

TraceViewer.setupCanvasSize = function(canvas) {
    if (!canvas.parentElement) {
        setTimeout(() => this.setupCanvasSize(canvas), 100);
        return;
    }
    const rect = canvas.parentElement.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) {
        setTimeout(() => this.setupCanvasSize(canvas), 100);
        return;
    }
    
    // Set canvas pixel dimensions for high-DPI displays
    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
};

TraceViewer.handleNavigationClick = function(e, content) {
    if (e.target.id === 'navViewport' || e.target.id === 'navPosition') {
        return;
    }
    const rect = e.currentTarget.getBoundingClientRect();
    const clickY = e.clientY - rect.top;
    const navHeight = rect.height;
    if (navHeight === 0) return;
    const contentHeight = content.scrollHeight;
    const viewportHeight = content.clientHeight;
    const targetScroll = (clickY / navHeight) * contentHeight;

    content.scrollTo({
        top: Math.max(0, Math.min(targetScroll - (viewportHeight / 2), contentHeight - viewportHeight)),
        behavior: 'smooth'
    });
};

// Override original init to add the navigation bar initialization
const originalInit = TraceViewer.init;
TraceViewer.init = function(...args) {
    originalInit.apply(this, args);
    // Delay initialization to ensure layout is stable
    setTimeout(() => this.initNavigationBar(), 100);
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = TraceViewer;
    global.TraceViewer = TraceViewer;
    global.SearchDatabase = SearchDatabase;
    global.SearchModal = SearchModal;
    global.showSource = showSource;
    global.getFrameLines = getFrameLines;
    global.toggleCommentExpand = toggleCommentExpand;
}