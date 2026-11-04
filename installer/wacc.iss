; Inno Setup script: one WACC-Setup.exe, no admin rights, no settings to fill in.
; Build:  ISCC.exe installer\wacc.iss   (needs dist\WACC from installer\build_exe.py)
#define AppVersion "1.0.0"

[Setup]
AppName=WACC
AppVersion={#AppVersion}
AppPublisher=WACC
DefaultDirName={localappdata}\Programs\WACC
DefaultGroupName=WACC
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=WACC-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\WACC.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\dist\WACC\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\WACC"; Filename: "{app}\WACC.exe"
Name: "{autodesktop}\WACC"; Filename: "{app}\WACC.exe"

[Run]
Filename: "{app}\WACC.exe"; Description: "WACC'ı şimdi başlat"; Flags: nowait postinstall skipifsilent

; Your data (databases, tokens, workspace) lives in %LOCALAPPDATA%\WACC and is NOT removed on uninstall.
