import * as vscode from 'vscode';
import * as fs from 'fs/promises';
import * as os from 'os';
import * as path from 'path';

/**
 * Manages the lifecycle of temporary files created for diffing.
 * Ensures that temporary files are cleaned up reliably.
 */
export class TempFileManager {
    private tempFiles: string[] = [];
    private static orphanedFiles: Set<string> = new Set();
    private static activeFiles: Set<string> = new Set();

    /**
     * Creates a pair of temporary files to be used in a diff view.
     * @param originalContent - The original content to write to the first file.
     * @param newContent - The new content to write to the second file.
     * @param fileExtension - The file extension to use for syntax highlighting (e.g., '.ts').
     * @returns An object containing the URIs of the created temporary files.
     */
    public async createTempFilesForDiff(
        originalContent: string,
        newContent: string,
        fileExtension: string
    ): Promise<{ originalUri: vscode.Uri; newUri: vscode.Uri }> {
        const tempDir = os.tmpdir();
        const timestamp = Date.now();

        const originalFile = path.join(tempDir, `original-${timestamp}${fileExtension}`);
        const newFile = path.join(tempDir, `generated-${timestamp}${fileExtension}`);

        await fs.writeFile(originalFile, originalContent);
        await fs.writeFile(newFile, newContent);

        this.tempFiles.push(originalFile, newFile);
        TempFileManager.orphanedFiles.add(originalFile);
        TempFileManager.orphanedFiles.add(newFile);
        TempFileManager.activeFiles.add(originalFile);
        TempFileManager.activeFiles.add(newFile);

        return {
            originalUri: vscode.Uri.file(originalFile),
            newUri: vscode.Uri.file(newFile),
        };
    }

    /**
     * Deletes all temporary files tracked by this instance.
     */
    public async cleanup(): Promise<void> {
        const cleanupPromises = this.tempFiles.map(async (file) => {
            try {
                await fs.unlink(file);
                TempFileManager.orphanedFiles.delete(file);
                TempFileManager.activeFiles.delete(file);
            } catch (error) {
                // Ignore errors if file doesn't exist (already cleaned up)
                if (error instanceof Error && 'code' in error && error.code !== 'ENOENT') {
                    console.error(`Failed to delete temp file ${file}:`, error);
                }
            }
        });
        await Promise.all(cleanupPromises);
        this.tempFiles = [];
    }

    /**
     * A static method to clean up any tracked temporary files that might have been
     * left over if the normal cleanup flow was interrupted.
     * Typically called on extension deactivation.
     */
    public static async cleanupAll(): Promise<void> {
        const filesToClean = Array.from(this.orphanedFiles).filter(file => !this.activeFiles.has(file));
        if (filesToClean.length > 0) {
            console.log(`Treehouse Code Completer: Cleaning up ${filesToClean.length} orphaned temp files.`);
        }
        const cleanupPromises = filesToClean.map(async (file) => {
            try {
                await fs.unlink(file);
                this.orphanedFiles.delete(file);
                this.activeFiles.delete(file);
            } catch (error) {
                 if (error instanceof Error && 'code' in error && error.code !== 'ENOENT') {
                    console.error(`Failed to delete orphaned temp file ${file}:`, error);
                }
            }
        });
        await Promise.all(cleanupPromises);
    }
}