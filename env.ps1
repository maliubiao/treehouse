# env.ps1
# 获取Python可执行文件路径

# 设置 GPT_PATH
if (-not $env:GPT_PATH) {
    $scriptPath = $PSScriptRoot
    $env:GPT_PATH = $scriptPath
}

# 检测操作系统类型
if ($PSVersionTable.PSVersion.Major -lt 6) {
    # PowerShell 5.x 及以下版本
    $IsWindows = $env:OS -eq "Windows_NT"
}


function global:Get-PythonPath {
    # 检查虚拟环境中的Python路径
    $venvPythonPath = if ($IsWindows) {
        Join-Path $env:GPT_PATH ".venv" | Join-Path -ChildPath "Scripts" | Join-Path -ChildPath "python.exe"
    } else {
        Join-Path $env:GPT_PATH ".venv" | Join-Path -ChildPath "bin" | Join-Path -ChildPath "python"
    }

    # 如果虚拟环境中的Python存在，直接返回
    if (Test-Path $venvPythonPath) {
        return $venvPythonPath
    }

    # 检查系统默认的Python
    $systemPython = if ($IsWindows) { "python.exe" } else { "python3" }
    $systemPythonPath = Get-Command $systemPython -ErrorAction SilentlyContinue

    if ($systemPythonPath) {
        Write-Warning "未找到虚拟环境中的Python，将使用系统默认的Python。建议使用'uv venv'创建虚拟环境。"
        return $systemPythonPath.Source
    }

    # 如果都没有找到，抛出错误
    Write-Error "未找到可用的Python解释器。请先安装Python并使用'uv venv'创建虚拟环境。"
    return $null
}

# 导出其他环境变量
$env:GPT_DOC = Join-Path -Path $env:GPT_PATH -ChildPath "obsidian"
$env:PATH = [System.IO.Path]::Combine($env:GPT_PATH, "bin") + [System.IO.Path]::PathSeparator + $env:PATH
$env:GPT_PROMPTS_DIR = Join-Path -Path $env:GPT_PATH -ChildPath "prompts"
$env:GPT_LOGS_DIR = Join-Path -Path $env:GPT_PATH -ChildPath "logs"
$env:GPT_UUID_CONVERSATION = [guid]::NewGuid().ToString()
$env:GPT_MAX_TOKEN = 8192
# 初始化目录
$binPath = Join-Path -Path $env:GPT_PATH -ChildPath "bin"
$promptsPath = Join-Path -Path $env:GPT_PATH -ChildPath "prompts"
$logsPath = Join-Path -Path $env:GPT_PATH -ChildPath "logs"
New-Item -ItemType Directory -Force -Path $binPath | Out-Null
New-Item -ItemType Directory -Force -Path $promptsPath | Out-Null
New-Item -ItemType Directory -Force -Path $logsPath | Out-Null

# $env:DEBUG=1
# 函数定义
function global:newconversation {
    $env:GPT_UUID_CONVERSATION = [guid]::NewGuid().ToString()
    Write-Host "新会话编号: $env:GPT_UUID_CONVERSATION"
}

function global:allconversation {
    # 调用内部函数，传入0表示无限制输出
    _conversation_list 0
}

function global:_conversation_list {
    $limit = $args[0]
    if (-not $limit) { $limit = 0 }

    $conversation_dir = Join-Path -Path $env:GPT_PATH -ChildPath "conversation"
    $title = if ($limit -gt 0) { "最近的${limit}条对话记录" } else { "所有对话记录" }

    $pythonScript = @"
import os, sys, json, datetime
from datetime import datetime

conversation_dir = r"$conversation_dir"
files = []

for root, _, filenames in os.walk(conversation_dir):
    for fname in filenames:
        if fname in ["index.json", ".DS_Store"] or not fname.endswith(".json"):
            continue
        path = os.path.join(root, fname)
        try:
            date_str = os.path.basename(os.path.dirname(path))
            time_uuid = os.path.splitext(fname)[0]
            uuid = "-".join(time_uuid.split("-")[3:])
            time_str = ":".join(time_uuid.split("-")[0:3])
            mtime = os.path.getmtime(path)
            preview = "N/A"
            with open(path, "r") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    first_msg = data[0].get("content", "")
                    preview = first_msg[:32].replace("\n", " ").strip()
            files.append((mtime, date_str, time_str, uuid, preview, path))
        except Exception as e:
            continue

files.sort(reverse=True, key=lambda x: x[0])
if $limit > 0:
    files = files[:$limit]

for idx, (_, date, time, uuid, preview, _) in enumerate(files):
    print(f"{idx+1}\t{date} {time}\t{uuid}\t{preview}")
"@

    $pythonExecutable = Get-PythonPath
    $selection = & $pythonExecutable -c $pythonScript

    if (-not $selection) {
        Write-Host "没有找到历史对话"
        return
    }

    Write-Host "${title}："
    $selection | ForEach-Object {
        $parts = $_ -split "\t"
        $index = $parts[0]
        $datetime = $parts[1]
        $uuid = $parts[2]
        $preview = $parts[3]
        Write-Host ("{0,-3} {1,-19} {2,-36} {3}" -f "$index)", $datetime, $uuid, $preview)
    }

    $itemCount = ($selection | Measure-Object).Count
    if ($env:DEBUG -eq "1") {
        Write-Host "[DEBUG] 找到的对话数量: $itemCount"
        Write-Host "[DEBUG] 选择列表内容:"
        $selection | ForEach-Object { Write-Host "  $_" }
    }

    $choice = Read-Host "请选择对话 (1-${itemCount}，直接回车取消)"
    $choice = [int]$choice

    if ($choice -match '^\d+$' -and $choice -ge 1 -and $choice -le $itemCount) {
        $selected = $selection[$choice-1] -split "\t"
        if ($env:DEBUG -eq "1") {
            Write-Host "[DEBUG] 用户选择: $choice"
            Write-Host "[DEBUG] 解析后的选择项:"
            $selected | ForEach-Object { Write-Host "  $_" }
        }
        $env:GPT_UUID_CONVERSATION = $selected[2]
        Write-Host "已切换到对话: $($selected[2])"
    }
    else {
        if ($env:DEBUG -eq "1") {
            Write-Host "[DEBUG] 用户输入: $choice"
            Write-Host "[DEBUG] 输入无效或取消操作"
        }
        Write-Host "操作已取消"
    }
}

