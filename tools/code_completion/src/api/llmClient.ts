import OpenAI from 'openai';
import { ChatCompletionMessageParam, ChatCompletionCreateParamsStreaming, ChatCompletionCreateParamsNonStreaming } from 'openai/resources/chat';
import { getActiveAiServiceConfig, AiServiceConfig } from '../config/configuration';
import { logger } from '../utils/logger';
import * as vscode from 'vscode';
import { GenerationContext } from '../types';
import { t } from '../util/i18n';
import { HttpsProxyAgent } from 'https-proxy-agent';
import { Agent } from 'http';
import { StreamingAccumulator } from '../utils/streamingAccumulator';

/**
 * Retrieves the HttpsProxyAgent based on VS Code's proxy settings.
 * This allows the OpenAI client to respect the user's network configuration.
 * @returns An HttpsProxyAgent instance if a proxy is configured, otherwise undefined.
 */
function getHttpsProxyAgent(): Agent | undefined {
    const proxyUrl = vscode.workspace.getConfiguration('http').get<string>('proxy');
    if (proxyUrl) {
        logger.log(`Using proxy server: ${proxyUrl}`);
        return new HttpsProxyAgent(proxyUrl);
    }
    return undefined;
}

/**
 * Initializes the OpenAI client with configuration from the active service.
 * It automatically applies VS Code's proxy settings.
 * Throws an error if the API key is missing.
 */
function initializeClient(serviceConfig: AiServiceConfig): OpenAI {
    if (!serviceConfig || !serviceConfig.key) {
        throw new Error(t('llmClient.apiKeyRequired'));
    }
    
    const httpAgent = getHttpsProxyAgent();

    return new OpenAI({
        apiKey: serviceConfig.key,
        baseURL: serviceConfig.base_url,
        httpAgent,
    });
}

/**
 * Builds the message payload for the API call for code generation.
 * It uses a tagged, human-readable format for the prompt.
 * @param instruction - The user's instruction.
 * @param context - The GenerationContext object containing all necessary information.
 * @returns An array of messages for the API call.
 */
function buildMessages(
    instruction: string,
    context: GenerationContext
): ChatCompletionMessageParam[] {
    const config = vscode.workspace.getConfiguration('treehouseCodeCompleter');
    const systemMessage = config.get<string>('prompt.systemMessage', t('llmClient.defaultSystemPrompt'));
    const rule = config.get<string>('prompt.rule', '');

    let contextBlock = '';

    if (context.fullFileContent) {
        contextBlock = `
---
Full File Content for Context:
\`\`\`${context.fileExtension.slice(1)}
${context.fullFileContent}
\`\`\`
`;
    } else if (context.smartContext) {
        const { previousSiblingText, nextSiblingText } = context.smartContext;
        const smartContextParts: string[] = [];

        if (previousSiblingText) {
            smartContextParts.push(`<<< PREVIOUS_SIBLING >>>\n${previousSiblingText}\n<<< END_PREVIOUS_SIBLING >>>`);
        }
        if (nextSiblingText) {
            smartContextParts.push(`<<< NEXT_SIBLING >>>\n${nextSiblingText}\n<<< END_NEXT_SIBLING >>>`);
        }

        if (smartContextParts.length > 0) {
            contextBlock = `
---
Surrounding Code Context:
${smartContextParts.join('\n\n')}
`;
        }
    }
    
    const codeBlockPrompt = context.selectedText 
        ? `Code Block to Modify:\n\`\`\`${context.fileExtension.slice(1) || 'text'}\n${context.selectedText}\n\`\`\``
        : `User has not selected any code. You are generating new code to be inserted at the user's cursor position within the file context provided.`;

    const userPrompt = `
File Path: ${context.filePath}

---
Custom Rule:
${rule}
---
${contextBlock}
---
${codeBlockPrompt}
---
User Instruction:
${instruction}
`;

    return [
        { role: 'system', content: systemMessage },
        { role: 'user', content: userPrompt }
    ];
}

/**
 * Token usage information for billing purposes
 */
export interface TokenUsage {
    promptTokens: number;
    completionTokens: number;
    totalTokens: number;
    cost?: number;
    model: string;
}


/**
 * Calculate cost based on token usage and user-configured pricing
 */
function calculateCost(promptTokens: number, completionTokens: number): number {
    const activeService = getActiveAiServiceConfig();
    if (!activeService || activeService.price_1M_input === undefined || activeService.price_1M_output === undefined) {
        return 0;
    }
    
    const inputCost = (promptTokens / 1000000) * activeService.price_1M_input;
    const outputCost = (completionTokens / 1000000) * activeService.price_1M_output;
    return inputCost + outputCost;
}

/**
 * Generates code using the configured LLM API with streaming support and token usage tracking.
 * 
 * @param instruction - The user's instruction for modification.
 * @param context - The full generation context, including code, file info, etc.
 * @param onProgress - Callback function to report streaming progress (optional)
 * @param cancellationToken - Token to signal cancellation of the operation (optional)
 * @returns Object containing the raw generated code from the model and token usage information.
 */
