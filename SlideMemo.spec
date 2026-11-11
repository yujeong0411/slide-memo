# -*- mode: python ; coding: utf-8 -*-
import os

import re

from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
)

# exe 파일 속성(자세히)에 보일 버전. pyproject.toml 하나만 고치면 따라온다
_VERSION = re.search(r'^version\s*=\s*"(\d+)\.(\d+)\.(\d+)"', open('pyproject.toml', encoding='utf-8').read(), re.M).groups()
_VERSION_TUPLE = tuple(int(x) for x in _VERSION) + (0,)
_VERSION_TEXT = '.'.join(_VERSION)
VERSION_INFO = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_VERSION_TUPLE, prodvers=_VERSION_TUPLE),
    kids=[
        StringFileInfo([StringTable('041204B0', [
            StringStruct('FileDescription', 'SlideMemo'),
            StringStruct('FileVersion', _VERSION_TEXT),
            StringStruct('InternalName', 'SlideMemo'),
            StringStruct('OriginalFilename', 'SlideMemo.exe'),
            StringStruct('ProductName', 'SlideMemo'),
            StringStruct('ProductVersion', _VERSION_TEXT),
            StringStruct('LegalCopyright', '© 2026 nursecoder. MIT License.'),
        ])]),
        VarFileInfo([VarStruct('Translation', [0x0412, 1200])]),
    ],
)

litellm_datas, litellm_binaries, litellm_hiddenimports = collect_all('litellm')
tiktoken_datas, tiktoken_binaries, tiktoken_hiddenimports = collect_all('tiktoken')
tiktoken_ext_datas, tiktoken_ext_binaries, tiktoken_ext_hiddenimports = collect_all('tiktoken_ext')

# Google 동기화용 OAuth 클라이언트 JSON (docs/sync-design.md 10장). 저장소에 커밋하지 않고(.gitignore의 secrets/)
# 빌드할 때만 넣는다. 이 spec은 배포용 빌드이므로 파일이 없으면 멈춘다 (개발 실행은 spec을 쓰지 않는다).
OAUTH_CLIENT = os.path.join('secrets', 'google_oauth_client.json')
if not os.path.isfile(OAUTH_CLIENT):
    raise SystemExit(f'배포용 빌드를 멈춰요: {OAUTH_CLIENT}가 없어요. 동기화가 빠진 설치본이 나가지 않게 하려는 거예요.')

# 번들에서 빼는 것들 (근거는 아래 주석 — 되돌리려면 해당 줄만 지우면 된다)
EXCLUDE_MODULES = [
    'PIL',        # 어디서도 import하지 않음 (pillow는 dev 전용인데 번들에 딸려 들어옴) -12.7MB
    'tkinter',    # PyQt6 앱이라 불필요
    'unittest',   # 런타임에 안 씀
]

DROP_BINARIES = {
    # GPU 드라이버 없는 환경용 소프트웨어 OpenGL 폴백. 이 앱은 순수 QWidget이라
    # OpenGL 표면을 만들지 않는다. 문제 생기면 이 줄을 지워 되돌린다. -19.7MB
    'opengl32sw.dll',
    # QtPdf 파이썬 바인딩(QtPdf.pyd)이 번들에 없어 호출 경로 자체가 없다. -4.4MB
    'Qt6Pdf.dll',
}


def _keep_binary(entry):
    return os.path.basename(entry[0]).lower() not in {n.lower() for n in DROP_BINARIES}


def _keep_data(entry):
    # Qt 자체 번역 파일(.qm). 이 앱은 QTranslator/tr()을 쓰지 않고 한국어를
    # 파이썬 문자열로 직접 넣는다. -6.4MB
    dest = entry[0].replace('\\', '/')
    if dest.endswith('.map'):  # litellm 웹 화면에 딸린 sourcemap. 배포하지 않는다
        return False
    return not dest.startswith('PyQt6/Qt6/translations/') or dest.endswith('/qtbase_ko.qm')


a = Analysis(
    ['src/main.py'],
    pathex=['src'],
    binaries=litellm_binaries + tiktoken_binaries + tiktoken_ext_binaries,
    datas=[('assets', 'assets'), ('src/theme/*.qss', 'theme'), (OAUTH_CLIENT, 'secrets')] + litellm_datas + tiktoken_datas + tiktoken_ext_datas,
    hiddenimports=['keyring.backends', 'keyring.backends.Windows', 'tiktoken_ext', 'tiktoken_ext.openai_public'] + litellm_hiddenimports + tiktoken_hiddenimports + tiktoken_ext_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDE_MODULES,
    noarchive=False,
    optimize=0,
)

a.binaries = [b for b in a.binaries if _keep_binary(b)]
a.datas = [d for d in a.datas if _keep_data(d)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SlideMemo',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/icons/SlideMemo.ico'],
    version=VERSION_INFO,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SlideMemo',
)
