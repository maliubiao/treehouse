const { createMockDom } = require('../__fixtures__/test-data');

// Mock the global TraceViewer object before importing the script
const originalTraceViewer = global.TraceViewer;

beforeAll(() => {
  // Load the actual script
  require('../../../src/context_tracer/tracer_scripts.js');
});

afterAll(() => {
  global.TraceViewer = originalTraceViewer;
});

describe('Utility Functions', () => {
  let mockElements;
  
  beforeEach(() => {
    mockElements = createMockDom();
    
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
      themeSelector: mockElements.themeSelector
    };
  });

  afterEach(() => {
    // Clean up DOM
    document.body.innerHTML = '';
    jest.clearAllMocks();
  });

  describe('Clipboard Interceptor', () => {
    test('should initialize clipboard interceptor', () => {
      // Mock document.addEventListener to track calls
      const originalAddEventListener = document.addEventListener;
      document.addEventListener = jest.fn();
      
      global.TraceViewer.initClipboardInterceptor();
      
      // Should have added event listener
      expect(document.addEventListener).toHaveBeenCalledWith('copy', expect.any(Function));
      
      // Restore original function
      document.addEventListener = originalAddEventListener;
    });

    test('should handle copy events within content', () => {
      // Mock document.addEventListener to track calls
      const originalAddEventListener = document.addEventListener;
      let copyHandler = null;
      document.addEventListener = jest.fn((event, handler) => {
        if (event === 'copy') {
          copyHandler = handler;
        }
      });
      
      global.TraceViewer.initClipboardInterceptor();
      
      // Mock innerText to work around jsdom limitation
      Object.defineProperty(HTMLElement.prototype, 'innerText', {
        get() {
          return this.textContent;
        },
        configurable: true
      });
      
      // Create a test element with some content
      const testElement = document.createElement('div');
      testElement.textContent = 'Test content';
      
      // Mock selection within content
      const selection = {
        rangeCount: 1,
        isCollapsed: false,
        getRangeAt: jest.fn().mockReturnValue({
          commonAncestorContainer: mockElements.content,
          cloneContents: jest.fn().mockReturnValue(testElement.cloneNode(true))
        })
      };
      
      Object.defineProperty(document, 'getSelection', {
        value: jest.fn().mockReturnValue(selection),
        configurable: true
      });
      
      const copyEvent = {
        clipboardData: {
          setData: jest.fn()
        },
        preventDefault: jest.fn()
      };
      
      // Trigger copy event
      copyHandler(copyEvent);
      
      expect(copyEvent.clipboardData.setData).toHaveBeenCalledWith('text/plain', 'Test content');
      expect(copyEvent.preventDefault).toHaveBeenCalled();
      
      // Restore original function
      document.addEventListener = originalAddEventListener;
    });

    test('should ignore copy events outside content', () => {
      // Mock document.addEventListener to track calls
      const originalAddEventListener = document.addEventListener;
      let copyHandler = null;
      document.addEventListener = jest.fn((event, handler) => {
        if (event === 'copy') {
          copyHandler = handler;
        }
      });
      
      global.TraceViewer.initClipboardInterceptor();
      
      // Mock selection outside content
      const selection = {
        rangeCount: 1,
        isCollapsed: false,
        getRangeAt: jest.fn().mockReturnValue({
          commonAncestorContainer: document.body,
          cloneContents: jest.fn().mockReturnValue(document.createDocumentFragment())
        })
      };
      
      Object.defineProperty(document, 'getSelection', {
        value: jest.fn().mockReturnValue(selection),
        configurable: true
      });
      
      const copyEvent = {
        clipboardData: {
          setData: jest.fn()
        },
        preventDefault: jest.fn()
      };
      
      // Trigger copy event
      copyHandler(copyEvent);
      
      expect(copyEvent.clipboardData.setData).not.toHaveBeenCalled();
      expect(copyEvent.preventDefault).not.toHaveBeenCalled();
      
      // Restore original function
      document.addEventListener = originalAddEventListener;
    });
  });

  describe('Debug Variables Toggle', () => {
    test('should initialize debug vars toggle', () => {
      // Mock content.addEventListener to track calls
      const originalAddEventListener = mockElements.content.addEventListener;
      mockElements.content.addEventListener = jest.fn();
      
      global.TraceViewer.initDebugVarsToggle();
      
      // Should have added event listener
      expect(mockElements.content.addEventListener).toHaveBeenCalledWith('click', expect.any(Function));
      
      // Restore original function
      mockElements.content.addEventListener = originalAddEventListener;
    });

    test('should toggle debug vars expansion', () => {
      global.TraceViewer.initDebugVarsToggle();
      
      // Create a debug vars element
      const debugVars = document.createElement('div');
      debugVars.className = 'debug-vars';
      mockElements.content.appendChild(debugVars);
      
      // Click on debug vars
      const clickEvent = new Event('click', { bubbles: true });
      debugVars.dispatchEvent(clickEvent);
      
      expect(debugVars.classList.contains('expanded')).toBe(true);
      
      // Click again to collapse
      debugVars.dispatchEvent(clickEvent);
      expect(debugVars.classList.contains('expanded')).toBe(false);
    });
  });

  describe('Multi-line Toggle', () => {
    test('should initialize multi-line toggle', () => {
      // Mock content.addEventListener to track calls
      const originalAddEventListener = mockElements.content.addEventListener;
      mockElements.content.addEventListener = jest.fn();
      
      global.TraceViewer.initMultiLineToggle();
      
      // Should have added event listener
      expect(mockElements.content.addEventListener).toHaveBeenCalledWith('click', expect.any(Function));
      
      // Restore original function
      mockElements.content.addEventListener = originalAddEventListener;
    });

    test('should toggle multi-line expansion', () => {
      global.TraceViewer.initMultiLineToggle();
      
      // Create a multi-line container with expand button
      const container = document.createElement('div');
      container.className = 'multi-line-container';
      
      const expandBtn = document.createElement('button');
      expandBtn.className = 'expand-code-btn';
      expandBtn.textContent = '[+]';
      container.appendChild(expandBtn);
      
      mockElements.content.appendChild(container);
      
      // Click on expand button
      const clickEvent = new Event('click', { bubbles: true });
      expandBtn.dispatchEvent(clickEvent);
      
      expect(container.classList.contains('expanded')).toBe(true);
      expect(expandBtn.textContent).toBe('[-]');
      
      // Click again to collapse
      expandBtn.dispatchEvent(clickEvent);
      expect(container.classList.contains('expanded')).toBe(false);
      expect(expandBtn.textContent).toBe('[+]');
    });
  });

  describe('Comment Toggle', () => {
    test('should initialize comment toggle', () => {
      // Mock content.addEventListener to track calls
      const originalAddEventListener = mockElements.content.addEventListener;
      mockElements.content.addEventListener = jest.fn();
      
      global.TraceViewer.initCommentToggle();
      
      // Should have added event listener
      expect(mockElements.content.addEventListener).toHaveBeenCalledWith('click', expect.any(Function));
      
      // Restore original function
      mockElements.content.addEventListener = originalAddEventListener;
    });

    test('should toggle comment expansion', () => {
      global.TraceViewer.initCommentToggle();
      
      // Create a comment element
      const comment = document.createElement('div');
      comment.className = 'comment';
      mockElements.content.appendChild(comment);
      
      // Click on comment
      const clickEvent = new Event('click', { bubbles: true });
      comment.dispatchEvent(clickEvent);
      
      expect(comment.classList.contains('expanded')).toBe(true);
      
      // Click again to collapse
      comment.dispatchEvent(clickEvent);
      expect(comment.classList.contains('expanded')).toBe(false);
    });
  });

  describe('Text Extraction', () => {
    test('should extract clean text from selection', () => {
      // Create a simple test element with text content
      const testElement = document.createElement('div');
      testElement.textContent = 'Simple test content';
      
      // Mock selection
      const selection = {
        getRangeAt: jest.fn().mockReturnValue({
          cloneContents: jest.fn().mockReturnValue(testElement)
        })
      };
      
      // Mock innerText to work around jsdom limitation
      Object.defineProperty(HTMLElement.prototype, 'innerText', {
        get() {
          return this.textContent;
        },
        configurable: true
      });
      
      const extractedText = global.TraceViewer.extractTextFromSelection(selection);
      
      expect(extractedText).toBe('Simple test content');
    });
  });
});