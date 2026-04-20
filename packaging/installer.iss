; Inno Setup script for Cove Meme Maker (Windows)
; Invoked from build.ps1 via:
;   iscc /DAppVersion=X.Y.Z /DSourceDir=<abs dist\cove-meme-maker> \
;        /DOutputDir=<abs release> /DIconFile=<abs cove_icon.ico> installer.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\cove-meme-maker"
#endif
#ifndef OutputDir
  #define OutputDir "..\release"
#endif
#ifndef IconFile
  #define IconFile "..\cove_icon.ico"
#endif

[Setup]
AppId={{F2A17B84-93E2-4D3C-8A7E-6B91C5D4F182}
AppName=Cove Meme Maker
AppVersion={#AppVersion}
AppPublisher=Cove
AppPublisherURL=https://github.com/Sin213/cove-meme-maker
AppSupportURL=https://github.com/Sin213/cove-meme-maker/issues
AppUpdatesURL=https://github.com/Sin213/cove-meme-maker/releases
DefaultDirName={autopf}\Cove Meme Maker
DefaultGroupName=Cove Meme Maker
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\cove-meme-maker.exe
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=cove-meme-maker-{#AppVersion}-Setup
SetupIconFile={#IconFile}
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Cove Meme Maker"; Filename: "{app}\cove-meme-maker.exe"
Name: "{group}\Uninstall Cove Meme Maker"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Cove Meme Maker"; Filename: "{app}\cove-meme-maker.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\cove-meme-maker.exe"; Description: "Launch Cove Meme Maker"; Flags: nowait postinstall skipifsilent
