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
; Registers the task AND starts it. Starting matters most on an upgrade: re-registering
; the task terminates the running monitor, so without this an upgrade would silently
; leave monitoring switched off until the next logon.
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install.ps1"" -InstallDir ""{app}"" -Silent"; \
    StatusMsg: "Registering hw-sentinel to start at logon..."; Flags: runhidden waituntilterminated
Filename: "{app}\hw-sentinel.cmd"; Parameters: "doctor"; \
    Description: "Check that hw-sentinel can read your sensors"; \
    Flags: postinstall shellexec skipifsilent unchecked

[UninstallRun]
; Must run before the files disappear: it stops the task and the monitor, which would
; otherwise keep its own files open.
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install.ps1"" -Uninstall -Silent -InstallDir ""{app}"""; \
    Flags: runhidden waituntilterminated; RunOnceId: "RemoveTask"
; The sweep of run-time generated files now lives inside install.ps1 -Uninstall above,
; where it can be scoped to our own subfolders and skipped entirely if the install
; directory turns out not to contain this program.

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
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{8F3A1C42-5B7E-4D91-A6C3-2E9F7B4D8A15}_is1';

var
  RtssPage: TInputOptionWizardPage;
  DownloadPage: TDownloadWizardPage;
  RtssZip: String;

function ExistingInstall(var Path, Ver: String): Boolean;
begin
  { 64-bit view first: this installs in 64-bit mode, so that is where the key lands. }
  Result := RegQueryStringValue(HKLM64, UninstallKey, 'InstallLocation', Path) or
            RegQueryStringValue(HKLM, UninstallKey, 'InstallLocation', Path);
  if Result then
    if not RegQueryStringValue(HKLM64, UninstallKey, 'DisplayVersion', Ver) then
      RegQueryStringValue(HKLM, UninstallKey, 'DisplayVersion', Ver);
end;

function InitializeSetup(): Boolean;
var
  Path, Ver: String;
begin
  Result := True;
  if not ExistingInstall(Path, Ver) then
    Exit;
  { Silent runs are upgrades driven by a script or a package manager; prompting there
    would just hang them. }
  if WizardSilent() then
    Exit;
  if MsgBox('hw-sentinel ' + Ver + ' is already installed:' + #13#10 + #13#10 +
            '    ' + RemoveBackslash(Path) + #13#10 + #13#10 +
            'Install version {#AppVersion} over it?' + #13#10 + #13#10 +
            'Your thresholds and alert history are kept. Monitoring stops briefly and' + #13#10 +
            'restarts on its own when setup finishes.' + #13#10 + #13#10 +
            'Choose No to cancel and leave the current installation untouched.',
            mbConfirmation, MB_YESNO) = IDNO then
    Result := False;
end;

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
  Chosen: String;
begin
  Result := True;

  if CurPageID = wpSelectDir then
  begin
    { Always land in a folder of our own. Uninstall removes whole subtrees and stops
      processes by folder, so installing directly into something like D:\Tools - which
      may hold the user's own files - must not be possible. }
    Chosen := RemoveBackslash(WizardDirValue);
    if CompareText(ExtractFileName(Chosen), '{#AppName}') <> 0 then
      WizardForm.DirEdit.Text := AddBackslash(Chosen) + '{#AppName}';
  end;

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

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  Script: String;
begin
  Result := '';
  // Runs before a single file is copied. On an upgrade the previous monitor is still
  // running out of the install folder and holding its interpreter DLL open, which would
  // otherwise make Inno either fail the copy or defer it to a reboot. Stopping it here
  // means an upgrade replaces everything cleanly; the Run section then restarts it.
  // (Line comments, not braces: a brace comment ends at the first closing brace, so an
  // Inno constant written inside one would terminate it early.)
  Script := ExpandConstant('{app}\install.ps1');
  if FileExists(Script) then
    Exec('powershell.exe',
      '-NoProfile -ExecutionPolicy Bypass -File "' + Script + '" -Uninstall -Silent -InstallDir "' +
      ExpandConstant('{app}') + '"',
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if (CurStep = ssPostInstall) and (RtssZip <> '') then
  begin
    { Runs the vendor's installer visibly - see install-rtss.ps1 for why. }
    if Exec('powershell.exe',
        '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\install-rtss.ps1') +
        '" -ZipPath "' + RtssZip + '"',
        '', SW_SHOW, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0) then
    begin
      { Remember that WE put RTSS on this machine. Without this the uninstaller cannot
        tell an RTSS the user chose from one they only have because of us, and would
        have to leave every copy behind. }
      SaveStringToFile(ExpandConstant('{#DataDir}\.rtss-installed-by-setup'),
                       'Installed by hw-sentinel {#AppVersion} setup.' + #13#10, False);
    end
    else
    begin
      if MsgBox('RivaTuner Statistics Server was not installed, so in-game alerts will' + #13#10 +
                'not be available. Everything else works normally.' + #13#10 + #13#10 +
                'Open its download page so you can install it yourself?',
                mbInformation, MB_YESNO) = IDYES then
        ShellExecAsOriginalUser('open', '{#RtssPageUrl}', '', '', SW_SHOW, ewNoWait, ResultCode);
    end;
  end;
end;

procedure OfferRtssRemoval();
var
  Script, Report, Uninst: String;
  Text: AnsiString;   { LoadStringFromFile requires AnsiString, not String }
  ResultCode: Integer;
begin
  { Runs while our files still exist, so the checker is still on disk. }
  Script := ExpandConstant('{app}\rtss-check.ps1');
  Report := ExpandConstant('{tmp}\rtss-report.txt');
  if not FileExists(Script) then
    Exit;

  if not Exec('powershell.exe',
      '-NoProfile -ExecutionPolicy Bypass -File "' + Script + '" -ReportPath "' + Report + '"',
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Exit;

  { 0 means: we installed RTSS and nothing else appears to use it. Every other code
    means leave it alone, so there is nothing worth troubling the user about. }
  if ResultCode <> 0 then
    Exit;
  if not LoadStringFromFile(Report, Text) then
    Exit;

  if MsgBox(String(Text) + #13#10 + #13#10 +
            'Remove RivaTuner Statistics Server as well?' + #13#10 + #13#10 +
            'Choose No to keep it - you can always remove it yourself later from' + #13#10 +
            'Settings > Apps.',
            mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
  begin
    Uninst := ExpandConstant('{commonpf32}\RivaTuner Statistics Server\Uninstall.exe');
    if not FileExists(Uninst) then
      Uninst := ExpandConstant('{commonpf}\RivaTuner Statistics Server\Uninstall.exe');
    if FileExists(Uninst) then
      { /S is an NSIS silent uninstall. Without it this opens a language dialog that
        looks exactly like an installer, which is alarming mid-uninstall. It may also
        ask for a reboot to finish, because its hook DLL can still be loaded. }
      Exec(Uninst, '/S', '', SW_SHOW, ewWaitUntilTerminated, ResultCode);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataPath: String;
begin
  if CurUninstallStep = usUninstall then
    OfferRtssRemoval();

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
    { RTSS was handled during usUninstall by OfferRtssRemoval, while our files - and so
      the checker script - still existed. It is only ever offered, never removed
      silently: it is a separate product and the choice belongs to the user. }
  end;
end;
