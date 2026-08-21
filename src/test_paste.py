"""붙여넣기 시 원본 서식이 따라오지 않는지 확인 (offscreen 실행 가능)."""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QMimeData, Qt
from PyQt6.QtGui import QFont, QTextCursor, QTextCharFormat, QTextBlockFormat
import main as M

HTML = '<span style="font-family:Arial; font-size:28pt; color:#ff0000; font-weight:700">BIG</span>'


def _fragments(ed):
    out, blk = [], ed.document().firstBlock()
    while blk.isValid():
        it = blk.begin()
        while not it.atEnd():
            fr = it.fragment()
            if fr.isValid():
                out.append((fr.text(), fr.charFormat()))
            it += 1
        blk = blk.next()
    return out


def _editor():
    ed = M.RichPasteTextEdit()
    ed.setAcceptRichText(True)
    ed.document().setDefaultFont(QFont("Pretendard", 11))
    return ed


def _paste(ed, mime):
    QApplication.clipboard().setMimeData(mime)
    c = ed.textCursor()
    c.movePosition(QTextCursor.MoveOperation.End)
    ed.setTextCursor(c)
    ed.paste()


def demo():
    app = QApplication.instance() or QApplication(sys.argv)

    # 1) html + text/plain (일반 브라우저·워드 복사)
    md = QMimeData(); md.setHtml(HTML); md.setText("BIG")
    ed = _editor(); ed.setPlainText("a "); _paste(ed, md)
    for text, cf in _fragments(ed):
        assert not cf.fontFamilies(), f"글꼴이 따라옴: {text!r} {cf.fontFamilies()}"
        assert cf.fontPointSize() == 0.0, f"글자크기가 따라옴: {text!r}"

    # 2) text/plain 없이 html만 주는 소스
    md = QMimeData(); md.setHtml(HTML)
    assert not md.hasText()
    ed = _editor(); ed.setPlainText("a "); _paste(ed, md)
    frags = _fragments(ed)
    assert "".join(t for t, _ in frags) == "a BIG", frags
    for text, cf in frags:
        assert not cf.fontFamilies(), f"html-only 붙여넣기에서 글꼴이 따라옴: {text!r}"
        assert cf.fontPointSize() == 0.0, f"html-only 붙여넣기에서 크기가 따라옴: {text!r}"
        assert cf.foreground().color().name() == "#000000"

    # 3) 커서 위치에 서식이 있어도 붙여넣은 텍스트는 서식 없이
    md = QMimeData(); md.setHtml(HTML); md.setText("BIG")
    ed = _editor()
    cur = ed.textCursor()
    f = QTextCharFormat(); f.setFontPointSize(30); f.setFontFamilies(["Impact"])
    cur.insertText("styled ", f)
    ed.setTextCursor(cur)
    _paste(ed, md)
    pasted = [cf for t, cf in _fragments(ed) if t == "BIG"]
    assert pasted and not pasted[0].fontFamilies() and pasted[0].fontPointSize() == 0.0

    print("paste: OK")


if __name__ == "__main__":
    demo()
