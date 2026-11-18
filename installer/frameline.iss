; Windows installer for Frameline (Inno Setup 6). Built by CI: iscc /DAppVersion=1.0.0 installer\frameline.iss
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6B1E5F0C-3C7A-4C51-9E7B-6F0A9D2E8F11}
AppName=Frameline
AppVersion={#AppVersion}
AppPublisher=Miguel Rato
AppPublisherURL=https://github.com/iamgraphicartist/frameline
AppSupportURL=https://github.com/iamgraphicartist/frameline/issues
DefaultDirName={localappdata}\Programs\Frameline
DefaultGroupName=Frameline
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Frameline-Setup-{#AppVersion}
SetupIconFile=..\build_assets\frameline.ico
UninstallDisplayIcon={app}\Frameline.exe
UninstallDisplayName=Frameline
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "assoc"; Description: "Add Frameline to Open with and Default Apps for video files"; GroupDescription: "File types:"

[Files]
Source: "..\dist\Frameline.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\Frameline"; Filename: "{app}\Frameline.exe"
Name: "{userdesktop}\Frameline"; Filename: "{app}\Frameline.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Frameline.exe"; Parameters: "--register"; Tasks: assoc; Flags: runhidden waituntilterminated
Filename: "{app}\Frameline.exe"; Description: "Launch Frameline"; Flags: nowait postinstall skipifsilent
Filename: "ms-settings:defaultapps?registeredAppUser=Frameline"; Description: "Make Frameline my default video player (opens Settings)"; Tasks: assoc; Flags: shellexec postinstall skipifsilent unchecked

[UninstallRun]
Filename: "{app}\Frameline.exe"; Parameters: "--unregister"; Flags: runhidden waituntilterminated; RunOnceId: "Unregister"
