[Setup]
AppName=MyDM
AppVersion=1.0
DefaultDirName={autopf}\MyDM
DefaultGroupName=MyDM
OutputBaseFilename=MyDM_Setup
Compression=lzma
SolidCompression=yes

[Files]
Source: "dist\MyDM.exe"; DestDir: "{app}"

[Icons]
Name: "{group}\MyDM"; Filename: "{app}\MyDM.exe"
Name: "{autodesktop}\MyDM"; Filename: "{app}\MyDM.exe"

[Run]
Filename: "{app}\MyDM.exe"; Description: "Launch MyDM"; Flags: nowait postinstall skipifsilent
