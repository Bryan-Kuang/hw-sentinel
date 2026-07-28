<#
.SYNOPSIS
    Register hw-sentinel to start automatically at logon.

.DESCRIPTION
    Creates ONE scheduled task named "hw-sentinel". It runs with highest privileges,
    and hw-sentinel launches LibreHardwareMonitor and RTSS itself as child processes,
    which inherit that elevated token - so LHM gets the administrator rights it needs
    to read sensors with no second task and no UAC prompt at boot.

    This task is the only thing that lives outside the install folder.

    The Windows installer calls this with -InstallDir and -Silent. Run it by hand from
    an elevated PowerShell when working from a source checkout.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install.ps1
    powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [string]$InstallDir,
    [switch]$Uninstall,
    [switch]$NoStart,
    [switch]$Silent
)

$ErrorActionPreference = "Stop"
$TaskName = "hw-sentinel"
if (-not $InstallDir) { $InstallDir = $PSScriptRoot }

function Say($m) { if (-not $Silent) { Write-Host $m } }

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal $id).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Remove-TaskIfPresent([string]$Name) {
    if (Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false
        Say "removed task '$Name'"
    }
}

if (-not (Test-Admin)) {
    Write-Error "Run this from an elevated PowerShell (Run as Administrator)."
}

# Earlier versions registered three tasks, one per component. Clear those out so an
# upgrade does not leave orphans starting duplicate copies of LHM and RTSS.
foreach ($legacy in @("hw-sentinel-lhm", "hw-sentinel-rtss")) { Remove-TaskIfPresent $legacy }

if ($Uninstall) {
    # Stop the task before unregistering it, otherwise the monitor keeps running and
    # holds its files open - which makes the uninstaller leave the folder behind.
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        try { Stop-ScheduledTask -TaskName $TaskName -ErrorAction Stop } catch {}
    }
    Remove-TaskIfPresent $TaskName

    # Stop anything still running out of the install folder: the monitor, and the
    # LibreHardwareMonitor / RTSS copies it launched. Matching on path means a
    # system-wide RTSS the user runs for other things is never touched.
    # Excluding unins*.exe matters: the uninstaller itself runs from the install
    # directory, so an unfiltered sweep makes it terminate itself mid-uninstall.
    $mine = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ExecutablePath -and
        $_.ExecutablePath.StartsWith($InstallDir, 'OrdinalIgnoreCase') -and
        $_.Name -notlike 'unins*' -and
        $_.ProcessId -ne $PID
    })
    foreach ($p in $mine) {
        Say "stopping $($p.Name) (pid $($p.ProcessId))"
        try {
            $proc = Get-Process -Id $p.ProcessId -ErrorAction Stop
            [void]$proc.CloseMainWindow()
            if (-not $proc.WaitForExit(6000)) { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop }
        } catch {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
    if ($mine) { Start-Sleep -Seconds 2 }

    Say "`nautostart removed and processes stopped."
    return
}

$pythonw = Join-Path $InstallDir "runtime\python\pythonw.exe"
if (-not (Test-Path $pythonw)) {
    Write-Error "missing $pythonw - run bootstrap.ps1 first (or reinstall)."
}

Remove-TaskIfPresent $TaskName

$action  = New-ScheduledTaskAction -Execute $pythonw -Argument "-m hwsentinel run" `
                                   -WorkingDirectory $InstallDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
                                        -LogonType Interactive -RunLevel Highest
# A daemon, not a job that finishes: no execution time limit, restart if it dies.
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
                                         -DontStopIfGoingOnBatteries `
                                         -StartWhenAvailable `
                                         -ExecutionTimeLimit ([TimeSpan]::Zero) `
                                         -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
                       -Principal $principal -Settings $settings `
                       -Description "Show a hardware alert only when a metric is abnormal." | Out-Null
Say "registered '$TaskName' -> $pythonw"

if (-not $NoStart) {
    Start-ScheduledTask -TaskName $TaskName
    Say "started"
}
