// Import removed - using global jest
import { StreamingAccumulator } from '../../utils/streamingAccumulator';



// Mock vscode
jest.mock('vscode', () => ({
  workspace: {
    getConfiguration: jest.fn()
  }
}));

const mockGetConfiguration = {
  get: jest.fn()
};

import * as vscode from 'vscode';
(vscode.workspace.getConfiguration as jest.Mock).mockReturnValue(mockGetConfiguration);

// Mock logger
jest.mock('../../utils/logger', () => ({
  logger: {
    log: jest.fn(),
    warn: jest.fn(),
    error: jest.fn()
  }
}));

const originalConsole = global.console;

describe('StreamingAccumulator', () => {
  let accumulator: StreamingAccumulator;
  let mockConsole: any;

  beforeEach(() => {
    // Setup mock console
    mockConsole = {
      log: jest.fn(),
      error: jest.fn()
    };
    (global as any).console = mockConsole;

    // Reset singleton instance
    (StreamingAccumulator as any).instance = null;
    accumulator = StreamingAccumulator.getInstance();

    // Reset mocks
    mockGetConfiguration.get.mockReturnValue(false); // Default disable debug
  });

  afterEach(() => {
    // Restore console
    global.console = originalConsole;
    jest.clearAllMocks();
  });

  describe('getInstance', () => {
    it('should return singleton instance', () => {
      const instance1 = StreamingAccumulator.getInstance();
      const instance2 = StreamingAccumulator.getInstance();
      
      expect(instance1).toBe(instance2);
    });

    it('should create new instance if none exists', () => {
      (StreamingAccumulator as any).instance = null;
      const instance = StreamingAccumulator.getInstance();
      
      expect(instance).toBeInstanceOf(StreamingAccumulator);
      expect((StreamingAccumulator as any).instance).toBe(instance);
    });
  });

  describe('startSession', () => {
    it('should initialize session state', () => {
      accumulator.startSession();
      
      expect(accumulator.isActive()).toBe(true);
      expect(accumulator.getAccumulatedContent()).toBe('');
      expect(accumulator.getAllChunks()).toEqual([]);
    });
  });

  describe('addChunk', () => {
    beforeEach(() => {
      accumulator.startSession();
    });

    it('should add chunk when session is active', () => {
      const content = 'Hello world';
      accumulator.addChunk(content);
      
      expect(accumulator.getAccumulatedContent()).toBe(content);
      expect(accumulator.getAllChunks()).toHaveLength(1);
      expect(accumulator.getAllChunks()[0].content).toBe(content);
    });

    it('should handle multiple chunks', () => {
      accumulator.addChunk('Hello');
      accumulator.addChunk(' ');
      accumulator.addChunk('World');
      
      expect(accumulator.getAccumulatedContent()).toBe('Hello World');
      expect(accumulator.getAllChunks()).toHaveLength(3);
    });


    it('should throw error when adding chunk to inactive session', () => {
      accumulator.endSession(false);
      
      expect(() => {
        accumulator.addChunk('test');
      }).toThrow('Cannot add chunk to inactive streaming session');
    });


    it('should log debug info when debug mode is enabled', () => {
      mockGetConfiguration.get.mockReturnValue(true);
      accumulator.startSession();
      
      accumulator.addChunk('debug content');
      
      const logger = require('../../utils/logger');
      expect(logger.logger.log).toHaveBeenCalledWith(
        expect.stringContaining('Streaming chunk')
      );
    });
  });

  describe('clear', () => {
    it('should clear accumulated data', () => {
      accumulator.startSession();
      accumulator.addChunk('content');
      accumulator.clear();
      
      expect(accumulator.getAccumulatedContent()).toBe('');
      expect(accumulator.getAllChunks()).toEqual([]);
    });
  });

  describe('endSession', () => {
    beforeEach(() => {
      accumulator.startSession();
      accumulator.addChunk('test content');
    });

    it('should output to terminal when requested', () => {
      accumulator.endSession(true);
      
      expect(mockConsole.log).toHaveBeenCalled();
      expect(accumulator.isActive()).toBe(false);
    });

    it('should not output to terminal when not requested', () => {
      accumulator.endSession(false);
      
      expect(accumulator.isActive()).toBe(false);
    });

    it('should not output to terminal when cancelled', () => {
      accumulator.endSession(true, true);
      
      expect(mockConsole.log).not.toHaveBeenCalledWith(expect.stringContaining('STREAMING COMPLETION RESULTS'));
      expect(accumulator.isActive()).toBe(false);
    });

    it('should handle empty content', () => {
      accumulator.clear();
      accumulator.endSession(true);
      
      expect(mockConsole.log).toHaveBeenCalledWith('No streaming content to display.');
    });

    it('should handle long content truncation', () => {
      const longContent = Array(100).fill('line').join('\n');
      accumulator.clear();
      accumulator.addChunk(longContent);
      
      accumulator.endSession(true);
      
      expect(mockConsole.log).toHaveBeenCalledWith(expect.stringContaining('[First 25 lines - total 100 lines]'));
      expect(mockConsole.log).toHaveBeenCalledWith(expect.stringContaining('[Last 25 lines]'));
    });
  });

  describe('isActive', () => {
    it('should return false initially', () => {
      expect(accumulator.isActive()).toBe(false);
    });

    it('should return true during active session', () => {
      accumulator.startSession();
      expect(accumulator.isActive()).toBe(true);
    });

    it('should return false after session end', () => {
      accumulator.startSession();
      accumulator.endSession(false);
      expect(accumulator.isActive()).toBe(false);
    });
  });
});