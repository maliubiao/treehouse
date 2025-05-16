```
python gpt_workflow/code_trace --prompt-debug /Users/richard/code/terminal-llm/prompt_cache/20250515-113840_28dfa42a.json
```


## 转换工作流示例


### 1. 创建配置文件 (config.yaml):
```yaml
source_files:
  - "gpt_workflow/code_trace/test.cpp"
  - "gpt_workflow/code_trace/test1.cpp"


verify_cmd: "g++ gpt_workflow/code_trace/test.cpp gpt_workflow/code_trace/test1.cpp -o test && ./test"
```


### 2. 运行转换:
```bash
python gpt_workflow/code_trace --config config.yaml --parallel
```


### 3. 预期转换:
跟踪器将并行处理两个C++文件，可能转换如下函数：


test.cpp:
```cpp
// 原始代码
int add(int a, int b) {
    return a + b;
}


// 转换后示例
int add(int a, int b) {
    std::cout << "Adding " << a << " and " << b << std::endl;
    return a + b;
}
```


test1.cpp:
```cpp
// 原始代码
void print_thread_info(int thread_id) {
    std::cout << "Thread " << thread_id << " started" << std::endl;
    int result = factorial(thread_id);
    std::cout << "Thread " << thread_id << " result: " << result << std::endl;
}


// 转换后示例
void print_thread_info(int thread_id) {
    auto start = std::chrono::high_resolution_clock::now();
    std::cout << "Thread " << thread_id << " started" << std::endl;
    int result = factorial(thread_id);
    auto end = std::chrono::high_resolution_clock::now();
    std::cout << "Thread " << thread_id << " result: " << result 
              << " (耗时 " << std::chrono::duration_cast<std::chrono::milliseconds>(end-start).count() 
              << "毫秒)" << std::endl;
}
```


### 4. 验证变更:
验证命令将编译并运行两个程序以确保它们能协同工作。


### 5. 检查转换结果:
```bash
# 查看所有转换
python gpt_workflow/code_trace --inspect-transform


# 查看特定文件的转换
python gpt_workflow/code_trace --inspect-transform --inspect-file gpt_workflow/code_trace/test.cpp
python gpt_workflow/code_trace --inspect-transform --inspect-file gpt_workflow/code_trace/test1.cpp
```



## 配置示例

```yaml
# 示例 config.yaml
  source_files:
  - "**/*.cpp"
  - "**/*.h"

- "**/*.py"

  exclude_patterns:
  - "**/third_party/**"
  - "**/generated/**"
  - "**/test/**"
  - "**/*_test.cpp"

- "**/*_test.py"

verify_cmd: "make test"
  skip_crc32:
  - "12345678"
- "87654321"
```


### 配置选项


- `source_files`: 用于指定待处理文件的通配符模式列表
- `exclude_patterns`: 处理过程中需排除的通配符模式列表（匹配这些模式的文件将被跳过）
- `verify_cmd`: 处理完成后用于验证变更的待执行命令
- `skip_crc32`: 需跳过的CRC32校验值列表（适用于存在问题的符号）


### 直接应用转换


您无需查询GPT即可直接从日志文件应用转换：


```bash
python gpt_workflow/code_trace --apply-transform --skip-symbols symbol1,symbol2
```


选项说明：
- `--apply-transform`: 直接从文件专属转换文件应用转换
- `--skip-symbols`: 需跳过的符号列表（以逗号分隔）
- `--transform-file`: 自定义转换文件路径（默认：trace_debug/file_transformations/<filename>_transformations.json）

### 检查代码转换


运行跟踪器后，可通过以下命令检查代码转换：


```bash
# 查看所有已处理文件的转换记录
python gpt_workflow/code_trace --inspect-transform


# 查看指定文件的转换记录
python gpt_workflow/code_trace --inspect-transform --inspect-file path/to/file.py


# 从特定转换文件查看转换记录
python gpt_workflow/code_trace --inspect-transform --transform-file path/to/transform_file.json
```



输出内容将进行色彩标记和格式化，便于阅读代码变更。


#### 变换存储

变换现按文件存储于：
```
  trace_debug/
    file_transformations/
    <文件名>_transformations.json
...

```

每个变换文件包含：
- 每个符号的原始代码与转换后代码
- 文件路径及符号名称

- 变更状态（已修改/未更改）


#### 变换报告示例

该报告提供：
1. 摘要统计：显示处理的符号总数及变换率
   2. 每个符号的详细视图：
   - 符号路径及状态（已修改/未更改）
   - 原始代码（白色高亮显示）
- 转换后代码（若变更则绿色高亮显示）

3. 符号间用视觉分隔线提升可读性


#### 过滤变换


可按文件路径过滤变换：

```bash
python gpt_workflow/code_trace --inspect-transform --inspect-file src/utils.py

```


此命令仅显示路径包含"src/utils.py"的文件的变换。


#### 理解输出

- **已修改**符号显示原始与转换后代码
- **未更改**符号仅显示原始代码
- 变换率可识别代码库实际修改比例

- 色彩编码使变更一目了然



该系统支持多文件的并行处理，并提供线程安全的转换存储：  


1. 每个文件在独立线程中处理  
2. 转换结果存储于`trace_debug/file_transformations/`目录下的独立JSON文件  
3. 验证命令可一次性测试所有转换后的文件  
4. 支持按文件或全局范围检查转换结果  


并行处理命令示例：  
```bash  
python gpt_workflow/code_trace --config config.yaml --parallel  
```  


核心特性：  
- 线程安全的文件操作  
- 单文件转换追踪  
- 跨文件符号引用支持  
- 统一验证  
