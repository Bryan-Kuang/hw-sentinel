<#
.SYNOPSIS
    Build dist\hw-sentinel-setup-<version>.exe.

.DESCRIPTION
    Stages the redistributable payload into dist\stage, then compiles the Inno Setup
    script against it.

    The staging step is deliberately an allow-list rather than "copy everything minus
    exclusions": the payload is published, and a stray file is either a privacy leak or
    a licence violation. RTSS in particular is proprietary freeware that we are not
    permitted to redistribute, so the build FAILS if it ever reaches the stage.

    Requires Inno Setup:  winget install JRSoftware.InnoSetup

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipCompile
)

$ErrorActionPreference = "Stop"
$Packaging = $PSScriptRoot
$Root      = Split-Path $Packaging -Parent
$Dist      = Join-Path $Root "dist"
$Stage     = Join-Path $Dist "stage"

function Step($m) { Write-Host "`n== $m" -ForegroundColor Cyan }
function Info($m) { Write-Host "   $m" }

# --- prerequisites -------------------------------------------------------------
Step "checking the runtime"
if (-not (Test-Path (Join-Path $Root "runtime\python\python.exe"))) {
    Info "runtime missing - running bootstrap.ps1"
    & (Join-Path $Root "bootstrap.ps1")
}
if (-not (Test-Path (Join-Path $Root "assets\warn.wav"))) {
    & (Join-Path $Root "runtime\python\python.exe") (Join-Path $Root "generate_assets.py")
}
$version = (Select-String -Path (Join-Path $Root "hwsentinel\__init__.py") -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
Info "version $version"

# --- stage ---------------------------------------------------------------------
Step "staging payload"
if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Stage | Out-Null

# Files
foreach ($f in @("config.default.toml", "hw-sentinel.cmd", "install.ps1",
                 "install-rtss.ps1", "README.md", "LICENSE", "INSTALL-MANIFEST.md")) {
    Copy-Item (Join-Path $Root $f) $Stage
}

# Our package, without build artefacts
$pkg = Join-Path $Stage "hwsentinel"
New-Item -ItemType Directory -Force -Path $pkg | Out-Null
Get-ChildItem (Join-Path $Root "hwsentinel") -Filter "*.py" -File | Copy-Item -Destination $pkg

# Alert sounds
$assets = Join-Path $Stage "assets"
New-Item -ItemType Directory -Force -Path $assets | Out-Null
Get-ChildItem (Join-Path $Root "assets") -Filter "*.wav" -File | Copy-Item -Destination $assets

# Redistributable dependencies ONLY. runtime\rtss is deliberately absent.
foreach ($d in @("python", "lhm")) {
    $src = Join-Path $Root "runtime\$d"
    $dst = Join-Path $Stage "runtime\$d"
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    Copy-Item "$src\*" $dst -Recurse -Force
}
Get-ChildItem $Stage -Recurse -Include "__pycache__" -Directory -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force

# --- licence guard -------------------------------------------------------------
Step "licence guard"
$forbidden = @(Get-ChildItem $Stage -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '^(RTSS|RTSSHooks|EncoderServer)' -or $_.FullName -match '\\rtss\\' })
if ($forbidden) {
    $forbidden | ForEach-Object { Write-Host "   $($_.FullName)" -ForegroundColor Red }
    throw "RTSS files reached the staging tree. It is proprietary freeware and MUST NOT be redistributed."
}
Info "no RTSS files in the payload - correct"

# LibreHardwareMonitor's release zip ships no licence text, but MPL-2.0 requires it to
# travel with the binaries. Fetch it from the project's own repository and cache it.
$lhmLicence = Join-Path $Stage "runtime\lhm\LICENSE"
if (-not (Test-Path $lhmLicence)) {
    $cached = Join-Path $Root "runtime\_cache\LibreHardwareMonitor-LICENSE"
    if (-not (Test-Path $cached)) {
        Info "fetching the LibreHardwareMonitor licence (MPL-2.0)"
        Invoke-WebRequest "https://raw.githubusercontent.com/LibreHardwareMonitor/LibreHardwareMonitor/master/LICENSE" `
            -OutFile $cached -TimeoutSec 120 -UseBasicParsing
    }
    Copy-Item $cached $lhmLicence
}

$missingLicences = @()
foreach ($probe in @(@{ Dir = "runtime\python"; Pattern = "LICENSE*" },
                     @{ Dir = "runtime\lhm";    Pattern = "LICENSE*" })) {
    if (-not (Get-ChildItem (Join-Path $Stage $probe.Dir) -Filter $probe.Pattern -ErrorAction SilentlyContinue)) {
        $missingLicences += $probe.Dir
    }
}
if ($missingLicences) { throw "no licence file for: $($missingLicences -join ', ') - cannot ship without it" }
Info "third-party licences present"

@"
# Third-party components bundled with hw-sentinel

hw-sentinel itself is MIT licensed; see LICENSE.

## CPython (runtime\python)
Python Software Foundation License. https://www.python.org/
Unmodified redistribution of the official embeddable build plus the official
tcl/tk component.

## LibreHardwareMonitor (runtime\lhm)
Mozilla Public License 2.0. Unmodified.
Source: https://github.com/LibreHardwareMonitor/LibreHardwareMonitor

## RivaTuner Statistics Server - NOT BUNDLED
Proprietary freeware, redistribution not permitted. Downloaded from its official
mirror at install time, only with the user's explicit consent, and installed by its
own installer. https://www.guru3d.com/
"@ | Set-Content (Join-Path $Stage "THIRD-PARTY-NOTICES.md") -Encoding utf8

$size = [math]::Round((Get-ChildItem $Stage -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
Info "staged $size MB"

# --- compile -------------------------------------------------------------------
if ($SkipCompile) { Write-Host "`nstage only (-SkipCompile)"; return }

Step "compiling installer"
# winget may install Inno per-machine or per-user depending on the installer it picks,
# so check both rather than assuming Program Files.
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
          (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
         ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) {
    throw "ISCC.exe not found. Install Inno Setup:  winget install JRSoftware.InnoSetup"
}

& $iscc "/DAppVersion=$version" (Join-Path $Packaging "hw-sentinel.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC failed with exit code $LASTEXITCODE" }

$out = Join-Path $Dist "hw-sentinel-setup-$version.exe"
if (Test-Path $out) {
    $mb = [math]::Round((Get-Item $out).Length / 1MB, 1)
    Write-Host "`nbuilt $out ($mb MB)" -ForegroundColor Green
    Write-Host "sha256 $((Get-FileHash $out -Algorithm SHA256).Hash)"
} else {
    throw "ISCC reported success but $out is missing"
}
