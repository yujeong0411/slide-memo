; SlideMemo 인스톨러 스크립트 (Inno Setup)
; 빌드:  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" SlideMemo.iss
; 결과:  installer\SlideMemo-Setup.exe

#define MyAppName "SlideMemo"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "nursecoder"
#define MyAppExeName "SlideMemo.exe"

[Setup]
AppId={{C0F7E1B2-3D4A-4F5C-9E2B-A8D6F1C7E0B3}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=mailto:nursecoder04@gmail.com
DefaultDirName={localappdata}\Programs\SlideMemo
DefaultGroupName={#MyAppName}
; 2.0.0까지 시작 메뉴 폴더가 "Slide Memo"였다. 예전 폴더를 다시 쓰지 않고 새 이름 폴더를 쓴다
UsePreviousGroup=no
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
ShowLanguageDialog=no
CloseApplications=force
OutputDir=installer
OutputBaseFilename=SlideMemo-Setup
SetupIconFile=assets\icons\SlideMemo.ico
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
; 이름을 "Slide Memo" → "SlideMemo"로 바꾸면서(2.1.0) 2.0.0까지의 바로가기를 지운다.
; AppId가 같아 제어판 항목은 하나로 이어지지만, 바로가기는 이름이 달라 새로 생기고 옛것이 남기 때문이다.
Type: files; Name: "{autoprograms}\Slide Memo\Slide Memo.lnk"
Type: files; Name: "{autoprograms}\Slide Memo\Slide Memo 제거.lnk"
Type: dirifempty; Name: "{autoprograms}\Slide Memo"
Type: files; Name: "{autodesktop}\Slide Memo.lnk"

[Files]
Source: "dist\SlideMemo\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\SlideMemo\*"; Excludes: "{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
