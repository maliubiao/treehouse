/**
 * Chrome Context Tracer - Mouse Element Detector
 * 纯JavaScript实现的鼠标元素检测器
 * 通过控制台输出与Python端通信
 */

(function() {
    'use strict';
    
    // 防止重复注入
    if (window.chromeContextTracer) {
        console.log('[CHROME_TRACER] Already initialized');
        return;
    }
    
    window.chromeContextTracer = {
        version: '1.0.0',
        isActive: false,
        lastElement: null,
        overlay: null
    };
    
    const tracer = window.chromeContextTracer;
    
    /**
     * 生成元素的唯一CSS选择器路径
     */
    function getElementPath(element) {
        if (!element || element.nodeType !== Node.ELEMENT_NODE) {
            return null;
        }
        
        if (element.id) {
            return '#' + element.id;
        }
        
        if (element === document.body) {
            return 'body';
        }
        
        const path = [];
        while (element && element.parentNode) {
            if (element.id) {
                path.unshift('#' + element.id);
                break;
            }
            
            let selector = element.tagName.toLowerCase();
            const siblings = Array.from(element.parentNode.children);
            const index = siblings.indexOf(element);
            
            if (index > 0) {
                selector += ':nth-child(' + (index + 1) + ')';
            }
            
            path.unshift(selector);
            element = element.parentNode;
        }
        
        return path.join(' > ');
    }
    
    /**
     * 获取元素的详细信息
     */
    function getElementInfo(element, mouseX, mouseY) {
        if (!element) return null;
        
        const rect = element.getBoundingClientRect();
        const computedStyle = window.getComputedStyle(element);
        
        return {
            // 基本信息
            tagName: element.tagName,
            id: element.id || '',
            className: element.className || '',
            textContent: element.textContent ? element.textContent.substring(0, 100) : '',
            
            // 位置信息
            mouse: {
                x: mouseX,
                y: mouseY
            },
            rect: {
                left: Math.round(rect.left),
                top: Math.round(rect.top),
                width: Math.round(rect.width),
                height: Math.round(rect.height)
            },
            
            // 选择器信息
            path: getElementPath(element),
            
            // 样式信息
            style: {
                display: computedStyle.display,
                position: computedStyle.position,
                zIndex: computedStyle.zIndex,
                backgroundColor: computedStyle.backgroundColor,
                cursor: computedStyle.cursor
            },
            
            // 属性信息
            attributes: Array.from(element.attributes).reduce((acc, attr) => {
                acc[attr.name] = attr.value;
                return acc;
            }, {}),
            
            // 时间戳
            timestamp: Date.now()
        };
    }

    /**
     * 获取指定坐标处的元素信息
     */
    function getElementAtCoordinates(x, y) {
        const element = document.elementFromPoint(x, y);
        if (!element) {
            return {
                found: false,
                message: `No element found at coordinates (${x}, ${y})`
            };
        }
        
        const elementInfo = getElementInfo(element, x, y);
        return {
            found: true,
            element: elementInfo,
            coordinates: { x, y }
        };
    }

    /**
     * 获取屏幕坐标处的元素信息（自动转换为viewport坐标）
     */
    function getElementAtScreenCoordinates(screenX, screenY) {
        // 转换屏幕坐标为viewport坐标
        const viewportX = Math.round(screenX - window.screenX);
        const viewportY = Math.round(screenY - window.screenY);
        
        const element = document.elementFromPoint(viewportX, viewportY);
        if (!element) {
            return {
                found: false,
                message: `No element found at screen coordinates (${screenX}, ${screenY})`,
                viewportCoordinates: { x: viewportX, y: viewportY }
            };
        }
        
        const elementInfo = getElementInfo(element, viewportX, viewportY);
        return {
            found: true,
            element: elementInfo,
            screenCoordinates: { x: screenX, y: screenY },
            viewportCoordinates: { x: viewportX, y: viewportY }
        };
    }
    
    /**
     * 创建高亮覆盖层
     */
    function createOverlay() {
        if (tracer.overlay) return tracer.overlay;
        
        const overlay = document.createElement('div');
        overlay.id = 'chrome-tracer-overlay';
        overlay.style.cssText = `
            position: fixed;
            pointer-events: none;
            z-index: 10000;
            border: 2px solid #ff4444;
            background-color: rgba(255, 68, 68, 0.1);
            transition: all 0.1s ease;
            display: none;
        `;
        
        document.body.appendChild(overlay);
        tracer.overlay = overlay;
        return overlay;
    }
    
    /**
     * 更新覆盖层位置
     */
    function updateOverlay(element) {
        if (!tracer.overlay || !element) return;
        
        const rect = element.getBoundingClientRect();
        const overlay = tracer.overlay;
        
        overlay.style.left = rect.left + 'px';
        overlay.style.top = rect.top + 'px';
        overlay.style.width = rect.width + 'px';
        overlay.style.height = rect.height + 'px';
        overlay.style.display = 'block';
    }
    
    /**
     * 隐藏覆盖层
     */
    function hideOverlay() {
        if (tracer.overlay) {
            tracer.overlay.style.display = 'none';
        }
    }
    
    /**
     * 鼠标移动事件处理器
     */
    function handleMouseMove(event) {
        if (!tracer.isActive) return;
        
        const element = event.target;
        if (element === tracer.lastElement) return;
        
        tracer.lastElement = element;
        updateOverlay(element);
        
        // 输出元素信息到控制台 (Commented out to reduce noise)
        // const elementInfo = getElementInfo(element, event.clientX, event.clientY);
        // console.log('[CHROME_TRACER_HOVER]', JSON.stringify(elementInfo));
    }
    
    /**
     * 鼠标点击事件处理器
     */
    function handleMouseClick(event) {
        if (!tracer.isActive) return;
        
        // 阻止默认行为
        event.preventDefault();
        event.stopPropagation();
        
        const element = event.target;
        const elementInfo = getElementInfo(element, event.clientX, event.clientY);
        
        // 输出选中的元素信息
        console.log('[CHROME_TRACER_SELECTED]', JSON.stringify(elementInfo));
        
        // 停止检测模式
        tracer.stop();
        
        return false;
    }
    
    /**
     * 键盘事件处理器
     */
    function handleKeyDown(event) {
        if (!tracer.isActive) return;
        
        // ESC键退出检测模式
        if (event.key === 'Escape') {
            event.preventDefault();
            event.stopPropagation();
            
            console.log('[CHROME_TRACER_CANCELLED]', JSON.stringify({
                action: 'cancelled',
                timestamp: Date.now()
            }));
            
            tracer.stop();
        }
    }
    
    /**
     * 启动元素检测模式
     */
    tracer.start = function() {
        if (tracer.isActive) {
            console.log('[CHROME_TRACER] Already active');
            return;
        }
        
        tracer.isActive = true;
        tracer.lastElement = null;
        
        // 创建覆盖层
        createOverlay();
        
        // 添加事件监听器
        document.addEventListener('mousemove', handleMouseMove, true);
        document.addEventListener('click', handleMouseClick, true);
        document.addEventListener('keydown', handleKeyDown, true);
        
        // 改变鼠标样式
        document.body.style.cursor = 'crosshair';
        
        console.log('[CHROME_TRACER_STARTED]', JSON.stringify({
            action: 'started',
            timestamp: Date.now(),
            message: 'Element selection mode activated. Click to select, ESC to cancel.'
        }));
    };
    
    /**
     * 停止元素检测模式
     */
    tracer.stop = function() {
        if (!tracer.isActive) {
            return;
        }
        
        tracer.isActive = false;
        tracer.lastElement = null;
        
        // 移除事件监听器
        document.removeEventListener('mousemove', handleMouseMove, true);
        document.removeEventListener('click', handleMouseClick, true);
        document.removeEventListener('keydown', handleKeyDown, true);
        
        // 恢复鼠标样式
        document.body.style.cursor = '';
        
        // 隐藏覆盖层
        hideOverlay();
        
        console.log('[CHROME_TRACER_STOPPED]', JSON.stringify({
            action: 'stopped',
            timestamp: Date.now()
        }));
    };
    
    /**
     * 获取当前状态
     */
    tracer.getStatus = function() {
        return {
            isActive: tracer.isActive,
            version: tracer.version,
            lastElement: tracer.lastElement ? getElementPath(tracer.lastElement) : null
        };
    };
    
    // 暴露全局控制方法
    window.startElementSelection = tracer.start;
    window.stopElementSelection = tracer.stop;
    window.getTracerStatus = tracer.getStatus;
    window.getElementAtCoordinates = getElementAtCoordinates;
    window.getElementAtScreenCoordinates = getElementAtScreenCoordinates;
    
    console.log('[CHROME_TRACER] Initialized successfully');
    console.log('[CHROME_TRACER] Available commands:');
    console.log('[CHROME_TRACER]   - startElementSelection(): Start element detection');
    console.log('[CHROME_TRACER]   - stopElementSelection(): Stop element detection');
    console.log('[CHROME_TRACER]   - getTracerStatus(): Get current status');
    console.log('[CHROME_TRACER]   - getElementAtCoordinates(x, y): Get element at viewport coordinates');
    console.log('[CHROME_TRACER]   - getElementAtScreenCoordinates(x, y): Get element at screen coordinates');
    
})();