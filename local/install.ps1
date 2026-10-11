# LMB BioAge: установка для тестового режима на компьютере с Windows 10/11.
# Запускается из install.bat. Повторный запуск безопасен: готовые шаги пропускаются,
# база и ключи не пересоздаются, структура базы обновляется.
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

function Say($t) { Write-Host "[LMB] $t" -ForegroundColor Cyan }
function Have($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }
function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "Ошибка: $what (код $LASTEXITCODE)" } }
function Winget-Install($id, $extra) {
  Say "Устанавливаю $id (может появиться запрос разрешения Windows)…"
  $wargs = @("install", "--id", $id, "-e", "--silent", "--accept-package-agreements", "--accept-source-agreements") + $extra
  & winget @wargs
  # 0 — установлено; -1978335189 — уже установлено
  if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne -1978335189) { throw "Не удалось установить $id (код $LASTEXITCODE)" }
  Refresh-Path
}

function Find-Python {
  $cands = @("$env:LOCALAPPDATA\Programs\Python\Python312\python.exe", "$env:ProgramFiles\Python312\python.exe")
  foreach ($p in $cands) { if (Test-Path $p) { return $p } }
  if (Have "py") {
    try {
      $p = (& py -3.12 -c "import sys; print(sys.executable)" 2>$null)
      if ($LASTEXITCODE -eq 0 -and $p) { return $p.Trim() }
    } catch { }
  }
  return $null
}

function Find-Initdb {
  if (Have "initdb") { return $true }
  return [bool](Get-ChildItem "$env:ProgramFiles\PostgreSQL\*\bin\initdb.exe" -ErrorAction SilentlyContinue)
}

Say "LMB BioAge — установка (тестовый режим). Папка проекта: $Repo"
if (-not (Have "winget")) {
  throw "Не найден winget. Установите «Установщик приложений» (App Installer) из Microsoft Store и запустите снова."
}

# 1. Python 3.12
$py = Find-Python
if (-not $py) {
  Winget-Install "Python.Python.3.12" @("--scope", "user")
  $py = Find-Python
  if (-not $py) { throw "Python 3.12 установлен, но не найден. Перезапустите install.bat." }
}
Say "Python: $py"

# 2. Node.js (нужен только для сборки интерфейса)
if (-not (Have "npm.cmd")) {
  Winget-Install "OpenJS.NodeJS.LTS" @()
  if (-not (Have "npm.cmd")) { $env:Path += ";$env:ProgramFiles\nodejs" }
}

# 3. PostgreSQL 16 (используются только программы initdb/pg_ctl; база создаётся в папке данных LMB)
if (-not (Find-Initdb)) {
  $pw = [Guid]::NewGuid().ToString("N")
  Winget-Install "PostgreSQL.PostgreSQL.16" @("--override", "--mode unattended --unattendedmodeui none --superpassword $pw --disable-components stackbuilder")
  if (-not (Find-Initdb)) { throw "PostgreSQL установлен, но initdb.exe не найден в $env:ProgramFiles\PostgreSQL" }
}
Say "PostgreSQL найден"

# 4. Виртуальное окружение Python и пакеты проекта
$venvPy = Join-Path $Repo ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
  Say "Создаю окружение Python…"
  & $py -m venv (Join-Path $Repo ".venv"); Check "создание окружения Python"
}
Say "Устанавливаю пакеты Python…"
& $venvPy -m pip install --quiet --upgrade pip; Check "обновление pip"
& $venvPy -m pip install --quiet -e (Join-Path $Repo "lmb-engine") -e (Join-Path $Repo "lmb-server"); Check "установка пакетов"

# 5. Сборка интерфейса
Say "Собираю интерфейс…"
Push-Location (Join-Path $Repo "lmb-web")
& npm.cmd ci --no-audit --no-fund --loglevel=error; Check "загрузка пакетов интерфейса"
& npm.cmd run build --silent; Check "сборка интерфейса"
Pop-Location

# 6. База, ключи, учётная запись врача
& $venvPy (Join-Path $Repo "local\lmb_local.py") setup; Check "первичная настройка"

# 7. Ярлык на рабочем столе
$desk = [Environment]::GetFolderPath("Desktop")
$lnk = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desk "LMB BioAge.lnk"))
$lnk.TargetPath = Join-Path $Repo "local\start.bat"
$lnk.WorkingDirectory = $Repo
$lnk.Save()
Say "Ярлык «LMB BioAge» создан на рабочем столе. Установка завершена."
