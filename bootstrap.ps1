<#
.SYNOPSIS
    Build hw-sentinel's private runtime inside this folder. Touches nothing else.

.DESCRIPTION
    Everything hw-sentinel needs lands under .\runtime\ :

        runtime\python\   embeddable CPython + tkinter (no registry, no PATH)
        runtime\lhm\      LibreHardwareMonitor, web server pre-enabled
        runtime\rtss\     RivaTuner Statistics Server, run portably

    No system Python, no winget package, no Program Files, no PATH entry. Deleting
    this folder removes the runtime completely.

    Downloads are fetched over HTTPS from their official upstreams and checked against
    the SHA-256 values pinned below; a mismatch aborts.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File bootstrap.ps1
    powershell -ExecutionPolicy Bypass -File bootstrap.ps1 -Force
#>
[CmdletBinding()]
param(
    [switch]$Force,
    # Where to take RTSS from when it is not already vendored. Defaults to a normal
    # install; on a clean machine, install RTSS once, run this, then uninstall it.
    [string]$RtssSource = "C:\Program Files (x86)\RivaTuner Statistics Server"
)

$ErrorActionPreference = "Stop"
$Root      = $PSScriptRoot
$Runtime   = Join-Path $Root "runtime"
$PyDir     = Join-Path $Runtime "python"
$LhmDir    = Join-Path $Runtime "lhm"
$RtssDir   = Join-Path $Runtime "rtss"
$Cache     = Join-Path $Runtime "_cache"
$PyVersion = "3.12.10"

# Pinned artifact hashes. Verified on 2026-07-26.
$Artifacts = @(
    @{ Name = "python-embed.zip"
       Url  = "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-embed-amd64.zip"
       Sha  = "4ACBED6DD1C744B0376E3B1CF57CE906F9DC9E95E68824584C8099A63025A3C3" },
    @{ Name = "tcltk.msi"
       Url  = "https://www.python.org/ftp/python/$PyVersion/amd64/tcltk.msi"
       Sha  = "55C96FFAD69B1C834AA52E11B9CE41637A178BA6AD6607E83956044834276E2A" },
    @{ Name = "LibreHardwareMonitor.zip"
       Url  = "https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/download/v0.9.6/LibreHardwareMonitor.zip"
       Sha  = "086D9F1B5A99E643EDC2CFAAAC16051685B551E4C5AC0B32A57C58C0E529C001" }
)

function Step($m) { Write-Host "`n== $m" -ForegroundColor Cyan }
function Info($m) { Write-Host "   $m" }

function Get-Artifact($a) {
    $dest = Join-Path $Cache $a.Name
    if (-not (Test-Path $dest)) {
        Info "downloading $($a.Name)"
        $old = $ProgressPreference; $ProgressPreference = "SilentlyContinue"
        try { Invoke-WebRequest $a.Url -OutFile $dest -TimeoutSec 600 -UseBasicParsing }
        finally { $ProgressPreference = $old }
    } else {
        Info "cached $($a.Name)"
    }
    $hash = (Get-FileHash $dest -Algorithm SHA256).Hash
    if ($a.Sha -and $a.Sha -ne $hash) {
        Remove-Item $dest -Force
        throw "$($a.Name) hash mismatch`n  expected $($a.Sha)`n  got      $hash"
    }
    if (-not $a.Sha) { Info "sha256 $hash  (record this in `$Artifacts to pin it)" }
    $dest
}