export async function generateCode(
    instruction: string, 
    context: GenerationContext,
    onProgress?: (tokenCount: number, currentText: string) => void,
    cancellationToken?: { isCancellationRequested: boolean }
): Promise<{ code: string; usage: TokenUsage }> {
    const activeService = getActiveAiServiceConfig();
    if (!activeService) {
        throw new Error(t("generateCode.noActiveService"));
    }
    
    const openai = initializeClient(activeService);

    const messages = buildMessages(instruction, context);
    
    const { key, ...serviceToLog } = activeService;
    logger.log('Using AI Service for code generation:', { ...serviceToLog, key: '********' });
    logger.log('Sending prompt:', { messages });

    const abortController = new AbortController();
    
    const completionOptions: ChatCompletionCreateParamsStreaming = {
        model: activeService.model_name,
        messages: messages,
        temperature: activeService.temperature,
        stream: true,
    };
    logger.log('Sending OpenAI Chat Completion Request with options:', completionOptions);

    const streamingAccumulator = StreamingAccumulator.getInstance();
    const config = vscode.workspace.getConfiguration('treehouseCodeCompleter');
    const enableStreamingAccumulator = config.get<boolean>('output.streamingResults', true);
    
    try {
        const timeoutMs = (activeService.timeout_seconds || 60) * 1000;
        
        if (enableStreamingAccumulator) {
            streamingAccumulator.startSession();
        }
        
        const stream = await openai.chat.completions.create(
            completionOptions, 
            { 
                timeout: timeoutMs,
                signal: abortController.signal
            }
        );
        let accumulatedContent = '';
        let tokenCount = 0;
        let isComplete = false;

        for await (const chunk of stream) {
            if (cancellationToken?.isCancellationRequested) {
                abortController.abort();
                // This will cause the stream to throw an error, which is caught below
            }
            
            const content = chunk.choices[0]?.delta?.content || '';
            const finishReason = chunk.choices[0]?.finish_reason;
            
            if (content) {
                accumulatedContent += content;
                
                if (enableStreamingAccumulator) {
                    streamingAccumulator.addChunk(content);
                }
                
                tokenCount += content.split(/\s+/).length;
                
                if (onProgress) {
                    onProgress(tokenCount, accumulatedContent);
                }
            }
            
            if (finishReason === 'stop' || finishReason === 'length') {
                isComplete = true;
                break;
            }
        }
        
        if (!isComplete && !cancellationToken?.isCancellationRequested) {
            logger.warn("Stream finished without a 'stop' or 'length' reason.");
        }

        logger.log('Raw accumulated content from stream:', { content: accumulatedContent });

        const estimatedPromptTokens = Math.ceil(messages.reduce((total, msg) => total + (typeof msg.content === 'string' ? msg.content.length : 0), 0) / 4);
        const estimatedCompletionTokens = Math.ceil(accumulatedContent.length / 4);
        
        const usage: TokenUsage = {
            promptTokens: estimatedPromptTokens,
            completionTokens: estimatedCompletionTokens,
            totalTokens: estimatedPromptTokens + estimatedCompletionTokens,
            cost: calculateCost(estimatedPromptTokens, estimatedCompletionTokens),
            model: activeService.model_name,
        };

        logger.log('Estimated token usage:', usage);
        
        if (enableStreamingAccumulator) {
            streamingAccumulator.endSession(true, cancellationToken?.isCancellationRequested);
        }
        
        return { code: accumulatedContent, usage };
    } catch (error) {
        const isCancellation = (error instanceof Error && error.name === 'AbortError') || (cancellationToken?.isCancellationRequested ?? false);

        if (enableStreamingAccumulator) {
            streamingAccumulator.endSession(!isCancellation, isCancellation);
        }
        
        if (isCancellation) {
            throw new Error(t('generateCode.cancelled'));
        }

        const errorDetails = {
            message: error instanceof Error ? error.message : String(error),
            stack: error instanceof Error ? error.stack : undefined,
            name: error instanceof Error ? error.name : 'UnknownError',
        };
        
        logger.error('API Error Details:', errorDetails);
        
        if (errorDetails.name === 'TimeoutError') {
             throw new Error(t(`llmClient.requestTimeout`, { seconds: activeService.timeout_seconds || 60, stack: errorDetails.stack ?? 'N/A' }));
        }
        if (error instanceof OpenAI.APIError) {
            throw new Error(t(`llmClient.apiError`, { status: error.status, message: error.message, stack: errorDetails.stack ?? 'N/A' }));
        }
        throw new Error(t(`llmClient.communicationError`, { message: errorDetails.message, stack: errorDetails.stack ?? 'N/A' }));
    }
}

/**
 * Sends a prompt to a specified LLM service for a generic chat interaction in the playground.
 *
 * @param prompt - The user's prompt.
 * @param serviceConfig - The configuration of the AI service to use.
 * @returns Object containing response and token usage information.
 */
