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
; Resolved in code so that a silent upgrade still lands on the existing installation
; rather than the default folder - UsePreviousAppDir is off, so Inno will not do it.
DefaultDirName={code:GetDefaultDir}
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
; Both off so the mode page below is in charge of the install location. Left at their
; defaults, Inno silently reuses the previous folder and hides the folder page, which
; removes any chance of choosing a new one.
UsePreviousAppDir=no
DisableDirPage=no

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
  ModePage: TInputOptionWizardPage;   { upgrade in place, or move elsewhere }
  PrevLocation: String;               { where the existing copy lives, '' if none }
  PrevVersion: String;

const
  ModeInPlace = 0;
  ModeRelocate = 1;

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
begin
  Result := True;
  if not ExistingInstall(PrevLocation, PrevVersion) then
  begin
    PrevLocation := '';
    PrevVersion := '';
  end;
end;

function GetDefaultDir(Param: String): String;
begin
  { An explicit /DIR= must win. A code-based DefaultDirName is evaluated in preference
    to it, so without this an operator asking for a specific folder is silently ignored
    and the install goes wherever the previous one was. }
  Result := ExpandConstant('{param:DIR|}');
  Log('GetDefaultDir: /DIR="' + Result + '"  PrevLocation="' + PrevLocation + '"');
  if Result <> '' then
  begin
    Log('GetDefaultDir -> using /DIR: ' + Result);
    Exit;
  end;
  { Otherwise default to where it already is, so a scripted upgrade does not relocate
    an install that lives somewhere non-default. }
  if PrevLocation <> '' then
    Result := RemoveBackslash(PrevLocation)
  else
    Result := ExpandConstant('{autopf}\{#AppName}');
  Log('GetDefaultDir -> ' + Result);
end;

{ -1 this build is older than what is installed, 0 same, 1 newer. }
function VersionDelta(): Integer;
var
  Installed, Building: Int64;
begin
  Result := 0;
  if StrToVersion(PrevVersion, Installed) and StrToVersion('{#AppVersion}', Building) then
    Result := ComparePackedVersion(Building, Installed);
end;

function Upgrading(): Boolean;
begin
  Result := (PrevLocation <> '');
end;

function RelocateChosen(): Boolean;
begin
  Result := Upgrading() and (ModePage.SelectedValueIndex = ModeRelocate);
end;

function RtssFromRegistry(RootView: Integer): String;
var
  Names: TArrayOfString;
  I: Integer;
  Base, Display, Location, Uninst: String;
