(function () {
  const IDLE_TIMEOUT = 1000;
  const MAX_WAIT_TIME = 30000;
  const MAX_SCROLL_ATTEMPTS = 3;
  const SCROLL_HEIGHT_CHANGE_THRESHOLD = 50;

  let selectors = null;

  // 主执行流程
  async function main() {
    console.log("🏁 启动内容提取流程");
    try {
      await scrollUntilContentStable();
      const html = await processPageContent();
      sendHtmlContent(html);
    } catch (error) {
      console.error("🚨 内容提取失败:", error);
      // 即使失败，也发送错误信息回去，避免服务端超时
      sendHtmlContent(
        `<html><body><h1>Extraction Failed on Page</h1><p>${error.message}</p></body></html>`,
      );
    }
  }

  // 滚动直到内容稳定
  async function scrollUntilContentStable() {
    let scrollCount = 0;
    let lastScrollHeight = document.documentElement.scrollHeight;

    while (scrollCount < MAX_SCROLL_ATTEMPTS) {
      scrollCount++;
      console.log(`🔄 第${scrollCount}次滚动到底部`);

      window.scrollTo(0, document.documentElement.scrollHeight);
      const hadNetworkActivity = await waitForNetworkIdle();

      const newScrollHeight = document.documentElement.scrollHeight;
      const heightChanged =
        Math.abs(newScrollHeight - lastScrollHeight) >
        SCROLL_HEIGHT_CHANGE_THRESHOLD;

      console.log(
        `📏 高度变化: ${lastScrollHeight} -> ${newScrollHeight} (${heightChanged ? "有变化" : "无变化"}), 网络活动: ${hadNetworkActivity ? "有" : "无"}`,
      );

      if (!heightChanged && !hadNetworkActivity) {
        console.log("🛑 内容稳定，停止滚动");
        return;
      }

      lastScrollHeight = newScrollHeight;
    }

    console.log("🛑 达到最大滚动次数");
  }

  // 处理页面内容
  async function processPageContent() {
    return new Promise((resolve) => {
      console.log("🔍 正在处理页面内容...");
      const doc = new DOMParser().parseFromString(
        document.documentElement.outerHTML,
        "text/html",
      );
      console.log("✅ DOM树重建完成");

      const html =
        selectors && selectors.length > 0
          ? applySelectors(doc)
          : applyDefaultProcessing(doc);

      resolve(html);
    });
  }

  // 应用选择器提取内容
  function applySelectors(doc) {
    console.log("🎯 使用选择器过滤内容:", selectors);
    let selectedElements = [];

    selectors.forEach((selector) => {
      try {
        const elements = selector.startsWith("//")
          ? getElementsByXPath(selector, doc)
          : doc.querySelectorAll(selector);

        if (!elements || elements.length === 0) return;

        elements.forEach((element) => {
          if (!element || typeof element.outerHTML !== "string") return;

          const isChild = selectedElements.some((selected) =>
            selected.contains(element),
          );
          if (isChild) return;

          // 移除被当前元素包含的旧元素
          selectedElements = selectedElements.filter(
            (selected) => !element.contains(selected),
          );
          selectedElements.push(element);
        });
      } catch (e) {
        console.error(`🚨 无效的选择器 '${selector}':`, e);
      }
    });

    if (selectedElements.length === 0) {
      console.warn("⚠️ 选择器未匹配到任何内容，将使用默认处理");
      return applyDefaultProcessing(doc);
    }
    console.log(`✅ 选择器匹配到 ${selectedElements.length} 个顶层元素`);
    return wrapHtmlContent(
      selectedElements.map((el) => el.outerHTML).join("\n"),
    );
  }

  // XPath查询元素
  function getElementsByXPath(xpath, doc) {
    const result = doc.evaluate(
      xpath,
      doc,
      null,
      XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
      null,
    );
    const elements = [];
    for (let i = 0; i < result.snapshotLength; i++) {
      elements.push(result.snapshotItem(i));
    }
    return elements;
  }

  // 默认处理逻辑
  function applyDefaultProcessing(doc) {
    console.log("ℹ️ 使用默认处理逻辑 (提取body内容)");
    const elementsToRemove = doc.querySelectorAll(
      "script, style, noscript, svg, canvas, footer, header, nav",
    );
    elementsToRemove.forEach((el) => el.remove());
    console.log(`🗑️ 移除了 ${elementsToRemove.length} 个无关元素`);
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
    console.log("📄 生成最终HTML, 长度:", html.length);
    try {
      chrome.runtime.sendMessage({
        action: "htmlContent",
        content: html,
      });
      console.log("📨 已发送HTML内容到后台脚本");
    } catch (error) {
      console.error("🚨 发送HTML到后台脚本失败:", error);
    }
  }

  // 等待网络空闲
  function waitForNetworkIdle() {
    return new Promise((resolve) => {
      let lastRequestTime = Date.now();
      let timer;
      let observer;
      let hadNetworkActivity = false;

      if (window.PerformanceObserver) {
        observer = new PerformanceObserver((list) => {
          lastRequestTime = Date.now();
          hadNetworkActivity = true;
          resetTimer();
        });
        observer.observe({ entryTypes: ["resource"] });
      }

      const maxTimer = setTimeout(() => {
        cleanup();
        console.log("⏰ 达到最大等待时间，继续流程");
        resolve(hadNetworkActivity);
      }, MAX_WAIT_TIME);

      function resetTimer() {
        clearTimeout(timer);
        timer = setTimeout(checkIdle, IDLE_TIMEOUT);
      }

      function checkIdle() {
        if (Date.now() - lastRequestTime >= IDLE_TIMEOUT) {
          console.log("🛑 网络已空闲");
          cleanup();
          resolve(hadNetworkActivity);
        }
      }

      function cleanup() {
        clearTimeout(timer);
        clearTimeout(maxTimer);
        if (observer) observer.disconnect();
      }

      resetTimer();
    });
  }

  // 脚本入口: 监听来自 background.js 的消息
  console.log("🚀 extract.js 已加载，等待配置消息...");
  chrome.runtime.onMessage.addListener((message) => {
    if (message.action === "setSelectors") {
      selectors = message.selectors;
      console.log("🎯 收到选择器配置，即将开始提取:", selectors);
      main(); // 收到消息后，启动主流程
    }
  });
})();