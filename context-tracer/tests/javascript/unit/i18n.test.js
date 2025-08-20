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

describe('i18n System', () => {
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
    
    // Mock language selector
    const languageSelector = document.createElement('select');
    languageSelector.id = 'languageSelector';
    
    const enOption = document.createElement('option');
    enOption.value = 'en';
    enOption.textContent = 'English';
    
    const zhOption = document.createElement('option');
    zhOption.value = 'zh';
    zhOption.textContent = '简体中文';
    
    languageSelector.appendChild(enOption);
    languageSelector.appendChild(zhOption);
    document.body.appendChild(languageSelector);
  });

  afterEach(() => {
    // Clean up DOM
    document.body.innerHTML = '';
    jest.clearAllMocks();
    localStorage.clear();
  });

  test('should initialize i18n system', () => {
    global.TraceViewer.i18n.init();
    
    expect(global.TraceViewer.i18n.currentLang).toBeDefined();
    expect(document.documentElement.lang).toBeDefined();
  });

  test('should set language correctly', () => {
    // Reset i18n to ensure clean state
    global.TraceViewer.i18n.currentLang = 'en';
    
    // Clear localStorage to ensure clean state
    localStorage.clear();
    
    global.TraceViewer.i18n.setLang('zh');
    expect(global.TraceViewer.i18n.currentLang).toBe('zh');
    expect(document.documentElement.lang).toBe('zh');
    expect(localStorage.getItem('traceViewerLang')).toBe('zh');
    
    global.TraceViewer.i18n.setLang('en');
    expect(global.TraceViewer.i18n.currentLang).toBe('en');
    expect(document.documentElement.lang).toBe('en');
    expect(localStorage.getItem('traceViewerLang')).toBe('en');
  });

  test('should translate static content', () => {
    // Create elements with data-i18n attributes
    const titleElement = document.createElement('h1');
    titleElement.dataset.i18n = 'mainTitle';
    document.body.appendChild(titleElement);
    
    const searchInput = document.createElement('input');
    searchInput.dataset.i18nPlaceholder = 'searchPlaceholder';
    document.body.appendChild(searchInput);
    
    const expandBtn = document.createElement('button');
    expandBtn.dataset.i18nTitle = 'expandAllTitle';
    document.body.appendChild(expandBtn);
    
    // Test English translation
    global.TraceViewer.i18n.setLang('en');
    global.TraceViewer.i18n.apply();
    
    expect(titleElement.textContent).toBe('Python Trace Report');
    expect(searchInput.placeholder).toBe('Search messages...');
    expect(expandBtn.title).toBe('Expand all call stacks');
    
    // Test Chinese translation
    global.TraceViewer.i18n.setLang('zh');
    global.TraceViewer.i18n.apply();
    
    expect(titleElement.textContent).toBe('Python 追踪报告');
    expect(searchInput.placeholder).toBe('搜索消息...');
    expect(expandBtn.title).toBe('展开所有调用堆栈');
  });

  test('should handle skeleton view text switching', () => {
    const skeletonBtn = document.createElement('button');
    skeletonBtn.dataset.i18n = 'skeletonView';
    document.body.appendChild(skeletonBtn);
    
    // Test normal view
    global.TraceViewer.i18n.setLang('en');
    global.TraceViewer.i18n.apply();
    expect(skeletonBtn.textContent).toBe('Skeleton View');
    
    // Test skeleton mode text
    document.body.classList.add('skeleton-mode');
    global.TraceViewer.i18n.apply();
    expect(skeletonBtn.textContent).toBe('Full View');
    
    document.body.classList.remove('skeleton-mode');
    global.TraceViewer.i18n.apply();
    expect(skeletonBtn.textContent).toBe('Skeleton View');
  });

  test('should translate dynamic error messages', () => {
    // Create error elements with Chinese content
    const errorElement = document.createElement('div');
    errorElement.className = 'error';
    errorElement.textContent = '⚠ HTML报告大小已超过100MB限制，后续内容将被忽略';
    document.body.appendChild(errorElement);
    
    const assetErrorElement = document.createElement('div');
    assetErrorElement.className = 'error';
    assetErrorElement.textContent = '无法复制资源文件: Permission denied';
    document.body.appendChild(assetErrorElement);
    
    // Test English translation
    global.TraceViewer.i18n.setLang('en');
    global.TraceViewer.i18n.translateDynamicContent();
    
    expect(errorElement.textContent).toBe('⚠ HTML report size has exceeded 100MB limit, subsequent content will be ignored');
    expect(assetErrorElement.textContent).toBe('Failed to copy asset files: Permission denied');
    
    // Test Chinese translation (should remain unchanged)
    global.TraceViewer.i18n.setLang('zh');
    global.TraceViewer.i18n.translateDynamicContent();
    
    expect(errorElement.textContent).toBe('⚠ HTML报告大小已超过100MB限制，后续内容将被忽略');
    expect(assetErrorElement.textContent).toBe('无法复制资源文件: Permission denied');
  });

  test('should provide translation function', () => {
    // Ensure we start with English
    global.TraceViewer.i18n.currentLang = 'en';
    
    expect(global.TraceViewer.i18n.t('mainTitle')).toBe('Python Trace Report');
    expect(global.TraceViewer.i18n.t('searchPlaceholder')).toBe('Search messages...');
    
    global.TraceViewer.i18n.setLang('zh');
    expect(global.TraceViewer.i18n.t('mainTitle')).toBe('Python 追踪报告');
    expect(global.TraceViewer.i18n.t('searchPlaceholder')).toBe('搜索消息...');
    
    // Test fallback for unknown keys
    expect(global.TraceViewer.i18n.t('unknownKey')).toBe('unknownKey');
  });

  test('should handle browser language detection', () => {
    // Mock navigator.language for Chinese
    Object.defineProperty(navigator, 'language', {
      value: 'zh-CN',
      configurable: true
    });
    
    // Clear localStorage and reset i18n
    localStorage.clear();
    global.TraceViewer.i18n.currentLang = 'en'; // Reset to default
    
    global.TraceViewer.i18n.init();
    expect(global.TraceViewer.i18n.currentLang).toBe('zh');
    
    // Test English browser
    Object.defineProperty(navigator, 'language', {
      value: 'en-US',
      configurable: true
    });
    
    // Clear localStorage and reset i18n
    localStorage.clear();
    global.TraceViewer.i18n.currentLang = 'en'; // Reset to default
    
    global.TraceViewer.i18n.init();
    expect(global.TraceViewer.i18n.currentLang).toBe('en');
  });

  test('should persist language preference in localStorage', () => {
    localStorage.setItem('traceViewerLang', 'zh');
    
    global.TraceViewer.i18n.init();
    expect(global.TraceViewer.i18n.currentLang).toBe('zh');
    
    localStorage.setItem('traceViewerLang', 'en');
    global.TraceViewer.i18n.init();
    expect(global.TraceViewer.i18n.currentLang).toBe('en');
  });
});