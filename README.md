
# Treehouse

[English users please view README.en.md](README.en.md)

一个基于openai兼容接口的代码辅助工具，提供便捷的命令行交互和上下文感知功能, 目标是命令行版本的cursor, windsurf, 推荐使用deepseek R1跟V3。

## 使用场景

一个askgpt后边可以用多个@，混合构成上下文, 可以一边使用网址，同时加入文件内容，不必带""号, 但需要注意shell里的特别字符比如>

```bash


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

#目录引用
askgpt @src 解释这个react项目的结构
#目录引用支持通配符
askgpt "@src/*tsx" 解释这些组件的用途
#文件引用支持通配符
askgpt "@*json" 当前目录下的json作用是什么

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

#聊天机器人, 满足闲聊的需要 
#新会话
chatbot

#接着聊, 注意这个受newconversation的影响
chatagain

#多行输入, 正常情况下可以用\换行
naskgpt \
> hello \
> world

#文件行号选择, 文件太大的折中办法, 前100, or 100-, 20-50
naskgpt @large-file:-100

#把prompt文件当脚本执行,  如果你给它设置了可执行权限, 或者以#!开头, 它的stdout会进入上下文，这是个prompt扩展功能
naskgpt @script.sh

#以下功能涉及符号，也是核心功能，需要symbolgpt启动一个符号服务器, env.sh有定义
#启动符号服务,即tree.py, 在终端多项目切换时，如果那个目录里已经起了tree.py, 则可以直接source .tree/rc.sh, 使用它的服务 
symbolgpt
symbolgptrestart

#@patch表示响应中有要patch的符号
askgpt @patch @symbol_tree.py/ParserUtil traverse在遇到function_definition这样的节点时,要额外考虑,它是父节点是否decorated_definition, 如果是,则需要用父节点　的全文,　以包括装饰器

#符号补全, 支持bash,zsh,powershell在输入到@symbol_后补前当前文件，当前文件里的符号，得tree.py支持了语言才行
askgpt @symbol_file/symbol 

#从行号指定符号, 函数可能是匿名的, 直接写它的行号
askgpt @symbol_llm_query.py/at_4204

#从行号指定符号，但是查找包括这行的父节点, 这样不需要知道它父节点的命名
askgpt @symbol_llm_query.py/near_4215

# 修改代码的bug,会生成一个diff, 看你要不要使用patch, @edit表示响应中有要patch的内容, @edit-file是在规定输出些什么
askgpt @edit @edit-file @main.py 找到其中可能的bug，并加以修复

#跟前面一样的功能
codegpt @main.py 找到其中可能的bug，并加以修复

# 改写某个符号, patchgpt是naskgpt @patch的缩写，参考env.sh定义的命令集
patchgpt @symbol_file/symbol 修复里边的bug

# 改写符号并提供LSP上下文
patchgpt @context @symbol_file/symbol 修复里边的bug

# 重新执行上一条命令, 诊断为什么会失败
fixgpt 

# 使用ripgrep 项目搜索，并自动定位搜索到的符号, 里边也可以用@symbol_file/symbol这样添加具体符号
# 可用.rgignore控制搜索范围 https://github.com/BurntSushi/ripgrep/blob/master/GUIDE.md
patchgpt ..LintFix.. ..main.. 增加单元测试套件

# 类，函数，定位补全, 在某个文件里写个占位符class MyClass: pass
patchgpt ..MyClass.. 根据说明，写完这个这测试套件

```

## 功能特性

- **代码生成**：实现cursor, windsurf的代码生成功能,基于AST,LSP获取精准的上下文
- **对话保存，对话切换**： 跟进提问，还可以恢复过去的会话，继续提问
- **强大符号引用功能**: 用class, function这些符号为单位让大模型修改，然后跟本地代码diff, patch, 大幅度节约响应时间及token消耗
- **丰富的上下文集成**：
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
- **多个模型切换**： 用配置文件在本机ollama 14b,32b小模型, 远程r1全量模型之间切换
- **高级调试功能**: 支持对python的代码的行级追踪，将局部变量的变化，输出到tracing日志


## 代码生成
可对文件或者具体代码符号补丁，需要启动tree.py以支持符号精准查找, 可以使用language server自动获取某个函数的上下文, 提问之后， 之后根据大模型的的代码输出, 根据diff的结果自主决定是否patch, 参考后边的配置说明     


