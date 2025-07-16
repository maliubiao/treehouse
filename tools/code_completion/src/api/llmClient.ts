import OpenAI from 'openai';
import { ChatCompletionMessageParam } from 'openai/resources/chat';
import { getActiveAiServiceConfig, AiServiceConfig } from '../config/configuration';
import { logger } from '../utils/logger';
import * as vscode from 'vscode';
import { GenerationContext } from '../types';
// The user needs to manually install this dependency by running: npm install https-proxy-agent
import { HttpsProxyAgent } from 'https-proxy-agent';
import { Agent } from 'http';

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
        throw new Error('AI service configuration with an API key is required.');
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
    const systemMessage = config.get<string>('prompt.systemMessage', "You are an expert software architect and programmer. Your task is to rewrite the provided code block according to the instruction, using the context of the file.\n\nIMPORTANT: Your response MUST be wrapped with these exact tags:\n<CODE_GENERATED>\n[your modified code here]\n</CODE_GENERATED>\n\nInclude ONLY the modified code block between these tags, no explanations or additional text.");
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
    
    const userPrompt = `
File Path: ${context.filePath}

---
Custom Rule:
${rule}
---
${contextBlock}
---
Code Block to Modify:
\`\`\`${context.fileExtension.slice(1)}
${context.selectedText}
\`\`\`
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
 * Cleans the AI's response by extracting code from CODE_GENERATED tags.
 * Uses robust stack-based parsing to handle nested tags and malformed responses.
 * Includes comprehensive error handling for unbalanced tags and edge cases.
 */
function cleanResponse(responseText: string): string {
    let cleanedText = responseText.trim();
    
    if (!cleanedText) {
        return '';
    }
    
    const startTag = '<CODE_GENERATED>';
    const endTag = '</CODE_GENERATED>';
    
    // Phase 1: Validate basic tag presence
    const firstStart = cleanedText.indexOf(startTag);
    const firstEnd = cleanedText.indexOf(endTag);
    
    // Quick validation: if no tags found, skip to fallback
    if (firstStart === -1 && firstEnd === -1) {
        return handleFallbackExtraction(cleanedText);
    }
    
    // Phase 2: Robust stack-based parsing with error handling
    let stack = 0;
    let outermostStart = -1;
    let outermostEnd = -1;
    let contentStart = -1;
    let positions = [];
    
    // Collect all tag positions
    let pos = 0;
    while (pos < cleanedText.length) {
        const startMatch = cleanedText.indexOf(startTag, pos);
        const endMatch = cleanedText.indexOf(endTag, pos);
        
        if (startMatch === -1 && endMatch === -1) break;
        
        if (startMatch !== -1 && (endMatch === -1 || startMatch < endMatch)) {
            positions.push({ type: 'start', pos: startMatch });
            pos = startMatch + startTag.length;
        } else if (endMatch !== -1) {
            positions.push({ type: 'end', pos: endMatch });
            pos = endMatch + endTag.length;
        } else {
            break;
        }
    }
    
    // Phase 3: Validate tag balance and find outermost pair
    let validPairs = [];
    let openStack = [];
    
    for (let i = 0; i < positions.length; i++) {
        const current = positions[i];
        
        if (current.type === 'start') {
            openStack.push(current);
        } else if (current.type === 'end' && openStack.length > 0) {
            const matchingStart = openStack.pop();
            if (openStack.length === 0) {
                // This is the outermost pair
                outermostStart = matchingStart.pos;
                outermostEnd = current.pos;
                contentStart = matchingStart.pos + startTag.length;
                break;
            }
        }
    }
    
    // Phase 4: Extract content or handle errors
    if (outermostStart !== -1 && outermostEnd !== -1 && contentStart < outermostEnd) {
        const extracted = cleanedText.slice(contentStart, outermostEnd).trim();
        
        // Validate extracted content isn't empty
        if (extracted.length > 0) {
            return extracted;
        }
    }
    
    // Phase 5: Handle malformed cases with partial recovery
    if (firstStart !== -1 && firstEnd !== -1 && firstStart < firstEnd) {
        // Fallback to first valid pair if outermost detection failed
        const fallbackContent = cleanedText.slice(firstStart + startTag.length, firstEnd).trim();
        if (fallbackContent.length > 0) {
            return fallbackContent;
        }
    }
    
    // Phase 6: Final fallback mechanisms
    return handleFallbackExtraction(cleanedText);
}

/**
 * Handles fallback extraction when CODE_GENERATED tags are malformed or missing.
 * Provides multiple levels of fallback for maximum compatibility.
 */
function handleFallbackExtraction(text: string): string {
    if (!text) return '';
    
    // Fallback 1: Try markdown code blocks
    const markdownRegex = /```(?:\w+)?\s*\n?([\s\S]*?)\s*\n?```/g;
    const matches = [...text.matchAll(markdownRegex)];
    
    if (matches.length > 0) {
        // Return the largest content from markdown blocks
        let largestContent = '';
        for (const match of matches) {
            if (match[1] && match[1].trim().length > largestContent.length) {
                largestContent = match[1].trim();
            }
        }
        if (largestContent) return largestContent;
    }
    
    // Fallback 2: Remove common prefixes/suffixes
    let cleaned = text.trim();
    
    // Remove common AI response prefixes
    const prefixes = [
        'Here is the modified code:',
        'Here\'s the updated code:',
        'Modified code:',
        'Updated code:',
        'The modified code is:',
        '```',
        '```\w+',
    ];
    
    for (const prefix of prefixes) {
        const regex = new RegExp(`^${prefix}\s*\n?`, 'i');
        cleaned = cleaned.replace(regex, '');
    }
    
    // Remove common suffixes
    const suffixes = [
        '\n```$',
        '\s+Let me know if you need any changes.$',
        '\s+Please let me know if you need anything else.$',
    ];
    
    for (const suffix of suffixes) {
        const regex = new RegExp(suffix, 'i');
        cleaned = cleaned.replace(regex, '');
    }
    
    return cleaned.trim();
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
    if (!activeService) {
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
 * @returns Object containing generated code and token usage information.
 */
export async function generateCode(
    instruction: string, 
    context: GenerationContext,
    onProgress?: (tokenCount: number, currentText: string) => void
): Promise<{ code: string; usage: TokenUsage }> {
    const activeService = getActiveAiServiceConfig();
    if (!activeService) {
        throw new Error("No active AI service configured.");
    }
    
    const openai = initializeClient(activeService);

    const messages = buildMessages(instruction, context);
    
    const { key, ...serviceToLog } = activeService;
    logger.log('Using AI Service for code generation:', { ...serviceToLog, key: '********' });
    logger.log('Sending prompt:', { messages });

    const completionOptions = {
        model: activeService.model_name,
        messages: messages,
        temperature: activeService.temperature,
        stream: true, // Always use streaming mode
    };
    logger.log('Sending OpenAI Chat Completion Request with options:', completionOptions);

    try {
        const timeoutMs = (activeService.timeout_seconds || 60) * 1000;
        
        // Always use streaming mode
        const stream = await openai.chat.completions.create(completionOptions, { timeout: timeoutMs });
        let accumulatedContent = '';
        let tokenCount = 0;
        let isComplete = false;

        try {
            for await (const chunk of stream) {
                const content = chunk.choices[0]?.delta?.content || '';
                const finishReason = chunk.choices[0]?.finish_reason;
                
                if (content) {
                    accumulatedContent += content;
                    tokenCount += content.split(/\s+/).length;
                    
                    // Always update progress if callback provided
                    if (onProgress) {
                        onProgress(tokenCount, accumulatedContent);
                    }
                }
                
                // Check if streaming is complete
                if (finishReason === 'stop' || finishReason === 'length') {
                    isComplete = true;
                    break;
                }
            }
            
            // Ensure we mark progress as complete
            if (!isComplete && accumulatedContent.length > 0 && onProgress) {
                onProgress(tokenCount, accumulatedContent);
            }
            
        } catch (streamError) {
            logger.error('Streaming error:', streamError);
            throw streamError;
        }

        // For streaming, we estimate usage since OpenAI doesn't provide usage in streaming
        const estimatedPromptTokens = Math.ceil(messages.reduce((total, msg) => total + (msg.content?.toString().length || 0), 0) / 4);
        const estimatedCompletionTokens = Math.ceil(accumulatedContent.length / 4);
        
        const usage: TokenUsage = {
            promptTokens: estimatedPromptTokens,
            completionTokens: estimatedCompletionTokens,
            totalTokens: estimatedPromptTokens + estimatedCompletionTokens,
            cost: calculateCost(estimatedPromptTokens, estimatedCompletionTokens),
            model: activeService.model_name,
        };

        logger.log('Estimated token usage:', usage);
        return { code: cleanResponse(accumulatedContent), usage };
    } catch (error) {
        const errorDetails = {
            message: error instanceof Error ? error.message : String(error),
            stack: error instanceof Error ? error.stack : new Error().stack,
            type: error?.constructor?.name || 'Unknown',
            timestamp: new Date().toISOString()
        };
        
        logger.error('API Error Details:', errorDetails);
        logger.error('Full Error Object:', error);
        
        if (error?.constructor?.name === 'TimeoutError') {
             throw new Error(`The request timed out after ${activeService.timeout_seconds || 60} seconds.\nStack: ${errorDetails.stack}`);
        }
        if (error instanceof OpenAI.APIError) {
            throw new Error(`API request failed with status ${error.status}: ${error.message}\nStack: ${errorDetails.stack}`);
        }
        throw new Error(`Failed to communicate with the API. Check your network connection and configuration.\nError: ${errorDetails.message}\nStack: ${errorDetails.stack}`);
    }
}

/**
 * Sends a prompt to a specified LLM service for a generic chat interaction in the playground.
 *
 * @param prompt - The user's prompt.
 * @param serviceConfig - The configuration of the AI service to use.
 * @param onProgress - Callback function to report streaming progress (optional)
 * @returns Object containing response and token usage information.
 */
export async function playgroundChat(
    prompt: string, 
    serviceConfig: AiServiceConfig,
    onProgress?: (tokenCount: number, currentText: string) => void
): Promise<{ response: string; usage: TokenUsage }> {
    const openai = initializeClient(serviceConfig);
    const { key, ...serviceToLog } = serviceConfig;
    logger.log('Using AI Service for playground:', { ...serviceToLog, key: '********' });
    logger.log('Sending playground prompt:', { prompt });
    
    const completionOptions = {
        model: serviceConfig.model_name,
        messages: [{ role: 'user', content: prompt }],
        temperature: serviceConfig.temperature,
        stream: true, // Always use streaming mode
    };
    logger.log('Sending OpenAI Chat Completion Request from playground with options:', completionOptions);

    try {
        const timeoutMs = (serviceConfig.timeout_seconds || 60) * 1000;
        
        // Always use streaming mode
        const stream = await openai.chat.completions.create(completionOptions, { timeout: timeoutMs });
        let accumulatedContent = '';
        let tokenCount = 0;
        let isComplete = false;

        try {
            for await (const chunk of stream) {
                const content = chunk.choices[0]?.delta?.content || '';
                const finishReason = chunk.choices[0]?.finish_reason;
                
                if (content) {
                    accumulatedContent += content;
                    tokenCount += content.split(/\s+/).length;
                    
                    // Always update progress if callback provided
                    if (onProgress) {
                        onProgress(tokenCount, accumulatedContent);
                    }
                }
                
                // Check if streaming is complete
                if (finishReason === 'stop' || finishReason === 'length') {
                    isComplete = true;
                    break;
                }
            }
            
            // Ensure we mark progress as complete
            if (!isComplete && accumulatedContent.length > 0 && onProgress) {
                onProgress(tokenCount, accumulatedContent);
            }
            
        } catch (streamError) {
            logger.error('Playground streaming error:', streamError);
            throw streamError;
        }

        // Estimate usage for streaming
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
            stack: error instanceof Error ? error.stack : new Error().stack,
            type: error?.constructor?.name || 'Unknown',
            timestamp: new Date().toISOString(),
            service: serviceConfig.name,
            model: serviceConfig.model_name
        };
        
        logger.error('Playground API Error Details:', errorDetails);
        logger.error('Full Error Object:', error);
        
        const usage: TokenUsage = {
            promptTokens: 0,
            completionTokens: 0,
            totalTokens: 0,
            cost: 0,
            model: serviceConfig.model_name,
        };
        
        if (error?.constructor?.name === 'TimeoutError') {
             const message = `The request timed out after ${serviceConfig.timeout_seconds || 60} seconds.\nStack: ${errorDetails.stack}`;
             logger.error('Timeout Error Message:', message);
             return { response: message, usage };
        }
        if (error instanceof OpenAI.APIError) {
            const message = `API Error: ${error.status} ${error.name} - ${error.message}\nStack: ${errorDetails.stack}`;
            logger.error('API Error Message:', message);
            return { response: message, usage };
        }
        const message = `Failed to communicate with the API: ${errorDetails.message}\nStack: ${errorDetails.stack}`;
        logger.error('Communication Error Message:', message);
        return { response: message, usage };
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
        // Use the centralized client initializer to include proxy support
        const client = initializeClient(apiConfig);
        
        const timeoutMs = (apiConfig.timeout_seconds || 15) * 1000; // Shorter timeout for a simple test
        const testPrompt = "Respond with only the word 'test'";
        logger.log(`Sending test prompt: "${testPrompt}" to model: ${apiConfig.model_name}`);

        const response = await client.chat.completions.create({
            model: apiConfig.model_name,
            messages: [{ role: 'user', content: testPrompt }],
            max_tokens: 5,
        }, { timeout: timeoutMs });
        
        logger.log('Received test response from API:', response);
        const content = response.choices[0]?.message?.content?.trim().toLowerCase();

        if (content === 'test') {
            logger.log('Test connection successful.');
            return { success: true, message: 'Connection successful.' };
        } else {
            logger.log('WARN: Test connection failed: Unexpected response.', { response: content });
            return { success: false, message: `Received an unexpected response: "${content}"` };
        }
    } catch (error) {
        const errorDetails = {
            message: error instanceof Error ? error.message : String(error),
            stack: error instanceof Error ? error.stack : new Error().stack,
            type: error?.constructor?.name || 'Unknown',
            timestamp: new Date().toISOString(),
            service: apiConfig.name,
            model: apiConfig.model_name,
            timeout: apiConfig.timeout_seconds
        };
        
        logger.error('Test Connection Error Details:', errorDetails);
        logger.error('Full Error Object:', error);
        
        if (error?.constructor?.name === 'TimeoutError') {
            const message = `Request timed out after ${apiConfig.timeout_seconds || 15}s.\nStack: ${errorDetails.stack}`;
            logger.error('Test Timeout Message:', message);
            return { success: false, message };
        }
        if (error instanceof OpenAI.APIError) {
            const message = `API Error: ${error.status} ${error.name} - ${error.message}\nStack: ${errorDetails.stack}`;
            logger.error('Test API Error Message:', message);
            return { success: false, message };
        }
        const message = `An unknown error occurred: ${errorDetails.message}\nStack: ${errorDetails.stack}`;
        logger.error('Test Unknown Error Message:', message);
        return { success: false, message };
    }
}