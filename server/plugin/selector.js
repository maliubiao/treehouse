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

  // 检测系统语言
  const isChinese = navigator.language.startsWith("zh");

  // 多语言文本
  const texts = {
    title: isChinese ? "元素选择器 v3.1" : "Element Inspector v3.1",
    startBtn: isChinese ? "🎯 开始" : "🎯 Start",
    clearBtn: isChinese ? "🗑️ 清除" : "🗑️ Clear",
    inputPlaceholder: isChinese ? "CSS 选择器" : "CSS Selector",
  };
  // 创建控制面板
  const panel = document.createElement("div");
  panel.id = "element-selector-panel";

  // 使用特定前缀隔离样式
  const prefix = "element-selector-";
  const panelStyles = `
    .${prefix}panel {
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
    }
    .${prefix}panel-title {
      margin-bottom: 12px;
      font-weight: bold;
      color: #00ff9d;
    }
    .${prefix}button-group {
      margin-bottom: 10px;
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .${prefix}input-group {
      margin-top: 10px;
    }
    .${prefix}url-input {
      width: 100%;
      padding: 6px;
      background: ${isDarkMode ? "#333" : "#f0f0f0"};
      color: ${isDarkMode ? "white" : "#333"};
      border: none;
      border-radius: 4px;
    }
    .${prefix}css-input {
      flex: 1;
      padding: 6px;
      background: ${isDarkMode ? "#333" : "#f0f0f0"};
      color: ${isDarkMode ? "white" : "#333"};
      border: none;
      border-radius: 4px;
    }
    .${prefix}highlight-layer {
      position: absolute;
      pointer-events: none;
      box-sizing: border-box;
      z-index: 99999;
      opacity: 0.7;
      transition: all 0.15s;
    }
    .${prefix}fixed-highlight {
      box-shadow: 0 0 6px rgba(255,255,255,0.5);
    }
    .${prefix}path-part {
      display: inline-block;
      margin-right: 4px;
      transition: color 0.2s;
      cursor: pointer;
      padding: 2px 4px;
      border-radius: 3px;
    }
    .${prefix}path-part:hover {
      background: ${isDarkMode ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)"};
    }
    .${prefix}validation-success {
      outline: 2px solid #00ff00 !important;
    }
    .${prefix}validation-error {
      outline: 2px solid #ff0000 !important;
    }
  `;

  // 添加样式到文档
  const styleSheet = document.createElement("style");
  styleSheet.type = "text/css";
  styleSheet.innerText = panelStyles;
  document.head.appendChild(styleSheet);

  // 设置面板类名
  panel.className = `${prefix}panel`;

  // 构建面板内容
  panel.innerHTML = `
    <div class="${prefix}panel-title">${texts.title}</div>
    <div class="${prefix}button-group">
      <button id="${prefix}toggleBtn" class="${prefix}tool-btn">${texts.startBtn}</button>
      <button id="${prefix}clearBtn" class="${prefix}tool-btn">${texts.clearBtn}</button>
    </div>
    <div id="${prefix}elementPath" class="${prefix}path-container"></div>
    <div class="${prefix}input-group">
      <div style="margin-bottom: 8px;">
        <input id="${prefix}urlInput" class="${prefix}url-input" placeholder="当前网址" value="${window.location.href}">
      </div>
      <div style="display: flex; gap: 8px;">
        <input id="${prefix}cssQueryInput" class="${prefix}css-input" placeholder="匹配模式">
        <button id="${prefix}saveQueryBtn" class="${prefix}tool-btn" style="background: #4CAF50;">💾保存配置</button>
      </div>
    </div>
  `;
  document.body.appendChild(panel);

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
      select.className = `${prefix}path-part`; // 添加前缀
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

      // 选择时更新输入框并添加闪烁效果
      select.addEventListener("change", () => {
        panel.querySelector(`#${prefix}cssQueryInput`).value = select.value;

        // 创建闪烁图层
        const highlight = document.createElement("div");
        highlight.style.position = "absolute";
        highlight.style.backgroundColor = "rgba(0, 0, 255, 0.2)";
        highlight.style.pointerEvents = "none";

        // 获取元素位置
        const rect = el.getBoundingClientRect();
        highlight.style.width = `${rect.width}px`;
        highlight.style.height = `${rect.height}px`;
        highlight.style.left = `${rect.left + window.scrollX}px`;
        highlight.style.top = `${rect.top + window.scrollY}px`;

        // 添加到页面
        document.body.appendChild(highlight);

        // 2秒后移除
        setTimeout(() => {
          highlight.remove();
        }, 2000);
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
    highlight.className = `${prefix}highlight-layer${isFixed ? ` ${prefix}fixed-highlight` : ""}`; // 添加前缀
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
    const pathContainer = panel.querySelector(`#${prefix}elementPath`);
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
    panel.querySelector(`#${prefix}cssQueryInput`).value = generateCssQuery(
      e.target,
    );
    stopSelecting();
  };

  // 状态控制
  const startSelecting = () => {
    state.isSelecting = true;
    state.fixedElement = null;
    panel.querySelector(`#${prefix}toggleBtn`).textContent = "Stop Selecting";
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
    panel.querySelector(`#${prefix}toggleBtn`).textContent = "Start Selecting";

    dynamicHighlights.forEach((h) => h.remove());
    dynamicHighlights = [];
  };

  // 按钮事件
  panel.querySelector(`#${prefix}toggleBtn`).addEventListener("click", () => {
    state.isSelecting ? stopSelecting() : startSelecting();
  });

  panel.querySelector(`#${prefix}clearBtn`).addEventListener("click", () => {
    state.fixedElement = null;
    fixedHighlights.forEach((h) => h.remove());
    fixedHighlights = [];
    panel.querySelector(`#${prefix}elementPath`).textContent = "";
    panel.querySelector(`#${prefix}cssQueryInput`).value = "";
  });

  panel
    .querySelector(`#${prefix}saveQueryBtn`)
    .addEventListener("click", () => {
      const saveBtn = panel.querySelector(`#${prefix}saveQueryBtn`);
      const url = window.location.href;
      const cssQuery = panel
        .querySelector(`#${prefix}cssQueryInput`)
        .value.trim();

      // 验证URL模式，支持完整的GLOB模式匹配
      const urlPattern = panel.querySelector(`#${prefix}urlInput`).value;
      if (!urlPattern) {
        panel.querySelector(`#${prefix}urlInput`).style.border =
          "1px solid red";
        setTimeout(() => {
          panel.querySelector(`#${prefix}urlInput`).style.border = "none";
        }, 1000);
        return;
      }

      // 将GLOB模式转换为正则表达式
      // 1. 转义特殊字符
      let regexPattern = urlPattern
        .replace(/[.+^${}()|[\]\\]/g, "\\$&") // 转义正则特殊字符
        .replace(/\*/g, ".*") // 将*替换为任意字符
        .replace(/\?/g, ".") // 将?替换为单个字符
        .replace(/\//g, "\\/") // 转义路径分隔符
        .replace(/^\^+|\$+$/g, ""); // 去除多余的开始和结束锚点
      // 添加标准化的开始和结束锚点
      regexPattern = `^${regexPattern}$`;

      try {
        const regex = new RegExp(regexPattern);
        if (!regex.test(url)) {
          panel.querySelector(`#${prefix}urlInput`).style.border =
            "1px solid red";
          setTimeout(() => {
            panel.querySelector(`#${prefix}urlInput`).style.border = "none";
          }, 1000);
          return;
        }
      } catch (error) {
        console.error("无效的URL模式:", error);
        panel.querySelector(`#${prefix}urlInput`).style.border =
          "1px solid red";
        setTimeout(() => {
          panel.querySelector(`#${prefix}urlInput`).style.border = "none";
        }, 1000);
        return;
      }

      // 验证CSS选择器
      try {
        const elements = document.querySelectorAll(cssQuery);
        if (elements.length === 0) {
          throw new Error("No matching elements");
        }
      } catch (error) {
        panel.querySelector(`#${prefix}cssQueryInput`).style.border =
          "1px solid red";
        setTimeout(() => {
          panel.querySelector(`#${prefix}cssQueryInput`).style.border = "none";
        }, 1000);
        return;
      }

      // 保存配置
      chrome.runtime.sendMessage(
        {
          type: "selectorConfig",
          url: urlPattern,
          selector: cssQuery,
        },
        (response) => {
          if (chrome.runtime.lastError) {
            console.error("保存失败:", chrome.runtime.lastError);
            // 保存失败时按钮变红
            saveBtn.style.backgroundColor = "#ff4444";
            saveBtn.textContent = "❌ 保存失败";
            setTimeout(() => {
              saveBtn.style.backgroundColor = "";
              saveBtn.textContent = "💾 保存配置";
            }, 2000);
          } else {
            console.log("保存成功");
            // 保存成功时按钮变绿
            saveBtn.style.backgroundColor = "#4CAF50";
            saveBtn.textContent = "✅ 保存成功";
            setTimeout(() => {
              saveBtn.style.backgroundColor = "";
              saveBtn.textContent = "💾 保存配置";
            }, 2000);
          }
        },
      );
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
