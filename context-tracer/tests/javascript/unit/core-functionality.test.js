const { createMockDom, mockTraceData } = require('../__fixtures__/test-data');

// Mock the global TraceViewer object before importing the script
const originalTraceViewer = global.TraceViewer;

beforeAll(() => {
  // Load the actual script
  require('../../../src/context_tracer/tracer_scripts.js');
});

afterAll(() => {
  global.TraceViewer = originalTraceViewer;
});

describe('Core Functionality', () => {
  let mockElements;
  
  beforeEach(() => {
    mockElements = createMockDom();
    
    // Set up global data
    global.window.executedLines = mockTraceData.executedLines;
    global.window.sourceFiles = mockTraceData.sourceFiles;
    global.window.commentsData = mockTraceData.commentsData;
    global.window.lineComment = mockTraceData.lineComment;
    global.window.eventMetadata = mockTraceData.eventMetadata;
    
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
      searchBtn: mockElements.searchBtn
    };
    
    // Initialize search functionality
    global.TraceViewer.initSearch();
    
    // Initialize search modal functionality
    global.TraceViewer.initSearchModal();
    
    // Initialize search database manually (since DOMContentLoaded won't fire in tests)
    if (window.eventMetadata) {
      global.TraceViewer.searchDatabase = new global.SearchDatabase();
      global.TraceViewer.searchDatabase.initializeFromMetadata();
    }
    
    // Initialize themes functionality
    global.TraceViewer.initThemes(mockElements.themeSelector);
    
    // Initialize copy subtree functionality
    global.TraceViewer.initCopySubtree();
    
    // Initialize export functionality
    global.TraceViewer.initExport();
  });

  afterEach(() => {
    // Clean up DOM
    document.body.innerHTML = '';
    jest.clearAllMocks();
  });

  describe('Folding and Expansion', () => {
    test('should calculate subtree sizes correctly', () => {
      global.TraceViewer.calculateSubtreeSizes();
      
      const foldables = mockElements.content.querySelectorAll('.foldable.call');
      expect(foldables.length).toBe(2);
      
      const mainFunction = foldables[0];
      const nestedFunction = foldables[1];
      
      console.log('Main function subtree size:', mainFunction.dataset.subtreeSize);
      console.log('Nested function subtree size:', nestedFunction.dataset.subtreeSize);
      
      // Debug: check what elements are in the call group
      const callGroup = mainFunction.nextElementSibling;
      if (callGroup && callGroup.classList.contains('call-group')) {
        const directDescendants = callGroup.querySelectorAll(':scope > div[data-indent]');
        console.log('Direct descendants:', directDescendants.length);
        directDescendants.forEach((el, index) => {
          console.log(`Descendant ${index}:`, el.className, el.textContent.trim());
        });
      }
      
      expect(mainFunction.dataset.subtreeSize).toBe('3');
      expect(nestedFunction.dataset.subtreeSize).toBe('1');
    });

    test('should toggle foldable elements', () => {
      const foldable = mockElements.content.querySelector('.foldable.call');
      const callGroup = foldable.nextElementSibling;
      
      // Initially collapsed
      expect(callGroup.classList.contains('collapsed')).toBe(true);
      expect(foldable.classList.contains('expanded')).toBe(false);
      
      // Expand
      global.TraceViewer.expandSubtree(foldable);
      expect(callGroup.classList.contains('collapsed')).toBe(false);
      expect(foldable.classList.contains('expanded')).toBe(true);
      
      // Collapse
      global.TraceViewer.collapseSubtree(foldable);
      expect(callGroup.classList.contains('collapsed')).toBe(true);
      expect(foldable.classList.contains('expanded')).toBe(false);
    });

    test('should handle smart expand all', () => {
      // Mock the config
      global.TraceViewer.config.INITIAL_LOAD_MAX_LINES = 1000;
      
      global.TraceViewer.smartExpandAll();
      
      const expandedFoldables = mockElements.content.querySelectorAll('.foldable.expanded');
      expect(expandedFoldables.length).toBeGreaterThan(0);
    });
  });

  describe('Search Functionality', () => {
    test('should debounce search input', () => {
      jest.useFakeTimers();
      
      const mockFn = jest.fn();
      const debouncedFn = global.TraceViewer.utils.debounce(mockFn, 100);
      
      debouncedFn();
      debouncedFn();
      debouncedFn();
      
      // Should only call once after debounce period
      jest.advanceTimersByTime(150);
      expect(mockFn).toHaveBeenCalledTimes(1);
      
      jest.useRealTimers();
    });

    test('should highlight search results', () => {
      jest.useFakeTimers();
      
      const searchTerm = 'test_function';
      mockElements.search.value = searchTerm;
      
      // Trigger search
      const event = new Event('input');
      mockElements.search.dispatchEvent(event);
      
      // Advance timers to trigger debounced search
      jest.advanceTimersByTime(350);
      
      const highlighted = mockElements.content.querySelectorAll('.highlight');
      expect(highlighted.length).toBeGreaterThan(0);
      
      jest.useRealTimers();
    });

    test('should initialize search modal functionality', () => {
      // Check that search modal was initialized
      expect(global.TraceViewer.searchModal).toBeDefined();
      expect(global.TraceViewer.searchModal instanceof global.TraceViewer.SearchModal).toBe(true);
      
      // Check that search button has click handler
      const clickSpy = jest.spyOn(global.TraceViewer.searchModal, 'show');
      mockElements.searchBtn.click();
      
      expect(clickSpy).toHaveBeenCalled();
      clickSpy.mockRestore();
    });

    test('should respond to Ctrl+F keyboard shortcut', () => {
      const showSpy = jest.spyOn(global.TraceViewer.searchModal, 'show');
      
      // Simulate Ctrl+F keypress
      const event = new KeyboardEvent('keydown', {
        key: 'f',
        ctrlKey: true,
        bubbles: true
      });
      document.dispatchEvent(event);
      
      expect(showSpy).toHaveBeenCalled();
      showSpy.mockRestore();
    });

    test('should initialize search database with event metadata', () => {
      expect(global.TraceViewer.searchDatabase).toBeDefined();
      expect(global.TraceViewer.searchDatabase.events.length).toBe(5); // From mock data
      
      // Verify events are properly indexed
      const testFunctionEvents = global.TraceViewer.searchDatabase.getEventsByFunction('test_function');
      expect(testFunctionEvents.length).toBe(2); // CALL and RETURN
      
      const fileEvents = global.TraceViewer.searchDatabase.getEventsByFilename('/path/to/file.py');
      expect(fileEvents.length).toBe(5); // All events from mock file
    });
  });

  describe('Export Functionality', () => {
    test('should export HTML content', () => {
      // Mock URL.createObjectURL and URL.revokeObjectURL to avoid actual file operations
      const originalCreateObjectURL = URL.createObjectURL;
      const originalRevokeObjectURL = URL.revokeObjectURL;
      
      URL.createObjectURL = jest.fn(() => 'blob:test-url');
      URL.revokeObjectURL = jest.fn();
      
      const clickEvent = new Event('click');
      mockElements.exportBtn.dispatchEvent(clickEvent);
      
      // Should create download link (it gets removed immediately, so we test the mock calls)
      expect(URL.createObjectURL).toHaveBeenCalled();
      expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test-url');
      
      // Restore original functions
      URL.createObjectURL = originalCreateObjectURL;
      URL.revokeObjectURL = originalRevokeObjectURL;
    });
  });

  describe('Utility Functions', () => {
    test('should escape HTML correctly', () => {
      const unsafe = '<script>alert("xss")</script>';
      const safe = global.TraceViewer.utils.escapeHTML(unsafe);
      
      console.log('Escaped HTML:', safe);
      
      expect(safe).toBe('&lt;script&gt;alert("xss")&lt;/script&gt;');
      expect(safe).not.toContain('<script>');
    });

    test('should handle theme changes', () => {
      const themeChangeEvent = new Event('change');
      
      // Add theme options
      const darkTheme = document.createElement('option');
      darkTheme.value = 'prism-dark';
      darkTheme.dataset.isDark = 'true';
      mockElements.themeSelector.appendChild(darkTheme);
      
      mockElements.themeSelector.value = 'prism-dark';
      mockElements.themeSelector.dispatchEvent(themeChangeEvent);
      
      expect(document.body.classList.contains('dark-theme')).toBe(true);
    });
  });

  describe('Copy Subtree', () => {
    test('should copy subtree text to clipboard', async () => {
      const copyBtn = mockElements.content.querySelector('.copy-subtree-btn');
      const clickEvent = new Event('click', { bubbles: true });
      
      await copyBtn.dispatchEvent(clickEvent);
      
      expect(navigator.clipboard.writeText).toHaveBeenCalled();
      const copiedText = navigator.clipboard.writeText.mock.calls[0][0];
      
      expect(copiedText).toContain('test_function()');
      expect(copiedText).toContain('RETURN test_function()');
    });
  });
});