## 安装与配置

1. **克隆仓库**
```bash
git clone https://github.com/maliubiao/treehouse
cd treehouse
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
# 在shell配置文件中添加 (~/.bashrc 或 ~/.zshrc), 如果配置了model.json则只需要设置GPT_PATH为项目目录，source /your/path/to/env.sh
export GPT_PATH="/path/to/treehouse"
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
#需要将env.ps1转成UTF8-BOM格式，不然windows可能乱码, Vs Code的save with encoding可以做到, 也可用tools/utf8_bom.py
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
➜  treehouse git:(main) ✗ allconversation #allconversation 2只显示最近两个, recentconversation是allconversation 10
所有对话记录：
 1) 2025-02-09 19:07:34 E8737837-AD37-46B0-ACEA-8A7F93BE25E8 文件 /Users/richard/code/termi...
 2) 2025-02-09 18:34:37 C63CA6F6-CB89-42D2-B108-A551F8E55F75 hello
 3) 2025-02-09 18:48:47 5EC8AF87-8E00-4BCB-9588-1F131D6BC9FE recentconversation() {     # 使...
 4) 2025-02-09 18:35:27 EB6E6ED0-CAFE-488F-B247-11C1CE549B12 我前面说了什么
 5) 2025-02-09 18:23:13 27CDA712-9CD9-4C6A-98BD-FACA02844C25 hello
请选择对话 (1-       5，直接回车取消):
#选之后可以恢复到对话，或者什么也不选,Enter退出
➜  treehouse git:(main) ✗ newconversation #开始一个空对话
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

## 编码项目配置
```yaml
# 示例LLM 项目搜索配置文件， 文件名为.llm_project.yml
# 排除配置（支持glob模式）
#
#项目主目录，这个目录下必须有.llm_project.yml, 用来定位符号, @symbol_src/file.py/main 是这个目录下src/file.py的main函数
project_root_dir: /path/to/your/project
lsp: #lsp配置
  commands: #这个项目配置的lsp启动命令
    py: pylsp
    clangd: clangd
  subproject: #子目录的lsp
    debugger/cpp/: clangd 
  default: py #默认无匹配时的lsp
  suffix:
    cpp: clangd #根据后缀匹配查询哪个lsp
#..main.. ripgrep搜索范围控制，在哪些文件中搜索main字符串
exclude:
  dirs:
    - .git          # 版本控制目录
    - .venv         # Python虚拟环境
    - node_modules  # Node.js依赖目录
    - build         # 构建目录
    - dist          # 分发目录
    - __pycache__   # Python缓存目录
    - conversation
    - obsidian
    - web
  files:
    - "*.min.js"    # 压缩后的JS文件
    - "*.bundle.css" # 打包的CSS文件
    - "*.log"       # 日志文件
    - "*.tmp"       # 临时文件

# 包含配置（留空则使用默认文件类型）
include:
  dirs: []  # 指定要包含的目录（覆盖排除规则）
  files:
    - "*.py"  # Python源文件
    - "*.cpp" # CPP
    - "*.js"  # JavaScript文件
    - "*.md"  # Markdown文档
    - "*.txt" # 文本文件

# 搜索的文件类型（扩展名或预定义类型）
file_types:
  - .py    # Python
  - .js    # JavaScript
  - .md    # Markdown
  - .txt   # 文本文件
  - .cpp   #cpp

```

**模型切换**

```bash
#同目录下创建model.json, 用listgpt检查，配置了model.json后，不需要再加GPT_*环境变量，会使用"default" 供应商，或者第一个
➜  treehouse git:(main) ✗ listgpt 
14b: deepseek-r1:14b
➜  treehouse :(main) ✗ usegpt 14b
成功设置GPT环境变量：
  GPT_KEY: olla****
  GPT_BASE_URL: http://192.168.40.116:11434/v1
  GPT_MODEL: deepseek-r1:14b