if ($Force -and (Test-Path $Runtime)) {
    Step "removing existing runtime"
    Remove-Item $Runtime -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $Cache | Out-Null

Step "fetching artifacts"
$files = @{}
foreach ($a in $Artifacts) { $files[$a.Name] = Get-Artifact $a }

# --- Python -------------------------------------------------------------------
Step "installing private Python $PyVersion"
if (Test-Path $PyDir) {
    Info "already present, skipping (use -Force to rebuild)"
} else {
    New-Item -ItemType Directory -Force -Path $PyDir | Out-Null
    Expand-Archive -LiteralPath $files["python-embed.zip"] -DestinationPath $PyDir -Force
    Info "extracted embeddable interpreter"

    # The embeddable build deliberately omits tkinter. Its files come from the
    # official tcltk component, extracted with an administrative install (/a), which
    # unpacks without registering the product anywhere.
    $tcl = Join-Path $Cache "tcltk"
    if (Test-Path $tcl) { Remove-Item $tcl -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $tcl | Out-Null
    $log = Join-Path $Cache "msiexec.log"
    $p = Start-Process msiexec.exe -Wait -PassThru -WindowStyle Hidden `
         -ArgumentList "/a", "`"$($files['tcltk.msi'])`"", "/qn", "TARGETDIR=`"$tcl`"", "/l*v", "`"$log`""
    if ($p.ExitCode -ne 0) { throw "msiexec /a failed with exit code $($p.ExitCode); see $log" }

    # The component lays out DLLs\, Lib\ and tcl\ mirroring a normal install. The
    # embeddable layout keeps extension modules beside python.exe instead of in DLLs\.
    foreach ($src in @(Get-ChildItem (Join-Path $tcl "DLLs") -File -ErrorAction SilentlyContinue)) {
        Copy-Item $src.FullName $PyDir -Force
    }
    foreach ($dir in @("Lib\tkinter", "tcl")) {
        $from = Join-Path $tcl $dir
        if (Test-Path $from) {
            $to = Join-Path $PyDir $dir
            New-Item -ItemType Directory -Force -Path (Split-Path $to) | Out-Null
            Copy-Item $from $to -Recurse -Force
        }
    }
    Info "added tkinter + tcl/tk"

    # The ._pth file is what makes an embeddable build isolated: it pins sys.path and
    # suppresses the user's PYTHONPATH and site-packages. Keep that, but add the two
    # directories our own code lives in.
    $pth = Get-ChildItem $PyDir -Filter "python*._pth" | Select-Object -First 1
    if (-not $pth) { throw "no ._pth file in the embeddable package" }
    $lines = @(Get-Content $pth.FullName)
    foreach ($add in @("Lib", "..\..")) {
        if ($lines -notcontains $add) { $lines += $add }
    }
    Set-Content $pth.FullName ($lines -join "`r`n") -Encoding ascii
    Info "pinned sys.path via $($pth.Name)"
}

# --- LibreHardwareMonitor ------------------------------------------------------
Step "installing LibreHardwareMonitor"
if (Test-Path (Join-Path $LhmDir "LibreHardwareMonitor.exe")) {
    Info "already present, skipping"
} else {
    New-Item -ItemType Directory -Force -Path $LhmDir | Out-Null
    Expand-Archive -LiteralPath $files["LibreHardwareMonitor.zip"] -DestinationPath $LhmDir -Force
    Info "extracted"
}

# Pre-seed its settings so the web server is on from the very first launch. LHM
# rewrites this file when it exits, so it is only safe to write while LHM is closed.
$lhmCfg = Join-Path $LhmDir "LibreHardwareMonitor.config"
if (-not (Test-Path $lhmCfg)) {
    @'
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <appSettings>
    <add key="runWebServerMenuItem" value="true" />
    <add key="listenerPort" value="8085" />
    <add key="startMinMenuItem" value="true" />
    <add key="minTrayMenuItem" value="true" />
    <add key="minCloseMenuItem" value="true" />
  </appSettings>
</configuration>
'@ | Set-Content $lhmCfg -Encoding utf8
    Info "seeded config (web server on :8085)"
} else {
    Info "config already present, left alone"
}

# --- RTSS ----------------------------------------------------------------------
Step "installing RTSS"
if (Test-Path (Join-Path $RtssDir "RTSS.exe")) {
    Info "already present, skipping"
} elseif (Test-Path (Join-Path $RtssSource "RTSS.exe")) {
    New-Item -ItemType Directory -Force -Path $RtssDir | Out-Null
    Copy-Item (Join-Path $RtssSource "*") $RtssDir -Recurse -Force
    Info "copied from $RtssSource"
    Info "RTSS runs portably from here; you can now uninstall the system copy."
} else {
    Write-Warning "RTSS not found at $RtssSource."
    Write-Warning "In-game alerts will be unavailable; everything else still works."
    Write-Warning "To add it: install RTSS once, re-run bootstrap, then uninstall the system copy."
}

# --- working config ---------------------------------------------------------------
Step "seeding config.toml"
$cfgWorking = Join-Path $Root "config.toml"
$cfgTemplate = Join-Path $Root "config.default.toml"
if (Test-Path $cfgWorking) {
    Info "already present, left alone"
} elseif (Test-Path $cfgTemplate) {
    Copy-Item $cfgTemplate $cfgWorking
    Info "copied from config.default.toml - check the [sensors] block against your"
    Info "hardware with:  .\hw-sentinel.cmd doctor"
} else {
    throw "missing $cfgTemplate"
}

# --- generated assets -------------------------------------------------------------
Step "generating alert sounds and tray icons"
$python = Join-Path $PyDir "python.exe"
# Check every asset, not just one: an existing checkout has the sounds but not the
# icons, and testing a single file would skip generation and leave the tray blank.
$assets = @("warn.wav", "critical.wav", "idle.ico", "alert.ico")
$missing = @($assets | Where-Object { -not (Test-Path (Join-Path $Root "assets\$_")) })
if ($missing.Count -eq 0) {
    Info "all present, skipping"
} else {
    Info "missing: $($missing -join ', ')"
    & $python (Join-Path $Root "generate_assets.py")
    if ($LASTEXITCODE -ne 0) { throw "generate_assets.py failed" }
}

# --- verify --------------------------------------------------------------------
Step "verifying"
& $python -c "import sys, tkinter, ctypes, winsound, urllib.request, tomllib; print('   python', sys.version.split()[0]); print('   tkinter', tkinter.TkVersion); print('   prefix', sys.prefix)"
if ($LASTEXITCODE -ne 0) { throw "the private Python failed its import check" }

Write-Host "`nruntime ready under $Runtime" -ForegroundColor Green
Write-Host "next:  .\hw-sentinel.cmd doctor"
