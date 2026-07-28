<#
.SYNOPSIS
    Install RivaTuner Statistics Server from a downloaded Guru3D archive.

.DESCRIPTION
    Called by the hw-sentinel installer, only after the user has explicitly consented
    on the setup page that names the download URL.

    RTSS is proprietary freeware and cannot be redistributed, so it is fetched from its
    official mirror at install time. Its own installer is run VISIBLY rather than
    silently: it is a separate product with its own licence, and the user should see
    what is being installed on their machine and be able to cancel it.

    Exit codes: 0 installed / already present, 2 archive unusable, 3 the RTSS installer
    failed or was cancelled. The caller opens the official download page on any failure
    rather than retrying blindly.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install-rtss.ps1 -ZipPath C:\Temp\rtss.zip
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ZipPath,
    [string]$WorkDir
)

$ErrorActionPreference = "Continue"
if (-not $WorkDir) { $WorkDir = Join-Path ([System.IO.Path]::GetTempPath()) "hw-sentinel-rtss" }

function Find-Rtss {
    foreach ($p in @("${env:ProgramFiles(x86)}\RivaTuner Statistics Server\RTSS.exe",
                     "$env:ProgramFiles\RivaTuner Statistics Server\RTSS.exe")) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

$existing = Find-Rtss
if ($existing) {
    Write-Host "RTSS is already installed at $existing"
    exit 0
}

if (-not (Test-Path $ZipPath)) {
    Write-Host "archive not found: $ZipPath"
    exit 2
}

if (Test-Path $WorkDir) { Remove-Item $WorkDir -Recurse -Force -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

try {
    Expand-Archive -LiteralPath $ZipPath -DestinationPath $WorkDir -Force -ErrorAction Stop
} catch {
    Write-Host "could not extract the archive: $($_.Exception.Message)"
    exit 2
}

# Guru3D archives have contained the setup at the root and one level down over time,
# so search rather than assuming a layout.
$setup = Get-ChildItem $WorkDir -Recurse -Filter "*.exe" -ErrorAction SilentlyContinue |
         Sort-Object Length -Descending | Select-Object -First 1
if (-not $setup) {
    Write-Host "no installer executable inside the archive"
    exit 2
}

Write-Host "running $($setup.Name) - accept its prompts to finish installing RTSS"
try {
    $p = Start-Process -FilePath $setup.FullName -Wait -PassThru -ErrorAction Stop
} catch {
    Write-Host "could not start the RTSS installer: $($_.Exception.Message)"
    exit 3
}

# Trust the outcome on disk rather than the exit code: this installer reports 0 in
# cases where nothing was actually installed.
$installed = Find-Rtss
if ($installed) {
    Write-Host "RTSS installed at $installed"
    exit 0
}

Write-Host "the RTSS installer exited with code $($p.ExitCode) but RTSS is not present"
exit 3
