; Windows installer for Stillframe (Inno Setup 6). Built by CI: iscc /DAppVersion=1.0.0 installer\stillframe.iss
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{9C2D7A41-5E8B-4F3A-B6D2-1A7E4C9F0B23}
AppName=Stillframe
AppVersion={#AppVersion}
AppPublisher=Miguel Rato
AppPublisherURL=https://github.com/iamgraphicartist/frameline
AppSupportURL=https://github.com/iamgraphicartist/frameline/issues
DefaultDirName={localappdata}\Programs\Stillframe
DefaultGroupName=Stillframe
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Stillframe-Setup-{#AppVersion}
SetupIconFile=..\build_assets\stillframe.ico
UninstallDisplayIcon={app}\Stillframe.exe
UninstallDisplayName=Stillframe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "assoc"; Description: "Add Stillframe to Open with for photos"; GroupDescription: "File types:"

[Files]
Source: "..\dist\Stillframe.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\Stillframe"; Filename: "{app}\Stillframe.exe"
Name: "{userdesktop}\Stillframe"; Filename: "{app}\Stillframe.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Stillframe.exe"; Parameters: "--register"; Tasks: assoc; Flags: runhidden waituntilterminated
Filename: "{app}\Stillframe.exe"; Description: "Launch Stillframe"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\Stillframe.exe"; Parameters: "--unregister"; Flags: runhidden waituntilterminated; RunOnceId: "Unregister"