```
```
//不同模型的max_context_size差别很大，有的只能到8192, 甚至更小只有4k, 写大了会报错
//max_context_size是上下文大小，max_tokens 是输出大小，不同api供应商有不同的参数
//温度会严重影响回答的倾向，编程问题可设为0.0, 文学类需要设置成0.6, 官方建议是这样
//is_thinking标记这是否思考型模型， 思考型的模型不需要复杂的提示词, 他自己会推导, 比如r1是，v3不是
```
```json
{
    "14b": {
        "key": "ollama",
        "base_url": "http://192.168.40.116:11434/v1",
        "model_name": "r1-qwen-14b:latest",
        "max_context_size": 131072,
        "temperature": 0.6,
        "max_tokens": 8096,
        "is_thinking": false,
        "temperature": 0.0
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

tree.py是一个tree-sitter实现的抽象语法树解析库，提供多语言ast及lsp符号查找支持

```bash
#一个典型的输出
(treehouse) ➜  treehouse git:(main) ✗ python tree.py --project /Volumes/外置2T/android-kernel-preprocess/aosp/ --port 9050

INFO:     Started server process [74500]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:9050 (Press CTRL+C to quit)
INFO:     127.0.0.1:57943 - "GET /symbols/show_tty_driver/context?max_depth=5 HTTP/1.1" 200 OK
INFO:     127.0.0.1:57957 - "GET /symbols/show_tty_driver/context?max_depth=5 HTTP/1.1" 200 OK
```

### 启动针对新项目的tree服务
在项目的主目录，执行, `.llm_project` 没有配置会生成一个默认的，配置里指示了如何使用language server, 以及ripgrep的搜索配置
```bash
symbolgpt
symbolgptrestart
```
或者手工启动一个
```bash
#新建一个.llm_project.yml，配置lsp
$GPT_PYTHON_BIN $GPT_PATH/tree.py --port 9060;
#GPT_PYTHON_BIN GPT_PATH是env.sh设置的环境变量，指向treehouse的目录
export GPT_SYMBOL_API_URL=http://127.0.0.1:9060/;
#在askgpt中使用@symbol_file.xx/main 这样获取符号上下文，bash, zsh shell支持补号补全, 比较方便
```


### 高级调试器
支持对python程序进行bytecode级别的line trace, 输出执行了哪一行，变量的改变，而且性能足够好，不至于卡住
#### 编译
```bash
#python 3.11.11  uv python pin {version}, 最好3.11.11，因为cpp会访问python虚拟机内部数据，版本不对会崩
cd treehouse; source .venv/bin/activate
cd debugger/cpp
#编译不成功，到下边qq群交流, 如果文档内容不能复现，请到群里反馈
cmake ../ -DCMAKE_BUILD_TYPE=Debug -DENABLE_ASAN=ON #or
cmake ../ -DCMAKE_BUILD_TYPE=Release
#在treehouse/debugger/tracer_core.so
```
#### 使用
```bash
#改path后再用, --watch-files=是glob匹配，通配符, --open-report是结束打开网页, 不建议trace执行几十万行的那种，浏览器负担太大
python -m debugger.tracer_main --watch-files="*path.py"  --watch-files="*query.py" --open-report test_llm_query.py -v TestDiffBlockFilter
```

<img src="doc/debugger-preview.png" width = "600" alt="line tracer" align=center />

### 自定义提示词库

在`prompts/`目录中创建自定义模板, 可以在这个目录放脚本或者可执行文件动态生成prompt， 请复制参考现有的文件：
```py
#! /usr/bin/env python
#在prompts下边写shell脚本，脚本会被执行，输出会当成提示器的一部分, 加上可执行权限
print("你是一个友好的助手")
```

## 环境变量

| 变量名         | 说明                           |
| -------------- | ------------------------------ |
| `GPT_PATH`     | 项目根目录路径                 |
| `GPT_KEY`      | OpenAI API密钥                 |
| `GPT_BASE_URL` | API基础地址 (默认Groq官方端点) |
| `GPT_KEY`      | API KEY                        |

```bash
env |grep GPT_
```

## 注意事项

1. **可选工具**：
   - 安装`tree`命令查看目录结构
   - 安装`diff` `patch`工具用来操作源代码, windows上可能默认没有

2. **代理配置**：
   自动检测`http_proxy`/`https_proxy`环境变量

3. **网页转换服务依赖**：
   - 需要安装Chrome浏览器扩展配合使用
   - 确保8000端口未被占用, 或者在插件配置option页改地址
   - 转换服务仅接受本地连接


## treehouse群
<img src="doc/qrcode_1739088418032.jpg" width = "200" alt="QQ群" align=center />

## 许可证

MIT License © 2024 maliubiao