export async function playgroundChat(
    prompt: string, 
    serviceConfig: AiServiceConfig
): Promise<{ response: string; usage: TokenUsage }> {
    const openai = initializeClient(serviceConfig);
    const { key, ...serviceToLog } = serviceConfig;
    logger.log('Using AI Service for playground:', { ...serviceToLog, key: '********' });
    logger.log('Sending playground prompt:', { prompt });

    const messages: ChatCompletionMessageParam[] = [{ role: 'user', content: prompt }];
    
    const completionOptions: ChatCompletionCreateParamsStreaming = {
        model: serviceConfig.model_name,
        messages: messages,
        temperature: serviceConfig.temperature,
        stream: true,
    };
    logger.log('Sending OpenAI Chat Completion Request from playground with options:', completionOptions);

    try {
        const timeoutMs = (serviceConfig.timeout_seconds || 60) * 1000;
        
        const stream = await openai.chat.completions.create(completionOptions, { timeout: timeoutMs });
        
        let accumulatedContent = '';

        for await (const chunk of stream) {
            accumulatedContent += chunk.choices[0]?.delta?.content || '';
        }

        logger.log('Raw accumulated content from playground stream:', { content: accumulatedContent });

        const estimatedPromptTokens = Math.ceil(prompt.length / 4);
        const estimatedCompletionTokens = Math.ceil(accumulatedContent.length / 4);
        
        const usage: TokenUsage = {
            promptTokens: estimatedPromptTokens,
            completionTokens: estimatedCompletionTokens,
            totalTokens: estimatedPromptTokens + estimatedCompletionTokens,
            cost: calculateCost(estimatedPromptTokens, estimatedCompletionTokens),
            model: serviceConfig.model_name,
        };

        return { response: accumulatedContent, usage };
    } catch (error) {
        const errorDetails = {
            message: error instanceof Error ? error.message : String(error),
            stack: error instanceof Error ? error.stack : 'N/A',
            name: error instanceof Error ? error.name : 'UnknownError',
        };
        
        logger.error('Playground API Error Details:', errorDetails);
        
        const usage: TokenUsage = {
            promptTokens: 0,
            completionTokens: 0,
            totalTokens: 0,
            cost: 0,
            model: serviceConfig.model_name,
        };
        
        if (errorDetails.name === 'TimeoutError') {
             return { response: t('llmClient.playground.timeout', { seconds: serviceConfig.timeout_seconds || 60, stack: errorDetails.stack }), usage };
        }
        if (error instanceof OpenAI.APIError) {
            return { response: t('llmClient.playground.apiError', { status: error.status, name: error.name, message: error.message, stack: errorDetails.stack }), usage };
        }
        return { response: t('llmClient.playground.communicationError', { message: errorDetails.message, stack: errorDetails.stack }), usage };
    }
}


/**
 * Tests the connection to the API using the provided configuration.
 * @param apiConfig - The API configuration to test.
 * @returns An object indicating success and a message.
 */
export async function testApiConnection(apiConfig: AiServiceConfig): Promise<{ success: boolean; message: string }> {
    logger.log('Testing API connection with config:', { ...apiConfig, key: '********' });
    
    try {
        const client = initializeClient(apiConfig);
        
        const timeoutMs = (apiConfig.timeout_seconds || 15) * 1000;
        const testPrompt = t("llmClient.testConnection.prompt");
        logger.log(`Sending test prompt: "${testPrompt}" to model: ${apiConfig.model_name}`);

        const messages: ChatCompletionMessageParam[] = [{ role: 'user', content: testPrompt }];

        const params: ChatCompletionCreateParamsNonStreaming = {
            model: apiConfig.model_name,
            messages: messages,
            max_tokens: 5,
        };

        const response = await client.chat.completions.create(params, { timeout: timeoutMs });
        
        logger.log('Received test response from API:', response);
        const content = response.choices[0]?.message?.content?.toLowerCase().trim();

        if (content === 'test') {
            logger.log('Test connection successful.');
            return { success: true, message: t('llmClient.testConnection.success') };
        } else {
            logger.warn('Test connection failed: Unexpected response.', { response: content });
            return { success: false, message: t('llmClient.testConnection.unexpectedResponse', { response: content ?? 'null' }) };
        }
    } catch (error) {
         const errorDetails = {
            message: error instanceof Error ? error.message : String(error),
            stack: error instanceof Error ? error.stack : 'N/A',
            name: error instanceof Error ? error.name : 'UnknownError',
        };
        
        logger.error('Test Connection Error Details:', errorDetails);
        
        if (errorDetails.name === 'TimeoutError') {
            return { success: false, message: t('llmClient.testConnection.timeout', { seconds: apiConfig.timeout_seconds || 15, stack: errorDetails.stack }) };
        }
        if (error instanceof OpenAI.APIError) {
            return { success: false, message: t('llmClient.testConnection.apiError', { status: error.status, name: error.name, message: error.message, stack: errorDetails.stack }) };
        }
        return { success: false, message: t('llmClient.testConnection.unknownError', { message: errorDetails.message, stack: errorDetails.stack }) };
    }
}