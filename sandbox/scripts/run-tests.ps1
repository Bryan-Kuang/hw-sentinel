<#
    Installer test suite. Runs INSIDE Windows Sandbox, never on a real machine.

    The sandbox logs in as an administrator, so nothing here prompts for elevation
    and the whole run is unattended. Results are written to the one writable mapped
    folder so they can be read back on the host.

    What this can prove: files land in the right place, the scheduled task is
    registered against the right target, settings are seeded and survive an upgrade,
    uninstall removes everything, and a relocation cleans up after itself.

    What it cannot prove: anything involving real hardware. There are no sensors, no
    GPU and no games in here, so LibreHardwareMonitor will find nothing and `doctor`
    is expected to report failures for every sensor rule. That is not a bug in the
    installer, and the suite does not treat it as one.
#>
[CmdletBinding()]
param(
    [switch]$KeepOpen   # leave the sandbox running afterwards instead of shutting down
)

$ErrorActionPreference = "Continue"
$Results = "C:\sandbox\results"
$Report  = Join-Path $Results ("report-{0}.txt" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
$Setup   = Get-ChildItem "C:\sandbox\dist" -Filter "hw-sentinel-setup-*.exe" |
           Sort-Object LastWriteTime | Select-Object -Last 1

$App   = "C:\Program Files\hw-sentinel"
$Data  = "C:\ProgramData\hw-sentinel"
$Flags = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")

$pass = 0; $fail = 0

function Log($m) { $m | Add-Content $Report -Encoding utf8; Write-Host $m }
function Check($name, $ok, $detail = "") {
    if ($ok) { $script:pass++; Log ("  PASS  {0}" -f $name) }
    else     { $script:fail++; Log ("  FAIL  {0}{1}" -f $name, $(if ($detail) { " -- $detail" } else { "" })) }
}
function Section($t) { Log ""; Log "== $t" }
function TaskTarget {
    $t = Get-ScheduledTask -TaskName 'hw-sentinel' -ErrorAction SilentlyContinue
    if ($t) { $t.Actions.Execute } else { "" }
}
function ArpEntry {
    Get-ItemProperty HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*, `
                     HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\* `
                     -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -match 'hw-sentinel' }
}
function RunSetup($extra = @()) {
    (Start-Process $Setup.FullName -ArgumentList ($Flags + $extra) -Wait -PassThru).ExitCode
}

New-Item -ItemType Directory -Force -Path $Results | Out-Null
Log "hw-sentinel installer tests"
Log "started : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Log "installer: $($Setup.Name)"
Log "sha256   : $((Get-FileHash $Setup.FullName -Algorithm SHA256).Hash)"
Log ("windows  : {0}" -f (Get-CimInstance Win32_OperatingSystem).Caption)

# --- 1. a genuinely first-time install ----------------------------------------
Section "1. First-time install (never possible on the dev machine)"
$code = RunSetup
Check "installer exits 0" ($code -eq 0) "exit $code"
Start-Sleep -Seconds 8
Check "program files created"      (Test-Path "$App\hwsentinel\__main__.py")
Check "private python bundled"     (Test-Path "$App\runtime\python\pythonw.exe")
Check "LHM bundled"                (Test-Path "$App\runtime\lhm\LibreHardwareMonitor.exe")
Check "LHM licence shipped"        (Test-Path "$App\runtime\lhm\LICENSE")
Check "RTSS NOT bundled"           (-not (Test-Path "$App\runtime\rtss"))
Check "settings seeded"            (Test-Path "$Data\config.toml")
Check "one scheduled task"         ((@(Get-ScheduledTask -TaskName 'hw-sentinel*' -ErrorAction SilentlyContinue)).Count -eq 1)
Check "task points at install dir" ((TaskTarget) -like "$App\*") (TaskTarget)
Check "appears in Add/Remove"      ([bool](ArpEntry))

# --- 2. settings are the user's ------------------------------------------------
Section "2. Settings belong to the user"
$marker = "# SANDBOX-EDIT-MARKER"
Add-Content "$Data\config.toml" "`r`n$marker"
$code = RunSetup
Start-Sleep -Seconds 8
Check "upgrade exits 0"            ($code -eq 0) "exit $code"
Check "edited settings survive"    (Select-String -Path "$Data\config.toml" -Pattern $marker -SimpleMatch -Quiet)
Check "still one task"             ((@(Get-ScheduledTask -TaskName 'hw-sentinel*' -ErrorAction SilentlyContinue)).Count -eq 1)

# --- 3. doctor runs (sensors are expected to fail in here) ---------------------
Section "3. doctor runs without crashing"
$doctor = & "$App\hw-sentinel.cmd" doctor 2>&1 | Out-String
Check "doctor produced output"     ($doctor.Length -gt 200)
Check "doctor reports its paths"   ($doctor -match [regex]::Escape($Data))
Log "  note: sensor rules are expected to FAIL here - no real hardware in a sandbox"

# --- 4. relocating the install -------------------------------------------------
Section "4. Install elsewhere, old folder cleaned up"
$moved = "C:\Apps\hw-sentinel"
$code = RunSetup @("/DIR=`"$moved`"")
Start-Sleep -Seconds 10
Check "relocate exits 0"           ($code -eq 0) "exit $code"
Check "new location populated"     (Test-Path "$moved\hwsentinel\__main__.py")
Check "old folder removed"         (-not (Test-Path $App))
Check "task retargeted"            ((TaskTarget) -like "$moved\*") (TaskTarget)
Check "settings still intact"      (Select-String -Path "$Data\config.toml" -Pattern $marker -SimpleMatch -Quiet)

# --- 5. uninstall ---------------------------------------------------------------
Section "5. Uninstall leaves nothing behind"
$unins = Join-Path $moved "unins000.exe"
if (Test-Path $unins) {
    $code = (Start-Process $unins -ArgumentList $Flags -Wait -PassThru).ExitCode
    Start-Sleep -Seconds 8
    Check "uninstaller exits 0"    ($code -eq 0) "exit $code"
    Check "program folder gone"    (-not (Test-Path $moved))
    Check "task removed"           ([string]::IsNullOrEmpty((TaskTarget)))
    Check "Add/Remove entry gone"  (-not [bool](ArpEntry))
    Check "settings kept by default" (Test-Path "$Data\config.toml")
} else {
    Check "uninstaller present"    $false "no unins000.exe at $moved"
}

# --- summary ---------------------------------------------------------------------
Log ""
Log "=================================="
Log " PASS $pass    FAIL $fail"
Log "=================================="
Log "finished: $(Get-Date -Format 'HH:mm:ss')"
"DONE" | Add-Content $Report -Encoding utf8

if (-not $KeepOpen) {
    Start-Sleep -Seconds 3
    shutdown.exe /s /t 0    # closing the sandbox destroys it, which is the point
}
