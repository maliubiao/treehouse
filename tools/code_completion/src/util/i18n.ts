import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import i18next from 'i18next';
import { logger } from '../utils/logger';

// This will hold all loaded translations
const resources: Record<string, Record<string, any>> = {};

/**
 * Loads translation resources from the filesystem.
 * @param context - The extension context.
 */
function loadTranslations(context: vscode.ExtensionContext): void {
    // Try to determine the correct locales directory location
    let localesDir = path.join(context.extensionPath, 'locales');
    
    // Check if production environment path exists
    if (!fs.existsSync(localesDir)) {
        // If not, try development environment path
        localesDir = path.join(context.extensionPath, 'src', 'locales');
        
        // If still not found, log warning
        if (!fs.existsSync(localesDir)) {
            logger.warn(`Localization directory not found in either ${path.join(context.extensionPath, 'locales')} or ${path.join(context.extensionPath, 'src', 'locales')}`);
            return;
        }
    }

    try {
        const langDirs = fs.readdirSync(localesDir);
        for (const lang of langDirs) {
            const langPath = path.join(localesDir, lang);
            if (fs.statSync(langPath).isDirectory()) {
                // Initialize language resources
                resources[lang] = {};
                
                const nsFiles = fs.readdirSync(langPath);
                for (const nsFile of nsFiles) {
                    if (nsFile.endsWith('.json')) {
                        const ns = path.basename(nsFile, '.json');
                        const nsPath = path.join(langPath, nsFile);
                        try {
                            const content = fs.readFileSync(nsPath, 'utf8');
                            // Add translation resources to the corresponding language and namespace
                            resources[lang][ns] = JSON.parse(content);
                        } catch (e) {
                            logger.error(`Failed to load or parse translation file: ${nsPath}`, e);
                        }
                    }
                }
            }
        }
    } catch(e) {
        logger.error(`Failed to read localization directory: ${localesDir}`, e);
    }
}

/**
 * Initializes the i18next instance.
 * @param context - The extension context.
 */
export async function initI18n(context: vscode.ExtensionContext): Promise<void> {
    loadTranslations(context);
    
    // The language is set to 'pseudo' to show the translation keys.
    // vscode.env.language is the correct way to get the user's language.
    // For example: 'en', 'zh-cn', etc.
    const vscodeLang = vscode.env.language;
    
    // Create language code mapping (e.g., zh-cn -> zh)
    const langMap: Record<string, string> = {
        'zh-cn': 'zh',
        'zh-tw': 'zh',
        'en-us': 'en',
        'en-gb': 'en'
    };
    
    // Try to get the most matching language
    let lang = langMap[vscodeLang.toLowerCase()] || vscodeLang.split('-')[0];
    
    // If the specified language has no resources, try falling back to base language (e.g., zh-cn -> zh)
    if (!resources[lang]) {
        const baseLang = vscodeLang.split('-')[0];
        if (resources[baseLang]) {
            lang = baseLang;
        } else {
            lang = 'en'; // Final fallback to English
        }
    }

    await i18next.init({
        lng: lang,
        fallbackLng: 'en',
        resources,
        ns: Object.keys(resources[lang] || resources.en || {}),
        defaultNS: 'common',
        interpolation: {
            escapeValue: false // Not needed as we don't render HTML from translations
        }
    });
    logger.log(`i18n initialized with language: ${lang}, fallback: en`);
}

/**
* The translation function.
*/
export const t = i18next.t.bind(i18next);

/**
 * Gets all translations in a structured format suitable for Webview.
 * Returns the full i18next configuration including resources, language, and namespaces.
 */
export function getI18nConfigForWebview(): {
  resources: Record<string, Record<string, any>>;
  language: string;
  namespaces: string[];
} {
  return {
    resources,
    language: i18next.language || 'en',
    namespaces: i18next.options.ns as string[]
  };
}