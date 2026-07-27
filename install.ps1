<#
.SYNOPSIS
    Start hw-sentinel and its bundled dependencies automatically at logon.

.DESCRIPTION
    Registers three scheduled tasks, all pointing at the private runtime in this folder:

        hw-sentinel-lhm    LibreHardwareMonitor (the sensor source)
        hw-sentinel-rtss   RivaTuner Statistics Server (in-game rendering)
        hw-sentinel        the monitor itself

    They run "with highest privileges" because LibreHardwareMonitor needs administrator
    rights to read CPU temperature and voltage. That flag is what avoids a UAC prompt on
    every boot.

    These three task entries are the ONLY thing this project puts outside its own folder.
    uninstall.ps1 removes them.

    Run from an elevated PowerShell.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install.ps1
    powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [switch]$Uninstall,
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

$Tasks = [ordered]@{
    "hw-sentinel-lhm"  = @{ Exe = Join-Path $Root "runtime\lhm\LibreHardwareMonitor.exe";  Args = ""
                            Desc = "Sensor source for hw-sentinel (needs elevation)." }
    "hw-sentinel-rtss" = @{ Exe = Join-Path $Root "runtime\rtss\RTSS.exe";                 Args = ""
                            Desc = "In-game overlay renderer for hw-sentinel." }
    "hw-sentinel"      = @{ Exe = Join-Path $Root "runtime\python\pythonw.exe"
                            Args = "-m hwsentinel --config `"$(Join-Path $Root 'config.toml')`" run"
                            Desc = "Show a hardware alert only when a metric is abnormal." }
}

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal $id).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Remove-TaskIfPresent([string]$Name) {
    if (Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false
        Write-Host "removed task '$Name'"
        return $true
    }
    return $false
}

if (-not (Test-Admin)) {
    Write-Error "Run this from an elevated PowerShell (Run as Administrator)."
}

if ($Uninstall) {
    foreach ($name in $Tasks.Keys) { [void](Remove-TaskIfPresent $name) }
    Write-Host "`nautostart removed. The folder itself is untouched."
    return
}

foreach ($name in $Tasks.Keys) {
    if (-not (Test-Path $Tasks[$name].Exe)) {
        Write-Error "missing $($Tasks[$name].Exe)`nRun bootstrap.ps1 first."
    }
}

$trigger   = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
                                        -LogonType Interactive -RunLevel Highest
# These are daemons, not jobs that finish, so no execution time limit.
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
                                          -DontStopIfGoingOnBatteries `
                                          -StartWhenAvailable `
                                          -ExecutionTimeLimit ([TimeSpan]::Zero) `
                                          -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

foreach ($name in $Tasks.Keys) {
    $t = $Tasks[$name]
    [void](Remove-TaskIfPresent $name)
    $action = if ($t.Args) {
        New-ScheduledTaskAction -Execute $t.Exe -Argument $t.Args -WorkingDirectory $Root
    } else {
        New-ScheduledTaskAction -Execute $t.Exe -WorkingDirectory (Split-Path $t.Exe)
    }
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
                           -Principal $principal -Settings $settings -Description $t.Desc | Out-Null
    Write-Host "registered '$name'"
}

if (-not $NoStart) {
    Write-Host "`nstarting now..."
    # LHM first: hw-sentinel tolerates it being absent, but there is no reason to make
    # it spend its first seconds reporting a dead sensor source.
    foreach ($name in @("hw-sentinel-lhm", "hw-sentinel-rtss")) {
        Start-ScheduledTask -TaskName $name; Write-Host "  started $name"
    }
    Start-Sleep -Seconds 10
    Start-ScheduledTask -TaskName "hw-sentinel"; Write-Host "  started hw-sentinel"
}

Write-Host "`nDone. Verify with:  .\hw-sentinel.cmd doctor"
Write-Host "Remove with:        powershell -ExecutionPolicy Bypass -File uninstall.ps1"
