# SlideMemo 덮어 설치와 제거 시험 (Windows Sandbox 안에서 저절로 실행된다. 직접 실행하지 않는다)
# make_wsb.ps1이 build\sandbox\in에 이 파일, 시험용 메모(seed), 설치본 두 개를 모아 둔다.
#   SlideMemo-Setup-old.exe  쓰던 버전 (예: 2.0.0)
#   SlideMemo-Setup.exe      새로 만든 설치본
# 시험용 메모(seed)는 2.0.0 형식 DB다: 메모 4개(그림·고정·휴지통 포함), 설정 3개(어두운 화면, 창 폭, 마지막 안내 버전).
$ErrorActionPreference = 'Continue'
$in = 'C:\sm\in'; $out = 'C:\sm\out'; $log = "$out\result.txt"
function W($t) { Add-Content -Path $log -Value $t -Encoding UTF8 }
$app = "$env:LOCALAPPDATA\Programs\SlideMemo"
$exe = "$app\SlideMemo.exe"
$md = "$env:USERPROFILE\.memo_slide"
function Snap($label) {
  W ""
  W "===== $label ====="
  foreach ($root in 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall', 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall', 'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall') {
    Get-ChildItem $root -ErrorAction SilentlyContinue | ForEach-Object {
      $p = Get-ItemProperty $_.PSPath
      if ($p.DisplayName -like '*Slide*') { W ("제어판 항목: " + $_.PSChildName + " | " + $p.DisplayName + " | " + $p.DisplayVersion) }
    }
  }
  $programs = [Environment]::GetFolderPath('Programs')
  Get-ChildItem $programs -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.Name -like '*Slide*' } | ForEach-Object { W ("시작 메뉴: " + $_.FullName.Substring($programs.Length)) }
  foreach ($d in [Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('CommonDesktopDirectory')) {
    Get-ChildItem $d -ErrorAction SilentlyContinue | Where-Object { $_.Name -like '*Slide*' } | ForEach-Object { W ("바탕화면: " + $_.Name) }
  }
  $run = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -ErrorAction SilentlyContinue
  $runs = @()
  if ($run) { $runs = @($run.PSObject.Properties | Where-Object { $_.Name -like '*Slide*' }) }
  if ($runs.Count) { $runs | ForEach-Object { W ("자동 실행: " + $_.Name + " = " + $_.Value) } } else { W "자동 실행: 없음" }
  W ("설치 폴더: " + (Test-Path $app))
  W ("OAuth 설정 파일(설치본 안, 있는지만 본다): " + (Test-Path "$app\_internal\secrets\google_oauth_client.json"))
  if (Test-Path $exe) { $v = (Get-Item $exe).VersionInfo; W ("exe 파일 버전: " + $v.FileVersion + " / 제품 버전: " + $v.ProductVersion) } else { W "exe: 없음" }
  W ("실행 중인 SlideMemo 프로세스: " + @(Get-Process SlideMemo -ErrorAction SilentlyContinue).Count)
  if (Test-Path $md) { Get-ChildItem $md -Recurse -File | Where-Object { $_.FullName -notlike '*theme_cache*' } | ForEach-Object { W ("메모 폴더: " + $_.FullName.Substring($md.Length) + " (" + $_.Length + ")") } }
}
W ("시작 " + (Get-Date -Format s))

# 1) 쓰던 버전 설치, 쓰던 상태 만들기 (시험용 메모, 그림, 설정, 자동 실행 켬)
Start-Process "$in\SlideMemo-Setup-old.exe" -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait
Get-Process SlideMemo -ErrorAction SilentlyContinue | Stop-Process -Force
New-Item -ItemType Directory -Force "$md\images" | Out-Null
Copy-Item "$in\seed\memos.db" "$md\memos.db" -Force
Copy-Item "$in\seed\images\*" "$md\images\" -Force
New-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'SlideMemo' -Value ('"' + $exe + '"') -PropertyType String -Force | Out-Null
Start-Process $exe | Out-Null
Start-Sleep 20
Snap "1. 쓰던 버전 (덮어 설치 전, 앱 켜져 있음)"
Copy-Item "$md\memos.db" "$out\before_memos.db" -Force

# 2) 앱이 켜진 채로 새 설치본 덮어 설치
Start-Process "$in\SlideMemo-Setup.exe" -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait
Start-Sleep 10
W ""
W ("덮어 설치 직후 실행 중인 SlideMemo: " + @(Get-Process SlideMemo -ErrorAction SilentlyContinue).Count)
if (-not (Get-Process SlideMemo -ErrorAction SilentlyContinue)) { Start-Process $exe | Out-Null }
Start-Sleep 25
Snap "2. 새 설치본 덮어 설치 후 (앱을 한 번 켬)"
Get-Process SlideMemo -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 3
Copy-Item $md "$out\after_profile" -Recurse -Force

# 3) 제거
$unins = Get-ChildItem $app -Filter 'unins*.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($unins) { Start-Process $unins.FullName -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait }
Start-Sleep 20
Snap "3. 제거 후"
W ("끝 " + (Get-Date -Format s))
Set-Content "$out\done.txt" "done"
