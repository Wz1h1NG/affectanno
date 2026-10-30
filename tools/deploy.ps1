# 批量部署脚本：媒体从 GBU 拉取 -> 部署 -> 清理，本地不留持久副本
#
# 用法：
#   .\tools\deploy.ps1              # 同步媒体并部署，完成后删除本地媒体
#   .\tools\deploy.ps1 -KeepMedia   # 保留本地媒体（调试用）
#   .\tools\deploy.ps1 -NoMedia     # 只更新代码（媒体已在线上，不重新上传）
#
# 前置：
#   - SSH 别名 GBU 可用
#   - GBU 上 $GbuMedia 存在（当前批次的 public/vid）
param(
  [switch]$KeepMedia,
  [switch]$NoMedia
)

$ErrorActionPreference = "Stop"
$Proj    = Split-Path -Parent $PSScriptRoot
$GbuMedia = "/public_hw/share/cit_ztyu/zehengW/video_anno_site/public/vid"
$NodeBin = "C:\Users\11641\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin"
$env:PATH = "$NodeBin;" + $env:PATH
$env:CLOUDFLARE_API_TOKEN = $env:CF_TOKEN  # 由外部环境提供

Push-Location $Proj
try {
  # 1) 依赖
  if (-not (Test-Path "$Proj\node_modules\wrangler")) {
    Write-Host "[1/4] 安装 wrangler ..." -ForegroundColor Cyan
    & (Join-Path $NodeBin "node.exe") `
       "C:\Users\11641\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\pnpm\bin\pnpm.mjs" `
       add -D wrangler 2>&1 | Select-Object -Last 3
  } else {
    Write-Host "[1/4] wrangler 已就绪" -ForegroundColor DarkGray
  }

  # 2) 媒体同步：GBU -> 本地 temp
  $VidDir = "$Proj\public\vid"
  if ($NoMedia) {
    Write-Host "[2/4] 跳过媒体同步（-NoMedia）" -ForegroundColor DarkGray
  } else {
    Write-Host "[2/4] 从 GBU 同步媒体 ..." -ForegroundColor Cyan
    if (Test-Path $VidDir) { Remove-Item $VidDir -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $VidDir | Out-Null
    scp -o BatchMode=yes -o ConnectTimeout=25 -r "GBU:${GbuMedia}/*" "$VidDir\" 2>&1 |
      Select-Object -Last 2
    $n = (Get-ChildItem $VidDir -Recurse -File).Count
    $mb = [math]::Round((Get-ChildItem $VidDir -Recurse -File | Measure-Object Length -Sum).Sum/1MB, 1)
    Write-Host "      同步 $n 个文件 / $mb MB" -ForegroundColor DarkGray
    if ($n -eq 0) { throw "媒体为空，中止（避免把线上视频删光）" }
  }

  # 3) 部署
  Write-Host "[3/4] 部署到 Cloudflare ..." -ForegroundColor Cyan
  $out = & (Join-Path $NodeBin "node.exe") "$Proj\node_modules\wrangler\bin\wrangler.js" deploy 2>&1
  $out | Select-Object -Last 10
  if ($LASTEXITCODE -ne 0) { throw "部署失败" }

  # 4) 清理本地媒体
  if (-not $KeepMedia -and -not $NoMedia) {
    Write-Host "[4/4] 清理本地媒体副本" -ForegroundColor Cyan
    Remove-Item $VidDir -Recurse -Force
    Write-Host "      已删除 public\vid（GBU 仍有母本）" -ForegroundColor DarkGray
  } else {
    Write-Host "[4/4] 保留本地媒体（-KeepMedia / -NoMedia）" -ForegroundColor DarkGray
  }

  Write-Host ""
  Write-Host "完成。站点: https://wzh.lovezyq.asia" -ForegroundColor Green
} finally {
  Pop-Location
}
