#!/usr/bin/env pwsh  
<#  
.SYNOPSIS  
格式化 PowerShell 脚本文件  

.DESCRIPTION  
使用 PSScriptAnalyzer 的 Invoke-Formatter 自动格式化 .ps1 文件  
支持批量处理多个文件/目录，保留 UTF-8 BOM 编码  

.PARAMETER Path  
要格式化的文件或目录路径（支持通配符和多个参数）  

.EXAMPLE  
./Format-Script.ps1 ./test.ps1            # 格式化单个文件  
./Format-Script.ps1 ./scripts *.ps1       # 批量处理多个路径  
./Format-Script.ps1                       # 格式化当前目录所有ps1文件  
#>  

[CmdletBinding(SupportsShouldProcess)]  
param(  
    [Parameter(Position = 0, ValueFromPipeline, ValueFromRemainingArguments)]  # 移除 Mandatory 属性
    [Alias("FilePath")]  
    [string[]]$Path = @(Get-Location)  # 默认处理当前目录
)  

begin {  
    # 调试输出实际接收的参数  
    Write-Host "[DEBUG] 输入参数: $($Path -join ', ')" -ForegroundColor Cyan  

    # 检查 PSScriptAnalyzer 模块  
    if (-not (Get-Module -ListAvailable PSScriptAnalyzer)) {  
        Write-Host "正在安装 PSScriptAnalyzer 模块..." -ForegroundColor Cyan  
        Install-Module PSScriptAnalyzer -Scope CurrentUser -Force -Confirm:$false  
    }  

    # 获取所有待处理文件  
    function Get-Files($targetPath) {  
        try {  
            if (Test-Path $targetPath -PathType Container) {  
                Get-ChildItem $targetPath -Recurse -Filter *.ps1 | Where-Object { !$_.PSIsContainer }  
            }  
            else {  
                Get-Item $targetPath | Where-Object { $_.Extension -eq '.ps1' }  
            }  
        }  
        catch {  
            Write-Warning "路径解析失败: $targetPath"  
            return @()  
        }  
    }  
}  

process {  
    # 合并来自管道和参数输入的路径  
    $allPaths = @($Path)  
    foreach ($item in $allPaths) {  
        try {  
            $resolvedPaths = Resolve-Path $item -ErrorAction Stop | Select-Object -ExpandProperty Path  
        }  
        catch {  
            Write-Warning "路径不存在: $item"  
            continue  
        }  

        foreach ($filePath in $resolvedPaths) {  
            $files = Get-Files $filePath  
            if (-not $files) {  
                Write-Warning "未找到.ps1文件: $filePath"  
                continue  
            }  

            foreach ($file in $files) {  
                if (-not $file.Exists) {  
                    Write-Warning "跳过无效文件: $($file.FullName)"  
                    continue  
                }  

                # 保留原始编码（兼容带 BOM 的 UTF-8）  
                $encoding = [System.Text.Encoding]::UTF8  
                $hasBom = $true  
                try {  
                    $currentContent = [IO.File]::ReadAllText($file.FullName, [Text.Encoding]::UTF8)  
                    $preamble = [Text.Encoding]::UTF8.GetPreamble()  
                    $hasBom = $currentContent.StartsWith($preamble)  
                }  
                catch {  
                    Write-Warning "无法检测文件编码: $($file.FullName)"  
                    continue  
                }  

                if ($PSCmdlet.ShouldProcess($file.FullName, "格式化文件")) {  
                    try {  
                        Write-Verbose "正在处理: $($file.FullName)"  
                          
                        # 读取并格式化内容  
                        $content = Get-Content $file.FullName -Raw  
                        $formatted = Invoke-Formatter -ScriptDefinition $content  

                        # 保持原始编码格式  
                        if ($hasBom) {  
                            [IO.File]::WriteAllText($file.FullName, $formatted, $encoding)  
                        }  
                        else {  
                            [IO.File]::WriteAllText($file.FullName, $formatted, [System.Text.UTF8Encoding]::new($false))  
                        }  

                        Write-Host "✅ 已格式化: $($file.FullName)" -ForegroundColor Green  
                    }  
                    catch {  
                        Write-Error "格式化失败 [$($file.FullName)]: $_"  
                    }  
                }  
            }  
        }  
    }  
}
