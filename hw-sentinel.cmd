@echo off
rem hw-sentinel launcher. Uses the private interpreter under runtime\python, never
rem whatever Python happens to be on PATH.
rem
rem   hw-sentinel.cmd doctor
rem   hw-sentinel.cmd discover --filter voltage
rem   hw-sentinel.cmd test --rule gpu_hotspot --seconds 10
rem   hw-sentinel.cmd run

setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%runtime\python\python.exe"

if not exist "%PY%" (
    echo hw-sentinel: no private runtime found.
    echo Run this first:  powershell -ExecutionPolicy Bypass -File "%ROOT%bootstrap.ps1"
    exit /b 1
)

rem In a source checkout config.toml sits beside this script, and pinning it keeps the
rem checkout isolated from an installed copy. An installed copy has no config.toml here
rem - only config.default.toml - so fall through and let hwsentinel find (or seed) the
rem user's config under %ProgramData%.
if exist "%ROOT%config.toml" (
    "%PY%" -m hwsentinel --config "%ROOT%config.toml" %*
) else (
    "%PY%" -m hwsentinel %*
)
