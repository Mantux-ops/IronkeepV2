; Packages the published .NET 10 WPF executable.
; AppId matches the earlier per-user installer so this version upgrades that install.
#ifndef AppVersion
  #error Pass /DAppVersion=x.y.z from the project version.
#endif

[Setup]
AppId={{8F4C2A71-6B19-4E53-9D80-2C7A15E64B08}
AppName=Ironkeep Companion
AppVersion={#AppVersion}
AppPublisher=Ironkeep
VersionInfoProductName=Ironkeep Companion
VersionInfoVersion={#AppVersion}.0
DefaultDirName={localappdata}\Ironkeep Companion
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableWelcomePage=yes
PrivilegesRequired=lowest
OutputDir=out\release
OutputBaseFilename=IronkeepCompanionSetup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\IronkeepCompanion.exe
UninstallDisplayName=Ironkeep Companion
Compression=zip
SolidCompression=no
WizardStyle=modern
InfoBeforeFile=wpf-install-info.txt
CloseApplications=no
ChangesAssociations=no
ChangesEnvironment=no

[Languages]
Name: "dutch"; MessagesFile: "compiler:Languages\Dutch.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "out\wpf\IronkeepCompanion.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Ironkeep Companion"; Filename: "{app}\IronkeepCompanion.exe"
Name: "{autodesktop}\Ironkeep Companion"; Filename: "{app}\IronkeepCompanion.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\IronkeepCompanion.exe"; Description: "{cm:LaunchProgram,Ironkeep Companion}"; Flags: nowait postinstall skipifsilent
