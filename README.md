
# terminal LLM

[English users please view README.en.md](README.en.md)

一个基于openai兼容接口的终端辅助工具，提供便捷的命令行交互和上下文感知功能, 目标是命令行版本的cursor, windsurf, 推荐使用deepseek R1。

## 使用场景

一个askgpt后边可以用多个@，混合构成上下文, 可以一边使用网址，同时加入文件内容，不必带""号, 但需要注意shell里的特别字符比如>

```bash

# 修改代码的bug,会生成一个diff, 看你要不要使用patch
askgpt @edit @main.py 找到其中可能的bug，并加以修复

# 分析剪贴板内容
askgpt 解释这段代码：@clipboard @tree

#命令建议
askgpt @cmd 找到2小时前的所有文件, 并全部删除

# 附加当前目录结构
askgpt "@tree，请分析主要模块"

# 附加当前目录结构, 包括子目录
askgpt "@treefull，请分析主要模块"

# 嵌入文件内容
askgpt "请优化这个配置文件：@config/settings.yaml"

# 访问网页
askgpt @https://tree-sitter.github.io/tree-sitter/using-parsers/1-getting-started.html 归纳这个文档

# 阅读新闻, 会用readability工具提取正文, 需要配置了浏览器转发，下边有教程   
askgpt @readhttps://www.guancha.cn/internation/2025_02_08_764448.shtml 总结新闻

# 嵌入常用提示词, 文件放到在prompts/目录
askgpt @advice #这个提示词是让gpt提供修改建议

#灵活引入提示词块，提供文件，完成修改目录, 同时将剪贴版里边的片段引入, @的东西后边最后需要加空格，以区分其它东西   
askgpt @advice @llm_query.py @clipboard  修复其中可能的bug   

#使用自定义上下文，prompts/目录下写的，支持自动补全
#实现功能，从网页里复制了一段别人的长文，用r1 `整理这个人的观点，点评一下`
askgpt @clipboard @comment

#最近的会话
recentconversation
#最近的对话记录：
# 1) 2025-02-09 18:35:27 EB6E6ED0-CAFE-488F-B247-11C1CE549B12 我前面说了什么
# 2) 2025-02-09 18:34:37 C63CA6F6-CB89-42D2-B108-A551F8E55F75 hello
# 3) 2025-02-09 18:23:13 27CDA712-9CD9-4C6A-98BD-FACA02844C25 hello
#请选择对话 (1-       4，直接回车取消): 2
#已切换到对话: C63CA6F6-CB89-42D2-B108-A551F8E55F75

#新会话，打开新的terminal就默认是新会话，或者手工重置
newconversation

#git add后，可以对stage的修改生成commmit message, powershell暂时不支持
commitgpt

#不在上下文中提问, 临时发起一个, 不干扰原来的会话
naskgpt hello

#剪贴版监听功能，把随后多次复制就加入上下文, 可以从文档的不同位置复制片断，写材料特别有用
askgpt @listen 用户这些评论反映了什么样的趋势

#把前面发的prompt再引用一次，网络故障或者改提问需要这个
askgpt @last

#符号上下文查询,　会列出这个符号调用的多级其它符号，　跨文件，构成一个完整的上下文，供gpt理解   
#这需要用本项目tree.py建一个index server，暂时支持c语言，其它语言开发中, 进展下边有说   
#可以说以后不再需要源代码解析类的文章了    
askgpt @symbol:show_tty_driver

#聊天机器人, 满足闲聊的需要 
#新会话
chatbot

#接着聊, 注意这个受newconversation的影响
chatagain

#prompt模板, 假设main.c.skel是main.c的框架文件(提炼的接口), 剪贴板里有我们想修改的代码, {}执行了字符串模板的功能
naskgpt  "{ @edit-with-skel @main.c.skel @clipboard }" 找出给定代码的bug

#多行输入, 正常情况下可以用\换行
naskgpt \
> hello \
> world

#文件行号选择, 文件太大的折中办法, 前100
naskgpt @large-file:-100

#100以后
naskgpt @large-file:100-

#20-50
naskgpt @large-file:20-50

#把prompt当shell脚本执行, 获取它的结果, 填入上下文, =号结尾，跟自定义prompt一样
naskgpt @script=
```



## 功能特性

- **代码文件分析**：替代view, vim, 用大模型分析本地源代码文件, 提供代码修改建议
- **对话保存，对话切换**： 跟进提问，还可以恢复过去的会话，继续提问
- **上下文集成**：
  - 剪贴板内容自动读取 (`@clipboard`)
  - 目录结构查看 (`@tree`/`@treefull`)
  - 文件内容嵌入 (`@文件路径`)
  - 网页内容嵌入 (`@http://example.com`)
  - 常用prompt引用 (`@advice`...)
  - 命令行建议 (`@cmd`)
  - 代码编辑 (`@edit`)
- **网页内容转换**：内置Web服务提供HTML转Markdown
  - 浏览器扩展集成支持, 绕过cloudflare干扰
  - 自动内容提取与格式转换
