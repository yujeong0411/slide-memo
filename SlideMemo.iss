; Slide Memo 인스톨러 스크립트 (Inno Setup)
; 빌드:  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" SlideMemo.iss
; 결과:  installer\SlideMemo-Setup.exe

#define MyAppName "Slide Memo"
#define MyAppVersion "1.0.9"
#define MyAppPublisher "nursecoder"
#define MyAppExeName "SlideMemo.exe"

[Setup]
AppId={{C0F7E1B2-3D4A-4F5C-9E2B-A8D6F1C7E0B3}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=mailto:choiyujeong0411@gmail.com
DefaultDirName={localappdata}\Programs\SlideMemo
DefaultGroupName={#MyAppName}
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
ShowLanguageDialog=no
CloseApplications=force
OutputDir=installer
OutputBaseFilename=SlideMemo-Setup
SetupIconFile=logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

; 업그레이드 시 이전 버전의 잔여 파일 정리 (의존성 변경으로 사라진 _internal 파일 등)
[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\SlideMemo\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\SlideMemo\*"; Excludes: "{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
