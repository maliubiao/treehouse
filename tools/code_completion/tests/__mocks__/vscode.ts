// Minimal VS Code API mock for tests
module.exports = {
  window: {
    showInformationMessage: jest.fn(),
    showErrorMessage: jest.fn(),
    showInputBox: jest.fn(),
    showTextDocument: jest.fn(),
    createOutputChannel: jest.fn().mockReturnValue({
      appendLine: jest.fn(),
      show: jest.fn()
    }),
    tabGroups: {
      all: [],
      onDidChangeTabs: jest.fn(),
      close: jest.fn()
    }
  },
  workspace: {
    getConfiguration: jest.fn().mockReturnValue({
      get: jest.fn()
    }),
    applyEdit: jest.fn(),
    fs: {
      readFile: jest.fn()
    }
  },
  commands: {
    executeCommand: jest.fn(),
    registerCommand: jest.fn()
  },
  Uri: {
    file: jest.fn().mockImplementation((path) => ({ fsPath: path, toString: () => `file://${path}` })),
    joinPath: jest.fn()
  },
  Range: jest.fn().mockImplementation((start, end) => ({ start, end })),
  Position: jest.fn().mockImplementation((line, character) => ({ line, character })),
  Selection: jest.fn().mockImplementation((start, end) => ({ start, end, isEmpty: start === end })),
  WorkspaceEdit: jest.fn().mockImplementation(() => ({
    replace: jest.fn()
  })),
  ViewColumn: {
    Active: 1,
    One: 1
  },
  ConfigurationTarget: {
    Global: 1
  }
};