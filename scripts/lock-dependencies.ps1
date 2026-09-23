[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) { throw 'uv is required to create the reproducible lockfile.' }
& $uv.Source lock
if ($LASTEXITCODE -ne 0) { throw 'uv lock failed.' }
Write-Host 'Created uv.lock' -ForegroundColor Green
