function initOptions() {
  // 加载保存的地址
  chrome.storage.local.get(["serverUrl"], function (result) {
    document.getElementById("serverUrl").value =
      result.serverUrl || "ws://localhost:8000/ws";
  });

  document.getElementById("testBtn").addEventListener("click", testConnection);
  document.getElementById("saveBtn").addEventListener("click", saveSettings);
}

document.addEventListener("DOMContentLoaded", initOptions);

function testConnection() {
  const url = document.getElementById("serverUrl").value;
  const status = document.getElementById("status");

  if (!url.startsWith("ws://") && !url.startsWith("wss://")) {
    showStatus("地址必须以 ws:// 或 wss:// 开头", "error");
    return;
  }

  showStatus("正在测试连接...");

  const testWs = new WebSocket(url);
  let timeout = setTimeout(() => {
    testWs.close();
    showStatus("连接超时", "error");
  }, 3000);

  testWs.onopen = () => {
    clearTimeout(timeout);
    testWs.close();
    showStatus("连接成功！", "success");
  };

  testWs.onerror = () => {
    clearTimeout(timeout);
    showStatus("连接失败，请检查地址和服务器状态", "error");
  };
}

function saveSettings() {
  const url = document.getElementById("serverUrl").value;
  chrome.storage.local.set({ serverUrl: url }, () => {
    showStatus("设置已保存！", "success");
  });
}

function showStatus(message, type) {
  const status = document.getElementById("status");
  status.textContent = message;
  status.className = type ? ` ${type}` : "";
  status.style.display = "block";
}
