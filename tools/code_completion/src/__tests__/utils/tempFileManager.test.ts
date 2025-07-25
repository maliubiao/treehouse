import * as fs from 'fs/promises';
import * as os from 'os';
import { TempFileManager } from '../../utils/tempFileManager';
import * as vscode from 'vscode';

// Mock fs/promises
jest.mock('fs/promises', () => ({
  writeFile: jest.fn(),
  unlink: jest.fn()
}));

// Mock os
jest.mock('os', () => ({
  tmpdir: jest.fn()
}));

// Mock vscode
jest.mock('vscode', () => ({
    Uri: {
        file: jest.fn(p => ({ path: p }))
    }
}));


describe('TempFileManager', () => {
  let tempFileManager: TempFileManager;
  
  beforeEach(() => {
    jest.clearAllMocks();
    tempFileManager = new TempFileManager();
    (os.tmpdir as jest.Mock).mockReturnValue('/tmp');
  });

  describe('createTempFilesForDiff', () => {
    it('should create temporary files with correct content', async () => {
      (fs.writeFile as jest.Mock).mockResolvedValue(undefined);
      
      const originalContent = 'const x = 1;';
      const newContent = 'const y = 2;';
      const fileExtension = '.js';
      
      const result = await tempFileManager.createTempFilesForDiff(
        originalContent,
        newContent,
        fileExtension
      );
      
      expect(fs.writeFile).toHaveBeenCalledTimes(2);
      expect(result.originalUri.path).toContain('original-');
      expect(result.originalUri.path).toContain('.js');
      expect(result.newUri.path).toContain('generated-');
      expect(result.newUri.path).toContain('.js');
    });
  });

  describe('cleanup', () => {
    it('should delete all tracked temporary files', async () => {
      (fs.writeFile as jest.Mock).mockResolvedValue(undefined);
      (fs.unlink as jest.Mock).mockResolvedValue(undefined);
      (vscode.Uri.file as jest.Mock).mockImplementation(p => ({ path: p, fsPath: p }));

      
      // Create some temp files
      await tempFileManager.createTempFilesForDiff('test1', 'test2', '.js');
      
      await tempFileManager.cleanup();
      
      expect(fs.unlink).toHaveBeenCalledTimes(2);
    });

    it('should handle file deletion errors gracefully', async () => {
      (fs.writeFile as jest.Mock).mockResolvedValue(undefined);
      const mockError = new Error('File not found');
      (mockError as any).code = 'ENOENT';
      (fs.unlink as jest.Mock).mockRejectedValue(mockError);
      
      // Create some temp files
      await tempFileManager.createTempFilesForDiff('test1', 'test2', '.js');
      
      // Should not throw
      await expect(tempFileManager.cleanup()).resolves.toBeUndefined();
    });
  });

  describe('cleanupAll', () => {
    it('should clean up orphaned files', async () => {
      (fs.writeFile as jest.Mock).mockResolvedValue(undefined);
      (fs.unlink as jest.Mock).mockResolvedValue(undefined);
      
      // Create some temp files
      await tempFileManager.createTempFilesForDiff('test1', 'test2', '.js');
      
      // Manually add an orphaned file
      (TempFileManager as any).orphanedFiles.add('/tmp/orphaned-file.js');
      (TempFileManager as any).activeFiles.delete('/tmp/orphaned-file.js');
      
      await TempFileManager.cleanupAll();
      
      expect(fs.unlink).toHaveBeenCalledWith('/tmp/orphaned-file.js');
    });
  });
});