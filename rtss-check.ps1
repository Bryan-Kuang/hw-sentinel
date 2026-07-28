<#
.SYNOPSIS
    Work out whether RivaTuner Statistics Server would be left orphaned.

.DESCRIPTION
    Run during uninstall. If hw-sentinel's setup was the thing that installed RTSS, and
    nothing else on the machine appears to use it, the user would otherwise be left with
    a program they never chose and will never use.

    This only reports. Removing RTSS is always the user's decision - it is a separate
    product, and guessing wrong in either direction is worse than asking.

    Exit codes:
      0  RTSS present, we installed it, no other user found -> suggest removing
      1  RTSS present, something else appears to use it     -> suggest keeping
      2  RTSS present, but we did not install it            -> suggest keeping
      3  RTSS not installed                                 -> nothing to do

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File rtss-check.ps1 -ReportPath C:\Temp\r.txt
#>
[CmdletBinding()]
param(
    [string]$ReportPath,
    [string]$DataDir = "$env:ProgramData\hw-sentinel",
    # Override where RTSS lives. Normally discovered; explicit for testing, and useful
    # if RTSS was installed somewhere unusual.
    [string]$RtssDir
)

$ErrorActionPreference = "Continue"
$lines = @()
function Add-Line($m) { $script:lines += $m }

function Get-RtssFromRegistry {
    # RTSS's own installer lets the user choose any folder, so the default Program Files
    # paths are a guess. Its Add/Remove Programs entry records where it actually went.
    $keys = Get-ItemProperty HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*, `
                             HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\* `
                             -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -match 'RivaTuner Statistics Server' }
    foreach ($k in $keys) {
        $dir = $k.InstallLocation
        if (-not $dir -and $k.UninstallString) {
            # Fall back to the folder holding the uninstaller.
            $dir = Split-Path ($k.UninstallString -replace '^"|"$', '') -Parent
        }
        if ($dir -and (Test-Path (Join-Path $dir "RTSS.exe"))) { return (Join-Path $dir "RTSS.exe") }
    }
    return $null
}

function Find-Rtss {
    if ($RtssDir) {
        $p = Join-Path $RtssDir "RTSS.exe"
        return $(if (Test-Path $p) { $p } else { $null })
    }
    $fromReg = Get-RtssFromRegistry
    if ($fromReg) { return $fromReg }
    foreach ($p in @("${env:ProgramFiles(x86)}\RivaTuner Statistics Server\RTSS.exe",
                     "$env:ProgramFiles\RivaTuner Statistics Server\RTSS.exe")) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

$rtss = Find-Rtss
if (-not $rtss) {
    Add-Line "RivaTuner Statistics Server is not installed. Nothing to clean up."
    $code = 3
} else {
    $rtssDir = Split-Path $rtss
    Add-Line "RivaTuner Statistics Server is installed at:"
    Add-Line "    $rtssDir"
    Add-Line ""

    # Did our setup put it there? Recorded when the consent page was accepted.
    $weInstalledIt = Test-Path (Join-Path $DataDir ".rtss-installed-by-setup")

    # Other things that commonly drive the RTSS overlay.
    $others = @()
    $arp = Get-ItemProperty HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*, `
                            HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\* `
                            -ErrorAction SilentlyContinue
    foreach ($known in @(@{ Match = 'Afterburner';  Name = 'MSI Afterburner' },
                         @{ Match = 'CapFrameX';    Name = 'CapFrameX' },
                         @{ Match = 'HWiNFO';       Name = 'HWiNFO' },
                         @{ Match = 'Precision X';  Name = 'EVGA Precision X' })) {
        if ($arp | Where-Object { $_.DisplayName -match $known.Match }) { $others += $known.Name }
    }

    # Per-game profiles the user configured by hand. RTSS ships a "Global" profile, so
    # anything beyond that means somebody set it up for specific games.
    $profiles = @(Get-ChildItem (Join-Path $rtssDir "Profiles") -File -ErrorAction SilentlyContinue |
                  Where-Object { $_.BaseName -ne 'Global' })
    if ($profiles.Count -gt 0) { $others += "$($profiles.Count) per-game profile(s) you configured" }

    if ($others.Count -gt 0) {
        Add-Line "Other things on this PC appear to use it:"
        $others | ForEach-Object { Add-Line "    - $_" }
        Add-Line ""
        Add-Line "RECOMMENDATION: keep it. Removing it would affect the above."
        $code = 1
    } elseif (-not $weInstalledIt) {
        Add-Line "It was already on this PC before hw-sentinel was installed, and was not"
        Add-Line "installed by our setup."
        Add-Line ""
        Add-Line "RECOMMENDATION: keep it. It is not ours to remove."
        $code = 2
    } else {
        Add-Line "It was installed by hw-sentinel's setup, and nothing else on this PC"
        Add-Line "appears to use it:"
        Add-Line "    - no MSI Afterburner, CapFrameX, HWiNFO or Precision X"
        Add-Line "    - no per-game profiles were configured"
        Add-Line ""
        Add-Line "RECOMMENDATION: you can remove it. Otherwise it stays on your PC"
        Add-Line "unused."
        $code = 0
    }
}

$text = $lines -join "`r`n"
# ASCII deliberately: the installer reads this into a message box as an AnsiString, so a
# UTF-8 BOM would show up as stray characters at the top of the dialog.
if ($ReportPath) { Set-Content -LiteralPath $ReportPath -Value $text -Encoding ascii }
Write-Host $text
exit $code
