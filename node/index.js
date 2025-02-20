const express = require("express");
const { JSDOM } = require("jsdom");
const { Readability } = require("@mozilla/readability");
const yargs = require("yargs/yargs");
const { hideBin } = require("yargs/helpers");

// 解析命令行参数
const argv = yargs(hideBin(process.argv)).option("addr", {
  type: "string",
  default: "0.0.0.0:3000",
  description: "Server address to bind",
}).argv;

// 拆分地址和端口
const [host, port] = argv.addr.split(":");

const app = express();
app.use(express.json({ limit: "200mb" }));

// 处理 POST 请求
app.post("/html_reader", (req, res) => {
  try {
    const htmlContent = req.body.content;

    if (!htmlContent) {
      return res.status(400).json({ error: "Missing HTML content" });
    }

    // 创建虚拟 DOM 环境
    const dom = new JSDOM(htmlContent, {
      url: req.body.url || "http://example.com",
    });

    // 使用 Readability 解析内容
    const reader = new Readability(dom.window.document);
    const article = reader.parse();

    res.json({
      title: article.title,
      content: article.content,
      textContent: article.textContent,
      excerpt: article.excerpt,
    });
  } catch (error) {
    console.error("Processing error:", error);
    res.status(500).json({ error: "Failed to process HTML" });
  }
});

// 启动服务器
app.listen(parseInt(port), host, () => {
  console.log(`Server running at http://${host}:${port}`);
});
