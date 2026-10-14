[Setup]
AppName=MyDM
AppVersion=3.4
DefaultDirName={autopf}\MyDM
DefaultGroupName=MyDM
OutputBaseFilename=MyDM_Setup_v3.4
Compression=lzma2
SolidCompression=yes
CloseApplications=yes

[Files]
Source: "dist\MyDM\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "ffmpeg.exe"; DestDir: "{app}"
Source: "qjs.exe"; DestDir: "{app}"
Source: "yt-dlp"; DestDir: "{app}"
Source: "extension\*"; DestDir: "{app}\extension"; Flags: recursesubdirs

[Icons]
Name: "{group}\MyDM"; Filename: "{app}\MyDM.exe"
Name: "{autodesktop}\MyDM"; Filename: "{app}\MyDM.exe"

[Run]
Filename: "{app}\MyDM.exe"; Description: "Launch MyDM"; Flags: nowait postinstall skipifsilent

[Code]
// MyDM may be running hidden in the notification area: close it before the files are replaced
function PrepareToInstall(var NeedsRestart: Boolean): String;
var R: Integer;
begin
  Exec('taskkill.exe', '/F /IM MyDM.exe', '', SW_HIDE, ewWaitUntilTerminated, R);
  Result := '';
end;
