import { generateCode, testApiConnection, playgroundChat } from '../../api/llmClient';
import { getActiveAiServiceConfig, AiServiceConfig } from '../../config/configuration';
import { GenerationContext } from '../../types';
import * as vscode from 'vscode';
import OpenAI from 'openai';

// Mock dependencies
jest.mock('../../config/configuration');
jest.mock('../../utils/logger');

// This mock is critical. It ensures that:
// 1. All instances of the OpenAI client share the same `create` function, so tests can mock it.
// 2. The `OpenAI.APIError` static property exists, so `instanceof` checks don't throw.
jest.mock('openai', () => {
    const mockCreate = jest.fn();

    class MockAPIError extends Error {
        status?: number;
        constructor(message?: string, status?: number) {
            super(message);
            this.name = 'APIError';
            this.status = status;
        }
    }

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

    beforeEach(() => {
        jest.clearAllMocks();
        (vscode.workspace.getConfiguration as jest.Mock).mockReturnValue(mockGetConfiguration);
        mockGetConfiguration.get.mockImplementation((key: string) => {
            if (key === 'prompt.systemMessage') return 'Test system message';
            if (key === 'prompt.rule') return 'Test rule';
            // Make sure the streaming accumulator is enabled for tests to cover that path
            if (key === 'output.streamingResults') return true;
            return undefined;
        });
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
                .toThrow('No active AI service configured.');
        });

        it('should call OpenAI API and return raw content', async () => {
            const mockServiceConfig = {
                name: 'test-service',
                key: 'test-key',
                base_url: 'https://api.test.com',
                model_name: 'test-model',
                temperature: 0.7,
                max_context_size: 128000,
                max_tokens: 4000,
                is_thinking: false,
                price_1M_input: 0.01,
                price_1M_output: 0.02,
                supports_json_output: true,
                timeout_seconds: 60
            };
            
            (getActiveAiServiceConfig as jest.Mock).mockReturnValue(mockServiceConfig);
            
            const rawResponseWithTags = '<UPDATED_CODE>Hello World</UPDATED_CODE>';
            const mockStream = {
                [Symbol.asyncIterator]: jest.fn().mockImplementation(() => {
                    let called = false;
                    return {
                        next: jest.fn().mockImplementation(() => {
                            if (!called) {
                                called = true;
                                return Promise.resolve({
                                    done: false,
                                    value: {
                                        choices: [{
                                            delta: { content: rawResponseWithTags },
                                            finish_reason: 'stop'
                                        }]
                                    }
                                });
                            }
                            return Promise.resolve({ done: true });
                        })
                    };
                })
            };
            
            const mockOpenAIInstance = new (OpenAI as any)();
            mockOpenAIInstance.chat.completions.create.mockResolvedValue(mockStream);
            
            const result = await generateCode('test instruction', mockContext);
            
            expect(result.code).toBe(rawResponseWithTags);
            expect(result.usage.promptTokens).toBeGreaterThan(0);
            expect(result.usage.completionTokens).toBeGreaterThan(0);
        });


        it('should handle API errors gracefully', async () => {
            const mockServiceConfig = {
                name: 'test-service',
                key: 'test-key',
                base_url: 'https://api.test.com',
                model_name: 'test-model',
                temperature: 0.7,
                max_context_size: 128000,
                max_tokens: 4000,
                is_thinking: false,
                price_1M_input: 0.01,
                price_1M_output: 0.02,
                supports_json_output: true,
                timeout_seconds: 60
            };
            
            (getActiveAiServiceConfig as jest.Mock).mockReturnValue(mockServiceConfig);
            
            const mockOpenAIInstance = new (OpenAI as any)();
            mockOpenAIInstance.chat.completions.create.mockRejectedValue(new Error('API Error'));
            
            await expect(generateCode('test instruction', mockContext))
                .rejects
                .toThrow(/Failed to communicate with the API/);
        });
    });

    describe('testApiConnection', () => {
        it('should return success for valid connection', async () => {
            const mockServiceConfig: AiServiceConfig = {
                name: 'test-service',
                key: 'test-key',
                base_url: 'https://api.test.com',
                model_name: 'test-model',
                temperature: 0.7,
                max_context_size: 128000,
                max_tokens: 4000,
                is_thinking: false,
                price_1M_input: 0.01,
                price_1M_output: 0.02,
                supports_json_output: true,
                timeout_seconds: 15
            };
            
            const mockOpenAIInstance = new (OpenAI as any)();
            mockOpenAIInstance.chat.completions.create.mockResolvedValue({
                choices: [{
                    message: {
                        content: 'test'
                    }
                }]
            });
            
            const result = await testApiConnection(mockServiceConfig);
            
            expect(result.success).toBe(true);
            expect(result.message).toBe('Connection successful.');
        });

        it('should return failure for invalid response', async () => {
            const mockServiceConfig: AiServiceConfig = {
                name: 'test-service',
                key: 'test-key',
                base_url: 'https://api.test.com',
                model_name: 'test-model',
                temperature: 0.7,
                max_context_size: 128000,
                max_tokens: 4000,
                is_thinking: false,
                price_1M_input: 0.01,
                price_1M_output: 0.02,
                supports_json_output: true,
                timeout_seconds: 15
            };
            
            const mockOpenAIInstance = new (OpenAI as any)();
            mockOpenAIInstance.chat.completions.create.mockResolvedValue({
                choices: [{
                    message: {
                        content: 'invalid'
                    }
                }]
            });
            
            const result = await testApiConnection(mockServiceConfig);
            
            expect(result.success).toBe(false);
            expect(result.message).toContain('Received an unexpected response');
        });

        it('should handle API errors gracefully', async () => {
            const mockServiceConfig: AiServiceConfig = {
                name: 'test-service',
                key: 'test-key',
                base_url: 'https://api.test.com',
                model_name: 'test-model',
                temperature: 0.7,
                max_context_size: 128000,
                max_tokens: 4000,
                is_thinking: false,
                price_1M_input: 0.01,
                price_1M_output: 0.02,
                supports_json_output: true,
                timeout_seconds: 15
            };
            
            const mockOpenAIInstance = new (OpenAI as any)();
            mockOpenAIInstance.chat.completions.create.mockRejectedValue(new Error('API Error'));
            
            const result = await testApiConnection(mockServiceConfig);
            
            expect(result.success).toBe(false);
            expect(result.message).toContain('An unknown error occurred');
        });
    });

    describe('playgroundChat', () => {
        it('should send prompt and return response', async () => {
            const mockServiceConfig: AiServiceConfig = {
                name: 'test-service',
                key: 'test-key',
                base_url: 'https://api.test.com',
                model_name: 'test-model',
                temperature: 0.7,
                max_context_size: 128000,
                max_tokens: 4000,
                is_thinking: false,
                price_1M_input: 0.01,
                price_1M_output: 0.02,
                supports_json_output: true,
                timeout_seconds: 60
            };
            
            const mockStream = {
                [Symbol.asyncIterator]: jest.fn().mockImplementation(() => {
                    let callCount = 0;
                    return {
                        next: jest.fn().mockImplementation(() => {
                            callCount++;
                            if (callCount === 1) {
                                return Promise.resolve({
                                    done: false,
                                    value: {
                                        choices: [{
                                            delta: { content: 'Hello' },
                                            finish_reason: null
                                        }]
                                    }
                                });
                            }
                            if (callCount === 2) {
                                return Promise.resolve({
                                    done: false,
                                    value: {
                                        choices: [{
                                            delta: { content: ' Playground' },
                                            finish_reason: 'stop'
                                        }]
                                    }
                                });
                            }
                            return Promise.resolve({ done: true });
                        })
                    };
                })
            };
            
            const mockOpenAIInstance = new (OpenAI as any)();
            mockOpenAIInstance.chat.completions.create.mockResolvedValue(mockStream);
            
            const result = await playgroundChat('test prompt', mockServiceConfig);
            
            expect(result.response).toBe('Hello Playground');
            expect(result.usage.promptTokens).toBeGreaterThan(0);
            expect(result.usage.completionTokens).toBeGreaterThan(0);
            expect(result.usage.totalTokens).toBeGreaterThan(0);
            expect(result.usage.model).toBe('test-model');
        });

        it('should handle API errors gracefully', async () => {
            const mockServiceConfig: AiServiceConfig = {
                name: 'test-service',
                key: 'test-key',
                base_url: 'https://api.test.com',
                model_name: 'test-model',
                temperature: 0.7,
                max_context_size: 128000,
                max_tokens: 4000,
                is_thinking: false,
                price_1M_input: 0.01,
                price_1M_output: 0.02,
                supports_json_output: true,
                timeout_seconds: 60
            };
            
            const mockOpenAIInstance = new (OpenAI as any)();
            mockOpenAIInstance.chat.completions.create.mockRejectedValue(new Error('API Error'));
            
            const result = await playgroundChat('test prompt', mockServiceConfig);
            
            expect(result.response).toContain('Failed to communicate with the API');
            expect(result.usage.promptTokens).toBe(0);
            expect(result.usage.completionTokens).toBe(0);
            expect(result.usage.totalTokens).toBe(0);
            expect(result.usage.model).toBe('test-model');
        });
    });
});