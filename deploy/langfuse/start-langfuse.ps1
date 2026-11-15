# 一键拉起 Langfuse 容器服务
$ErrorActionPreference = "Stop"
$composeFile = Join-Path $PSScriptRoot "docker-compose.yml"

Write-Host "==> 检查 Docker Engine 状态..." -ForegroundColor Cyan
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker Desktop 尚未就绪，正在尝试启动 Docker Desktop..." -ForegroundColor Yellow
    $dockerExe = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerExe) {
        Start-Process $dockerExe
        Write-Host "请等待 Docker Engine 启动完成后重新执行本脚本（若首次启用 WSL2 虚拟化，请先重启一次 Windows）。" -ForegroundColor Yellow
    } else {
        Write-Host "未检测到 Docker Desktop，请先安装 Docker Desktop。" -ForegroundColor Red
    }
    exit 1
}

Write-Host "==> 正在启动 Langfuse 服务 (http://localhost:3000)..." -ForegroundColor Cyan
docker compose -f $composeFile up -d

Write-Host ""
Write-Host "=========================================================" -ForegroundColor Green
Write-Host " Langfuse 部署完成！" -ForegroundColor Green
Write-Host " 控制台地址 : http://localhost:3000"
Write-Host " 预置管理员 : admin@insight.local / Admin123456!"
Write-Host " Public Key : pk-lf-insight-aitest"
Write-Host " Secret Key : sk-lf-insight-aitest"
Write-Host "=========================================================" -ForegroundColor Green
