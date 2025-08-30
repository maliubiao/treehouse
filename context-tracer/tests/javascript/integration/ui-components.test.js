const { createMockDom, mockTraceData } = require('../__fixtures__/test-data');

// Mock the global TraceViewer object before importing the script
const originalTraceViewer = global.TraceViewer;

beforeAll(() => {
  // Load the actual script
  require('../../../src/context_tracer/static/js/tracer_scripts.js');
});

afterAll(() => {
  global.TraceViewer = originalTraceViewer;
});

describe('UI Components Integration', () => {
  let mockElements;
  
  beforeEach(() => {
    mockElements = createMockDom();
    
    // Set up global data
    global.window.executedLines = mockTraceData.executedLines;
    global.window.sourceFiles = mockTraceData.sourceFiles;
    global.window.commentsData = mockTraceData.commentsData;
    global.window.lineComment = mockTraceData.lineComment;
    
    // Initialize TraceViewer with mock elements
    global.TraceViewer.elements = {
      content: mockElements.content,
      search: mockElements.search,
      expandAllBtn: mockElements.expandAllBtn,
      collapseAllBtn: mockElements.collapseAllBtn,
      skeletonViewBtn: mockElements.skeletonViewBtn,
      exportBtn: mockElements.exportBtn,
      sourceDialog: mockElements.sourceDialog,
      dialogCloseBtn: mockElements.dialogCloseBtn,
      settingsDialog: mockElements.settingsDialog,
      themeSelector: mockElements.themeSelector,
      settingsBtn: document.createElement('button'), // Add settings button
      sidebar: document.createElement('div'),
      sidebarOverlay: document.createElement('div'),
      toggleSidebar: document.createElement('button'),
      filterCall: document.createElement('input'),
      filterReturn: document.createElement('input'),
      filterLine: document.createElement('input'),
      filterException: document.createElement('input')
    };
    
    // Initialize components
    global.TraceViewer.calculateSubtreeSizes();
  });

  afterEach(() => {
    // Clean up DOM
    document.body.innerHTML = '';
    jest.clearAllMocks();
  });

  describe('Source Viewer', () => {
    test('should show source dialog with executed lines', () => {
      // Use fake timers to handle setTimeout
      jest.useFakeTimers();
      
      // Call showSource function
      global.showSource('/path/to/file.py', 10, 1);
      
      // Advance timers to execute setTimeout
      jest.advanceTimersByTime(20);
      
      // Mock Prism to be available
      global.Prism = {
        highlightElement: jest.fn()
      };
      
      // Advance timers again to process source code
      jest.advanceTimersByTime(20);
      
      expect(mockElements.sourceDialog.style.display).toBe('flex');
      
      // Check elements inside the source dialog
      const sourceTitle = document.getElementById('sourceTitle');
      const sourceContent = document.getElementById('sourceContent');
      
      expect(sourceTitle.textContent).toContain('/path/to/file.py');
      expect(sourceTitle.textContent).toContain('10');
      
      // Restore real timers
      jest.useRealTimers();
    });

    test('should handle missing source files gracefully', () => {
      // Remove the source file from mock data
      delete global.window.sourceFiles['/path/to/file.py'];
      
      global.showSource('/path/to/file.py', 10, 1);
      
      // Check elements inside the source dialog
      const sourceTitle = document.getElementById('sourceTitle');
      const sourceContent = document.getElementById('sourceContent');
      
      expect(sourceTitle.textContent).toContain('/path/to/file.py');
      expect(sourceContent.textContent).toContain('Source not available');
    });
  });

  describe('Settings Dialog', () => {
    test('should open and close settings dialog', () => {
      const settingsBtn = document.createElement('button');
      settingsBtn.id = 'settingsBtn';
      document.body.appendChild(settingsBtn);
      
      global.TraceViewer.elements.settingsBtn = settingsBtn;
      
      // Initialize settings dialog
      global.TraceViewer.initSettingsDialog();
      
      // Open dialog
      settingsBtn.click();
      expect(mockElements.settingsDialog.style.display).toBe('flex');
      
      // Close dialog
      const closeBtn = mockElements.settingsDialog.querySelector('.modal-close-btn');
      closeBtn.click();
      expect(mockElements.settingsDialog.style.display).toBe('none');
      
      // Close via overlay click
      settingsBtn.click();
      mockElements.settingsDialog.click(); // Simulate overlay click
      expect(mockElements.settingsDialog.style.display).toBe('none');
    });

    test('should handle tab switching in settings', () => {
      global.TraceViewer.initSettingsDialog();
      
      // Get tab elements directly from the settings dialog
      const tabLinks = mockElements.settingsDialog.querySelectorAll('.tab-link');
      const tabContents = mockElements.settingsDialog.querySelectorAll('.tab-content');
      
      // Find the help tab (should be the second tab link)
      const helpTab = tabLinks[1];
      const displayTab = tabLinks[0];
      const helpContent = document.getElementById('tab-help');
      const displayContent = document.getElementById('tab-display');
      
      console.log('Tab links found:', tabLinks.length);
      console.log('Help tab classes before click:', helpTab.classList.toString());
      console.log('Display tab classes before click:', displayTab.classList.toString());
      
      // Switch to help tab
      helpTab.click();
      
      console.log('After click - Help tab classes:', helpTab.classList.toString());
      console.log('After click - Display tab classes:', displayTab.classList.toString());
      console.log('After click - Help content classes:', helpContent.classList.toString());
      console.log('After click - Display content classes:', displayContent.classList.toString());
      
      expect(helpTab.classList.contains('active')).toBe(true);
      expect(displayTab.classList.contains('active')).toBe(false);
      expect(helpContent.classList.contains('active')).toBe(true);
      expect(displayContent.classList.contains('active')).toBe(false);
    });
  });

  describe('Sidebar and Filters', () => {
    test('should toggle sidebar visibility', () => {
      global.TraceViewer.initSidebar();
      
      // Initially closed
      expect(global.TraceViewer.elements.sidebar.classList.contains('open')).toBe(false);
      expect(global.TraceViewer.elements.sidebarOverlay.classList.contains('show')).toBe(false);
      
      // Open sidebar
      global.TraceViewer.elements.toggleSidebar.click();
      expect(global.TraceViewer.elements.sidebar.classList.contains('open')).toBe(true);
      expect(global.TraceViewer.elements.sidebarOverlay.classList.contains('show')).toBe(true);
      
      // Close sidebar via overlay
      global.TraceViewer.elements.sidebarOverlay.click();
      expect(global.TraceViewer.elements.sidebar.classList.contains('open')).toBe(false);
      expect(global.TraceViewer.elements.sidebarOverlay.classList.contains('show')).toBe(false);
    });

    test('should apply content filters', () => {
      // Initialize filters but don't apply them yet
      const { filterCall, filterReturn, filterLine, filterException } = global.TraceViewer.elements;
      const filters = {
        call: filterCall,
        return: filterReturn,
        line: filterLine,
        exception: filterException
      };
      
      // Add change event listeners to all filters
      Object.values(filters).forEach(filter => {
        if (filter) {
          filter.addEventListener('change', () => global.TraceViewer.applyFilters());
        }
      });
      
      // Initially all elements should be visible
      const initialVisible = mockElements.content.querySelectorAll('div:not([style*="display: none"])').length;
      expect(initialVisible).toBeGreaterThan(0);
      
      // Filter out calls
      global.TraceViewer.elements.filterCall.checked = false;
      global.TraceViewer.elements.filterCall.dispatchEvent(new Event('change'));
      
      const afterFilter = mockElements.content.querySelectorAll('div:not([style*="display: none"])').length;
      expect(afterFilter).toBeLessThan(initialVisible);
      
      // Check that call groups are also hidden
      const callGroups = mockElements.content.querySelectorAll('.call-group:not([style*="display: none"])');
      expect(callGroups.length).toBe(0);
    });
  });

  describe('Skeleton View', () => {
    test('should toggle skeleton mode', () => {
      global.TraceViewer.initSkeletonView();
      
      // Initially not in skeleton mode
      expect(document.body.classList.contains('skeleton-mode')).toBe(false);
      
      // Enable skeleton mode
      mockElements.skeletonViewBtn.click();
      expect(document.body.classList.contains('skeleton-mode')).toBe(true);
      
      // Disable skeleton mode
      mockElements.skeletonViewBtn.click();
      expect(document.body.classList.contains('skeleton-mode')).toBe(false);
    });

    test('should handle local detail toggling in skeleton mode', () => {
      global.TraceViewer.initToggleDetails();
      
      const toggleBtn = mockElements.content.querySelector('.toggle-details-btn');
      const callGroup = mockElements.content.querySelector('.call-group');
      
      // Initially not showing details
      expect(callGroup.classList.contains('show-details')).toBe(false);
      
      // Show details
      toggleBtn.click();
      expect(callGroup.classList.contains('show-details')).toBe(true);
      
      // Hide details
      toggleBtn.click();
      expect(callGroup.classList.contains('show-details')).toBe(false);
    });
  });

  describe('Focus Subtree', () => {
    test('should focus on subtree in new window', () => {
      global.TraceViewer.initFocusSubtree();
      
      const focusBtn = mockElements.content.querySelector('.focus-subtree-btn');
      const originalOpen = window.open;
      const mockWindow = { document: { write: jest.fn(), close: jest.fn() } };
      window.open = jest.fn().mockReturnValue(mockWindow);
      
      focusBtn.click();
      
      expect(window.open).toHaveBeenCalled();
      expect(mockWindow.document.write).toHaveBeenCalled();
      expect(mockWindow.document.write.mock.calls[0][0]).toContain('test_function');
      
      window.open = originalOpen;
    });
  });

  describe('Keyboard Shortcuts', () => {
    test('should handle escape key for closing dialogs', () => {
      global.TraceViewer.initKeyboardShortcuts();
      
      // Open dialogs
      mockElements.sourceDialog.style.display = 'flex';
      mockElements.settingsDialog.style.display = 'flex';
      
      // Press escape
      const escapeEvent = new KeyboardEvent('keydown', { key: 'Escape' });
      document.dispatchEvent(escapeEvent);
      
      expect(mockElements.sourceDialog.style.display).toBe('none');
      expect(mockElements.settingsDialog.style.display).toBe('none');
    });
  });
});