; Inno Setup script for Apex Roller.
; Produces a per-user installer (no UAC prompt) that registers in Add/Remove
; Programs and ships an uninstaller which also deregisters the app from
; SteelSeries GameSense and wipes %LocalAppData%\ApexRoller.
;
; Build with:
;   iscc /DAppVersion=0.1.3 installer\apex-roller.iss
; (CI passes the version from the pushed tag.)

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName        "Apex Roller"
#define AppExeName     "apex-roller.exe"
#define AppPublisher   "StableFlux"
#define AppURL         "https://github.com/StableFlux/steelseries-apex-roller"

[Setup]
; This GUID identifies the app for upgrades and Add/Remove Programs.
; It MUST stay the same across versions for upgrades to work.
AppId={{C9F8E4DB-7B36-4F8F-9C20-3B5F1F7E5A2C}
AppName={#AppName}
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases

; All-users install only. We require admin so the installer can land in
; Program Files and register in HKLM\...\Uninstall, which guarantees the
; entry shows up in Settings > Apps and the legacy Programs and Features.
; Per-user state (config, logs, Startup-folder shortcut, GameSense
; registration) is still written to the running user's profile -- the tray
; app runs as the user, not as SYSTEM. The uninstaller's --cleanup step
; reads %LocalAppData% from the user's environment so it cleans the right
; profile.
DefaultDirName={commonpf}\ApexRoller
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin

; Don't use Inno's Restart Manager integration. RM doesn't reliably detect the
; PyInstaller --onefile tray app (the running image is in a temp extraction
; dir, not in {app}) and has been observed to interfere with the explicit
; taskkill our --cleanup performs. The uninstall flow handles process
; teardown itself in [UninstallRun].
CloseApplications=no
RestartApplications=no

; Output goes to dist/ alongside the PyInstaller exe.
OutputDir=..\dist
OutputBaseFilename=apex-roller-setup-v{#AppVersion}
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName} {#AppVersion}
SetupIconFile=..\apex_roller\assets\apex-roller.ico

[Files]
Source: "..\dist\apex-roller.exe";       DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md";                  DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE";                    DestDir: "{app}"; Flags: ignoreversion
Source: "uninstall-cleanup.ps1";         DestDir: "{app}"; Flags: ignoreversion

[Tasks]
Name: "startup"; Description: "Launch {#AppName} automatically at Windows startup"; \
    GroupDescription: "Additional options:"; Flags: checkedonce

[Icons]
Name: "{userprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: startup

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName} now"; \
    Flags: nowait postinstall skipifsilent

[UninstallRun]
; All uninstall teardown is done by a PowerShell script run as a SEPARATE
; process. We deliberately don't use `apex-roller.exe --cleanup` for this:
; that approach caused the cleanup process itself to hold the install
; dir's apex-roller.exe open (since it was the same binary) and got
; tangled with our own taskkill calls. PowerShell.exe has no such
; conflict -- it can freely kill all apex-roller.exe instances.
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\uninstall-cleanup.ps1"""; \
    RunOnceId: "ApexRollerCleanup"; \
    Flags: runhidden

[UninstallDelete]
; Wipe per-user state (config + logs) on uninstall.
Type: filesandordirs; Name: "{localappdata}\ApexRoller"
