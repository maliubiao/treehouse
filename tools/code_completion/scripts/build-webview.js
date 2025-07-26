const esbuild = require('esbuild');
const fse = require('fs-extra'); // Use fs-extra for easier file operations
const fs = require('fs');
const path = require('path');

// --- Configuration ---
const isWatchMode = process.argv.includes('--watch');

const webviewSourceDir = path.resolve(__dirname, '..', 'src', 'webview');
const outDir = path.resolve(__dirname, '..', 'dist');
const htmlTemplatePath = path.join(webviewSourceDir, 'index.html');
const finalHtmlPath = path.join(outDir, 'webview.html');
const libOutDir = path.join(outDir, 'lib'); // Directory for copied libraries

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

/**
 * Copies required i18next libraries from node_modules to dist/lib
 */
async function copyI18nLibs() {
    console.log('Copying i18next libraries...');
    try {
        // Ensure the output lib directory exists
        await fse.ensureDir(libOutDir);

        // --- Correctly locate i18next UMD file ---
        // Find the i18next package root directory. require.resolve('i18next/package.json') is a robust way to do this.
        const i18nextPackageJsonPath = require.resolve('i18next/package.json');
        const i18nextPackageDir = path.dirname(i18nextPackageJsonPath);
        // The UMD file is typically in 'dist/umd/'. This works around the ERR_PACKAGE_PATH_NOT_EXPORTED error.
        const i18nextUmdPath = path.join(i18nextPackageDir, 'dist', 'umd', 'i18next.min.js');


        // Define the libraries to copy
        const libsToCopy = [
            // Main i18next library
            {
                from: i18nextUmdPath,
                to: path.join(libOutDir, 'i18next', 'i18next.min.js')
            },
            // Http Backend Plugin (if used directly in webview, though not currently in use based on main.ts)
            // {
            //     from: require.resolve('i18next-http-backend/i18nextHttpBackend.min.js'),
            //     to: path.join(libOutDir, 'i18next-http-backend', 'i18nextHttpBackend.min.js')
            // },
            // Browser Language Detector Plugin (if used directly in webview, though not currently in use based on main.ts)
            // {
            //     from: require.resolve('i18next-browser-languagedetector/i18nextBrowserLanguageDetector.min.js'),
            //     to: path.join(libOutDir, 'i18next-browser-languagedetector', 'i18nextBrowserLanguageDetector.min.js')
            // }
        ];

        // Copy each library
        for (const lib of libsToCopy) {
            const destDir = path.dirname(lib.to);
            // Ensure destination directory exists
            await fse.ensureDir(destDir);
            
            // Copy file synchronously
            fs.copyFileSync(lib.from, lib.to);
            console.log(`  Copied ${path.basename(lib.from)} to ${path.relative(outDir, lib.to)}`);
        }

        console.log('✅ i18next libraries copied successfully.');
    } catch (e) {
        console.error('❌ Failed to copy i18next libraries:', e);
        throw e; // Re-throw to fail the build/watch process
    }
}


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
        fs.promises.readFile(jsPath, 'utf-8'),
        fs.promises.readFile(cssPath, 'utf-8'),
        fs.promises.readFile(htmlTemplatePath, 'utf-8'),
    ]);

    const finalHtml = htmlTemplate
        .replace('<!-- INJECT_CSS -->', cssContent)
        .replace('<!-- INJECT_JS -->', jsContent);

    await fs.promises.writeFile(finalHtmlPath, finalHtml);
    return { jsPath, cssPath };
}

/**
 * Runs a one-off build for production.
 */
async function build() {
    console.log('Building webview...');
    try {
        await fs.promises.mkdir(outDir, { recursive: true });
        await copyI18nLibs(); // Copy libraries before building
        const result = await esbuild.build(esbuildOptions);
        const { jsPath, cssPath } = await createHtmlFile(result);

        // Clean up intermediate files as they are now embedded in the HTML
        await Promise.all([
            fs.promises.unlink(jsPath),
            fs.promises.unlink(cssPath),
            fs.promises.unlink(jsPath + '.map').catch(() => {}), // Ignore error if map file doesn't exist
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
        await fs.promises.mkdir(outDir, { recursive: true });
        await copyI18nLibs(); // Copy libraries before starting watch
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