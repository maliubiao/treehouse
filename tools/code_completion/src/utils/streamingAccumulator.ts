import * as vscode from 'vscode';
import { logger } from './logger';

/**
 * Accumulates streaming results from LLM responses and provides terminal output
 */
export class StreamingAccumulator {
    private static instance: StreamingAccumulator;
    private accumulatedContent: string = '';
    private chunks: Array<{ timestamp: number; content: string }> = [];
    private isSessionActive: boolean = false;
    private sessionStartTime: number = 0;

    private constructor() {}

    /**
     * Get the singleton instance of the StreamingAccumulator
     */
    public static getInstance(): StreamingAccumulator {
        if (!StreamingAccumulator.instance) {
            StreamingAccumulator.instance = new StreamingAccumulator();
        }
        return StreamingAccumulator.instance;
    }

    /**
     * Start a new accumulation session
     */
    public startSession(): void {
        this.accumulatedContent = '';
        this.chunks = [];
        this.isSessionActive = true;
        this.sessionStartTime = Date.now();
        logger.log('Streaming accumulator session started');
    }

    /**
     * Add a chunk to the accumulation
     * @param content - The streaming chunk content
     */
    public addChunk(content: string): void {
        if (!this.isSessionActive) {
            throw new Error('Cannot add chunk to inactive streaming session');
        }

        this.chunks.push({
            timestamp: Date.now(),
            content
        });
        
        this.accumulatedContent += content;
        
        // Optionally log chunk for debugging
        const config = vscode.workspace.getConfiguration('treehouseCodeCompleter');
        if (config.get<boolean>('debug.streamingChunks', false)) {
            logger.log(`Streaming chunk (${content.length} chars): ${content.substring(0, 100)}...`);
        }
    }

    /**
     * Get the full accumulated content
     */
    public getAccumulatedContent(): string {
        return this.accumulatedContent;
    }

    /**
     * Get all chunks with timestamps
     */
    public getAllChunks(): Array<{ timestamp: number; content: string }> {
        return [...this.chunks];
    }

    /**
     * End the accumulation session and optionally output to terminal
     * @param outputToTerminal - Whether to output the accumulated content to terminal
     * @param cancelled - Whether the session was cancelled by the user
     */
    public endSession(outputToTerminal: boolean = true, cancelled: boolean = false): void {
        if (!this.isSessionActive) {
            return;
        }

        const sessionDuration = Date.now() - this.sessionStartTime;
        
        if (outputToTerminal && !cancelled) {
            this.outputToTerminal(sessionDuration);
        }

        logger.log('Streaming accumulator session ended', {
            totalChunks: this.chunks.length,
            totalCharacters: this.accumulatedContent.length,
            sessionDuration: `${sessionDuration}ms`,
            cancelled: cancelled
        });

        this.isSessionActive = false;
    }

    /**
     * Output the accumulated content to terminal
     * @param sessionDuration - Duration of the streaming session in milliseconds
     */
    private outputToTerminal(sessionDuration: number): void {
        if (!this.accumulatedContent) {
            console.log('No streaming content to display.');
            return;
        }

        // Create a formatted output
        const lines = this.accumulatedContent.split('\n');
        const timestamp = new Date().toISOString();
        
        console.log(`\n${'='.repeat(80)}`);
        console.log(`📊 STREAMING COMPLETION RESULTS`);
        console.log(`   Session Started: ${new Date(this.sessionStartTime).toLocaleTimeString()}`);
        console.log(`   Duration: ${sessionDuration}ms`);
        console.log(`   Total Chunks: ${this.chunks.length}`);
        console.log(`   Total Characters: ${this.accumulatedContent.length}`);
        console.log(`${'='.repeat(80)}`);
        console.log(`\nGenerated Content:`);
        console.log(`${'-'.repeat(40)}`);
        
        if (lines.length <= 50) {
            console.log(this.accumulatedContent);
        } else {
            // For very long content, show first and last 25 lines
            console.log(`\n[First 25 lines - total ${lines.length} lines]`);
            console.log(lines.slice(0, 25).join('\n'));
            console.log(`\n... [${lines.length - 50} lines truncated] ...`);
            console.log(`\n[Last 25 lines]`);
            console.log(lines.slice(-25).join('\n'));
            
            console.log(`\n💡 Full content available in: ~/.vscode/extensions/treehouse-code-completer/logs/streaming-content-${timestamp.split('T')[0]}.log`);
            
            // Also log to file for full content
            logger.log('Full streaming content:', { content: this.accumulatedContent });
        }
        
        console.log(`${'-'.repeat(40)}`);
        console.log(`End of streaming content\n`);
    }

    /**
     * Clear the accumulated content
     */
    public clear(): void {
        this.accumulatedContent = '';
        this.chunks = [];
    }

    /**
     * Check if a session is currently active
     */
    public isActive(): boolean {
        return this.isSessionActive;
    }
}