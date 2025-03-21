# env.ps1
# PowerShell 5.0 compatible environment configuration

# 设置控制台编码为UTF-8
[console]::InputEncoding = [System.Text.Encoding]::UTF8
[console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 初始化基础环境变量
function global:Initialize-GptEnv {
    if (-not $env:GPT_PATH) {
        $env:GPT_PATH = $PSScriptRoot
    }

    $env:GPT_DOC = Join-Path -Path $env:GPT_PATH -ChildPath "obsidian"
    $env:PATH = "$(Join-Path -Path $env:GPT_PATH -ChildPath 'bin');$env:PATH"
    $env:GPT_PROMPTS_DIR = Join-Path -Path $env:GPT_PATH -ChildPath "prompts"
    $env:GPT_LOGS_DIR = Join-Path -Path $env:GPT_PATH -ChildPath "logs"
    $env:GPT_MAX_TOKEN = if ($env:GPT_MAX_TOKEN) { $env:GPT_MAX_TOKEN } else { 16384 }
    $env:GPT_UUID_CONVERSATION = if ($env:GPT_UUID_CONVERSATION) { $env:GPT_UUID_CONVERSATION } else { [guid]::NewGuid().ToString() }
}

# 初始化目录结构
function global:Initialize-Directories {
    $paths = @('bin', 'prompts', 'logs', 'conversation')
    foreach ($dir in $paths) {
        $fullPath = Join-Path -Path $env:GPT_PATH -ChildPath $dir
        if (-not (Test-Path $fullPath)) {
            New-Item -ItemType Directory -Path $fullPath -Force | Out-Null
        }
    }
}

# 会话管理函数
function global:New-Conversation {
    $env:GPT_UUID_CONVERSATION = [guid]::NewGuid().ToString()
    Write-Host "新会话编号: $env:GPT_UUID_CONVERSATION"
}

# 会话列表核心逻辑（纯PowerShell实现）
function global:Get-ConversationList {
    param(
        [int]$Limit = 0
    )

    $conversationDir = Join-Path -Path $env:GPT_PATH -ChildPath "conversation"
    $allFiles = @()

    if (Test-Path $conversationDir) {
        Get-ChildItem -Path $conversationDir -Recurse -File -Filter *.json | ForEach-Object {
            try {
                $dirName = $_.Directory.Name
                $fileName = $_.BaseName
                $uuidParts = $fileName -split '-'
                $dateStr = $dirName
                $timeStr = "$($uuidParts[0])-$($uuidParts[1])-$($uuidParts[2])"
                $uuid = $uuidParts[3..($uuidParts.Count)] -join '-'
                
                # 读取预览内容
                $preview = "N/A"
                $content = Get-Content $_.FullName -Encoding UTF8 | ConvertFrom-Json
                if ($content -is [array] -and $content.Count -gt 0) {
                    $preview = ($content[0].content -replace "`n", " ").Substring(0, [Math]::Min(32, $content[0].content.Length))
                }

                $allFiles += [PSCustomObject]@{
                    MTime   = $_.LastWriteTime
                    Date    = $dateStr
                    Time    = $timeStr
                    UUID    = $uuid
                    Preview = $preview
                    Path    = $_.FullName
                }
            }
            catch {}
        }
    }

    $sorted = $allFiles | Sort-Object -Property MTime -Descending
    if ($Limit -gt 0) {
        $sorted = $sorted | Select-Object -First $Limit
    }

    return $sorted
}

function global:Show-ConversationMenu {
    param(
        [Parameter (ValueFromPipeline)]$Items,
        [string]$Title
    )

    Write-Host "`n$Title："
    $index = 1
    $Items | ForEach-Object {
        $preview = if ($_.Preview.Length -gt 32) { "$($_.Preview.Substring(0,32))..." } else { $_.Preview }
        Write-Host ("{0,-3} {1,-19} {2,-36} {3}" -f "$index)", "$($_.Date) $($_.Time)", $_.UUID, $preview)
        $index++
    }
}

function global:Invoke-ConversationSelection {
    param(
        [Parameter(ValueFromPipeline)]$Items,
        [string]$Title
    )

    $list = @($Items)
    if ($list.Count -eq 0) {
        Write-Host "没有找到历史对话"
        return
    }

    Show-ConversationMenu -Items $list -Title $Title
    $choice = Read-Host "`n请选择对话 (1-$($list.Count)，直接回车取消)"

    if ($choice -match '^\d+$' -and [int]$choice -ge 1 -and [int]$choice -le $list.Count) {
        $selected = $list[[int]$choice - 1]
        $env:GPT_UUID_CONVERSATION = $selected.UUID
        Write-Host "已切换到对话: $($selected.UUID)"
    }
    else {
        Write-Host "操作已取消"
    }
}

# 模型管理函数
function global:Get-ModelList {
    param(
        [string]$ConfigFile = (Join-Path -Path $env:GPT_PATH -ChildPath "model.json")
    )

    if (-not (Test-Path $ConfigFile)) {
        Write-Error "错误：未找到配置文件: $ConfigFile"
        return
    }

    $config = Get-Content -Path $ConfigFile -Encoding UTF8 | ConvertFrom-Json
    $config.PSObject.Properties | Where-Object { $_.Value.key } | ForEach-Object {
        Write-Host "$($_.Name): $($_.Value.model_name)"
    }
}

function global:Use-GptModel {
    param(
        [Parameter(Mandatory)]$ModelName,
        [string]$ConfigFile = (Join-Path -Path $env:GPT_PATH -ChildPath "model.json"),
        [switch]$Silent
    )

    if (-not (Test-Path $ConfigFile)) {
        Write-Error "错误：未找到配置文件: $ConfigFile"
        return
    }

    # 清空相关环境变量
    $env:GPT_KEY = $null
    $env:GPT_BASE_URL = $null
    $env:GPT_MODEL = $null
    $env:GPT_MAX_TOKEN = $null
    $env:GPT_TEMPERATURE = $null
    $env:GPT_IS_THINKING = $null

    $config = Get-Content -Path $ConfigFile -Encoding UTF8 | ConvertFrom-Json
    $modelConfig = $config.$ModelName

    if (-not $modelConfig -or -not $modelConfig.key -or -not $modelConfig.base_url -or -not $modelConfig.model_name) {
        Write-Error "错误：未找到模型 '$ModelName' 或配置不完整"
        return
    }

    $env:GPT_KEY = $modelConfig.key
    $env:GPT_BASE_URL = $modelConfig.base_url
    $env:GPT_MODEL = $modelConfig.model_name
    if ($modelConfig.max_tokens) { $env:GPT_MAX_TOKEN = $modelConfig.max_tokens }
    if ($modelConfig.temperature) { $env:GPT_TEMPERATURE = $modelConfig.temperature }
    if ($modelConfig.is_thinking) { $env:GPT_IS_THINKING = $modelConfig.is_thinking }

    if (-not $Silent) {
        Write-Host "成功设置GPT环境变量："
        Write-Host "  GPT_KEY: $($modelConfig.key.Substring(0,4))****"
        Write-Host "  GPT_BASE_URL: $($modelConfig.base_url)"
        Write-Host "  GPT_MODEL: $($modelConfig.model_name)"
        if ($modelConfig.max_tokens) { Write-Host "  GPT_MAX_TOKEN: $($modelConfig.max_tokens)" }
        if ($modelConfig.temperature) { Write-Host "  GPT_TEMPERATURE: $($modelConfig.temperature)" }
        if ($modelConfig.is_thinking) { Write-Host "  GPT_IS_THINKING: $($modelConfig.is_thinking)" }
    }
}

# 新增 usegpt 函数
function global:usegpt {
    param(
        [Parameter(ValueFromRemainingArguments)]$ModelName
    )
    if (-not $ModelName) {
        Write-Host "可用模型列表："
        Get-ModelList
        return
    }
    Use-GptModel -ModelName $ModelName
}

# 环境检查
function global:Test-GptEnv {
    if (-not $env:GPT_KEY -or -not $env:GPT_BASE_URL -or -not $env:GPT_MODEL) {
        Write-Error "错误：请先配置GPT_KEY、GPT_BASE_URL和GPT_MODEL环境变量"
        return $false
    }
    return $true
}

# 公共工具函数
function global:Write-Debug {
    param([string]$Message)
    if ($env:GPT_DEBUG -eq "1") {
        Write-Host "DEBUG: $Message" -ForegroundColor DarkGray
    }
}

# 主功能命令
function global:allconversation {
    Get-ConversationList -Limit 0 | Invoke-ConversationSelection -Title "所有对话记录"
}

function global:recentconversation {
    Get-ConversationList -Limit 10 | Invoke-ConversationSelection -Title "最近10条对话记录"
}

function global:listgpt {
    Get-ModelList @args
}

function global:explaingpt {
    param(
        [Parameter(Mandatory)]$File,
        $PromptFile = (Join-Path -Path $env:GPT_PROMPTS_DIR -ChildPath "source-query.txt")
    )

    if (-not (Test-Path $File)) { throw "源文件不存在: $File" }
    if (-not (Test-Path $PromptFile)) { throw "提示文件不存在: $PromptFile" }

    & (Get-PythonPath) (Join-Path -Path $env:GPT_PATH -ChildPath "llm_query.py") --file $File --prompt-file $PromptFile
}

function global:chat {
    param([switch]$New)
    if (-not (Test-GptEnv)) { return }
    if ($New) { New-Conversation }
    & (Get-PythonPath) (Join-Path -Path $env:GPT_PATH -ChildPath "llm_query.py") --chatbot
}

function global:chatbot {
    chat -New
}

function global:chatagain {
    chat
}

function global:askgpt {
    param([Parameter(ValueFromRemainingArguments)]$Question)
    if (-not $Question) { throw "问题不能为空" }
    # 将Question中的\@替换为@
    $Question = $Question -replace '\\@', '@'
    & (Get-PythonPath) (Join-Path -Path $env:GPT_PATH -ChildPath "llm_query.py") --ask $Question
}

# 补全支持
function global:Get-PromptFiles {
    Get-ChildItem -Path $env:GPT_PROMPTS_DIR -File | Select-Object -ExpandProperty Name
}

Register-ArgumentCompleter -CommandName askgpt -ScriptBlock {
    param($commandName, $commandAst, $cursorPosition)

    # 从AST中获取当前输入的单词
    $wordToComplete = $commandAst.CommandElements[-1].Value

    if ($env:GPT_DEBUG -eq "1") {
        $debugInfo = @(
            "开始自动补全调试信息：",
            "当前输入: $wordToComplete",
            "光标位置: $cursorPosition",
            "完整AST结构:",
            ($commandAst.CommandElements)
        )
        $debugInfo | ForEach-Object {
            Write-Host $_ -ForegroundColor DarkGray
        }
    }

    if ($wordToComplete -like '*@*' -or $wordToComplete -like '*\@*') {
        # 处理包含@或\@的情况
        $search = if ($wordToComplete.StartsWith('@')) {
            $wordToComplete.Substring(1)
        }
        elseif ($wordToComplete.StartsWith('\@')) {
            $wordToComplete.Substring(2)
        }
        else {
            $wordToComplete.Substring($wordToComplete.IndexOf('@') + 1)
        }
        
        if ($env:GPT_DEBUG -eq "1") {
            Write-Host "搜索前缀: $search" -ForegroundColor DarkGray
        }

        $prompts = @(Get-PromptFiles | Where-Object { $_ -like "$search*" } | ForEach-Object { "\@$_" })
        $special = @('clipboard', 'tree', 'treefull', 'read', 'listen', 'symbol_', 'glow', 'last', 'patch', 'edit') | Where-Object { $_ -like "$search*" } | ForEach-Object { "\@$_" }
        $files = Get-ChildItem -File -Filter "$search*" | Select-Object -ExpandProperty Name | ForEach-Object { "\@$_" }
        
        # 添加API补全支持
        $apiCompletions = @()
        if ($env:GPT_API_SERVER -and $search -like "symbol_*") {
            $symbolPrefix = $search.Substring(7)  # 去掉"symbol_"
            if ($symbolPrefix -notmatch "\.") {
                # 本地文件补全
                $apiCompletions = Get-ChildItem -File -Filter "$symbolPrefix*" | 
                    Select-Object -ExpandProperty Name | 
                    ForEach-Object { "\@symbol_$_" }
            }
            else {
                # 远程API补全
                try {
                    $apiServer = $env:GPT_API_SERVER.TrimEnd('/')
                    $response = Invoke-RestMethod -Uri "$apiServer/complete_realtime?prefix=symbol:$symbolPrefix" -UseBasicParsing
                    $apiCompletions = $response -split "`n" | ForEach-Object { "\@$_" -replace 'symbol:', 'symbol_' }
                }
                catch {
                    Write-Debug "API补全请求失败: $_"
                }
            }
        }
        
        if ($env:GPT_DEBUG -eq "1") {
            Write-Host "找到的提示文件: $($prompts -join ', ')" -ForegroundColor DarkGray
            Write-Host "找到的特殊命令: $($special -join ', ')" -ForegroundColor DarkGray
            Write-Host "找到的匹配文件: $($files -join ', ')" -ForegroundColor DarkGray
            Write-Host "找到的API补全: $($apiCompletions -join ', ')" -ForegroundColor DarkGray
        }

        $results = @($special) + @($prompts) + @($files) + @($apiCompletions)
        
        if ($env:GPT_DEBUG -eq "1") {
            Write-Host "最终补全结果: $($results -join ', ')" -ForegroundColor DarkGray
            Write-Host "自动补全调试结束" -ForegroundColor DarkGray
        }

        $results | ForEach-Object {
            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
        }
    } 
}


Register-ArgumentCompleter -CommandName usegpt -ScriptBlock {
    param($commandName, $commandAst, $cursorPosition)

    if ($env:GPT_DEBUG -eq "1") {
        Write-Host "开始usegpt自动补全" -ForegroundColor DarkGray
    }

    # 获取当前命令元素
    $elements = $commandAst.CommandElements

    # 如果当前是空格后的补全（即没有输入任何内容）
    if ($elements.Count -eq 1 -or ($elements.Count -eq 2 -and $elements[-1].Value -eq "")) {
        $wordToComplete = ""
    }
    else {
        # 从AST中获取当前输入的单词
        $wordToComplete = $elements[-1].Value

        # 处理可能存在的./前缀
        if ($wordToComplete -like "./*") {
            $wordToComplete = $wordToComplete.Substring(2)
        }
    }

    if ($env:GPT_DEBUG -eq "1") {
        Write-Host "当前补全单词: $wordToComplete" -ForegroundColor DarkGray
    }

    $configFile = Join-Path -Path $env:GPT_PATH -ChildPath "model.json"
    if (Test-Path $configFile) {
        if ($env:GPT_DEBUG -eq "1") {
            Write-Host "找到模型配置文件: $configFile" -ForegroundColor DarkGray
        }

        $models = (Get-Content $configFile | ConvertFrom-Json).PSObject.Properties.Name
        
        if ($env:GPT_DEBUG -eq "1") {
            Write-Host "所有可用模型: $($models -join ', ')" -ForegroundColor DarkGray
        }

        $filteredModels = $models | Where-Object { $_ -like "$wordToComplete*" }
        
        if ($env:GPT_DEBUG -eq "1") {
            Write-Host "匹配的模型: $($filteredModels -join ', ')" -ForegroundColor DarkGray
        }

        $filteredModels | ForEach-Object {
            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
        }
    }
    else {
        if ($env:GPT_DEBUG -eq "1") {
            Write-Host "未找到模型配置文件" -ForegroundColor DarkGray
        }
    }

    if ($env:GPT_DEBUG -eq "1") {
        Write-Host "usegpt自动补全结束" -ForegroundColor DarkGray
    }
}

# 初始化流程
Initialize-GptEnv
Initialize-Directories

# 自动配置默认模型
if (-not $env:GPT_KEY -or -not $env:GPT_BASE_URL -or -not $env:GPT_MODEL) {
    $configFile = Join-Path -Path $env:GPT_PATH -ChildPath "model.json"
    if (Test-Path $configFile) {
        $firstModel = (Get-Content $configFile | ConvertFrom-Json).PSObject.Properties | 
            Where-Object { $_.Value.key } | 
            Select-Object -First 1 -ExpandProperty Name
        if ($firstModel) {
            Use-GptModel -ModelName $firstModel -Silent
        }
    }
}

# 获取Python路径
function global:Get-PythonPath {
    $venvPython = if ($env:OS -eq 'Windows_NT') {
        Join-Path -Path $env:GPT_PATH -ChildPath ".venv\Scripts\python.exe"
    }
    else {
        Join-Path -Path $env:GPT_PATH -ChildPath ".venv/bin/python"
    }

    if (Test-Path $venvPython) { return $venvPython }
    
    $sysPython = if ($env:OS -eq 'Windows_NT') { 'python.exe' } else { 'python3' }
    $sysPath = Get-Command $sysPython -ErrorAction SilentlyContinue
    if ($sysPath) { 
        Write-Warning "使用系统Python: $($sysPath.Source)"
        return $sysPath.Source
    }

    throw "未找到可用的Python解释器"
}