begin
  Result := '';
  Base := 'Software\Microsoft\Windows\CurrentVersion\Uninstall';
  if not RegGetSubkeyNames(RootView, Base, Names) then
    Exit;
  for I := 0 to GetArrayLength(Names) - 1 do
  begin
    if not RegQueryStringValue(RootView, Base + '\' + Names[I], 'DisplayName', Display) then
      Continue;
    if Pos('RivaTuner Statistics Server', Display) = 0 then
      Continue;
    if not RegQueryStringValue(RootView, Base + '\' + Names[I], 'InstallLocation', Location) then
      Location := '';
    if Location = '' then
      if RegQueryStringValue(RootView, Base + '\' + Names[I], 'UninstallString', Uninst) then
        Location := ExtractFileDir(RemoveQuotes(Uninst));
    if (Location <> '') and FileExists(AddBackslash(Location) + 'RTSS.exe') then
    begin
      Result := AddBackslash(Location) + 'RTSS.exe';
      Exit;
    end;
  end;
end;

function RtssInstalled(): Boolean;
begin
  { RTSS's installer lets the user choose any folder, so its Add/Remove Programs entry
    is the only reliable answer. Probing the default paths alone would keep offering to
    install a copy the user already has somewhere else. }
  Result := (RtssFromRegistry(HKLM32) <> '') or
            (RtssFromRegistry(HKLM64) <> '') or
            FileExists(ExpandConstant('{commonpf32}\RivaTuner Statistics Server\RTSS.exe')) or
            FileExists(ExpandConstant('{commonpf}\RivaTuner Statistics Server\RTSS.exe'));
end;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  Result := True;
end;

procedure InitializeWizard();
var
  Headline, InPlaceLabel: String;
  Delta: Integer;
begin
  if Upgrading() then
  begin
    Delta := VersionDelta();
    if Delta > 0 then
    begin
      Headline := 'Version ' + PrevVersion + ' is already installed. This is version {#AppVersion}.';
      InPlaceLabel := 'Upgrade it where it is  (recommended)';
    end
    else if Delta = 0 then
    begin
      Headline := 'Version {#AppVersion} is already installed - the same version as this one.';
      InPlaceLabel := 'Repair it where it is  (recommended)';
    end
    else
    begin
      Headline := 'Version ' + PrevVersion + ' is installed, which is NEWER than this one ({#AppVersion}).';
      InPlaceLabel := 'Go back to version {#AppVersion} where it is';
    end;

    { Radio buttons, not checkboxes: these are mutually exclusive. }
    ModePage := CreateInputOptionPage(wpWelcome,
      'hw-sentinel is already installed',
      Headline,
      'Currently installed in:' + #13#10 + #13#10 +
      '    ' + RemoveBackslash(PrevLocation) + #13#10 + #13#10 +
      'Your alert thresholds and history are kept either way - they are stored' + #13#10 +
      'separately from the program.' + #13#10 + #13#10 +
      'To leave the current installation completely untouched, press Cancel.',
      True, False);
    ModePage.Add(InPlaceLabel);
    ModePage.Add('Install to a different folder, and delete the old one afterwards');
    ModePage.SelectedValueIndex := ModeInPlace;
  end;

  Log('InitializeWizard: WizardDirValue="' + WizardDirValue + '"');

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
  Result := False;
  { Nothing to ask if RTSS is already on the machine. }
  if PageID = RtssPage.ID then
    Result := RtssInstalled();
  { Upgrading in place: the folder is already decided, so asking would only invite
    accidentally splitting the install across two locations. }
  if PageID = wpSelectDir then
    Result := Upgrading() and (not RelocateChosen());
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

  { Only ever widen the choice, never narrow it. Setting the directory for the in-place
    case used to live here too, which was both redundant - GetDefaultDir already returns
    it - and actively wrong: a silent install still walks the page flow and calls this,
    so it silently overwrote an explicit /DIR= and the install went nowhere near where
    it was asked to go. }
  if (ModePage <> nil) and (CurPageID = ModePage.ID) and RelocateChosen()
     and (ExpandConstant('{param:DIR|}') = '') then
    { They asked to move, so offer the default location rather than the old one. }
    WizardForm.DirEdit.Text := ExpandConstant('{autopf}\{#AppName}');

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
  Log('PrepareToInstall: WizardDirValue="' + WizardDirValue + '"  {app}="' +
      ExpandConstant('{app}') + '"');
  // Runs before a single file is copied. On an upgrade the previous monitor is still
  // running out of the install folder and holding its interpreter DLL open, which would
  // otherwise make Inno either fail the copy or defer it to a reboot. Stopping it here
  // means an upgrade replaces everything cleanly; the Run section then restarts it.
  // (Line comments, not braces: a brace comment ends at the first closing brace, so an
  // Inno constant written inside one would terminate it early.)
  Script := ExpandConstant('{app}\install.ps1');
  if FileExists(Script) then
    { -StopOnly, not -Uninstall: the scheduled task is re-registered later anyway, and
      tearing it down here would leave the machine with no autostart if setup failed
      partway through. }
    Exec('powershell.exe',
      '-NoProfile -ExecutionPolicy Bypass -File "' + Script + '" -StopOnly -Silent -InstallDir "' +
      ExpandConstant('{app}') + '"',
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure RemoveOldInstall();
var
  OldDir, NewDir, Script: String;
  ResultCode: Integer;
begin
  { Triggered by the mode page, and also by /DIR= on a scripted upgrade - in both cases
    the program has moved and the old copy is dead weight. }
  if not Upgrading() then
    Exit;
  OldDir := RemoveBackslash(PrevLocation);
  NewDir := RemoveBackslash(ExpandConstant('{app}'));
  if (OldDir = '') or (CompareText(OldDir, NewDir) = 0) or (not DirExists(OldDir)) then
    Exit;
  { Last line of defence before deleting a whole tree: it must actually contain this
    program. A stale or wrong registry entry must never turn into a recursive delete. }
  if not FileExists(OldDir + '\hwsentinel\__main__.py') then
    Exit;

  { Stop whatever is still running there first. -StopOnly leaves the scheduled task
    alone: by now it points at the new location and must survive. The script also
    refuses to touch a folder that does not contain this program. }
  Script := OldDir + '\install.ps1';
  if FileExists(Script) then
    Exec('powershell.exe',
      '-NoProfile -ExecutionPolicy Bypass -File "' + Script + '" -StopOnly -Silent -InstallDir "' +
      OldDir + '"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

  if not DelTree(OldDir, True, True, True) then
    MsgBox('The program was installed to:' + #13#10 + #13#10 +
           '    ' + NewDir + #13#10 + #13#10 +
           'but the old folder could not be fully removed:' + #13#10 + #13#10 +
           '    ' + OldDir + #13#10 + #13#10 +
           'It is no longer used and can be deleted by hand.',
           mbInformation, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
    RemoveOldInstall();

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
    { Derive the uninstaller from wherever RTSS actually is, not a guessed path. }
    Uninst := RtssFromRegistry(HKLM32);
    if Uninst = '' then Uninst := RtssFromRegistry(HKLM64);
    if Uninst <> '' then
      Uninst := AddBackslash(ExtractFileDir(Uninst)) + 'Uninstall.exe'
    else
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
