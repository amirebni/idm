[Setup]
AppName=MyDM
AppVersion=2.1
DefaultDirName={autopf}\MyDM
DefaultGroupName=MyDM
OutputBaseFilename=MyDM_Setup_v2.1
Compression=lzma
SolidCompression=yes

[Files]
Source: "dist\MyDM.exe"; DestDir: "{app}"
Source: "extension\*"; DestDir: "{app}\extension"; Flags: recursesubdirs

[Icons]
Name: "{group}\MyDM"; Filename: "{app}\MyDM.exe"
Name: "{autodesktop}\MyDM"; Filename: "{app}\MyDM.exe"

[Run]
Filename: "{app}\MyDM.exe"; Description: "Launch MyDM"; Flags: nowait postinstall skipifsilent