- **Obsidian支持**： markdown保存历史查询到指定目录
- **代理支持**：完善的HTTP代理配置检测
- **多个模型切换**： 用配置文件在本机ollama 14b,32b小模型, 远程r1全量模型之间切换
- **流式响应**：实时显示API响应内容, 推理思考内容的输出

## 安装与配置

1. **克隆仓库**
```bash
git clone https://github.com/maliubiao/terminal-llm
cd terminal-llm
```

2. **设置虚拟环境**
```bash
#windows上安装uv, powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
#mac or linux上安装uv, curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync #uv python list; uv python install 某个版本的python, 3.12及以上
source .venv/bin/activate
```

3. **环境变量配置**
```bash
# 在shell配置文件中添加 (~/.bashrc 或 ~/.zshrc), 如果配置了model.json则只需要最后一行，source /your/path/to/env.sh
export GPT_PATH="/path/to/terminal-llm"
export GPT_KEY="your-api-key"
export GPT_MODEL="your-model"
export GPT_BASE_URL="https://api.example.com/v1"  # OpenAI兼容API地址
source $GPT_PATH/env.sh #zsh, bash支持@后补全
```

4. **在windows powershell上使用**  
需要特别指出powershell的@有特殊含义，不能直接补全，需要用\\@才能补全，比直接@增加一个字符  
```powershell
#PS C:\Users\user> $PROFILE  这个变量会返回当前的配置文件，在配置文件后把env.ps1加入进去
[Console]::InputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
. \your\path\to\env.ps1
```

