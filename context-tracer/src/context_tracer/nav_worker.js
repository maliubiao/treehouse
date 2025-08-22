/**
 * Web Worker for rendering the navigation bar thumbnail in the background.
 * This avoids blocking the main UI thread when dealing with large trace logs.
 */

self.onmessage = function(event) {
    if (event.data.type === 'render') {
        const {
            canvasWidth,
            canvasHeight,
            navHeight,
            contentHeight,
            isDark,
            elements
        } = event.data;

        // Create an OffscreenCanvas. The dimensions are the actual pixel dimensions (for high DPI).
        const offscreenCanvas = new OffscreenCanvas(canvasWidth, canvasHeight);
        const ctx = offscreenCanvas.getContext('2d');
        
        // The display size is half the pixel size due to scaling for high DPI
        const displayWidth = canvasWidth / 2;
        
        ctx.scale(2, 2); // Scale context to match the main thread's high-DPI scaling

        drawThumbnailOnWorker(ctx, displayWidth, navHeight, contentHeight, isDark, elements);
        
        // Transfer the rendered image back to the main thread as an ImageBitmap.
        // This is a zero-copy operation, making it very efficient.
        const imageBitmap = offscreenCanvas.transferToImageBitmap();
        self.postMessage({ type: 'rendered', imageBitmap: imageBitmap }, [imageBitmap]);
    }
};

/**
 * Draws the thumbnail representation of the trace log onto the provided canvas context.
 * This function is designed to be executed within the Web Worker.
 *
 * @param {OffscreenCanvasRenderingContext2D} ctx - The context of the OffscreenCanvas to draw on.
 * @param {number} displayWidth - The logical width of the canvas.
 * @param {number} navHeight - The logical height of the navigation bar.
 * @param {number} contentHeight - The total scrollable height of the content.
 * @param {boolean} isDark - Whether the dark theme is active.
 * @param {Array<Object>} elements - The data for elements to be drawn.
 */
function drawThumbnailOnWorker(ctx, displayWidth, navHeight, contentHeight, isDark, elements) {
    if (contentHeight <= 0) return;
    const scale = navHeight / contentHeight;
    
    // Clear canvas and set background color
    ctx.clearRect(0, 0, displayWidth, navHeight);
    ctx.fillStyle = isDark ? 'rgba(30, 41, 59, 0.8)' : 'rgba(248, 250, 252, 0.8)';
    ctx.fillRect(0, 0, displayWidth, navHeight);
    
    // Draw each sampled element as a rectangle
    elements.forEach(element => {
        const y = element.top * scale;
        const height = element.height * scale;
        
        // Only draw elements that are visible within the navigation bar's bounds
        if (y >= 0 && y < navHeight) {
            let color;
            switch (element.type) {
                case 'call':
                    color = isDark ? 'rgba(96, 165, 250, 0.6)' : 'rgba(59, 130, 246, 0.6)';
                    break;
                case 'return':
                    color = isDark ? 'rgba(52, 211, 153, 0.6)' : 'rgba(16, 185, 129, 0.6)';
                    break;
                case 'error':
                    color = isDark ? 'rgba(248, 113, 113, 0.6)' : 'rgba(239, 68, 68, 0.6)';
                    break;
                default: // 'line' and others
                    color = isDark ? 'rgba(156, 163, 175, 0.4)' : 'rgba(107, 114, 128, 0.4)';
            }
            
            ctx.fillStyle = color;
            // Draw the rectangle, ensuring a minimum height of 1px for visibility
            ctx.fillRect(2, y, displayWidth - 4, Math.max(height, 1));
        }
    });
}