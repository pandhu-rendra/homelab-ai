#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$InstallDir = $(if ($env:INSTALL_DIR) { $env:INSTALL_DIR } else { Join-Path $HOME '.homelab-ai' }),
    [string]$BinDir = $(if ($env:BIN_DIR) { $env:BIN_DIR } else { Join-Path $HOME '.local\bin' }),
    [string]$ReleaseUrl = $(if ($env:RELEASE_URL) { $env:RELEASE_URL } else { 'https://altivon.my.id/releases/homelab-ai.tar.gz.enc' }),
    [string]$ReleaseKey = $(if ($env:HOMELAB_RELEASE_KEY) { $env:HOMELAB_RELEASE_KEY } else { '__HOMELAB_RELEASE_KEY__' }),
    [string]$Checksum = '',
    [switch]$NoUv,
    [switch]$DryRun,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'
$InstallerLog = Join-Path ([IO.Path]::GetTempPath()) 'homelab-ai-install.log'
Start-Transcript -Path $InstallerLog -Append | Out-Null
trap {
    Write-Error $_
    Stop-Transcript | Out-Null
    throw
}

function Info([string]$Message) { Write-Host "  -> $Message" -ForegroundColor Cyan }
function Ok([string]$Message) { Write-Host "  OK $Message" -ForegroundColor Green }
function Warn([string]$Message) { Write-Host "  !! $Message" -ForegroundColor Yellow }
function Fail([string]$Message) { throw $Message }

if ($Help) {
    @"
Usage: .\install.ps1 [options]

Options:
  -InstallDir DIR       Install directory (default: $HOME\.homelab-ai)
  -BinDir DIR           Launcher directory (default: $HOME\.local\bin)
  -ReleaseUrl URL       Encrypted release URL
  -ReleaseKey KEY       Release decryption key (normally embedded)
    -Checksum HASH        Expected SHA-256 checksum of the encrypted release
  -NoUv                 Use pip instead of uv
    -DryRun               Validate and plan without changing the system
  -Help                 Show this help

Example:
  irm https://altivon.my.id/install.ps1 | iex
  .\install.ps1 -InstallDir C:\Apps\homelab-ai
"@
    exit 0
}

Write-Host "`n  HomeLab AI Installer (Windows PowerShell)`n" -ForegroundColor Green

if ($ReleaseKey -eq '__HOMELAB_RELEASE_KEY__') {
    Fail 'This installer has no decryption key. Use -ReleaseKey or download the configured release installer.'
}

$pythonCommand = Get-Command py -ErrorAction SilentlyContinue
if ($pythonCommand) {
    $pythonArgs = @('-3')
    $pythonExe = $pythonCommand.Source
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { Fail 'Python 3 is required. Install it from python.org or the Microsoft Store.' }
    $pythonArgs = @()
    $pythonExe = $pythonCommand.Source
}

$pythonVersion = & $pythonExe @pythonArgs -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0) { Fail 'Unable to execute Python 3.' }
$versionParts = $pythonVersion.Trim().Split('.')
if ([int]$versionParts[0] -lt 3 -or ([int]$versionParts[0] -eq 3 -and [int]$versionParts[1] -lt 10)) {
    Fail "Python 3.10 or newer is required (found $pythonVersion)."
}
Ok "Python $($pythonVersion.Trim())"

$opensslCommand = Get-Command openssl -ErrorAction SilentlyContinue
if (-not $opensslCommand) {
    Fail 'OpenSSL is required for release decryption. Install Git for Windows or OpenSSL, then run this installer again.'
}
Ok 'OpenSSL'

