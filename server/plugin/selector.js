(function() {
        const state = {                                                           
            isSelecting: false,                                                   
            fixedElement: null,                                                   
            validationHighlight: null                                             
        };                                                                        
                                                                                  
        // 创建控制面板                                                           
        const panel = document.createElement('div');                              
        panel.id = 'element-selector-panel';                                      
        panel.style.cssText = `                                                   
            position: fixed;                                                      
            bottom: 20px;                                                         
            right: 20px;                                                          
            background: rgba(0,0,0,0.95);                                         
            color: white;                                                         
            padding: 15px;                                                        
            border-radius: 8px;                                                   
            font-family: Arial, sans-serif;                                       
            z-index: 100000;                                                      
            min-width: 320px;                                                     
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);                               
        `;                                                                        
        panel.innerHTML = `                                                       
            <div style="margin-bottom: 12px; font-weight: bold; color: #00ff9d;"> 
                Element Inspector v3.1                                            
            </div>                                                                
            <div style="margin-bottom: 10px; display: flex; gap: 8px; flex-wrap:  
  wrap;">                                                                         
                <button id="toggleBtn" class="tool-btn">🎯 Start</button>         
                <button id="validateBtn" class="tool-btn" disabled>✅             
  Validate</button>                                                               
                <button id="clearBtn" class="tool-btn">🗑️ Clear</button>         
            </div>                                                                
            <div id="elementPath" class="path-container"></div>                   
            <div id="cssSelector" class="selector-container"></div>               
        `;                                                                        
        document.body.appendChild(panel);    

    // 样式和高亮元素
    const style = document.createElement('style');
    style.textContent = `
        .highlight-layer {
            position: absolute;
            pointer-events: none;
            box-sizing: border-box;
            z-index: 99999;
            opacity: 0.7;
            transition: all 0.15s;
        }
        .fixed-highlight {
            box-shadow: 0 0 6px rgba(255,255,255,0.5);
        }
        .path-part {
            display: inline-block;
            margin-right: 4px;
            transition: color 0.2s;
        }
    `;
    document.head.appendChild(style);

    let dynamicHighlights = [];
    let fixedHighlights = [];

    // 颜色生成函数
    const getColorForLevel = (level) => {
        return `hsl(${(level * 60) % 360}, 100%, 65%)`;
    };

    // 核心功能函数
    const getFullPath = (target) => {
        const elements = [];
        let currentEl = target;
        while (currentEl && currentEl !== document.body) {
            elements.push(currentEl);
            currentEl = currentEl.parentElement;
        }
        return elements;
    };

    const formatPathWithColors = (elements) => {
        const container = document.createElement('div');
        elements.forEach((el, index) => {
            const level = elements.length - index - 1;
            const span = document.createElement('span');
            span.className = 'path-part';
            span.style.color = getColorForLevel(level);
            
            let selector = el.tagName.toLowerCase();
            if (el.id) selector += `#${el.id}`;
            if (el.className) selector += Array.from(el.classList).map(c => `.${c}`).join('');
            
            span.textContent = selector + (index < elements.length - 1 ? ' → ' : '');
            container.appendChild(span);
        });
        return container;
    };

    const getUniqueSelector = (target) => {
        const elements = getFullPath(target);
        const path = elements.map((el, index) => {
            const level = elements.length - index - 1;
            const color = getColorForLevel(level);
            
            let selector = el.tagName.toLowerCase();
            if (el.id) {
                return `<span style="color:${color}">${selector}#${el.id}</span>`;
            } else {
                const index = Array.from(el.parentElement.children).indexOf(el) + 1;
                return `<span style="color:${color}">${selector}:nth-child(${index})</span>`;
            }
        }).join(' <span style="opacity:0.6">></span> ');
        
        return path;
    };

    // 高亮控制
    const createHighlight = (el, level, isFixed) => {
        const rect = el.getBoundingClientRect();
        const highlight = document.createElement('div');
        highlight.className = `highlight-layer${isFixed ? ' fixed-highlight' : ''}`;
        highlight.style.cssText = `
            border: 2px solid ${getColorForLevel(level)};
            z-index: ${99999 - level};
            width: ${rect.width}px;
            height: ${rect.height}px;
            left: ${rect.left + window.scrollX}px;
            top: ${rect.top + window.scrollY}px;
        `;
        return highlight;
    };

    const updateDynamicHighlights = (target) => {
        dynamicHighlights.forEach(h => h.remove());
        dynamicHighlights = [];

        const elements = getFullPath(target);
        elements.forEach((el, index) => {
            const level = elements.length - index - 1;
            const highlight = createHighlight(el, level, false);
            document.body.appendChild(highlight);
            dynamicHighlights.push(highlight);
        });

        // 更新路径显示
        const pathContainer = panel.querySelector('#elementPath');
        pathContainer.innerHTML = '';
        pathContainer.appendChild(formatPathWithColors(elements));

        // 更新选择器显示
        const selectorContainer = panel.querySelector('#cssSelector');
        selectorContainer.innerHTML = getUniqueSelector(target);
    };

    const createFixedHighlights = (target) => {
        fixedHighlights.forEach(h => h.remove());
        fixedHighlights = [];

        const elements = getFullPath(target);
        elements.forEach((el, index) => {
            const level = elements.length - index - 1;
            const highlight = createHighlight(el, level, true);
            document.body.appendChild(highlight);
            fixedHighlights.push(highlight);
        });
    };

    // 事件处理
    const handleMouseMove = e => {
        if (!state.isSelecting || state.fixedElement) return;
        updateDynamicHighlights(e.target);
    };

    const handleElementClick = e => {
        e.preventDefault();
        e.stopImmediatePropagation();
        state.fixedElement = e.target;
        createFixedHighlights(e.target);
        stopSelecting();
    };

    // 状态控制
    const startSelecting = () => {
        state.isSelecting = true;
        state.fixedElement = null;
        panel.querySelector('#toggleBtn').textContent = 'Stop Selecting';
        document.addEventListener('mousemove', handleMouseMove);
        document.addEventListener('click', handleElementClick, { capture: true, once: true });
    };

    const stopSelecting = () => {
        state.isSelecting = false;
        document.removeEventListener('mousemove', handleMouseMove);
        document.removeEventListener('click', handleElementClick, true);
        panel.querySelector('#toggleBtn').textContent = 'Start Selecting';
        
        // 清除动态高亮
        dynamicHighlights.forEach(h => h.remove());
        dynamicHighlights = [];
    };

    // 按钮事件
    panel.querySelector('#toggleBtn').addEventListener('click', () => {
        if (state.isSelecting) {
            stopSelecting();
        } else {
            startSelecting();
        }
    });

    panel.querySelector('#clearBtn').addEventListener('click', () => {
        state.fixedElement = null;
        fixedHighlights.forEach(h => h.remove());
        fixedHighlights = [];
        panel.querySelector('#elementPath').textContent = '';
        panel.querySelector('#cssSelector').textContent = '';
    });

    // ESC退出
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') {
            dynamicHighlights.forEach(h => h.remove());
            fixedHighlights.forEach(h => h.remove());
            panel.remove();
            style.remove();
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('click', handleElementClick, true);
        }
    });
})();