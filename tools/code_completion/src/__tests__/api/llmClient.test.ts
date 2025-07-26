// The MockAPIError class must be defined BEFORE the jest.mock call that uses it.
export class MockAPIError extends Error {
    status?: number;
    constructor(message?: string, status?: number) {
        super(message);
        this.name = 'APIError';
        this.status = status;
    }
}

import { generateCode, testApiConnection, playgroundChat } from '../../api/llmClient';
import { getActiveAiServiceConfig, AiServiceConfig } from '../../config/configuration';
import { GenerationContext } from '../../types';
import * as vscode from 'vscode';


const mockCreate = jest.fn();

jest.mock('openai', () => {
    const mOpenAI = jest.fn().mockImplementation(() => {
        return {
            chat: {
                completions: {
                    create: mockCreate
                }
            }
        };
    });
    (mOpenAI as any).APIError = MockAPIError;
    return mOpenAI;
});

// Mock dependencies
jest.mock('../../config/configuration');
jest.mock('../../utils/logger');
jest.mock('../../util/i18n', () => ({
    t: jest.fn((key, options) => {
        // For test connection messages, return specific keys based on the actual implementation
        if (key === 'llmClient.testConnection.success') return 'llmClient.testConnection.success';
        if (key === 'llmClient.testConnection.unexpectedResponse') {
            return options?.response ? 
                `llmClient.testConnection.unexpectedResponse` : 
                'llmClient.testConnection.unexpectedResponse';
        }
        if (key === 'llmClient.testConnection.unknownError') {
            return options?.message ? 
                `llmClient.testConnection.unknownError` : 
                'llmClient.testConnection.unknownError';
        }
        if (key === 'llmClient.playground.communicationError') {
            return options?.message ? 
                `llmClient.playground.communicationError` : 
                'llmClient.playground.communicationError';
        }
        if (key === 'llmClient.requestTimeout') {
            return options?.seconds ? 
                `llmClient.requestTimeout` : 
                'llmClient.requestTimeout';
        }
        if (key === 'llmClient.apiError') {
            return options?.status && options?.message ? 
                `llmClient.apiError` : 
                'llmClient.apiError';
        }
        if (key === 'llmClient.communicationError') {
            return options?.message ? 
                `llmClient.communicationError` : 
                'llmClient.communicationError';
        }
        if (key === 'llmClient.playground.timeout') {
            return options?.seconds ? 
                `llmClient.playground.timeout` : 
                'llmClient.playground.timeout';
        }
        if (key === 'llmClient.playground.apiError') {
            return options?.status && options?.name && options?.message ? 
                `llmClient.playground.apiError` : 
                'llmClient.playground.apiError';
        }
        if (key === 'generateCode.noActiveService') return 'generateCode.noActiveService';
        if (key === 'generateCode.cancelled') return 'generateCode.cancelled';
        if (key === 'llmClient.testConnection.prompt') return 'test';
        
        // Default fallback
        return key;
    }),
}));


jest.mock('vscode', () => ({
    window: {
        createOutputChannel: jest.fn(() => ({
            appendLine: jest.fn(),
            show: jest.fn(),
        })),
    },
    workspace: {
        getConfiguration: jest.fn()
    }
}));

