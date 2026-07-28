<#
.SYNOPSIS
    Remove hw-sentinel completely, leaving nothing behind. See INSTALL-MANIFEST.md.

.DESCRIPTION
    Everything hw-sentinel uses lives inside this folder, so removal is mostly just
    deleting it. Three things exist outside it and are cleaned up here:

      * the three scheduled tasks created by install.ps1
      * HKCU\Software\Unwinder\RTSS   - settings keys RTSS writes when it runs
      * running processes started from this folder

    Nothing else was ever created: no Program Files, no PATH entry, no services, no
    site-packages, no uninstall registry entry.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File uninstall.ps1 -WhatIf
    powershell -ExecutionPolicy Bypass -File uninstall.ps1
    powershell -ExecutionPolicy Bypass -File uninstall.ps1 -RemoveProject
#>
[CmdletBinding()]
param(
    [switch]$RemoveProject,
    [switch]$KeepRtssSettings,
    [switch]$WhatIf
)

$ErrorActionPreference = "Continue"
$Root = $PSScriptRoot
$did = @(); $left = @()

function Act([string]$what, [scriptblock]$do) {
    if ($WhatIf) { Write-Host "WOULD: $what" -ForegroundColor DarkYellow; return }
    Write-Host "-> $what"
    try { & $do; $script:did += $what }
    catch { Write-Warning "  failed: $($_.Exception.Message)"; $script:left += "$what (FAILED)" }
}

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal $id).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

Write-Host "hw-sentinel uninstall" -ForegroundColor Cyan
Write-Host "folder: $Root`n"

# LHM and RTSS run elevated. An unelevated shell cannot read their executable paths, so
# they look like "nothing is running" rather than being matched and stopped - say so
# rather than reporting a clean sweep that did not happen.
if (-not (Test-Admin)) {
    Write-Warning "Not running as administrator. Scheduled tasks cannot be removed, and"
    Write-Warning "elevated processes started from this folder will not be detected."
    Write-Warning "Re-run from an elevated PowerShell for a complete uninstall.`n"
}

# --- 1. scheduled tasks -------------------------------------------------------
foreach ($name in @("hw-sentinel", "hw-sentinel-lhm", "hw-sentinel-rtss")) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        if (-not (Test-Admin)) {
            $left += "scheduled task '$name' (needs an elevated shell)"
        } else {
            Act "remove scheduled task '$name'" { Unregister-ScheduledTask -TaskName $name -Confirm:$false }
        }
    }
}

# --- 2. processes started from this folder ------------------------------------
# Match on the executable path so a system-wide RTSS or an unrelated Python is never
# touched - only what this folder started.
$mine = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($Root, 'OrdinalIgnoreCase')) -or
    ($_.CommandLine -and $_.CommandLine -match 'hwsentinel')
})
foreach ($p in $mine) {
    Act "stop $($p.Name) (pid $($p.ProcessId))" {
        $proc = Get-Process -Id $p.ProcessId -ErrorAction Stop
        [void]$proc.CloseMainWindow()
        if (-not $proc.WaitForExit(6000)) { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop }
    }
}
if (-not $mine) { Write-Host "   (nothing from this folder is running)" -ForegroundColor DarkGray }

# --- 3. RTSS's registry settings ----------------------------------------------
# RTSS is portable apart from this: it writes its own settings under HKCU when it runs.
$unwinder = "HKCU:\Software\Unwinder"
if (Test-Path $unwinder) {
    if ($KeepRtssSettings) {
        $left += "$unwinder (kept at your request)"
    } else {
        Act "delete $unwinder" { Remove-Item $unwinder -Recurse -Force }
    }
} else {
    Write-Host "   (no RTSS registry settings found)" -ForegroundColor DarkGray
}

# --- 4. the folder ------------------------------------------------------------
if ($RemoveProject) {
    if ($WhatIf) {
        Write-Host "WOULD: delete $Root" -ForegroundColor DarkYellow
    } else {
        Write-Host "-> deleting $Root"
        Set-Location (Split-Path $Root)
        # Can't delete the folder this script is running from, so hand it to a
        # detached shell that waits for us to exit first.
        Start-Process powershell -ArgumentList "-NoProfile","-Command",
            "Start-Sleep -Seconds 3; Remove-Item -LiteralPath '$Root' -Recurse -Force" `
            -WindowStyle Hidden
        $did += "delete $Root (running in background)"
    }
} else {
    $left += "the folder $Root - delete it by hand, or re-run with -RemoveProject"
}

Write-Host "`n--- done ---" -ForegroundColor Cyan
if ($did)  { Write-Host "removed:";        $did  | ForEach-Object { Write-Host "  - $_" } }
if ($left) { Write-Host "still present:";  $left | ForEach-Object { Write-Host "  - $_" -ForegroundColor DarkGray } }