function global:recentconversation {
    _conversation_list 10
}

function global:listgpt {
    $config_file = if ($args[0]) { $args[0] } else { Join-Path -Path $env:GPT_PATH -ChildPath "model.json" }

    if (-not (Test-Path $config_file)) {
        Write-Error "错误：未找到配置文件: $config_file"
        return
    }

    $config = Get-Content -Path $config_file -Raw | ConvertFrom-Json
    $config.PSObject.Properties | ForEach-Object {
        if ($_.Value.key) {
            Write-Host "$($_.Name): $($_.Value.model_name)"
        }
    }
}

function global:usegpt {
    if (-not $args[0]) {
        Write-Error "错误：模型名称不能为空"
        return
    }

    $model_name = $args[0]
    $config_file = if ($args[1]) { $args[1] } else { Join-Path -Path $env:GPT_PATH -ChildPath "model.json" }

    if (-not (Test-Path $config_file)) {
        Write-Error "错误：未找到配置文件: $config_file"
        return
    }

    $config = Get-Content -Path $config_file -Raw | ConvertFrom-Json
    $model_config = $config.$model_name
    $key = $model_config.key
    $base_url = $model_config.base_url
    $model = $model_config.model_name
    $max_tokens = $model_config.max_tokens

    if (-not $key -or -not $base_url -or -not $model) {
        Write-Error "错误：未找到模型 '$model_name' 或配置不完整"
        return
    }

    $env:GPT_KEY = $key
    $env:GPT_BASE_URL = $base_url
    $env:GPT_MODEL = $model
    if ($max_tokens) {
        $env:GPT_MAX_TOKEN = $max_tokens
    }

    Write-Host "成功设置GPT环境变量："
    Write-Host "  GPT_KEY: $($key.Substring(0,4))****"
    Write-Host "  GPT_BASE_URL: $base_url"
    Write-Host "  GPT_MODEL: $model"
    if ($max_tokens) {
        Write-Host "  GPT_MAX_TOKEN: $max_tokens"
    }
}

# $env:DEBUG=1

