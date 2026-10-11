#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{71A2F81C-B169-41BF-81D5-D0A45F3AC028}
AppName=NTF Insight
AppVersion={#AppVersion}
AppVerName=NTF Insight {#AppVersion}
AppPublisher=NTF Insight Projekt
DefaultDirName={localappdata}\Programs\NTF Insight
DefaultGroupName=NTF Insight
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=NTF-Insight-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\NTF Insight.exe
SetupLogging=yes

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung erstellen"; GroupDescription: "Zusätzliche Aufgaben:"; Flags: checkedonce

[Files]
Source: "..\dist\NTF Insight\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\NTF Insight"; Filename: "{app}\NTF Insight.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\NTF Insight"; Filename: "{app}\NTF Insight.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\NTF Insight.exe"; Description: "NTF Insight jetzt starten"; Flags: nowait postinstall skipifsilent
