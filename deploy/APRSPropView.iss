; APRS PropView Windows installer script for Inno Setup 6.
;
; Build through build_installer.py so MyAppVersion is supplied from main.py.

#ifndef MyAppVersion
#define MyAppVersion "1.14.1"
#endif

#define MyAppName "APRS PropView"
#define MyAppExeName "APRSPropView.exe"
#define MyAppPublisher "Wicker Made, LLC"
#define MyAppURL "https://github.com/RF-YVY/APRS-PropView"
#define MyAppId "{{8F56D489-53F5-4E9E-89B0-BA55762CDE37}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Programs\APRS PropView
DefaultGroupName={#MyAppName}
DisableDirPage=no
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=APRSPropViewSetup-{#MyAppVersion}
SetupIconFile=..\ico\favicon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=APRS PropView Setup
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\config.toml.example"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\NOTICE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\MODEM_THIRD_PARTY_NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\TRADEMARKS.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Set or reset operator password"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--operator-password-dialog"; WorkingDir: "{app}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "{code:GetLaunchParameters}"; WorkingDir: "{app}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent; BeforeInstall: PrepareAppLaunch

[UninstallDelete]
; Keep config.toml, propview.db, map_tile_cache, and user_audio intact.
Type: files; Name: "{app}\config.toml.example"

[Code]
function SetEnvironmentVariable(lpName, lpValue: String): Boolean;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

procedure PrepareAppLaunch();
begin
  SetEnvironmentVariable('PYINSTALLER_RESET_ENVIRONMENT', '1');
end;

function GetLaunchParameters(Param: String): String;
begin
  Result := '';
  if ExpandConstant('{param:PROPVIEWINAPPUPDATE|0}') = '1' then
    Result := '--update-relaunch';
end;

procedure StopRunningApp();
var
  ResultCode: Integer;
begin
  { In-app updates wait for the old process before setup starts. Keep the
    access-denied protection for stubborn processes, but give the normal
    shutdown path a little more time first. }
  if ExpandConstant('{param:PROPVIEWINAPPUPDATE|0}') = '1' then
    Sleep(2500);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM {#MyAppExeName} /T /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(1500);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    StopRunningApp();
end;
