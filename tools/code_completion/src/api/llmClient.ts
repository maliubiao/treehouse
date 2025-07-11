import OpenAI from 'openai';
import { ChatCompletionMessageParam } from 'openai/resources/chat';
import { getActiveAiServiceConfig, AiServiceConfig } from '../config/configuration';
import { logger } from '../utils/logger';
import * as vscode from 'vscode';
import { GenerationContext } from '../types';

/**
 * Initializes the OpenAI client with configuration from the active service.
 * Throws an error if the API key is missing.
 */
function initializeClient(serviceConfig?: AiServiceConfig): OpenAI {
    const config = serviceConfig || getActiveAiServiceConfig();
    if (!config || !config.key) {
        throw new Error('AI service configuration with an API key is required.');
    }
    
    return new OpenAI({
        apiKey: config.key,
        baseURL: config.base_url,
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
    const config = vscode.workspace.getConfiguration('aiCodeCompleter');
    const systemMessage = config.get<string>('prompt.systemMessage', "You are an expert software architect and programmer. Your task is to rewrite the provided code block according to the instruction, using the context of the file. Output only the raw, modified code block.");
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
${contextBlock.trim()}
---
Code Block to Modify:
\`\`\`${context.fileExtension.slice(1)}
${context.selectedText}
\`\`\`
---
User Instruction:
${instruction}
`.trim();

    return [
        { role: 'system', content: systemMessage },
        { role: 'user', content: userPrompt }
    ];
}


/**
 * Cleans the AI's response by trimming whitespace and removing markdown code blocks.
 */
function cleanResponse(responseText: string): string {
    let cleanedText = responseText.trim();
    
    const markdownRegex = /^```(?:\w+)?\n([\s\S]+)\n```$/;
    const match = cleanedText.match(markdownRegex);

    if (match && match[1]) {
        return match[1].trim();
    }

    return cleanedText;
}

/**
 * Generates code using the configured LLM API.
 * 
 * @param instruction - The user's instruction for modification.
 * @param context - The full generation context, including code, file info, etc.
 * @returns The generated code as a string.
 */
export async function generateCode(instruction: string, context: GenerationContext): Promise<string> {
    const activeService = getActiveAiServiceConfig();
    if (!activeService) {
        throw new Error("No active AI service configured.");
    }
    
    const openai = initializeClient(activeService);

    const messages = buildMessages(instruction, context);
    
    const { key, ...serviceToLog } = activeService;
    logger.log('Using AI Service for code generation:', { ...serviceToLog, key: '********' });
    logger.log('Sending prompt:', { messages });

    try {
        const timeoutMs = (activeService.timeout_seconds || 60) * 1000;
        const completion = await openai.chat.completions.create({
            model: activeService.model_name,
            messages: messages,
            temperature: activeService.temperature,
            max_tokens: activeService.max_tokens,
        }, { timeout: timeoutMs });

        logger.log('Received API response:', completion);

        const content = completion.choices[0]?.message?.content;
        if (!content) {
            throw new Error('API returned an empty response.');
        }
        return cleanResponse(content);
    } catch (error) {
        logger.error('API Error:', error);
        if (error instanceof OpenAI.APIError) {
            throw new Error(`API request failed with status ${error.status}: ${error.message}`);
        }
        if (error.constructor.name === 'TimeoutError') {
             throw new Error(`The request timed out after ${activeService.timeout_seconds} seconds.`);
        }
        throw new Error('Failed to communicate with the API. Check your network connection and configuration.');
    }
}

/**
 * Sends a prompt to a specified LLM service for a generic chat interaction in the playground.
 *
 * @param prompt - The user's prompt.
 * @param serviceConfig - The configuration of the AI service to use.
 * @returns The LLM's response as a string.
 */
export async function playgroundChat(prompt: string, serviceConfig: AiServiceConfig): Promise<string> {
    const openai = initializeClient(serviceConfig);
    const { key, ...serviceToLog } = serviceConfig;
    logger.log('Using AI Service for playground:', { ...serviceToLog, key: '********' });
    logger.log('Sending playground prompt:', { prompt });
    
    try {
        const timeoutMs = (serviceConfig.timeout_seconds || 60) * 1000;
        const completion = await openai.chat.completions.create({
            model: serviceConfig.model_name,
            messages: [{ role: 'user', content: prompt }],
            temperature: serviceConfig.temperature,
            max_tokens: serviceConfig.max_tokens,
            stream: false,
        }, { timeout: timeoutMs });

        logger.log('Received playground API response:', completion);
        const content = completion.choices[0]?.message?.content;

        if (!content) {
            throw new Error('API returned an empty response.');
        }
        return content;
    } catch (error) {
        logger.error('Playground API Error:', error);
        if (error instanceof OpenAI.APIError) {
            throw new Error(`API request failed with status ${error.status}: ${error.message}`);
        }
        if (error.constructor.name === 'TimeoutError') {
             throw new Error(`The request timed out after ${serviceConfig.timeout_seconds} seconds.`);
        }
        throw new Error(`Failed to communicate with the API: ${String(error)}`);
    }
}


/**
 * Tests the connection to the API using the provided configuration.
 * @param apiConfig - The API configuration to test.
 * @returns An object indicating success and a message.
 */
export async function testApiConnection(apiConfig: AiServiceConfig): Promise<{ success: boolean; message: string }> {
    try {
        const client = new OpenAI({
            apiKey: apiConfig.key,
            baseURL: apiConfig.base_url,
        });
        const timeoutMs = (apiConfig.timeout_seconds || 60) * 1000;
        const response = await client.chat.completions.create({
            model: apiConfig.model_name,
            messages: [{ role: 'user', content: "Respond with only the word 'test'" }],
            max_tokens: 5,
        }, { timeout: timeoutMs });

        if (response.choices[0].message.content?.trim().toLowerCase() === 'test') {
            return { success: true, message: 'Connection successful.' };
        } else {
            return { success: false, message: 'Received an unexpected response from the API.' };
        }
    } catch (error) {
        if (error instanceof OpenAI.APIError) {
            return { success: false, message: `API Error: ${error.status} ${error.name}` };
        }
        if (error.constructor.name === 'TimeoutError') {
             return { success: false, message: `Request timed out after ${apiConfig.timeout_seconds}s.`};
        }
        return { success: false, message: String(error) };
    }
}