describe('llmClient', () => {
    const mockGetConfiguration = {
        get: jest.fn()
    };
    // const mockOpenAIInstance = new (OpenAI as any)();

    beforeEach(() => {
        jest.clearAllMocks();
        (vscode.workspace.getConfiguration as jest.Mock).mockReturnValue(mockGetConfiguration);
        mockGetConfiguration.get.mockImplementation((key: string) => {
            if (key === 'prompt.systemMessage') return 'Test system message';
            if (key === 'prompt.rule') return 'Test rule';
            if (key === 'output.streamingResults') return true;
            return undefined;
        });
        // (t as jest.Mock).mockImplementation(key => key); // Simple mock for t
    });

    describe('generateCode', () => {
        const mockContext: GenerationContext = {
            editor: {} as any,
            selection: {} as any,
            selectedText: 'const x = 1;',
            filePath: '/test/file.js',
            fileExtension: '.js',
            fullFileContent: 'const x = 1;\nconsole.log(x);',
            smartContext: null,
            importBlock: null
        };

        it('should throw error when no active service is configured', async () => {
            (getActiveAiServiceConfig as jest.Mock).mockReturnValue(null);
            
            await expect(generateCode('test instruction', mockContext))
                .rejects
                .toThrow('generateCode.noActiveService');
        });

        it('should call OpenAI API and return raw content', async () => {
            const mockServiceConfig: AiServiceConfig = {
                name: 'test-service', key: 'test-key', base_url: 'https://api.test.com',
                model_name: 'test-model', temperature: 0.7, max_context_size: 128000,
                max_tokens: 4000, is_thinking: false, price_1M_input: 0.01,
                price_1M_output: 0.02, supports_json_output: true, timeout_seconds: 60
            };
            
            (getActiveAiServiceConfig as jest.Mock).mockReturnValue(mockServiceConfig);
            
            const rawResponseWithTags = '<UPDATED_CODE>Hello World</UPDATED_CODE>';
            const mockStream = {
                [Symbol.asyncIterator]: async function* () {
                    yield { choices: [{ delta: { content: rawResponseWithTags }, finish_reason: 'stop' }] };
                }
            };
            
            mockCreate.mockResolvedValue(mockStream);
            
            const result = await generateCode('test instruction', mockContext);
            
            expect(result.code).toBe(rawResponseWithTags);
            expect(result.usage.promptTokens).toBeGreaterThan(0);
            expect(result.usage.completionTokens).toBeGreaterThan(0);
        });

        it('should handle API errors gracefully', async () => {
            const mockServiceConfig: AiServiceConfig = {
                name: 'test-service', key: 'test-key', base_url: 'https://api.test.com',
                model_name: 'test-model', temperature: 0.7, max_context_size: 128000,
                max_tokens: 4000, is_thinking: false, price_1M_input: 0.01,
                price_1M_output: 0.02, supports_json_output: true, timeout_seconds: 60
            };
            (getActiveAiServiceConfig as jest.Mock).mockReturnValue(mockServiceConfig);
            
            mockCreate.mockRejectedValue(new Error('API Error'));
            
            await expect(generateCode('test instruction', mockContext))
                .rejects
                .toThrow(/llmClient.communicationError/);
        });
    });

    describe('testApiConnection', () => {
        const mockServiceConfig: AiServiceConfig = {
            name: 'test-service', key: 'test-key', base_url: 'https://api.test.com',
            model_name: 'test-model', temperature: 0.7, max_context_size: 128000,
            max_tokens: 4000, is_thinking: false, price_1M_input: 0.01,
            price_1M_output: 0.02, supports_json_output: true, timeout_seconds: 15
        };

        it('should return success for valid connection', async () => {
            mockCreate.mockResolvedValue({
                choices: [{ message: { content: 'test' } }]
            });
            
            const result = await testApiConnection(mockServiceConfig);
            
            expect(result.success).toBe(true);
            expect(result.message).toBe('llmClient.testConnection.success');
        });

        it('should return failure for invalid response', async () => {
            mockCreate.mockResolvedValue({
                choices: [{ message: { content: 'invalid' } }]
            });
            
            const result = await testApiConnection(mockServiceConfig);
            
            expect(result.success).toBe(false);
            expect(result.message).toBe('llmClient.testConnection.unexpectedResponse');
        });

        it('should handle API errors gracefully', async () => {
            mockCreate.mockRejectedValue(new Error('API Error'));
            
            const result = await testApiConnection(mockServiceConfig);
            
            expect(result.success).toBe(false);
            expect(result.message).toBe('llmClient.testConnection.unknownError');
        });
    });

    describe('playgroundChat', () => {
        const mockServiceConfig: AiServiceConfig = {
            name: 'test-service', key: 'test-key', base_url: 'https://api.test.com',
            model_name: 'test-model', temperature: 0.7, max_context_size: 128000,
            max_tokens: 4000, is_thinking: false, price_1M_input: 0.01,
            price_1M_output: 0.02, supports_json_output: true, timeout_seconds: 60
        };

        it('should send prompt and return response', async () => {
            const mockStream = {
                [Symbol.asyncIterator]: async function* () {
                    yield { choices: [{ delta: { content: 'Hello' }, finish_reason: null }] };
                    yield { choices: [{ delta: { content: ' Playground' }, finish_reason: 'stop' }] };
                }
            };
            
            mockCreate.mockResolvedValue(mockStream);
            
            const result = await playgroundChat('test prompt', mockServiceConfig);
            
            expect(result.response).toBe('Hello Playground');
            expect(result.usage.promptTokens).toBeGreaterThan(0);
            expect(result.usage.completionTokens).toBeGreaterThan(0);
            expect(result.usage.model).toBe('test-model');
        });

        it('should handle API errors gracefully', async () => {
            mockCreate.mockRejectedValue(new Error('API Error'));
            
            const result = await playgroundChat('test prompt', mockServiceConfig);
            
            expect(result.response).toContain('llmClient.playground.communicationError');
            expect(result.usage.totalTokens).toBe(0);
        });
    });
});