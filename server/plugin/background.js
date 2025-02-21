const DEBUG = true; // 设为false关闭调试输出

let ws = null,
  reconnectTimer = null;
let currentTabId = null;
let requestId = null;
let isTabCreatedByUs = false; // 新增标志位，标记是否是我们创建的标签页
let selectors = null; // 新增选择器变量

async function connectWebSocket(serverUrl) {
  if (ws && ws.readyState === WebSocket.OPEN) return;
  if (DEBUG) console.debug("🔄 正在连接WS服务器...");
  ws = new WebSocket(serverUrl);

  ws.onopen = () => {
    if (DEBUG) console.debug("✅ 成功连接WS服务器");
    clearTimeout(reconnectTimer);
  };

  ws.onmessage = async (event) => {
    if (DEBUG) console.debug("📨 收到服务器消息:", event.data);
    const data = JSON.parse(event.data);
    if (data.type === "extract") {
      const existingTab = await findExistingTab(data.url);
      if (existingTab) {
        currentTabId = existingTab.id;
        isTabCreatedByUs = false;
        if (DEBUG) console.debug(`🔍 找到已存在的标签页，ID: ${currentTabId}`);
        selectors = data.selectors; // 保存选择器
        await injectScript(currentTabId);
      } else {
        currentTabId = await createTab(data.url);
        isTabCreatedByUs = true;
        selectors = data.selectors; // 保存选择器
      }
      requestId = data.requestId;
    }
  };

  ws.onclose = () => {
    if (DEBUG) console.debug("❌ 连接断开，1秒后重连...");
    reconnectTimer = setTimeout(() => initWebSocket(), 1000);
  };
}

async function findExistingTab(url) {
  const tabs = await chrome.tabs.query({});
  return tabs.find((tab) => tab.url === url);
}

async function injectScript(tabId) {
  if (DEBUG) console.debug(`✅ 注入提取脚本到标签页 ${tabId}`);
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ["extract.js"],
    });
    // 注入后立即发送选择器数据
    await chrome.tabs.sendMessage(tabId, {
      action: "setSelectors",
      selectors: selectors,
    });
  } catch (error) {
    console.error("脚本注入失败:", error);
  }
}

function initWebSocket() {
  chrome.storage.local.get(["serverUrl"], (result) => {
    const serverUrl = result.serverUrl || "ws://localhost:8000/ws";
    connectWebSocket(serverUrl);
  });
}

async function createTab(url) {
  if (DEBUG) console.debug(`🆕 正在创建标签页: ${url}`);
  const tab = await chrome.tabs.create({ url, active: false });
  if (DEBUG) console.debug(`✅ 标签页创建成功，ID: ${tab.id}`);
  chrome.tabs.onUpdated.addListener(async function listener(tabId, changeInfo) {
    if (tabId === tab.id && changeInfo.status === "complete") {
      await injectScript(tabId);
      chrome.tabs.onUpdated.removeListener(listener);
    }
  });
  return tab.id;
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === "htmlContent" && sender.tab.id === currentTabId) {
    if (DEBUG)
      console.debug(`📤 发送HTML内容，长度: ${message.content.length} 字符`);
    ws.send(
      JSON.stringify({
        type: "htmlResponse",
        content: message.content,
        requestId: requestId,
      }),
    );
    requestId = null;
    if (isTabCreatedByUs) {
      chrome.tabs.remove(sender.tab.id);
    }
    currentTabId = null;
    isTabCreatedByUs = false;
    selectors = null; // 清除选择器
    sendResponse({ status: "success" }); // 添加响应
  } else if (message.type == "selectorConfig") {
    // 处理selector配置消息
    if (DEBUG) console.debug(`📤 发送selector配置: ${message.selector}`);
    ws.send(
      JSON.stringify({
        type: "selectorConfig",
        url: message.url,
        selector: message.selector,
      }),
    );
    sendResponse({ status: "success" }); // 确保调用sendResponse
  }
  return true; // 保持消息通道开放
});

// 初始化连接
initWebSocket();
const keepAlive = () => {
  chrome.alarms.create("keep-alive", { delayInMinutes: 20 / 60 });
  chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === "keep-alive") {
      if (DEBUG)
        console.debug("💓 发送保持活跃心跳", new Date().toLocaleTimeString());
      chrome.storage.local.set({ keepAlive: Date.now() }, () => {
        chrome.alarms.create("keep-alive", { delayInMinutes: 20 / 60 });
        if (DEBUG) console.debug("⏱ 已设置下一次心跳");
      });
    }
  });
};

chrome.runtime.onStartup.addListener(keepAlive);
chrome.runtime.onInstalled.addListener(keepAlive);