$tempDir = Join-Path ([IO.Path]::GetTempPath()) ('homelab-ai-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
try {
    $encryptedPath = Join-Path $tempDir 'release.tar.gz.enc'
    $archivePath = Join-Path $tempDir 'release.tar.gz'

    Info 'Downloading HomeLab AI release...'
    Invoke-WebRequest -Uri $ReleaseUrl -OutFile $encryptedPath -UseBasicParsing
    Ok ('Downloaded (' + [math]::Round((Get-Item $encryptedPath).Length / 1KB, 1) + ' KB)')
    if ($Checksum) {
        $actual = (Get-FileHash $encryptedPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $Checksum.ToLowerInvariant()) { Fail 'Release checksum verification failed.' }
        Ok 'Checksum verified'
    }
    if ($DryRun) {
        Ok "Dry run complete; no files changed. Target: $InstallDir"
        exit 0
    }

    Info 'Decrypting release...'
    & $opensslCommand.Source enc -d -aes-256-cbc -salt -in $encryptedPath -out $archivePath -pass "pass:$ReleaseKey"
    if ($LASTEXITCODE -ne 0) { Fail 'Release decryption failed. Check the release key and URL.' }
    Ok 'Decrypted'

    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    Info "Extracting to $InstallDir..."
    & tar -xzf $archivePath -C $InstallDir
    if ($LASTEXITCODE -ne 0) { Fail 'Archive extraction failed. Windows 10 or newer includes tar; install bsdtar if needed.' }
    Ok 'Extracted'

    Push-Location $InstallDir
    try {
        Info 'Compiling Python bytecode...'
        & $pythonExe @pythonArgs -c "import compileall; raise SystemExit(0 if compileall.compile_dir('.', force=True, quiet=1) else 1)"
        if ($LASTEXITCODE -eq 0) {
            & $pythonExe @pythonArgs -c "import homelab_ai"
            if ($LASTEXITCODE -eq 0) {
                if ($env:HOMELAB_PROTECT_SOURCE -eq '1') {
                    Get-ChildItem -Path . -Filter '*.py' -Recurse -File |
                        Where-Object { $_.Name -notlike '.env*' } |
                        Remove-Item -Force
                    Ok 'Source protected (compiled to bytecode)'
                } else {
                    Ok 'Bytecode compiled; source retained'
                }
            } else {
                Warn 'Package import check failed; source files were kept.'
            }
        } else {
            Warn 'Bytecode compilation failed; source files were kept.'
        }
    } finally {
        Pop-Location
    }

    $venvDir = Join-Path $InstallDir '.venv'
    $venvPython = Join-Path $venvDir 'Scripts\python.exe'
    if (-not (Test-Path $venvPython)) {
        Info 'Creating virtual environment...'
        & $pythonExe @pythonArgs -m venv $venvDir
        if ($LASTEXITCODE -ne 0) { Fail 'Virtual environment creation failed.' }
        Ok 'Virtual environment created'
    }

    $uvCommand = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $NoUv -and -not $uvCommand) {
        Info 'Installing uv...'
        & $venvPython -m pip install --user uv --quiet
        $uvCommand = Get-Command uv -ErrorAction SilentlyContinue
    }
    if (-not $NoUv -and $uvCommand) {
        Info 'Installing dependencies with uv...'
        & $uvCommand.Source pip install --python $venvPython -r (Join-Path $InstallDir 'requirements.txt')
    } else {
        Info 'Installing dependencies with pip...'
        & $venvPython -m pip install --quiet -r (Join-Path $InstallDir 'requirements.txt')
    }
    if ($LASTEXITCODE -ne 0) { Fail 'Dependency installation failed.' }
    Ok 'Dependencies installed'

    $envPath = Join-Path $InstallDir '.env'
    $envExamplePath = Join-Path $InstallDir '.env.example'
    if (-not (Test-Path $envPath) -and (Test-Path $envExamplePath)) {
        Copy-Item $envExamplePath $envPath
        Warn 'Created .env from .env.example; add your API keys.'
    }

    New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
    $launcherPath = Join-Path $BinDir 'homelab.cmd'
    $launcher = @"
@echo off
setlocal
pushd "$InstallDir"
"$venvPython" -m homelab_ai %*
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%
"@
    Set-Content -Path $launcherPath -Value $launcher -Encoding ASCII
    Ok "Launcher created: $launcherPath"

    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $pathEntries = @($userPath -split ';' | Where-Object { $_ })
    if ($pathEntries -notcontains $BinDir) {
        [Environment]::SetEnvironmentVariable('Path', (($pathEntries + $BinDir) -join ';'), 'User')
        $env:Path = "$env:Path;$BinDir"
        Ok 'Added launcher directory to the user PATH'
    }

    Write-Host "`n  HomeLab AI installed successfully!`n  Run: homelab`n" -ForegroundColor Green
} finally {
    if (Test-Path $tempDir) { Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue }
    Stop-Transcript | Out-Null
}
