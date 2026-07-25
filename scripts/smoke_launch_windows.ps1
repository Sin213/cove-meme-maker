<#
.SYNOPSIS
    Packaged launch smoke for a Windows Cove Meme Maker executable.

.DESCRIPTION
    The Nexus/tab-web protocol smoke (scripts/smoke_tab_web.py) cannot run on
    Windows: the app connects to Nexus over an AF_UNIX socket, and CPython does
    not expose AF_UNIX on Windows. Nexus itself only serves the protocol socket
    on Linux, so a Windows build never receives COVE_NEXUS_SOCKET and always
    takes the normal Qt desktop branch.

    This script therefore validates the path Windows users actually get: the
    packaged executable starts, stays alive, and terminates cleanly. It is
    deliberately not a substitute for the tab-web contract, which is covered on
    Linux (AppImage + .deb) and macOS (.app).

.EXAMPLE
    .\scripts\smoke_launch_windows.ps1 -Exe "release\cove-meme-maker-2.3.7-Portable.exe"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [int]$AliveSeconds = 10
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not (Test-Path -LiteralPath $Exe)) {
    throw "Executable not found: $Exe"
}

$item = Get-Item -LiteralPath $Exe
if ($item.Length -le 0) {
    throw "Executable is empty: $($item.FullName)"
}
Write-Host "==> Launch smoke: $($item.FullName) ($([math]::Round($item.Length / 1MB, 1)) MB)"

$proc = Start-Process -FilePath $item.FullName -PassThru
Write-Host "    started pid=$($proc.Id); waiting ${AliveSeconds}s"
Start-Sleep -Seconds $AliveSeconds

$proc.Refresh()
if ($proc.HasExited) {
    throw "Process exited early with code $($proc.ExitCode) - packaged app failed to start"
}
Write-Host "    still running after ${AliveSeconds}s OK"

# Ask politely first so the app can shut down normally, then force if needed.
try { $proc.CloseMainWindow() | Out-Null } catch { }
if (-not $proc.WaitForExit(10000)) {
    Write-Host "    did not close on request; forcing termination"
    Stop-Process -Id $proc.Id -Force
    $proc.WaitForExit(10000) | Out-Null
}

$proc.Refresh()
if (-not $proc.HasExited) {
    throw "Process $($proc.Id) could not be terminated"
}

Write-Host "    terminated cleanly OK"
Write-Host "LAUNCH SMOKE PASSED"
