param([switch]$Preview)
$ErrorActionPreference = 'Stop'
$cubeRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path.TrimEnd('\')
$cubePlanPath = Join-Path $cubeRoot 'cube_ai\private\cleanup-plan.json'
$cubeReceiptPath = Join-Path $cubeRoot '项目资料\发布验收\github-releases-verified.json'
$cubeReportPath = Join-Path $cubeRoot '项目资料\本机清理结果.json'
if (!(Test-Path -LiteralPath $cubePlanPath) -or !(Test-Path -LiteralPath $cubeReceiptPath)) {
    throw '未找到维护者本机的清单或发布验收记录，未删除任何文件。'
}
$cubePlan = Get-Content -LiteralPath $cubePlanPath -Raw -Encoding UTF8 | ConvertFrom-Json
$cubeReceipt = Get-Content -LiteralPath $cubeReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
$cubeRepository = 'Guangming1356/MTG_Cube_Builder'
if ($cubeReceipt.repository -ne $cubeRepository -or !$cubeReceipt.release_assets_match_original_archives) {
    throw '发布验收记录不匹配。'
}
# Validate every absolute target before performing any deletion.
$cubeTargets = @()
foreach ($cubeEntry in $cubePlan.targets) {
    $cubeAbsolute = [IO.Path]::GetFullPath($cubeEntry.path)
    if (!$cubeAbsolute.StartsWith($cubeRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "清单目标超出项目目录：$cubeAbsolute"
    }
    if (Test-Path -LiteralPath $cubeAbsolute) {
        $cubeResolved = (Resolve-Path -LiteralPath $cubeAbsolute).Path
        if ($cubeResolved -ne $cubeAbsolute -or ((Get-Item -LiteralPath $cubeResolved).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "目标不是已审查的普通路径：$cubeAbsolute"
        }
        $cubeTargets += $cubeEntry
    }
}
if ($Preview) {
    $cubeTargets | Select-Object path, bytes, files, links | Format-Table -AutoSize
    Write-Host ('预计清理 {0:N2} GB。' -f (($cubeTargets | Measure-Object bytes -Sum).Sum / 1e9))
    exit 0
}
# Refuse to run while the main app has live work.
$cubeEntrance = Join-Path $cubeRoot 'cube_ai\runtime\entrance.json'
if (Test-Path -LiteralPath $cubeEntrance) {
    $cubeConnection = Get-Content -LiteralPath $cubeEntrance -Raw -Encoding UTF8 | ConvertFrom-Json
    $cubeStatus = $null
    try { $cubeStatus = Invoke-RestMethod -Uri ($cubeConnection.url.TrimEnd('/') + '/api/status') -TimeoutSec 5 } catch {}
    if ($cubeStatus -and $cubeStatus.active_jobs -gt 0) { throw '助手还有运行中的任务，请等任务结束后再清理。' }
}
$cubeGhCommand = Get-Command gh -ErrorAction SilentlyContinue
$cubeGhExecutable = if ($cubeGhCommand) { $cubeGhCommand.Source } else { $null }
if (!$cubeGhExecutable) {
    foreach ($cubeCandidate in @((Join-Path $env:ProgramFiles 'GitHub CLI\gh.exe'), (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\gh.exe'))) {
        if (Test-Path -LiteralPath $cubeCandidate -PathType Leaf) { $cubeGhExecutable = $cubeCandidate; break }
    }
}
if (!$cubeGhExecutable) { throw '未找到 GitHub CLI，未开始清理。' }
Write-Host '正在重新核对 GitHub 上的 8 个历史版本……'
foreach ($cubeRelease in $cubeReceipt.releases) {
    $cubeRemoteText = & $cubeGhExecutable api "repos/$cubeRepository/releases/tags/$($cubeRelease.tag)"
    if ($LASTEXITCODE -ne 0) { throw '无法验证 GitHub，未开始清理。请确认联网并登录 GitHub。' }
    $cubeRemote = $cubeRemoteText | ConvertFrom-Json
    if ($cubeRemote.draft) { throw '远端版本尚未正式发布。' }
    foreach ($cubeAsset in $cubeRelease.assets) {
        $cubeFound = @($cubeRemote.assets | Where-Object { $_.name -eq $cubeAsset.name })
        if ($cubeFound.Count -ne 1 -or $cubeFound[0].state -ne 'uploaded' -or $cubeFound[0].size -ne $cubeAsset.size -or $cubeFound[0].digest -ne $cubeAsset.digest) {
            throw "远端附件不完整或校验不同：$($cubeRelease.tag)/$($cubeAsset.name)"
        }
    }
}
$cubePreserved = @{}
foreach ($cubeProperty in $cubePlan.preserved_hashes.PSObject.Properties) {
    $cubeFile = Join-Path $cubeRoot $cubeProperty.Name
    if (!(Test-Path -LiteralPath $cubeFile -PathType Leaf)) { throw "需要保留的文件不存在：$($cubeProperty.Name)" }
    $cubePreserved[$cubeProperty.Name] = (Get-FileHash -LiteralPath $cubeFile -Algorithm SHA256).Hash
}
$cubeReport = [ordered]@{ time = (Get-Date -Format o); status = 'running'; deleted_bytes = 0; removed = @(); preserved_files_verified = $false }
try {
    foreach ($cubeEntry in $cubeTargets) {
        $cubeTarget = (Resolve-Path -LiteralPath $cubeEntry.path).Path
        if (!$cubeTarget.StartsWith($cubeRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw '删除路径检查失败。' }
        if (Test-Path -LiteralPath $cubeTarget -PathType Container) {
            # Unlink directory junctions without traversing them, including on Windows PowerShell 5.1.
            $cubeStack = New-Object 'System.Collections.Generic.Stack[System.IO.DirectoryInfo]'
            $cubeStack.Push([IO.DirectoryInfo]::new($cubeTarget))
            while ($cubeStack.Count -gt 0) {
                foreach ($cubeDirectory in $cubeStack.Pop().EnumerateDirectories()) {
                    if ($cubeDirectory.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                        if (!$cubeDirectory.FullName.StartsWith($cubeTarget + '\', [StringComparison]::OrdinalIgnoreCase)) { throw '目录链接超出清理范围。' }
                        [IO.Directory]::Delete($cubeDirectory.FullName)
                    } else { $cubeStack.Push($cubeDirectory) }
                }
            }
            Remove-Item -LiteralPath $cubeTarget -Recurse -Force
        } else { Remove-Item -LiteralPath $cubeTarget -Force }
        $cubeReport.deleted_bytes += $cubeEntry.bytes
        $cubeReport.removed += $cubeTarget.Substring($cubeRoot.Length + 1)
        Write-Host ('已清理：' + $cubeTarget.Substring($cubeRoot.Length + 1))
    }
    foreach ($cubeName in $cubePreserved.Keys) {
        if ((Get-FileHash -LiteralPath (Join-Path $cubeRoot $cubeName) -Algorithm SHA256).Hash -ne $cubePreserved[$cubeName]) {
            throw "保留文件在清理期间发生变化：$cubeName"
        }
    }
    $cubeReport.preserved_files_verified = $true
    $cubeReport.status = 'done'
    Write-Host ('清理完成：移除 {0:N2} GB 文件。程序、账号、牌表和实战记录已保留。' -f ($cubeReport.deleted_bytes / 1e9))
} catch {
    $cubeReport.status = 'failed'
    $cubeReport.error = $_.Exception.Message
    throw
} finally {
    $cubeReport | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $cubeReportPath -Encoding UTF8
}
