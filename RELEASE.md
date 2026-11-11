# 릴리즈 가이드

## 사전 준비

- [GitHub CLI](https://cli.github.com/) 설치 (`C:\Program Files\GitHub CLI\gh.exe`)
- [Inno Setup 6](https://jrsoftware.org/isinfo.php) 설치 (`C:\Program Files (x86)\Inno Setup 6\ISCC.exe`)
- `gh auth login` 으로 GitHub 로그인 완료

---

## 배포 저장소 (2.1.0부터)

설치 파일은 공개 저장소 **`yujeong0411/slide-memo-releases`** 에 올린다. 앱은 이 저장소의 최신 Release를 보고 업데이트를 알린다(주소는 `src/links.py`의 `UPDATE_REPO` 한 곳).

| 버전 | 올리는 곳 | 이유 |
|---|---|---|
| 2.0.0 이하 | `yujeong0411/slide-memo` | 그때까지의 배포 |
| **2.1.0** | **두 곳 모두**: `slide-memo`와 `slide-memo-releases` | 2.0.0 설치본은 `slide-memo`를 본다. 거기에 2.1.0을 올려 두어야 2.0.0 사용자가 2.1.0으로 올라오고, 2.1.0부터는 새 저장소를 본다(다리) |
| 2.1.1부터 | `slide-memo-releases`에만 | `slide-memo`에는 2.1.0을 마지막으로 남겨 둔다. 지우면 늦게 업데이트하는 2.0.0 사용자가 길을 잃는다 |

- 두 곳 모두 첨부 이름은 **`SlideMemo-Setup.exe`** 이다. 앱은 `releases/latest/download/SlideMemo-Setup.exe`로 받는다.
- 이어지는지는 `src/test_update_chain.py`가 가짜 응답으로 확인한다(2.0.0 → 2.1.0 → 2.1.1).
- `bump_version.ps1`이 이 표대로 올린다. 2.1.0이면 두 곳, 그다음부터는 새 저장소에만.
- 프로젝트 폴더에 `release_notes.md`가 있으면 그 내용을 릴리즈 노트로 쓴다. 없으면 제목만 들어간다. 새 저장소에는 커밋 기록이 없어 자동 노트(`--generate-notes`)가 의미 없기 때문이다.

---

## 릴리즈 방법

PowerShell에서 프로젝트 폴더로 이동 후 실행:

```powershell
cd <프로젝트 폴더>
.\bump_version.ps1
```

### 버전 자동 증가 (patch)
```powershell
.\bump_version.ps1          # 1.0.4 → 1.0.5
```

### 버전 직접 지정
```powershell
.\bump_version.ps1 1.1.0
```

---

## 실행 흐름

1. `pyproject.toml`, `SlideMemo.iss`, `src/main.py` 버전 일괄 수정
2. **git commit + tag + push + GitHub Release 생성할까요?** (y/n)
3. **인스톨러 빌드도 할까요?** (y/n)
   - `y` → PyInstaller + Inno Setup 빌드 후 Release에 자동 첨부
   - `n` → Release만 생성 (인스톨러는 나중에 수동 업로드)
4. Release는 배포 저장소에 만든다. 2.1.0이면 `slide-memo`에도 같은 것을 만든다(위 표).

---

## 인스톨러 수동 업로드

빌드 후 따로 올리고 싶을 때:

```powershell
& "C:\Program Files\GitHub CLI\gh.exe" release upload v2.1.1 -R yujeong0411/slide-memo-releases installer\SlideMemo-Setup.exe
# 2.1.0만: 지금 저장소에도
& "C:\Program Files\GitHub CLI\gh.exe" release upload v2.1.0 -R yujeong0411/slide-memo installer\SlideMemo-Setup.exe
```
