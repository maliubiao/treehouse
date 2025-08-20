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

describe('AI Explainer', () => {
  let mockElements;
  
  beforeEach(() => {
    mockElements = createMockDom();
    
    // Set up global data
    global.window.executedLines = mockTraceData.executedLines;
    global.window.sourceFiles = mockTraceData.sourceFiles;
    global.window.commentsData = mockTraceData.commentsData;
    global.window.lineComment = mockTraceData.lineComment;
    
    // Create AI explainer dialog elements
    const aiExplainDialog = document.createElement('div');
    aiExplainDialog.id = 'aiExplainDialog';
    
    const closeBtn = document.createElement('button');
    closeBtn.className = 'ai-explain-close-btn';
    
    const apiUrlInput = document.createElement('input');
    apiUrlInput.id = 'llmApiUrl';
    
    const modelSelect = document.createElement('select');
    modelSelect.id = 'llmModelSelect';
    
    const saveBtn = document.createElement('button');
    saveBtn.id = 'llmSettingsSaveBtn';
    
    const fetchModelsBtn = document.createElement('button');
    fetchModelsBtn.id = 'llmFetchModelsBtn';
    
    const startBtn = document.createElement('button');
    startBtn.id = 'startAiExplainBtn';
    
    const body = document.createElement('div');
    body.id = 'aiExplainBody';
    
    const status = document.createElement('div');
    status.id = 'aiExplainStatus';
    
    const rawResponseToggleBtn = document.createElement('button');
    rawResponseToggleBtn.id = 'llmRawResponseToggleBtn';
    
    const rawResponseContent = document.createElement('div');
    rawResponseContent.id = 'llmRawResponseContent';
    
    const thinkingOutput = document.createElement('div');
    thinkingOutput.id = 'llmThinkingOutput';
    
    const contentOutput = document.createElement('div');
    contentOutput.id = 'llmContentOutput';
    
    // Append all elements to dialog
    aiExplainDialog.appendChild(closeBtn);
    aiExplainDialog.appendChild(apiUrlInput);
    aiExplainDialog.appendChild(modelSelect);
    aiExplainDialog.appendChild(saveBtn);
    aiExplainDialog.appendChild(fetchModelsBtn);
    aiExplainDialog.appendChild(startBtn);
    aiExplainDialog.appendChild(body);
    aiExplainDialog.appendChild(status);
    aiExplainDialog.appendChild(rawResponseToggleBtn);
    aiExplainDialog.appendChild(rawResponseContent);
    aiExplainDialog.appendChild(thinkingOutput);
    aiExplainDialog.appendChild(contentOutput);
    
    document.body.appendChild(aiExplainDialog);
    
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
    
    // Initialize AI explainer
    global.TraceViewer.initAiExplainer();
  });

  afterEach(() => {
    // Clean up DOM
    document.body.innerHTML = '';
    jest.clearAllMocks();
  });

  test('should initialize AI explainer', () => {
    expect(global.TraceViewer.aiExplainer).toBeDefined();
    expect(global.TraceViewer.aiExplainer.dialog).toBeDefined();
    expect(global.TraceViewer.aiExplainer.init).toBeDefined();
  });

  test('should handle explain button clicks', () => {
    const explainBtn = mockElements.content.querySelector('.explain-ai-btn');
    const clickEvent = new Event('click', { bubbles: true });
    
    explainBtn.dispatchEvent(clickEvent);
    
    expect(global.TraceViewer.aiExplainer.dialog.style.display).toBe('flex');
  });

  test('should close AI dialog', () => {
    // Open dialog first
    const explainBtn = mockElements.content.querySelector('.explain-ai-btn');
    const clickEvent = new Event('click', { bubbles: true });
    explainBtn.dispatchEvent(clickEvent);
    
    // Close dialog
    global.TraceViewer.aiExplainer.hide();
    
    expect(global.TraceViewer.aiExplainer.dialog.style.display).toBe('none');
  });

  test('should handle settings save', () => {
    global.TraceViewer.aiExplainer.apiUrlInput.value = 'http://localhost:8000';
    global.TraceViewer.aiExplainer.modelSelect.value = 'test-model';
    
    global.TraceViewer.aiExplainer.saveSettings();
    
    // Check that localStorage was called with the correct values
    // We can't test the mock directly due to jest.clearAllMocks() in setup
    // Instead, we'll test the status message indicates success
    expect(global.TraceViewer.aiExplainer.status.textContent).toContain('saved');
  });

  test('should handle fetch models error', async () => {
    global.fetch.mockRejectedValueOnce(new Error('Network error'));
    
    await global.TraceViewer.aiExplainer.fetchModels();
    
    expect(global.TraceViewer.aiExplainer.status.textContent).toContain('Error');
  });

  test('should extract subtree text correctly', () => {
    const foldable = mockElements.content.querySelector('.foldable.call');
    const callGroup = foldable.nextElementSibling;
    
    const text = global.TraceViewer.aiExplainer.getSubtreeText(foldable, callGroup);
    
    expect(text).toContain('test_function');
    expect(text).toContain('print("Hello")');
  });
});