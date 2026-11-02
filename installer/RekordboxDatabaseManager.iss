; Build with Build-Setup.ps1 from the project root.
#ifndef AppVersion
  #error AppVersion must be supplied by Build-Setup.ps1.
#endif
#define AppName "Rekordbox Database Manager"
#define AppExe "RekordboxDatabaseManager.exe"
#define ProjectRoot AddBackslash(SourcePath) + ".."
#ifndef PayloadDir
  #define PayloadDir ProjectRoot + "\dist\RekordboxDatabaseManager-" + AppVersion
#endif
#if !FileExists(PayloadDir + "\" + AppExe)
  #error Application build not found. Run Build.ps1 first.
#endif

[Setup]
; Keep this ID unchanged so subsequent versions update the same installation.
AppId={{65C03D73-2F6A-4D23-A0EF-EF142D3369C6}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
VersionInfoVersion={#AppVersion}.0
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#ProjectRoot}\dist\Setup
OutputBaseFilename=RekordboxDatabaseManager-{#AppVersion}-Setup-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableWelcomePage=no
UninstallDisplayIcon={app}\{#AppExe}
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Desktopverknüpfung erstellen"; GroupDescription: "Verknüpfungen:"; Flags: unchecked

[Files]
; Include the complete PyInstaller distribution: Python, Qt, SQLCipher and licenses.
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{group}\Anleitung"; Filename: "{app}\_internal\README.md"
Name: "{group}\Deinstallieren"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{#AppName} starten"; Flags: nowait postinstall skipifsilent
