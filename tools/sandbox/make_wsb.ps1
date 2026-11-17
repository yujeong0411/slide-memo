# Windows Sandbox 덮어 설치 시험 준비. 저장소 위치에 맞춰 build\sandbox에 시험 폴더와 .wsb를 만든다.
# 만든 것은 모두 build\ 안이라 저장소에 들어가지 않는다 (.gitignore의 build/).
#
# 사용법 (저장소 폴더에서):
#   .\tools\sandbox\make_wsb.ps1 -OldSetup <쓰던 버전 설치본> [-NewSetup <새 설치본>]
#   -OldSetup  예: GitHub 릴리스(slide-memo-releases의 v2.0.0)에서 받은 SlideMemo-Setup.exe
#   -NewSetup  기본값 installer\SlideMemo-Setup.exe (방금 빌드한 설치본)
# 그다음 build\sandbox\slidememo-test.wsb를 열면 시험이 저절로 돌고, 결과는 build\sandbox\out\result.txt에 남는다.
param(
    [Parameter(Mandatory = $true)][string]$OldSetup,
    [string]$NewSetup = ""
)
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if ($NewSetup -eq "") { $NewSetup = Join-Path $repo "installer\SlideMemo-Setup.exe" }
foreach ($f in $OldSetup, $NewSetup) {
    if (-not (Test-Path $f)) { Write-Error "설치본이 없어요: $f" }
}
$root = Join-Path $repo "build\sandbox"
$in = Join-Path $root "in"
$out = Join-Path $root "out"
if (Test-Path $root) { Remove-Item $root -Recurse -Force }  # 지난 시험의 결과와 설치본을 지운다
New-Item -ItemType Directory -Force $in, $out | Out-Null
Copy-Item (Join-Path $PSScriptRoot "run_test.ps1") $in
Copy-Item (Join-Path $PSScriptRoot "seed") $in -Recurse
Copy-Item $OldSetup (Join-Path $in "SlideMemo-Setup-old.exe")
Copy-Item $NewSetup (Join-Path $in "SlideMemo-Setup.exe")

$wsb = @"
<Configuration>
  <Networking>Disable</Networking>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>$in</HostFolder>
      <SandboxFolder>C:\sm\in</SandboxFolder>
      <ReadOnly>true</ReadOnly>
    </MappedFolder>
    <MappedFolder>
      <HostFolder>$out</HostFolder>
      <SandboxFolder>C:\sm\out</SandboxFolder>
      <ReadOnly>false</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <LogonCommand>
    <Command>powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\sm\in\run_test.ps1</Command>
  </LogonCommand>
</Configuration>
"@
$wsbPath = Join-Path $root "slidememo-test.wsb"
[System.IO.File]::WriteAllText($wsbPath, $wsb, (New-Object System.Text.UTF8Encoding $false))
Write-Host "준비됨: $wsbPath"
Write-Host "이 파일을 열면 시험이 시작돼요. 결과: $out\result.txt (끝나면 done.txt가 생겨요)"
