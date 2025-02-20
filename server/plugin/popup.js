document.getElementById("injectBtn").addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  try {
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ["selector.js"],
    });
    alert("选择器注入成功！");
  } catch (error) {
    console.error("注入失败:", error);
    alert("选择器注入失败，请重试");
  }
});

document.getElementById("configBtn").addEventListener("click", () => {
  chrome.runtime.openOptionsPage();
});
