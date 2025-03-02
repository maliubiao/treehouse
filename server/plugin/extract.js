(function () {
  const DEBUG = true;
  const IDLE_TIMEOUT = 1000;
  const MAX_WAIT_TIME = 30000;
  const SCROLL_ATTEMPTS = 2; // 增加滚动次数
  const SCROLL_BACK_DELAY = 1000; // 新增回滚等待时间

  let selectors = null;

  chrome.runtime.onMessage.addListener((message) => {
    if (message.action === "setSelectors") {
      selectors = message.selectors;
      if (DEBUG) console.debug("🎯 收到选择器:", selectors);
    }
  });

  async function main() {
    if (DEBUG) console.debug("🏁 启动内容提取流程");

    try {
      // 改进的滚动逻辑：滚动到底部 -> 等待 -> 回滚顶部 -> 等待
      for (let i = 0; i < SCROLL_ATTEMPTS; i++) {
        // 向下滚动
        window.scrollTo(0, document.body.scrollHeight);
        if (DEBUG) console.debug(`🔄 第${i + 1}次滚动到底部`);
        await waitForNetworkIdle();

        // 向上滚动并等待
        window.scrollTo(0, 0);
        if (DEBUG) console.debug(`🔼 第${i + 1}次滚动回顶部`);
        await new Promise((resolve) => setTimeout(resolve, SCROLL_BACK_DELAY));
      }

      const html = await processContent();
      sendContent(html);
    } catch (error) {
      console.error("内容提取失败:", error);
    } finally {
      window.scrollTo(0, document.body.scrollHeight);
    }
  }

  function processContent() {
    return new Promise((resolve) => {
      if (DEBUG) console.debug("🔍 开始处理页面内容...");

      const parser = new DOMParser();
      const doc = parser.parseFromString(
        document.documentElement.outerHTML,
        "text/html",
      );
      if (DEBUG) console.debug("✅ 重建DOM树完成");

      if (selectors && selectors.length > 0) {
        if (DEBUG) console.debug("🎯 使用选择器过滤内容");
        const selectedElements = [];
        selectors.forEach((selector) => {
          const elements = selector.startsWith("//")
            ? (() => {
                const result = document.evaluate(
                  selector,
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
              })()
            : doc.querySelectorAll(selector);
          if (elements.length > 0) {
            elements.forEach((element) => {
              const isChild = selectedElements.some((selected) =>
                selected.contains(element),
              );
              const isParent = selectedElements.some((selected) =>
                element.contains(selected),
              );

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

      if (DEBUG) console.debug("ℹ️ 未使用选择器或选择器未匹配，使用原始逻辑");

      const links = doc.querySelectorAll('link[rel="stylesheet"]');
      links.forEach((link) => link.remove());
      if (DEBUG) console.debug(`🗑️ 移除 ${links.length} 个CSS链接`);

      const mediaSelectors =
        "audio, source, track, object, embed, canvas, svg, style, noscript, script";
      const mediaElements = doc.querySelectorAll(mediaSelectors);
      mediaElements.forEach((el) => el.remove());
      if (DEBUG) console.debug(`🗑️ 移除 ${mediaElements.length} 个媒体元素`);

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

      resetTimer();
    });
  }

  setTimeout(main, 1000);
})();
