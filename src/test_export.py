# ponytail: minimal self-check for txt/md export. run: python src/test_export.py
# 주의: 일부러 offscreen을 쓰지 않는다. offscreen에는 폰트가 없어서 Qt의 마크다운
# 변환기가 굵게/기울임을 판정하지 못하고 조용히 서식을 떨어뜨린다(창은 안 뜬다).
from PyQt6.QtWidgets import QApplication

import main as m
from database import Memo

app = QApplication([])


def memo(title: str, content: str) -> Memo:
    return Memo(id=1, title=title, content=content, color="ivory",
                created_at="", updated_at="")


# 파일명 정리 (경로 조작·Windows 금지문자가 그대로 나가면 안 되는 지점)
assert m._safe_filename('a/b\\c:d*e?f"g<h>i|j') == "abcdefghij"
assert m._safe_filename("../../etc/passwd") == "....etcpasswd"  # 구분자가 사라져 경로가 못 됨
assert m._safe_filename("  제목  ") == "제목"
assert m._safe_filename("끝점...") == "끝점"       # Windows는 끝의 점을 허용 안 함
assert m._safe_filename("") == "메모"              # 빈 제목 → 기본값
assert m._safe_filename("///") == "메모"
assert len(m._safe_filename("가" * 200)) == 80

html = (
    "<h2>소제목</h2><p><b>굵게</b> <a href='https://ex.com'>링크</a></p>"
    "<ul><li>항목</li></ul>"
    "<table border=1><tr><td>1</td><td>2</td></tr></table>"
    "<p><img src='C:/x/y.png'></p>"
)

md = m._memo_as_text(memo("내 제목", html), markdown=True)
assert md.startswith("# 내 제목\n\n")     # 제목이 h1로 앞에 붙는다
assert "**굵게**" in md, "서식 누락 — offscreen으로 돌리고 있지 않은지 확인"
assert "[링크](https://ex.com)" in md
assert "- 항목" in md
assert "|1|2|" in md.replace(" ", "")    # 표가 파이프 문법으로
assert "![image](C:/x/y.png)" in md
assert "<b>" not in md and "<table" not in md

txt = m._memo_as_text(memo("내 제목", html), markdown=False)
assert txt.startswith("내 제목\n")   # 제목이 첫 줄 (toPlainText는 블록을 \n 하나로 잇는다)
assert "\ufffc" not in txt               # 이미지 자리표시자가 남으면 안 된다
assert "<b>" not in txt and "**" not in txt
assert "굵게" in txt and "항목" in txt

# 제목이 없으면 머리말도 없어야 한다
assert not m._memo_as_text(memo("", "<p>본문</p>"), markdown=True).startswith("#")
assert not m._memo_as_text(memo("   ", "<p>본문</p>"), markdown=False).startswith(" ")

# 옛 plain text 메모(HTML 아님)도 그대로 나가야 한다
plain = m._memo_as_text(memo("T", "그냥 텍스트"), markdown=False)
assert "그냥 텍스트" in plain

# 본문이 비어도 제목만으로 나가야 한다 (제목 삽입이 빈 문서에서 깨지지 않는지)
assert m._memo_as_text(memo("제목뿐", ""), markdown=True).startswith("# 제목뿐")

# ODF: Word·한글이 여는 형식. 실제로 zip 컨테이너인지 + 서식이 들어갔는지
import tempfile
import zipfile
from pathlib import Path

from PyQt6.QtGui import QTextDocumentWriter

odt = Path(tempfile.mkdtemp()) / "out.odt"
w = QTextDocumentWriter(str(odt))
w.setFormat(b"ODF")
assert w.write(m._memo_document(memo("내 제목", html)))
assert zipfile.is_zipfile(odt), "ODF가 zip 컨테이너가 아니다 — Word가 못 연다"
with zipfile.ZipFile(odt) as z:
    assert "content.xml" in z.namelist() and "mimetype" in z.namelist()
    body = z.read("content.xml").decode("utf-8")
assert "<table:table" in body, "표가 빠졌다"
assert "text:list" in body, "목록이 빠졌다"
assert "fo:font-weight" in body, "굵게가 빠졌다"
assert "내 제목" in body

# 이미지가 ODT 안에 실제로 들어가야 한다 (리소스 등록을 빼먹으면 통째로 사라진다)
from PyQt6.QtGui import QImage

pic = Path(tempfile.mkdtemp()) / "pic.png"
img = QImage(40, 30, QImage.Format.Format_RGB32)
img.fill(0xFF0000)
assert img.save(str(pic))

odt2 = pic.parent / "with_image.odt"
w2 = QTextDocumentWriter(str(odt2))
w2.setFormat(b"ODF")
assert w2.write(m._memo_document(memo("사진", f'<p><img src="{pic.as_posix()}"></p>')))
with zipfile.ZipFile(odt2) as z:
    embedded = [n for n in z.namelist() if n.startswith("Pictures/")]
    assert embedded, "이미지가 ODT에 임베드되지 않았다"
    assert "draw:image" in z.read("content.xml").decode("utf-8")

# 이미지 파일이 사라진 메모도 예외 없이 내보내져야 한다
pic.unlink()
assert m._memo_as_text(memo("깨진 사진", f'<p><img src="{pic.as_posix()}"></p>'), markdown=True)

print("export OK")
