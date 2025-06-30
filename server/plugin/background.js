let ws = null,
  reconnectTimer = null;
let currentTabId = null;
let requestId = null;
let isTabCreatedByUs = false;
let selectors = null;
let pingInterval = null; // 心跳定时器
const PING_INTERVAL = 25000; // 25秒发送一次心跳

async function connectWebSocket(serverUrl) {
  if (ws && ws.readyState === WebSocket.OPEN) return;
  console.log("🔄 正在连接WS服务器...");
  
  // 清理之前的连接
  if (ws) {
    ws.onopen = null;
    ws.onmessage = null;
    ws.onclose = null;
    ws.onerror = null;
    if (ws.readyState !== WebSocket.CLOSED) {
      ws.close();
    }
    ws = null;
  }
  
  ws = new WebSocket(serverUrl);

  ws.onopen = () => {
    console.log("✅ 成功连接WS服务器");
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    
    // 启动心跳机制
    startHeartbeat();
  };

  ws.onmessage = async (event) => {
    console.log("📨 收到服务器消息:", event.data.substring(0, 200) + "...");
    try {
      const data = JSON.parse(event.data);
      if (data.type === "extract") {
        const existingTab = await findExistingTab(data.url);
        requestId = data.requestId; // Set request ID early
        selectors = data.selectors; // 保存选择器

        if (existingTab) {
          currentTabId = existingTab.id;
          isTabCreatedByUs = false;
          console.log(`🔍 找到已存在的标签页，ID: ${currentTabId}`);
          await injectScript(currentTabId);
        } else {
          isTabCreatedByUs = true;
          currentTabId = await createTab(data.url);
        }
      } else if (data.type === "pong") {
        console.log("💓 收到服务器pong响应");
      }
    } catch (e) {
      console.error("🚨 解析服务器消息失败. Error:", e, "Raw data:", event.data);
    }
  };

  ws.onclose = (event) => {
    console.error(
      `❌ WS连接断开. Code: ${event.code}, Reason: '${event.reason}'. 1秒后重连...`,
    );
    stopHeartbeat();
    ws = null;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(() => initWebSocket(), 1000);
  };

  ws.onerror = (error) => {
    console.error("🚨 WebSocket 发生错误:", error);
    stopHeartbeat();
  };
}

// 启动心跳机制
function startHeartbeat() {
  if (pingInterval) {
    clearInterval(pingInterval);
  }
  
  pingInterval = setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      console.log("💓 发送心跳ping");
      ws.send(JSON.stringify({ type: "ping" }));
    }
  }, PING_INTERVAL);
}

// 停止心跳机制
function stopHeartbeat() {
  if (pingInterval) {
    clearInterval(pingInterval);
    pingInterval = null;
  }
}

async function findExistingTab(url) {
  const tabs = await chrome.tabs.query({});
  return tabs.find((tab) => tab.url === url);
}

async function injectScript(tabId) {
  console.log(`⏳ 准备向Tab ${tabId} 注入提取脚本...`);
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ["extract.js"],
    });
    console.log(`✅ 脚本注入成功. 正在发送选择器到Tab ${tabId}:`, selectors);
    await chrome.tabs.sendMessage(tabId, {
      action: "setSelectors",
      selectors: selectors,
    });
    console.log(`👍 选择器已成功发送到Tab ${tabId}`);
  } catch (error) {
    console.error(`🚨 脚本注入或消息发送失败 Tab ${tabId}:`, error);
    // 向服务端报告错误，而不是静默失败
    if (ws && ws.readyState === WebSocket.OPEN && requestId) {
      const errorMessage = `<html><body><h1>Extraction Failed</h1><p>Could not execute script in the target tab. Please ensure the page is not a protected system page (e.g., chrome://) and that the extension has permissions.</p><p>Error: ${error.message}</p></body></html>`;
      ws.send(
        JSON.stringify({
          type: "htmlResponse",
          content: errorMessage,
          requestId: requestId,
        }),
      );
      // 重置状态
      requestId = null;
      currentTabId = null;
    }
  }
}

function initWebSocket() {
  chrome.storage.local.get(["serverUrl"], (result) => {
    const serverUrl = result.serverUrl || "ws://localhost:8000/ws";
    connectWebSocket(serverUrl);
  });
}

async function createTab(url) {
  console.log(`🆕 正在创建新标签页: ${url}`);
  try {
    const tab = await chrome.tabs.create({ url, active: false });
    console.log(`✅ 标签页创建成功，ID: ${tab.id}`);
    chrome.tabs.onUpdated.addListener(async function listener(
      tabId,
      changeInfo,
    ) {
      if (tabId === tab.id && changeInfo.status === "complete") {
        console.log(`✨ Tab ${tabId} 加载完成，注入脚本...`);
        await injectScript(tabId);
        chrome.tabs.onUpdated.removeListener(listener);
      }
    });
    return tab.id;
  } catch (error) {
    console.error(`🚨 创建标签页失败: ${url}`, error);
    return null;
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === "htmlContent") {
    if (sender.tab && sender.tab.id === currentTabId) {
      console.log(
        `📤 收到来自Tab ${sender.tab.id} 的HTML内容，长度: ${message.content.length}。正在发往服务器...`,
      );
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(
          JSON.stringify({
            type: "htmlResponse",
            content: message.content,
            requestId: requestId,
          }),
        );
      } else {
        console.error("🚨 无法发送HTML内容：WebSocket未连接。");
      }
      // 重置状态
      requestId = null;
      if (isTabCreatedByUs) {
        chrome.tabs.remove(sender.tab.id);
        console.log(`🚮 已关闭由插件创建的Tab ${sender.tab.id}`);
      }
      currentTabId = null;
      isTabCreatedByUs = false;
      selectors = null;
    } else {
      console.warn(
        `⚠️ 收到来自非预期Tab的消息，忽略。来源Tab: ${sender.tab ? sender.tab.id : "未知"}, 预期Tab: ${currentTabId}`,
      );
    }
  } else if (message.type == "selectorConfig") {
    console.log(`📤 正在发送selector配置到服务器: ${message.selector}`);
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(
        JSON.stringify({
          type: "selectorConfig",
          url: message.url,
          selector: message.selector,
        }),
      );
      sendResponse({ status: "success" });
    } else {
      console.error("🚨 无法发送配置：WebSocket未连接。");
      sendResponse({ status: "error", message: "WebSocket not connected" });
    }
    return true; // 为sendResponse保持通道开放
  }
  return true; // 保持消息通道对其他异步事件开放
});

// 初始化连接
initWebSocket();

// 添加周期性的闹钟唤醒Service Worker
chrome.alarms.create("keepAlive", { periodInMinutes: 4.5 });

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "keepAlive") {
    console.log("⏰ 保活闹钟触发，保持Service Worker活跃");
    // 检查WebSocket连接状态
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      console.log("🔌 WebSocket未连接，尝试重新连接");
      initWebSocket();
    }
  }
});

// 安装时设置闹钟
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("keepAlive", { periodInMinutes: 4.5 });
  console.log("🔔 已创建保活闹钟");
});