Register-ArgumentCompleter -CommandName askgpt -ScriptBlock {
    param(
        $wordToComplete,
        $commandAst,
        $cursorPosition
    )

    # 调试信息输出
    if ($env:DEBUG) {
        Write-Host "`n[DEBUG] 自动补全调试信息:"
        Write-Host "  wordToComplete: $wordToComplete"
        Write-Host "  cursorPosition: $cursorPosition"
        Write-Host "  CommandAst: $($commandAst | Out-String)"
    }

    $currentToken = $commandAst.CommandElements |
        Where-Object { 
            $_.Extent.StartOffset -le $cursorPosition -and 
            $_.Extent.EndOffset -ge $cursorPosition 
        } |
        Select-Object -ExpandProperty Value -First 1

    if ($currentToken -like '\@*') {
        $prefix = '\@'
        $search = $currentToken.Substring(2)

        if ($env:DEBUG) {
            Write-Host "  currentToken: $currentToken"
            Write-Host "  search: $search"
        }

        # 特殊项（保持原样）
        $special = @('clipboard', 'tree', 'treefull', 'read')

        # 提示词文件（仅搜索prompts目录）
        $prompts = @()
        if (Test-Path $env:GPT_PROMPTS_DIR) {
            $prompts = Get-ChildItem -Path $env:GPT_PROMPTS_DIR -File -Filter "$search*" |
                ForEach-Object { $prefix + $_.Name }
        }

        if ($env:DEBUG) {
            Write-Host "  找到提示词文件: $($prompts -join ', ')"
        }

        # 文件系统补全（仅当前目录，不递归子目录）
        $files = @()
        try {
            $searchPath = Join-Path (Get-Location).Path $search
            if ($search -match "[/\\]") {
                $dir = Split-Path $searchPath -Parent
                $file = Split-Path $searchPath -Leaf
                $files = Get-ChildItem -Path $dir -File -Filter "$file*" -ErrorAction SilentlyContinue |
                    ForEach-Object { $prefix + (Join-Path (Split-Path $search) $_.Name) }
            } else {
                $files = Get-ChildItem -Path . -File -Filter "$search*" -ErrorAction SilentlyContinue |
                    ForEach-Object { $prefix + $_.Name }
            }
        } catch {}

        if ($env:DEBUG) {
            Write-Host "  找到文件系统匹配项: $($files -join ', ')"
        }

        # 合并建议项（优先显示特殊项和提示词）
        $suggestions = @()
        $suggestions += $special | Where-Object { $_ -like "$search*" } | ForEach-Object { $prefix + $_ }
        $suggestions += $prompts
        $suggestions += $files | Sort-Object -Unique

        if ($env:DEBUG) {
            Write-Host "  最终建议项: $($suggestions -join ', ')"
        }

        $suggestions | ForEach-Object {
            [System.Management.Automation.CompletionResult]::new(
                $_, 
                $_, 
                "ParameterValue", 
                $_
            )
        }
    }
}


Register-ArgumentCompleter -CommandName usegpt -ScriptBlock {
    param($commandName, $wordToComplete, $cursorPosition)

    if ($env:DEBUG) {
        Write-Host "开始补全useGPT命令参数"
        Write-Host "当前输入: $wordToComplete"
    }

    $config_file = Join-Path $env:GPT_PATH "model.json"
    if (-not (Test-Path $config_file)) {
        if ($env:DEBUG) {
            Write-Host "未找到配置文件: $config_file"
        }
        return 
    }

    if ($env:DEBUG) {
        Write-Host "正在读取配置文件: $config_file"
    }

    $providers = & {
        $config = Get-Content $config_file | ConvertFrom-Json
        $config.PSObject.Properties | Where-Object { $_.Value.key } | ForEach-Object { $_.Name }
    }

    if ($env:DEBUG) {
        Write-Host "找到的可用provider: $($providers -join ', ')"
        Write-Host "正在过滤匹配项..."
    }
    
    $searchTerm = if ($wordToComplete -like "usegpt*") { $wordToComplete -replace "^usegpt[ .\\/]*", "" } else { $wordToComplete }
    if ($env:DEBUG) {
        Write-Host "匹配词 $searchTerm"
    }
    $filteredProviders = $providers | Where-Object { $_ -like "$searchTerm*" }

    if ($env:DEBUG) {
        Write-Host "匹配的provider: $($filteredProviders -join ', ')"
        Write-Host "生成补全建议..."
    }

    $filteredProviders | ForEach-Object {
        [System.Management.Automation.CompletionResult]::new($_, $_, "ParameterValue", $_)
    }
}

# 加载默认配置
if (-not $env:GPT_KEY -or -not $env:GPT_BASE_URL -or -not $env:GPT_MODEL) {
    if (Test-Path (Join-Path $env:GPT_PATH "model.json")) {
        $config = Get-Content (Join-Path $env:GPT_PATH "model.json") | ConvertFrom-Json
        $defaultProvider = if ($config.PSObject.Properties["default"]) {
            "default"
        } else {
            ($config.PSObject.Properties.Name | Select-Object -First 1)
        }
        if ($defaultProvider) {
            usegpt $defaultProvider
        }
    }
}

# 主功能函数
function global:askgpt {
    # 将参数拼接为单个字符串
    $question = $args -join " "

    $pythonPath = Get-PythonPath
    & $pythonPath (Join-Path $env:GPT_PATH "llm_query.py") --ask "$question"
}

function global:explaingpt {
    if ($args.Count -lt 1) {
        Write-Error "错误：需要提供源文件路径"
        return
    }

    $file = $args[0]
    $prompt_file = if ($args.Count -gt 1) { $args[1] } else { Join-Path $env:GPT_PROMPTS_DIR "source-query.txt" }

    if (-not (Test-Path $file)) {
        Write-Error "错误：未找到源文件: $file"
        return
    }

    if (-not (Test-Path $prompt_file)) {
        Write-Error "错误：未找到提示文件: $prompt_file"
        return
    }

    $pythonPath = Get-PythonPath
    & $pythonPath (Join-Path $env:GPT_PATH "llm_query.py") --file $file --prompt-file $prompt_file
}
