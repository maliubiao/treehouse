(function () {
  const DEBUG = true;
  const IDLE_TIMEOUT = 1000;
  const MAX_WAIT_TIME = 30000;
  const MAX_SCROLL_ATTEMPTS = 3; // 减少到3次滚动
  const SCROLL_HEIGHT_CHANGE_THRESHOLD = 50;

  let selectors = null;

  // 初始化监听器
  function initListener() {
    chrome.runtime.onMessage.addListener((message) => {
      if (message.action === "setSelectors") {
        selectors = message.selectors;
        DEBUG && console.debug("🎯 收到选择器:", selectors);
      }
    });
  }

  // 主执行流程
  async function main() {
    DEBUG && console.debug("🏁 启动内容提取流程");
    
    try {
      await scrollUntilContentStable();
      const html = await processPageContent();
      sendHtmlContent(html);
    } catch (error) {
      console.error("内容提取失败:", error);
    } finally {
      window.scrollTo(0, document.documentElement.scrollHeight);
    }
  }

  // 滚动直到内容稳定
  async function scrollUntilContentStable() {
    let scrollCount = 0;
    let lastScrollHeight = document.documentElement.scrollHeight;
    
    while (scrollCount < MAX_SCROLL_ATTEMPTS) {
      scrollCount++;
      DEBUG && console.debug(`🔄 第${scrollCount}次滚动到底部`);
      
      // 滚动并等待
      window.scrollTo(0, document.documentElement.scrollHeight);
      const hadNetworkActivity = await waitForNetworkIdle();
      
      // 检查高度变化
      const newScrollHeight = document.documentElement.scrollHeight;
      const heightChanged = Math.abs(newScrollHeight - lastScrollHeight) > SCROLL_HEIGHT_CHANGE_THRESHOLD;
      
      DEBUG && console.debug(
        `📏 高度变化: ${lastScrollHeight} -> ${newScrollHeight} (${heightChanged ? "有变化" : "无变化"}), ` +
        `网络活动: ${hadNetworkActivity ? "有" : "无"}`
      );
      
      // 终止条件：内容稳定且无网络活动
      if (!heightChanged && !hadNetworkActivity) {
        DEBUG && console.debug("🛑 内容稳定，停止滚动");
        return;
      }
      
      lastScrollHeight = newScrollHeight;
    }
    
    DEBUG && console.debug("🛑 达到最大滚动次数");
  }

  // 处理页面内容
  async function processPageContent() {
    return new Promise((resolve) => {
      DEBUG && console.debug("🔍 处理页面内容...");
      
      // 创建新文档处理
      const doc = new DOMParser().parseFromString(
        document.documentElement.outerHTML,
        "text/html"
      );
      DEBUG && console.debug("✅ 重建DOM树完成");
      
      // 应用选择器或默认处理
      const html = selectors && selectors.length > 0 
        ? applySelectors(doc) 
        : applyDefaultProcessing(doc);
      
      resolve(html);
    });
  }

  // 应用选择器提取内容
  function applySelectors(doc) {
    DEBUG && console.debug("🎯 使用选择器过滤内容");
    
    const selectedElements = [];
    
    selectors.forEach((selector) => {
      const elements = selector.startsWith("//")
        ? getElementsByXPath(selector, doc)
        : doc.querySelectorAll(selector);
      
      if (!elements || elements.length === 0) return;
      
      elements.forEach((element) => {
        const isChild = selectedElements.some(selected => 
          selected.contains(element)
        );
        
        const isParent = selectedElements.some(selected => 
          element.contains(selected)
        );
        
        if (isParent) {
          // 移除被当前元素包含的旧元素
          selectedElements = selectedElements.filter(
            selected => !element.contains(selected)
          );
        }
        
        if (!isChild) {
          selectedElements.push(element);
        }
      });
    });
    
    if (selectedElements.length === 0) {
      DEBUG && console.debug("ℹ️ 选择器未匹配到内容，使用默认处理");
      return applyDefaultProcessing(doc);
    }
    
    return wrapHtmlContent(
      selectedElements.map(el => el.outerHTML).join("\n")
    );
  }

  // XPath查询元素
  function getElementsByXPath(xpath, doc) {
    const result = doc.evaluate(
      xpath,
      doc,
      null,
      XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
      null
    );
    
    const elements = [];
    for (let i = 0; i < result.snapshotLength; i++) {
      elements.push(result.snapshotItem(i));
    }
    
    return elements;
  }

  // 默认处理逻辑
  function applyDefaultProcessing(doc) {
    DEBUG && console.debug("ℹ️ 使用默认处理逻辑");
    
    // 移除样式表
    const links = doc.querySelectorAll('link[rel="stylesheet"]');
    links.forEach(link => link.remove());
    DEBUG && console.debug(`🗑️ 移除 ${links.length} 个CSS链接`);
    
    // 移除媒体元素
    const mediaElements = doc.querySelectorAll(
      "audio, source, track, object, embed, canvas, svg, style, noscript, script"
    );
    mediaElements.forEach(el => el.remove());
    DEBUG && console.debug(`🗑️ 移除 ${mediaElements.length} 个媒体元素`);
    
    return wrapHtmlContent(doc.body.innerHTML);
  }

  // 包装HTML内容
  function wrapHtmlContent(bodyContent) {
    return `<!DOCTYPE html>
<html>
<head>
  <meta charset="${document.characterSet}">
  <title>${document.title}</title>
</head>
<body>
${bodyContent}
</body>
</html>`;
  }

  // 发送HTML内容
  function sendHtmlContent(html) {
    if (DEBUG) {
      console.debug("📄 生成最终HTML:");
      console.debug(html.substring(0, 200) + (html.length > 200 ? "..." : ""));
    }
    
    chrome.runtime.sendMessage({
      action: "htmlContent",
      content: html
    });
    
    DEBUG && console.debug("📨 已发送HTML内容到后台脚本");
  }

  // 等待网络空闲
  function waitForNetworkIdle() {
    return new Promise((resolve) => {
      const startTime = Date.now();
      let lastRequestTime = Date.now();
      let timer;
      let observer;
      let hadNetworkActivity = false;

      // 使用PerformanceObserver监听网络活动
      if (window.PerformanceObserver) {
        observer = new PerformanceObserver((list) => {
          list.getEntries().forEach((entry) => {
            lastRequestTime = Date.now();
            hadNetworkActivity = true;
            DEBUG && console.debug("🌐 检测到网络活动:", entry.name);
            resetTimer();
          });
        });
        observer.observe({ entryTypes: ["resource"] });
      }

      // 最大等待超时
      const maxTimer = setTimeout(() => {
        cleanup();
        DEBUG && console.debug("⏰ 达到最大等待时间，继续流程");
        resolve(hadNetworkActivity);
      }, MAX_WAIT_TIME);

      // 重置空闲检测定时器
      function resetTimer() {
        clearTimeout(timer);
        timer = setTimeout(checkIdle, IDLE_TIMEOUT);
      }

      // 检查是否空闲
      function checkIdle() {
        const elapsed = Date.now() - lastRequestTime;
        if (elapsed >= IDLE_TIMEOUT) {
          DEBUG && console.debug(`🛑 网络空闲 ${(elapsed / 1000).toFixed(1)}秒`);
          cleanup();
          resolve(hadNetworkActivity);
        }
      }

      // 清理资源
      function cleanup() {
        clearTimeout(timer);
        clearTimeout(maxTimer);
        if (observer) observer.disconnect();
      }

      resetTimer();
    });
  }

  // 初始化
  initListener();
  setTimeout(main, 1000);
})();