; Docket Ledger installer (Inno Setup 6). Build it with build_installer.bat.
;
; Installs for the current user (no admin prompt) to %LOCALAPPDATA%\Programs\Docket Ledger,
; registers DocketLedger.exe under App Paths so Docket can find it, and adds a Start menu
; entry, an optional desktop shortcut and an uninstaller. Uninstalling keeps your data in
; %APPDATA%\Docket Ledger (profiles, clients, invoices), so reinstalling brings it back.
;
; For a new version: change MyAppVersion below and __version__ in ledger\__init__.py.

#define MyAppName "Docket Ledger"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Docket"
#define MyAppExeName "DocketLedger.exe"

[Setup]
; Keep this AppId the same forever: it's how Windows knows a new installer is an update.
AppId={{6A1F3C58-2E4B-4D7A-9C61-B8E05D2F7A43}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=installer_output
OutputBaseFilename=DocketLedger-Setup-{#MyAppVersion}
SetupIconFile=assets\docket-ledger.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
AppMutex=DocketLedgerRunningMutex
CloseApplications=yes
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\Docket Ledger\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "THIRD-PARTY-NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Lets Docket tell that Ledger is installed and start it (see the Docket-Ledger integration notes).
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\{#MyAppExeName}"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName}"; Flags: uninsdeletekey

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#MyAppExeName}"; Parameters: "--updated"; Flags: nowait; Check: WizardSilent
