(function () {
  const state = {
    isSelecting: false,
    fixedElement: null,
    validationHighlight: null,
  };

  // 检测系统主题
  const isDarkMode =
    window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: dark)").matches;

  // 创建控制面板
  const panel = document.createElement("div");
  panel.id = "element-selector-panel";
  panel.style.cssText = `                                                   
        position: fixed;                                                      
        bottom: 20px;                                                         
        right: 20px;                                                          
        background: ${isDarkMode ? "rgba(0,0,0,0.95)" : "rgba(255,255,255,0.95)"};                                         
        color: ${isDarkMode ? "white" : "#333"};                                                         
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
                                                           
            <button id="clearBtn" class="tool-btn">🗑️ Clear</button>         
        </div>                                                                
        <div id="elementPath" class="path-container"></div>                   
        <div style="display: flex; gap: 8px; margin-top: 10px;">
            <input id="cssQueryInput" style="flex:1; padding:6px; background:${isDarkMode ? "#333" : "#f0f0f0"}; 
color:${isDarkMode ? "white" : "#333"}; border:none; border-radius:4px;" placeholder="CSS Selector">
            <button id="testQueryBtn" class="tool-btn">🔍</button>
        </div>
    `;
  document.body.appendChild(panel);

  // 样式和高亮元素
  const style = document.createElement("style");
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
            cursor: pointer;
            padding: 2px 4px;
            border-radius: 3px;
        }
        .path-part:hover {
            background: ${isDarkMode ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)"};
        }
        .validation-success {
            outline: 2px solid #00ff00 !important;
        }
        .validation-error {
            outline: 2px solid #ff0000 !important;
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

  const generateCssQuery = (element) => {
    // 如果元素有ID，直接返回ID选择器
    if (element.id) {
      return `#${element.id}`;
    }

    const levelsToCheck = 3; // 最大检查3层父元素
    let currentEl = element;
    const selectors = [];

    // 收集3层元素的特征
    for (
      let i = 0;
      i < levelsToCheck && currentEl && currentEl !== document.body;
      i++
    ) {
      const features = {
        tag: currentEl.tagName.toLowerCase(),
        id: currentEl.id,
        classes: Array.from(currentEl.classList),
      };
      selectors.push(features);
      currentEl = currentEl.parentElement;
    }

    // 生成所有可能的CSS选择器组合
    const selectorQueue = [];
    for (let i = 0; i < selectors.length; i++) {
      const { tag, id, classes } = selectors[i];
      const options = [];

      // 优先使用ID选择器
      if (id) {
        options.push(`#${id}`);
        continue;
      }

      // 使用类名模糊匹配
      if (classes.length > 0) {
        // 只处理前三个类名
        classes.slice(0, 3).forEach((cls) => {
          if (cls.includes("_")) {
            const prefix = cls.substring(0, cls.lastIndexOf("_"));
            options.push(`${tag}[class*="${prefix}"]`);
          } else {
            // 添加完整类名匹配
            options.push(`${tag}.${cls}`);
          }
        });
      }

      // 使用标签名
      options.push(tag);

      // 将当前层的选择器选项加入队列
      selectorQueue.push(options);
    }

    // 生成所有可能的组合
    const allCombinations = [];
    const generateCombinations = (currentLevel, currentPath) => {
      if (currentLevel >= selectorQueue.length) {
        allCombinations.push(currentPath);
        return;
      }

      selectorQueue[currentLevel].forEach((selector) => {
        const newPath = currentPath ? `${selector} > ${currentPath}` : selector;
        generateCombinations(currentLevel + 1, newPath);
      });
    };

    generateCombinations(0, "");

    // 存储所有匹配的选择器
    const validSelectors = [];

    // 检查所有组合
    for (const selector of allCombinations) {
      try {
        const matched = document.querySelector(selector);
        if (matched === element) {
          validSelectors.push(selector);
        }
      } catch (e) {
        continue;
      }
    }

    // 返回所有有效的选择器，按长度排序（最短的优先）
    if (validSelectors.length > 0) {
      validSelectors.sort((a, b) => a.length - b.length);
      return validSelectors;
    }

    // 如果所有组合都失败，返回最保守的选择器
    let selector = "";
    let currentElement = element;
    while (currentElement && currentElement !== document.documentElement) {
      const parent = currentElement.parentElement;
      if (parent) {
        const index = Array.from(parent.children).indexOf(currentElement) + 1;
        const tag = currentElement.tagName.toLowerCase();
        selector = `${tag}:nth-child(${index})${selector ? " > " + selector : ""}`;
        currentElement = parent;
      } else {
        break;
      }
    }
    return [selector];
  };

  const formatPathWithColors = (elements) => {
    const container = document.createElement("div");
    elements.forEach((el, index) => {
      const level = elements.length - index - 1; // 将level倒过来，父元素level高
      const select = document.createElement("select");
      select.className = "path-part";
      select.style.color = getColorForLevel(level);
      select.dataset.element = index; // 使用正序index

      // 添加默认选项
      const defaultOption = document.createElement("option");
      defaultOption.textContent = `Level ${level} ${el.tagName}`;
      defaultOption.disabled = true;
      defaultOption.selected = true;
      select.appendChild(defaultOption);

      // 点击时才生成选择器
      select.addEventListener("click", () => {
        if (select.options.length === 1) {
          // 只有默认选项时才生成
          const selectors = generateCssQuery(el);
          selectors.forEach((selector) => {
            const option = document.createElement("option");
            option.value = selector;
            option.textContent = selector;
            select.appendChild(option);
          });
        }
      });

      // 选择时更新输入框
      select.addEventListener("change", () => {
        panel.querySelector("#cssQueryInput").value = select.value;
      });

      container.appendChild(select);
      if (index < elements.length - 1) {
        container.appendChild(document.createTextNode(" "));
      }
    });
    return container;
  };

  // 高亮控制
  const createHighlight = (el, level, isFixed) => {
    const rect = el.getBoundingClientRect();
    const highlight = document.createElement("div");
    highlight.className = `highlight-layer${isFixed ? " fixed-highlight" : ""}`;
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
    dynamicHighlights.forEach((h) => h.remove());
    dynamicHighlights = [];

    const elements = getFullPath(target);
    elements.forEach((el, index) => {
      const level = elements.length - index - 1;
      const highlight = createHighlight(el, level, false);
      document.body.appendChild(highlight);
      dynamicHighlights.push(highlight);
    });

    // 更新路径显示
    const pathContainer = panel.querySelector("#elementPath");
    pathContainer.innerHTML = "";
    pathContainer.appendChild(formatPathWithColors(elements));
  };

  const createFixedHighlights = (target) => {
    fixedHighlights.forEach((h) => h.remove());
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
  const handleMouseMove = (e) => {
    if (!state.isSelecting || state.fixedElement) return;
    updateDynamicHighlights(e.target);
  };

  const handleElementClick = (e) => {
    e.preventDefault();
    e.stopImmediatePropagation();
    state.fixedElement = e.target;
    createFixedHighlights(e.target);
    panel.querySelector("#cssQueryInput").value = generateCssQuery(e.target);
    stopSelecting();
  };

  // 状态控制
  const startSelecting = () => {
    state.isSelecting = true;
    state.fixedElement = null;
    panel.querySelector("#toggleBtn").textContent = "Stop Selecting";
    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("click", handleElementClick, {
      capture: true,
      once: true,
    });
  };

  const stopSelecting = () => {
    state.isSelecting = false;
    document.removeEventListener("mousemove", handleMouseMove);
    document.removeEventListener("click", handleElementClick, true);
    panel.querySelector("#toggleBtn").textContent = "Start Selecting";

    dynamicHighlights.forEach((h) => h.remove());
    dynamicHighlights = [];
  };

  // 按钮事件
  panel.querySelector("#toggleBtn").addEventListener("click", () => {
    state.isSelecting ? stopSelecting() : startSelecting();
  });

  panel.querySelector("#clearBtn").addEventListener("click", () => {
    state.fixedElement = null;
    fixedHighlights.forEach((h) => h.remove());
    fixedHighlights = [];
    panel.querySelector("#elementPath").textContent = "";
    panel.querySelector("#cssQueryInput").value = "";
  });

  // ESC退出
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      dynamicHighlights.forEach((h) => h.remove());
      fixedHighlights.forEach((h) => h.remove());
      panel.remove();
      style.remove();
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("click", handleElementClick, true);
    }
  });
})();
