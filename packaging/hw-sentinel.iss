; hw-sentinel installer (Inno Setup 6)
;
; Build with packaging\build.ps1 — it stages the payload into dist\stage first.
;
; Two things shape this script:
;   * Program files and user data are separate. {app} is read-only for ordinary
;     users, so the editable config and the event log live in {commonappdata}.
;   * RTSS cannot be redistributed. It is downloaded only with explicit consent,
;     from a page that names the URL, and its own installer runs visibly.

#define AppName      "hw-sentinel"
#define AppVersion   "1.1.0"
#define AppPublisher "the hw-sentinel contributors"
#define AppURL       "https://github.com/Bryan-Kuang/hw-sentinel"
#define DataDir      "{commonappdata}\hw-sentinel"

; Guru3D mirror. If this rots, setup falls back to opening the download page.
#define RtssZipUrl   "https://ftp.nluug.nl/pub/games/PC/guru3d/afterburner/%5BGuru3D%5D-RTSSSetup737Build28314.zip"
#define RtssPageUrl  "https://www.guru3d.com/download/rtss-rivatuner-statistics-server-download/"

[Setup]
AppId={{8F3A1C42-5B7E-4D91-A6C3-2E9F7B4D8A15}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename={#AppName}-setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Registering the scheduled task and writing to Program Files both need admin.
PrivilegesRequired=admin
; The bundled CPython is amd64.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName} {#AppVersion}
UninstallDisplayIcon={app}\runtime\lhm\LibreHardwareMonitor.exe
DisableProgramGroupPage=yes
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Dirs]
; The user must be able to edit thresholds and the app must be able to append to the
; log, so grant modify rather than relying on whatever ProgramData inherits.
Name: "{#DataDir}"; Permissions: users-modify

[Files]
Source: "..\dist\stage\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; Seed the user's config once. onlyifdoesntexist is what makes an upgrade preserve
; edited thresholds; uninsneveruninstall leaves it for the uninstaller to ask about.
Source: "..\dist\stage\config.default.toml"; DestDir: "{#DataDir}"; DestName: "config.toml"; \
    Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{group}\Check hw-sentinel setup"; Filename: "{app}\hw-sentinel.cmd"; Parameters: "doctor"; \
    Comment: "Verify sensors, dependencies and alert output"
Name: "{group}\Edit alert thresholds"; Filename: "notepad.exe"; Parameters: """{#DataDir}\config.toml"""; \
    Comment: "Open your configuration"
Name: "{group}\List all sensors"; Filename: "{app}\hw-sentinel.cmd"; Parameters: "discover"; \
    Comment: "Show every sensor your hardware exposes"
Name: "{group}\Documentation"; Filename: "{app}\README.md"

[Run]
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install.ps1"" -InstallDir ""{app}"" -Silent -NoStart"; \
    StatusMsg: "Registering hw-sentinel to start at logon..."; Flags: runhidden waituntilterminated
Filename: "{app}\hw-sentinel.cmd"; Parameters: "doctor"; \
    Description: "Check that hw-sentinel can read your sensors"; \
    Flags: postinstall shellexec skipifsilent
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Start-ScheduledTask -TaskName 'hw-sentinel'"""; \
    Description: "Start monitoring now"; Flags: postinstall runhidden skipifsilent

[UninstallRun]
; Must run before the files disappear: it stops the task and the monitor, which would
; otherwise keep its own files open.
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install.ps1"" -Uninstall -Silent -InstallDir ""{app}"""; \
    Flags: runhidden waituntilterminated; RunOnceId: "RemoveTask"
; Python writes bytecode caches and LibreHardwareMonitor rewrites its settings on exit.
; None of it is tracked by the installer, so without this sweep the install directory
; survives an uninstall.
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Get-ChildItem -LiteralPath '{app}' -Recurse -Directory -Filter __pycache__ -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue; Remove-Item -LiteralPath '{app}\runtime\lhm\LibreHardwareMonitor.config' -Force -ErrorAction SilentlyContinue"""; \
    Flags: runhidden waituntilterminated; RunOnceId: "SweepGenerated"

[UninstallDelete]
; These two trees are entirely ours and contain nothing a user would author, so remove
; them outright. Enumerating leftovers individually does not work: anything generated
; at run time (bytecode caches, rewritten settings) blocks the directory removal and
; leaves the whole branch behind. {app} itself is only removed if empty, in case
; someone installed into a shared folder.
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\hwsentinel"
Type: dirifempty; Name: "{app}\assets"
Type: dirifempty; Name: "{app}"

[Code]
var
  RtssPage: TInputOptionWizardPage;
  DownloadPage: TDownloadWizardPage;
  RtssZip: String;

function RtssInstalled(): Boolean;
begin
  Result := FileExists(ExpandConstant('{commonpf32}\RivaTuner Statistics Server\RTSS.exe')) or
            FileExists(ExpandConstant('{commonpf}\RivaTuner Statistics Server\RTSS.exe'));
end;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  Result := True;
end;

procedure InitializeWizard();
begin
  RtssPage := CreateInputOptionPage(wpSelectDir,
    'In-game alerts (optional)',
    'hw-sentinel can show alerts inside full-screen games, but needs one extra program.',
    'Inside a full-screen game, no ordinary window can be drawn on top. RivaTuner' + #13#10 +
    'Statistics Server (RTSS) solves that, and hw-sentinel sends its alert text to it.' + #13#10 + #13#10 +
    'RTSS is free, but it belongs to someone else and its licence does not let us' + #13#10 +
    'include it. Setup can download it from the official mirror:' + #13#10 + #13#10 +
    '    ' + '{#RtssZipUrl}' + #13#10 + #13#10 +
    'Its own installer will then open so you can see exactly what is being installed.' + #13#10 + #13#10 +
    'If you skip this, everything else still works: the alert card on your desktop,' + #13#10 +
    'alerts in windowed games, and the alert sound - which you hear in full-screen' + #13#10 +
    'games too. You would only lose the on-screen text inside them.',
    False, False);
  RtssPage.Add('Download and install RivaTuner Statistics Server');
  RtssPage.Values[0] := False;

  DownloadPage := CreateDownloadPage(
    'Downloading RivaTuner Statistics Server',
    'Fetching it from the Guru3D mirror...', @OnDownloadProgress);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  { Nothing to ask if RTSS is already on the machine. }
  Result := (PageID = RtssPage.ID) and RtssInstalled();
end;

function WantsRtss(): Boolean;
begin
  Result := (not RtssInstalled()) and RtssPage.Values[0];
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  ErrorCode: Integer;
begin
  Result := True;
  if (CurPageID = RtssPage.ID) and WantsRtss() then
  begin
    DownloadPage.Clear;
    DownloadPage.Add('{#RtssZipUrl}', 'rtss.zip', '');
    DownloadPage.Show;
    try
      try
        DownloadPage.Download;
        RtssZip := ExpandConstant('{tmp}\rtss.zip');
      except
        { A dead mirror must not block installing hw-sentinel itself. }
        RtssZip := '';
        if MsgBox('The download failed:' + #13#10 + #13#10 + GetExceptionMessage + #13#10 + #13#10 +
                  'Open the official RTSS download page in your browser instead?' + #13#10 +
                  'Setup will carry on without in-game alerts either way.',
                  mbConfirmation, MB_YESNO) = IDYES then
          ShellExecAsOriginalUser('open', '{#RtssPageUrl}', '', '', SW_SHOW, ewNoWait, ErrorCode);
      end;
    finally
      DownloadPage.Hide;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if (CurStep = ssPostInstall) and (RtssZip <> '') then
  begin
    { Runs the vendor's installer visibly - see install-rtss.ps1 for why. }
    if not Exec('powershell.exe',
        '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\install-rtss.ps1') +
        '" -ZipPath "' + RtssZip + '"',
        '', SW_SHOW, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
    begin
      if MsgBox('RivaTuner Statistics Server was not installed, so in-game alerts will' + #13#10 +
                'not be available. Everything else works normally.' + #13#10 + #13#10 +
                'Open its download page so you can install it yourself?',
                mbInformation, MB_YESNO) = IDYES then
        ShellExecAsOriginalUser('open', '{#RtssPageUrl}', '', '', SW_SHOW, ewNoWait, ResultCode);
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataPath: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataPath := ExpandConstant('{#DataDir}');
    if DirExists(DataPath) then
    begin
      if MsgBox('Remove your saved thresholds and alert history?' + #13#10 + #13#10 +
                DataPath + #13#10 + #13#10 +
                'Choose No to keep them for a future reinstall.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataPath, True, True, True);
    end;
    { RTSS is a separate product with its own uninstaller, and the user may be using
      it for other things, so it is deliberately left alone. }
  end;
end;
