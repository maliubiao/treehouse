/**
 * Integration test for JavaScript Container Reader with actual container files
 */

const fs = require('fs').promises;
const path = require('path');

// Mock Web Crypto API for Node.js environment
if (typeof crypto === 'undefined') {
    global.crypto = require('crypto').webcrypto;
}

// Import the container reader
const { DataContainerReader, FileManager, EventType } = require('../../src/context_tracer/static/js/container-reader.js');

// Mock msgpack for Node.js
const msgpack = require('@msgpack/msgpack');

// Mock the dynamic import in the container reader
const originalDecodeMsgPack = DataContainerReader.prototype._decodeMsgPack;
DataContainerReader.prototype._decodeMsgPack = async function(data) {
    return msgpack.decode(data);
};

describe('Container Reader Integration', () => {
    const containerPath = path.join(__dirname, '../../src/tracer-logs/trace_data.bin');
    const keyHex = 'cc27d9c1761735f0234a2297c9637b86f7db349fd4bdfb77052ec66eb1c418f0';
    
    let containerData = null;
    let keyBytes = null;

    beforeAll(async () => {
        try {
            // Read the container file
            const buffer = await fs.readFile(containerPath);
            containerData = buffer.buffer;
            
            // Convert hex key to bytes
            keyBytes = new Uint8Array(
                keyHex.match(/[0-9a-f]{2}/gi).map(h => parseInt(h, 16))
            );
        } catch (error) {
            console.warn('Could not read container file for integration tests:', error.message);
        }
    });

    test('should read actual container file', async () => {
        if (!containerData) {
            console.warn('Skipping integration test - no container file found');
            return;
        }

        const reader = new DataContainerReader(containerData, keyBytes);
        
        await expect(reader.open()).resolves.not.toThrow();
        
        expect(reader.fileManager).toBeInstanceOf(FileManager);
        expect(reader._formatVersion).toBeGreaterThanOrEqual(3);
        
        // Test that we can iterate through events
        let eventCount = 0;
        for await (const event of reader.events()) {
            eventCount++;
            expect(event).toHaveProperty('event_type');
            expect(event).toHaveProperty('timestamp');
            expect(event).toHaveProperty('file_id');
            
            // Basic event validation
            expect(typeof event.event_type).toBe('number');
            expect(typeof event.timestamp).toBe('number');
            expect(typeof event.file_id).toBe('number');
            
            // Stop after a few events to avoid long test times
            if (eventCount >= 10) {
                break;
            }
        }
        
        expect(eventCount).toBeGreaterThan(0);
        console.log(`Read ${eventCount} events from container`);
    });

    test('should handle V4 format with FileManager at end', async () => {
        if (!containerData) {
            console.warn('Skipping V4 format test - no container file found');
            return;
        }

        const reader = new DataContainerReader(containerData, keyBytes);
        await reader.open();
        
        // Check if this is V4 format
        if (reader._formatVersion >= 4) {
            expect(reader._fileManagerPosition).toBeGreaterThan(0);
            
            // Verify FileManager was loaded from the correct position
            expect(reader.fileManager).toBeDefined();
            expect(reader.fileManager._fileToId.size).toBeGreaterThan(0);
            
            console.log(`V4 container with ${reader.fileManager._fileToId.size} file mappings`);
        }
    });

    test('should properly map file IDs to paths', async () => {
        if (!containerData) {
            console.warn('Skipping file mapping test - no container file found');
            return;
        }

        const reader = new DataContainerReader(containerData, keyBytes);
        await reader.open();
        
        // Get some file mappings
        const fileManager = reader.fileManager;
        const fileIds = Array.from(fileManager._idToFile.keys()).slice(0, 5);
        
        for (const fileId of fileIds) {
            const filePath = fileManager.getPath(fileId);
            expect(typeof filePath).toBe('string');
            expect(filePath).not.toBe('');
            
            // Verify the mapping is consistent
            const expectedId = fileManager.getId(filePath);
            expect(expectedId).toBe(fileId);
        }
    });

    test('should handle event parsing correctly', async () => {
        if (!containerData) {
            console.warn('Skipping event parsing test - no container file found');
            return;
        }

        const reader = new DataContainerReader(containerData, keyBytes);
        await reader.open();
        
        let callEvents = 0;
        let returnEvents = 0;
        let lineEvents = 0;
        
        for await (const event of reader.events()) {
            switch (event.event_type) {
                case EventType.CALL:
                    callEvents++;
                    // CALL events should have function data
                    expect(Array.isArray(event.data)).toBe(true);
                    expect(event.data.length).toBeGreaterThanOrEqual(2);
                    break;
                case EventType.RETURN:
                    returnEvents++;
                    // RETURN events should have return data
                    expect(Array.isArray(event.data)).toBe(true);
                    expect(event.data.length).toBeGreaterThanOrEqual(3);
                    break;
                case EventType.LINE:
                    lineEvents++;
                    // LINE events should have line content
                    expect(Array.isArray(event.data)).toBe(true);
                    expect(event.data.length).toBeGreaterThanOrEqual(3);
                    break;
            }
            
            // Stop after reasonable number of events
            if (callEvents + returnEvents + lineEvents >= 20) {
                break;
            }
        }
        
        console.log(`Events parsed: ${callEvents} calls, ${returnEvents} returns, ${lineEvents} lines`);
        expect(callEvents + returnEvents + lineEvents).toBeGreaterThan(0);
    });
});

// Clean up mock after tests
afterAll(() => {
    DataContainerReader.prototype._decodeMsgPack = originalDecodeMsgPack;
});