### R1 api提供商
[字节火山方舟](https://www.volcengine.com/experience/ark?utm_term=202502dsinvite&ac=DSASUQY5&rc=FNTDEYLA) 目前api响应最快，资费最低，半价，注册就送3000万token    
[硅基流动](https://cloud.siliconflow.cn/i/BofVjNGq) 提供高性能API服务，但是厂小资源有限，容易堵，注册送2000万token，运行在华为昇腾全国产化平台上，安全可靠。  
附教程，[硅基云API使用教程](https://docs.siliconflow.cn/usercases/use-siliconcloud-in-chatbox)  


## 使用指南

### 基本命令

**会话管理**

```bash
#列出历史对话
➜  terminal-llm git:(main) ✗ allconversation #allconversation 2只显示最近两个, recentconversation是allconversation 10
所有对话记录：
 1) 2025-02-09 19:07:34 E8737837-AD37-46B0-ACEA-8A7F93BE25E8 文件 /Users/richard/code/termi...
 2) 2025-02-09 18:34:37 C63CA6F6-CB89-42D2-B108-A551F8E55F75 hello
 3) 2025-02-09 18:48:47 5EC8AF87-8E00-4BCB-9588-1F131D6BC9FE recentconversation() {     # 使...
 4) 2025-02-09 18:35:27 EB6E6ED0-CAFE-488F-B247-11C1CE549B12 我前面说了什么
 5) 2025-02-09 18:23:13 27CDA712-9CD9-4C6A-98BD-FACA02844C25 hello
请选择对话 (1-       5，直接回车取消):
#选之后可以恢复到对话，或者什么也不选,Enter退出
➜  terminal-llm git:(main) ✗ newconversation #开始一个空对话
新会话编号:  D84E64CF-F337-4B8B-AD2D-C58FD2AE713C
```

**分析源代码文件**
```bash
explaingpt path/to/file.py
# 使用自定义提示模板
explaingpt file.py prompts/custom-prompt.txt
```

**直接提问**

```bash
askgpt "如何实现快速排序算法？"
```

**模型切换**

```bash
#同目录下创建model.json, 用listgpt检查，配置了model.json后，不需要再加GPT_*环境变量，会使用"default" 供应商，或者第一个
➜  terminal-llm git:(main) ✗ listgpt 
14b: deepseek-r1:14b
➜  terminal-llm :(main) ✗ usegpt 14b
成功设置GPT环境变量：
  GPT_KEY: olla****
  GPT_BASE_URL: http://192.168.40.116:11434/v1
  GPT_MODEL: deepseek-r1:14b
```
```json
{
    "14b": {
        "key": "ollama",
        "base_url": "http://192.168.40.116:11434/v1",
        "model_name": "r1-qwen-14b:latest",
        "max_tokens": 131072, //不同模型的max_tokens差别很大，有的只能到8192, 甚至更小只有4k, 写大了会报错
        "temperature": 0.6 //温度会严重影响回答的倾向，编程问题可设为0.0, 文学类需要设置成0.6, 官方建议是这样
    }

}
```

**文档管理**  

推荐使用obsidian这种专业的工具，方便管理大量的markdown文档，本程序会自动生成每天的索引    
每次的prompt及响应，都默认保存在obsidian/目录，方便用obsidian打开这个目录，随时查阅   
历史会话默认保存在conversation/目录，按天存储，并不删除，因为不占什么地方    

### 高级功能

**网页内容转换服务**
```bash
# 启动转换服务器（默认端口8000), 用https://github.com/microsoft/markitdown实现
# 支持--addr, --port, 需要在插件option里也改
python server/server.py
# 调用转换接口（需配合浏览器扩展使用），server/plugin加载到浏览器
curl "http://localhost:8000/convert?url=当前页面URL"

# Firefox Readability新闻提取, 前面的server在收到is_news=True参数时，会查询这个, 端口3000, package.json中可改    
cd node; npm install; npm start
```

**网页转换服务的元素过滤器**   
网页上可能有非常多杂七杂八的东西，比如外链，浪费上下文，而且许多api限制8k上下文, 放不进去   
这时就需要自己定义css 或者 xpath selectors来告诉转换服务，哪里是需要关注的    
xpath selector功能更为强大，在处理混淆后的网页结构时有很好的效果   
网页转换服务自带一个元素过滤器, 在server/config.yaml配置    
另外在打开自带的元素选择器后，选好后，可以直接保存，插件会刷新到server/config.yaml    
```yaml
#支持glob, . * 这样的匹配网址方式
filters:
    - pattern: https://www.guancha.cn/*/*.shtml
      cache_seconds: 600 #对结果缓存10分钟，可许会再次查询，提出不同角度的问题  
      selectors:
        - "div.content > div > ul" #只关注网页正文,

    - pattern: https://x.com/*/status/*
      selectors:
        - "//article/ancestor::div[4]" #xpath, 必须以//开头，这个表示article的第四层父元素div
```

**插件的配置**  
点击插件的图标，有弹出选项，可在当前页面加载一个元素选择器，它可以帮助你定位想要的内容的css selector, 复制到config.yaml去    
如果你会用dev tools的inspector，可以使用它的copy selector    


### 符号查询

tree.py是一个tree-sitter实现的抽象语法树解析库，会生成一个sqlite做源代码索引，这个示例中我就索引了内核gcc　-E预处理过的源代码  
在环境中指定api server的位置，`GPT_SYMBOL_API_URL` 大概长这样`http://127.0.0.1:9050/symbols`  

```bash
#一个典型的输出
(terminal-llm) ➜  terminal-llm git:(main) ✗ python tree.py --project /Volumes/外置2T/android-kernel-preprocess/aosp/ --port 9050

数据库当前状态：
  总符号数: 246373
  总文件数: 2711
  索引数量: 3
    索引名: idx_symbols_file, 唯一性: 否
    索引名: idx_symbols_name, 唯一性: 否
    索引名: sqlite_autoindex_symbols_1, 唯一性: 是
符号缓存加载完成                                  
处理项目 /Volumes/外置2T/android-kernel-preprocess/aosp/:  26%|███████████████████████████████████▋                                                                                                   | 723/2731 [00:04<00:12, 161.06文件/s]
文件 /Volumes/外置2T/android-kernel-preprocess/aosp/fs/proc/proc_tty.c.pre.c 处理完成：
  总符号数: 4687
  已存在符号数: 1
  重复符号数: 2974
  新增符号数: 1
  过滤符号数: 2974
处理项目 /Volumes/外置2T/android-kernel-preprocess/aosp/: 100%|██████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████| 2731/2731 [00:17<00:00, 152.64文件/s]
符号索引构建完成
INFO:     Started server process [74500]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:9050 (Press CTRL+C to quit)
INFO:     127.0.0.1:57943 - "GET /symbols/show_tty_driver/context?max_depth=5 HTTP/1.1" 200 OK
INFO:     127.0.0.1:57957 - "GET /symbols/show_tty_driver/context?max_depth=5 HTTP/1.1" 200 OK
```

### 提示词模板

在`prompts/`目录中创建自定义模板, 请复制参考现有的文件：
```txt
请分析以下Python代码：

主要任务：
1. 解释核心功能
2. 找出潜在bug
3. 提出优化建议

文件名: {path}
{pager}
\```
{code}
\```
```

## 环境变量

| 变量名         | 说明                           |
| -------------- | ------------------------------ |
| `GPT_PATH`     | 项目根目录路径                 |
| `GPT_KEY`      | OpenAI API密钥                 |
| `GPT_BASE_URL` | API基础地址 (默认Groq官方端点) |
| `GPT_KEY`      | API KEY                        |

## 目录结构

```
groq/
├── bin/              # 工具脚本
├── server/           # 网页转换服务
│   └── server.py     # 转换服务器主程序
├── prompts/          # 提示词模板
├── logs/             # 运行日志
├── llm_query.py      # 核心处理逻辑
├── env.sh            # 环境配置脚本
└── pyproject.toml    # 项目依赖配置
```


## 注意事项

1. **依赖工具**：
   - 安装[glow](https://github.com/charmbracelet/glow)用于Markdown渲染
   - 安装`tree`命令查看目录结构

2. **代理配置**：
   自动检测`http_proxy`/`https_proxy`环境变量

3. **文件分块**：
   大文件自动分块处理（默认32k字符/块）

4. **网页转换服务依赖**：
   - 需要安装Chrome浏览器扩展配合使用
   - 确保8000端口未被占用, 或者在插件配置option页改地址
   - 转换服务仅接受本地连接


## terminal-llm群
<img src="doc/qrcode_1739088418032.jpg" width = "200" alt="QQ群" align=center />

## 许可证

MIT License © 2024 maliubiao


