const esbuild = require('esbuild');
const fs = require('fs/promises');
const path = require('path');

// --- Configuration ---
const isWatchMode = process.argv.includes('--watch');

const webviewSourceDir = path.resolve(__dirname, '..', 'src', 'webview');
const outDir = path.resolve(__dirname, '..', 'dist');
const htmlTemplatePath = path.join(webviewSourceDir, 'index.html');
const finalHtmlPath = path.join(outDir, 'webview.html');

const esbuildOptions = {
    entryPoints: [path.join(webviewSourceDir, 'main.ts')],
    bundle: true,
    outdir: outDir,
    // Use consistent naming to make cleanup/finding easier
    entryNames: 'webview-bundle',
    assetNames: 'webview-bundle',
    format: 'iife',
    platform: 'browser',
    sourcemap: isWatchMode ? 'inline' : false,
    minify: !isWatchMode,
    metafile: true,
};

// --- Build Logic ---

/**
 * Injects bundled JS and CSS into the HTML template to create the final webview.html.
 * @param {import('esbuild').BuildResult | import('esbuild').BuildIncremental} result - The esbuild result object.
 */
async function createHtmlFile(result) {
    let jsPath = '';
    let cssPath = '';

    for (const outFile in result.metafile.outputs) {
        if (outFile.endsWith('.js')) jsPath = outFile;
        else if (outFile.endsWith('.css')) cssPath = outFile;
    }

    if (!jsPath || !cssPath) {
        throw new Error('Bundled JS or CSS file not found in esbuild output.');
    }

    const [jsContent, cssContent, htmlTemplate] = await Promise.all([
        fs.readFile(jsPath, 'utf-8'),
        fs.readFile(cssPath, 'utf-8'),
        fs.readFile(htmlTemplatePath, 'utf-8'),
    ]);

    const finalHtml = htmlTemplate
        .replace('<!-- INJECT_CSS -->', cssContent)
        .replace('<!-- INJECT_JS -->', jsContent);

    await fs.writeFile(finalHtmlPath, finalHtml);
    return { jsPath, cssPath };
}

/**
 * Runs a one-off build for production.
 */
async function build() {
    console.log('Building webview...');
    try {
        await fs.mkdir(outDir, { recursive: true });
        const result = await esbuild.build(esbuildOptions);
        const { jsPath, cssPath } = await createHtmlFile(result);

        // Clean up intermediate files as they are now embedded in the HTML
        await Promise.all([
            fs.unlink(jsPath),
            fs.unlink(cssPath),
            fs.unlink(jsPath + '.map').catch(() => {}), // Ignore error if map file doesn't exist
        ]);

        console.log(`✅ WebView built successfully: ${finalHtmlPath}`);
    } catch (e) {
        console.error('❌ WebView build failed:', e);
        process.exit(1);
    }
}

/**
 * Starts the build process in watch mode for development.
 */
async function watch() {
    try {
        await fs.mkdir(outDir, { recursive: true });
        const context = await esbuild.context({
            ...esbuildOptions,
            plugins: [{
                name: 'html-generator',
                setup(build) {
                    build.onEnd(async (result) => {
                        if (result.errors.length > 0) {
                            console.error('Build failed with errors:', result.errors);
                            return;
                        }
                        try {
                            await createHtmlFile(result);
                            // In watch mode, we DON'T clean up intermediate files, esbuild needs them for incremental builds.
                            console.log(`✅ WebView rebuilt at ${new Date().toLocaleTimeString()}`);
                        } catch (e) {
                            console.error('❌ HTML generation failed:', e);
                        }
                    });
                },
            }],
        });

        await context.watch();
        console.log(`👀 Watching for changes in ${webviewSourceDir}...`);
    } catch (e) {
        console.error('❌ Failed to start watch mode:', e);
        process.exit(1);
    }
}

// --- Main ---
if (isWatchMode) {
    watch();
} else {
    build();
}