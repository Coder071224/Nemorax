#define ProjectRoot AddBackslash(SourcePath) + "..\"
#define AppSource ProjectRoot + "build\flutter\build\windows\x64\runner\Release"
#define OutputPath ProjectRoot + "website\downloads"

[Setup]
AppId={{A4E078E7-D05B-4BF4-8DE6-9F226B83A5D7}
AppName=Nemis
AppVersion=1.0.0
AppPublisher=Nemorax
AppPublisherURL=https://github.com/Coder071224/Nemorax
AppSupportURL=https://github.com/Coder071224/Nemorax
AppUpdatesURL=https://github.com/Coder071224/Nemorax
DefaultDirName={localappdata}\Programs\Nemis
DefaultGroupName=Nemis
DisableProgramGroupPage=yes
OutputDir={#OutputPath}
OutputBaseFilename=Nemis-Installer
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\Nemis.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#AppSource}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Nemis"; Filename: "{app}\Nemis.exe"
Name: "{autodesktop}\Nemis"; Filename: "{app}\Nemis.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Nemis.exe"; Description: "{cm:LaunchProgram,Nemis}"; Flags: nowait postinstall skipifsilent
