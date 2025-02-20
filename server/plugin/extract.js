(function () {
  // 在文件开头添加调试开关
  const DEBUG = true; // 设为false关闭调试输出

  // 配置参数
  const IDLE_TIMEOUT = 1000; // 2秒无网络活动视为空闲
  const MAX_WAIT_TIME = 30000; // 30秒最大等待时间
  const SCROLL_ATTEMPTS = 1; // 滚动尝试次数

  let selectors = null; // 存储从background.js接收的选择器

  // 监听来自background.js的消息
  chrome.runtime.onMessage.addListener((message) => {
    if (message.action === "setSelectors") {
      selectors = message.selectors;
      if (DEBUG) console.debug("🎯 收到选择器:", selectors);
    }
  });

  async function main() {
    if (DEBUG) console.debug("🏁 启动内容提取流程");

    try {
      // 初始滚动并等待内容加载
      for (let i = 0; i < SCROLL_ATTEMPTS; i++) {
        window.scrollTo(0, document.body.scrollHeight);
        if (DEBUG) console.debug(`🔄 第${i + 1}次滚动到底部`);
        await waitForNetworkIdle();
      }

      // 最终等待网络空闲后提取内容
      await waitForNetworkIdle();
      const html = await processContent();
      sendContent(html);
    } catch (error) {
      console.error("内容提取失败:", error);
    } finally {
      // 确保最终清理
      window.scrollTo(0, document.body.scrollHeight);
    }
  }

  function processContent() {
    return new Promise((resolve) => {
      if (DEBUG) console.debug("🔍 开始处理页面内容...");

      // 使用outerHTML重建独立DOM树
      const parser = new DOMParser();
      const doc = parser.parseFromString(
        document.documentElement.outerHTML,
        "text/html",
      );
      if (DEBUG) console.debug("✅ 重建DOM树完成");

      // 如果有选择器，优先使用选择器过滤内容
      if (selectors && selectors.length > 0) {
        if (DEBUG) console.debug("🎯 使用选择器过滤内容");
        const selectedElements = [];
        selectors.forEach((selector) => {
          const elements = doc.querySelectorAll(selector);
          if (elements.length > 0) {
            elements.forEach((element) => {
              // 检查当前元素是否是已添加元素的子元素
              const isChild = selectedElements.some((selected) =>
                selected.contains(element),
              );
              // 检查当前元素是否包含已添加元素
              const isParent = selectedElements.some((selected) =>
                element.contains(selected),
              );

              // 如果是父元素，移除所有子元素
              if (isParent) {
                selectedElements = selectedElements.filter(
                  (selected) => !element.contains(selected),
                );
              }
              if (!isChild) {
                selectedElements.push(element);
              }
            });
          }
        });
        if (selectedElements.length > 0) {
          // 使用选择器匹配的内容构建新HTML
          const html = `<!DOCTYPE html>
<html>
<head>
  <meta charset="${document.characterSet}">
  <title>${document.title}</title>
</head>
<body>
  ${selectedElements.map((el) => el.outerHTML).join("\n")}
</body>
</html>`;
          return resolve(html);
        }
      }

      // 如果没有选择器或选择器未匹配到内容，使用原始逻辑
      if (DEBUG) console.debug("ℹ️ 未使用选择器或选择器未匹配，使用原始逻辑");

      // 移除所有CSS链接（保留内联样式）
      const links = doc.querySelectorAll('link[rel="stylesheet"]');
      links.forEach((link) => link.remove());
      if (DEBUG) console.debug(`🗑️ 移除 ${links.length} 个CSS链接`);

      // 移除媒体元素（修正选择器排除style标签）
      const mediaSelectors =
        "audio, source, track, object, embed, canvas, svg, style, noscript, script";
      const mediaElements = doc.querySelectorAll(mediaSelectors);
      mediaElements.forEach((el) => el.remove());
      if (DEBUG) console.debug(`🗑️ 移除 ${mediaElements.length} 个媒体元素`);

      // 构建最终HTML（保留内联样式）
      const html = `<!DOCTYPE html>
<html>
<head>
  <meta charset="${document.characterSet}">
  <title>${document.title}</title>
</head>
<body>
  ${doc.body.innerHTML}
</body>
</html>`;

      resolve(html);
    });
  }

  function sendContent(html) {
    if (DEBUG) {
      console.debug("📄 生成最终HTML:");
      console.debug(html.substring(0, 200) + "...");
    }

    chrome.runtime.sendMessage({
      action: "htmlContent",
      content: html,
    });
    if (DEBUG) console.debug("📨 已发送HTML内容到后台脚本");
  }

  function waitForNetworkIdle() {
    return new Promise((resolve) => {
      const startTime = Date.now();
      let lastRequestTime = Date.now();
      let timer;
      let observer;

      // 网络活动检测
      if (window.PerformanceObserver) {
        observer = new PerformanceObserver((list) => {
          list.getEntries().forEach((entry) => {
            lastRequestTime = Date.now();
            if (DEBUG) console.debug("🌐 检测到网络活动:", entry.name);
            resetTimer();
          });
        });
        observer.observe({ entryTypes: ["resource"] });
      }

      // 设置超时后备
      const maxTimer = setTimeout(() => {
        cleanup();
        if (DEBUG) console.debug("⏰ 达到最大等待时间，继续流程");
        resolve();
      }, MAX_WAIT_TIME);

      function resetTimer() {
        clearTimeout(timer);
        timer = setTimeout(checkIdle, IDLE_TIMEOUT);
      }

      function checkIdle() {
        const elapsed = Date.now() - lastRequestTime;
        if (elapsed >= IDLE_TIMEOUT) {
          if (DEBUG)
            console.debug(`🛑 网络空闲 ${(elapsed / 1000).toFixed(1)}秒`);
          cleanup();
          resolve();
        }
      }

      function cleanup() {
        clearTimeout(timer);
        clearTimeout(maxTimer);
        if (observer) observer.disconnect();
      }

      resetTimer(); // 初始启动检测
    });
  }

  // 启动主流程
  setTimeout(main, 1000); // 初始延迟1秒开始流程
})();
