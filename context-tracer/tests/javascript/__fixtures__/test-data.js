// Test data fixtures for JavaScript tests

const mockTraceData = {
  executedLines: {
    '/path/to/file.py': {
      1: [10, 15, 20],
      2: [5, 12, 18]
    }
  },
  sourceFiles: {
    '/path/to/file.py': 'ZGVmIHRlc3RfZnVuY3Rpb24oKToKICAgIHByaW50KCJIZWxsbyIpCiAgICB4ID0gNDIKICAgIHJldHVybiB4'
  },
  commentsData: {
    '/path/to/file.py': {
      10: ['Comment for line 10'],
      15: ['Comment for line 15']
    }
  },
  lineComment: {
    '1-/path/to/file.py-10': { var1: 'value1', var2: 'value2' }
  }
};

const mockHtmlContent = `
<div class="foldable call" data-indent="0" data-subtree-size="3" style="--indent-space: 0ch;">
    ↘ CALL test_function() <span class="view-source-btn" onclick="showSource('/path/to/file.py', 10, 1)">view source</span> <span class="copy-subtree-btn" title="Copy subtree as text">📋</span> <span class="focus-subtree-btn" title="Focus on this subtree (crop)">🔍</span> <span class="explain-ai-btn" title="Explain with AI">🤖</span> <span class="toggle-details-btn" title="Show details for this subtree">👁️</span>
</div>
<div class="call-group collapsed">
    <div class="line" data-indent="2" style="padding-left:2ch">
        ▷ /path/to/file.py:10 print("Hello") <span class="view-source-btn" onclick="showSource('/path/to/file.py', 10, 1)">view source</span>
    </div>
    <div class="line" data-indent="2" style="padding-left:2ch">
        ▷ /path/to/file.py:15 x = 42 <span class="view-source-btn" onclick="showSource('/path/to/file.py', 15, 1)">view source</span>
    </div>
    <div class="foldable call" data-indent="2" data-subtree-size="1" style="--indent-space: 2ch;">
        ↘ CALL nested_function() <span class="view-source-btn" onclick="showSource('/path/to/file.py', 20, 2)">view source</span> <span class="copy-subtree-btn" title="Copy subtree as text">📋</span> <span class="focus-subtree-btn" title="Focus on this subtree (crop)">🔍</span> <span class="explain-ai-btn" title="Explain with AI">🤖</span> <span class="toggle-details-btn" title="Show details for this subtree">👁️</span>
        <div class="call-group collapsed">
            <div class="line" data-indent="4" style="padding-left:4ch">
                ▷ /path/to/file.py:20 print("Nested") <span class="view-source-btn" onclick="showSource('/path/to/file.py', 20, 2)">view source</span>
            </div>
        </div>
    </div>
</div>
<div class="return" data-indent="0" style="padding-left:0ch">
    ↗ RETURN test_function() -> None
</div>
`;

const mockSourceCode = `
def test_function():
    print("Hello")
    x = 42
    nested_function()

def nested_function():
    print("Nested")
`;

const createMockDom = () => {
  const content = document.createElement('div');
  content.id = 'content';
  content.innerHTML = mockHtmlContent;
  
  const search = document.createElement('input');
  search.id = 'sidebarSearch';
  
  const expandAllBtn = document.createElement('button');
  expandAllBtn.id = 'expandAll';
  
  const collapseAllBtn = document.createElement('button');
  collapseAllBtn.id = 'collapseAll';
  
  const skeletonViewBtn = document.createElement('button');
  skeletonViewBtn.id = 'skeletonViewBtn';
  
  const exportBtn = document.createElement('button');
  exportBtn.id = 'exportBtn';
  
  const sourceDialog = document.createElement('div');
  sourceDialog.id = 'sourceDialog';
  sourceDialog.style.display = 'none';
  
  // Create source dialog content elements
  const sourceTitle = document.createElement('div');
  sourceTitle.id = 'sourceTitle';
  sourceDialog.appendChild(sourceTitle);
  
  const sourceContent = document.createElement('div');
  sourceContent.id = 'sourceContent';
  sourceDialog.appendChild(sourceContent);
  
  const dialogCloseBtn = document.createElement('button');
  dialogCloseBtn.id = 'dialogCloseBtn';
  
  const settingsDialog = document.createElement('div');
  settingsDialog.id = 'settingsDialog';
  settingsDialog.style.display = 'none';
  
  // Create settings dialog content elements
  const modalCloseBtn = document.createElement('button');
  modalCloseBtn.className = 'modal-close-btn';
  settingsDialog.appendChild(modalCloseBtn);
  
  const tabsContainer = document.createElement('div');
  tabsContainer.className = 'tabs';
  
  const displayTab = document.createElement('button');
  displayTab.className = 'tab-link active';
  displayTab.setAttribute('data-tab', 'tab-display');
  tabsContainer.appendChild(displayTab);
  
  const helpTab = document.createElement('button');
  helpTab.className = 'tab-link';
  helpTab.setAttribute('data-tab', 'tab-help');
  tabsContainer.appendChild(helpTab);
  
  settingsDialog.appendChild(tabsContainer);
  
  const displayContent = document.createElement('div');
  displayContent.id = 'tab-display';
  displayContent.className = 'tab-content active';
  settingsDialog.appendChild(displayContent);
  
  const helpContent = document.createElement('div');
  helpContent.id = 'tab-help';
  helpContent.className = 'tab-content';
  settingsDialog.appendChild(helpContent);
  
  const themeSelector = document.createElement('select');
  themeSelector.id = 'themeSelector';
  
  document.body.appendChild(content);
  document.body.appendChild(search);
  document.body.appendChild(expandAllBtn);
  document.body.appendChild(collapseAllBtn);
  document.body.appendChild(skeletonViewBtn);
  document.body.appendChild(exportBtn);
  document.body.appendChild(sourceDialog);
  document.body.appendChild(dialogCloseBtn);
  document.body.appendChild(settingsDialog);
  document.body.appendChild(themeSelector);
  
  return {
    content,
    search,
    expandAllBtn,
    collapseAllBtn,
    skeletonViewBtn,
    exportBtn,
    sourceDialog,
    dialogCloseBtn,
    settingsDialog,
    themeSelector
  };
};

module.exports = {
  mockTraceData,
  mockHtmlContent,
  mockSourceCode,
  createMockDom
};