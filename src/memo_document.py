"""메모 문서의 표시용 색 처리. SlideMemo-design.md 9장 9·14·16번.

저장되는 HTML은 항상 밝은 화면 값이다. 불러올 때 화면 모드에 맞게 칠하고, 원래 값을
글자 서식의 사용자 속성에 적어 둔다. 저장할 때는 복제본에서 그 표시를 걷어낸다.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QPainter,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextFrame,
    QTextTable,
    QTextTableFormat,
)

from theme import tokens as T
from theme.memo_tokens import contrast, legible_color

# 값이 "" 이면 저장할 때 색을 지우고, hex면 그 색으로 되돌린다
ORIGINAL_FG = QTextFormat.Property.UserProperty + 1
ORIGINAL_BG = QTextFormat.Property.UserProperty + 2

_TEXT_PAIRS = {light.upper(): dark for _, light, dark in T.TEXT_COLORS}
_HIGHLIGHT_PAIRS = {light.upper(): dark for _, light, dark in T.HIGHLIGHTS}
_TABLE_LINE_ALPHA = 0.30
_TABLE_HEAD_ALPHA = 0.06
_CELL_PADDING_X = 12
_CELL_PADDING_Y = 6
_CELL_PADDING_PROPS = (
    QTextFormat.Property.TableCellLeftPadding,
    QTextFormat.Property.TableCellRightPadding,
    QTextFormat.Property.TableCellTopPadding,
    QTextFormat.Property.TableCellBottomPadding,
)


def link_color(mode: str) -> str:
    return T.MEMO_LINK_ON_DARK if mode == "dark" else T.MEMO_LINK_ON_LIGHT


def _ink(mode: str) -> str:
    return T.WHITE if mode == "dark" else T.INK_DARK


def _alpha_brush(color: str, alpha: float) -> QBrush:
    tint = QColor(color)
    tint.setAlphaF(alpha)
    return QBrush(tint)


def _brush_color(brush: QBrush) -> str | None:
    """칠해져 있으면 #RRGGBB, 없거나 투명이면 None."""
    if brush.style() == Qt.BrushStyle.NoBrush or brush.color().alpha() == 0:
        return None
    return brush.color().name().upper()


def better_ink(background: str) -> str:
    return max((T.INK_DARK, T.WHITE), key=lambda ink: contrast(ink, background))


def _reference_face(mode: str) -> str:
    """보정 기준 면. 밝은 화면은 종이 톤 중 가장 어두운 회색이라 어느 메모에서나 기준을 넘는다."""
    return T.DARK_MEMO_FACE if mode == "dark" else T.MEMO_PRESETS["gray"][1]


def display_text_color(light: str, mode: str) -> str:
    """저장 값 → 화면에 칠할 색. 목록 색은 짝으로, 목록 밖의 색은 읽히게 보정한다."""
    key = light.upper()
    if key in _TEXT_PAIRS:
        return _TEXT_PAIRS[key] if mode == "dark" else light
    return legible_color(key, _reference_face(mode), _ink(mode))


def display_highlight(light: str, mode: str) -> str:
    return _HIGHLIGHT_PAIRS.get(light.upper(), light) if mode == "dark" else light


def _fragments(doc: QTextDocument):
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            fragment = it.fragment()
            if fragment.isValid():
                yield fragment.position(), fragment.length(), fragment.charFormat()
            it += 1
        block = block.next()


def _apply_char_formats(doc: QTextDocument, changes: list[tuple[int, int, QTextCharFormat]]) -> None:
    cursor = QTextCursor(doc)
    for position, length, fmt in changes:
        cursor.setPosition(position)
        cursor.setPosition(position + length, QTextCursor.MoveMode.KeepAnchor)
        cursor.setCharFormat(fmt)


def _tables(frame: QTextFrame):
    for child in frame.childFrames():
        if isinstance(child, QTextTable):
            yield child
        yield from _tables(child)


def _is_head_row(table: QTextTable) -> bool:
    texts = 0
    for column in range(table.columns()):
        cursor = table.cellAt(0, column).firstCursorPosition()
        cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
        if cursor.selectedText():
            if cursor.charFormat().fontWeight() < int(QFont.Weight.Medium):
                return False
            texts += 1
    return texts > 0


def decorate_table(table: QTextTable, mode: str) -> None:
    fmt: QTextTableFormat = table.format()
    fmt.setBorderBrush(_alpha_brush(_ink(mode), _TABLE_LINE_ALPHA))
    fmt.setBorderCollapse(True)
    table.setFormat(fmt)
    for row in range(table.rows()):
        for column in range(table.columns()):
            cell = table.cellAt(row, column)
            cell_format = cell.format().toTableCellFormat()
            cell_format.setLeftPadding(_CELL_PADDING_X)
            cell_format.setRightPadding(_CELL_PADDING_X)
            cell_format.setTopPadding(_CELL_PADDING_Y)
            cell_format.setBottomPadding(_CELL_PADDING_Y)
            cell.setFormat(cell_format)
    if not _is_head_row(table):
        return
    for column in range(table.columns()):
        cell = table.cellAt(0, column)
        cell_format = cell.format()
        cell_format.setBackground(_alpha_brush(_ink(mode), _TABLE_HEAD_ALPHA))
        cell_format.setProperty(ORIGINAL_BG, "")
        cell.setFormat(cell_format)


def _decorated(fmt: QTextCharFormat, mode: str) -> QTextCharFormat | None:
    if fmt.isImageFormat():
        return None
    result = QTextCharFormat(fmt)
    changed = False
    foreground = _brush_color(fmt.foreground()) if fmt.hasProperty(QTextFormat.Property.ForegroundBrush) else None
    background = _brush_color(fmt.background()) if fmt.hasProperty(QTextFormat.Property.BackgroundBrush) else None

    if fmt.isAnchor() and foreground == link_color(mode).upper():
        result.setProperty(ORIGINAL_FG, "")  # 앱이 칠한 새 링크 색 (14번)
        changed = True
    elif foreground is not None and not fmt.isAnchor() and background is None:
        shown = display_text_color(foreground, mode)  # 예전 글자색도 여기서 보정한다 (21번)
        if shown.upper() != foreground:
            result.setForeground(QColor(shown))
            result.setProperty(ORIGINAL_FG, foreground)
            changed = True

    if background in _HIGHLIGHT_PAIRS:
        if mode == "dark":
            result.setBackground(QColor(_HIGHLIGHT_PAIRS[background]))
            result.setProperty(ORIGINAL_BG, background)
            changed = True
    elif background is not None and foreground is None:
        result.setForeground(QColor(better_ink(background)))  # 예전 배경색 (16번)
        result.setProperty(ORIGINAL_FG, "")
        changed = True
    return result if changed else None


def _set_line_heights(doc: QTextDocument) -> None:
    block = doc.begin()
    height_type = QTextBlockFormat.LineHeightTypes.ProportionalHeight.value
    while block.isValid():
        block_format = block.blockFormat()
        block_format.setLineHeight(T.MEMO_LINE_HEIGHT_PERCENT, height_type)
        QTextCursor(block).setBlockFormat(block_format)
        block = block.next()


def prepare_document(doc: QTextDocument) -> None:
    """HTML을 넣기 전에 부른다. 새 링크 색은 파서가 이 규칙으로 칠한다."""
    from theme import apply as A

    doc.setDefaultStyleSheet(f"a {{ color: {link_color(A.current_mode())}; }}")


def decorate(doc: QTextDocument, mode: str) -> None:
    """불러온 문서를 화면 모드에 맞춰 칠한다. 호출한 쪽에서 undo 기록을 지운다."""
    changes = []
    for position, length, fmt in _fragments(doc):
        new_format = _decorated(fmt, mode)
        if new_format is not None:
            changes.append((position, length, new_format))
    _apply_char_formats(doc, changes)
    _set_line_heights(doc)
    for table in _tables(doc.rootFrame()):
        decorate_table(table, mode)


def _restored(fmt: QTextCharFormat) -> QTextCharFormat | None:
    has_fg, has_bg = fmt.hasProperty(ORIGINAL_FG), fmt.hasProperty(ORIGINAL_BG)
    if not has_fg and not has_bg:
        return None
    result = QTextCharFormat(fmt)
    if has_fg:
        original = fmt.stringProperty(ORIGINAL_FG)
        result.clearProperty(ORIGINAL_FG)
        if original:
            result.setForeground(QColor(original))
        else:
            result.clearForeground()
    if has_bg:
        original = fmt.stringProperty(ORIGINAL_BG)
        result.clearProperty(ORIGINAL_BG)
        if original:
            result.setBackground(QColor(original))
        else:
            result.clearBackground()
    return result


def saved_html(doc: QTextDocument) -> str:
    """저장할 HTML. 표시용 색과 줄 높이를 뺀 밝은 화면 값이다. 원본 문서는 건드리지 않는다."""
    clone = doc.clone()
    changes = []
    for position, length, fmt in _fragments(clone):
        restored = _restored(fmt)
        if restored is not None:
            changes.append((position, length, restored))
    _apply_char_formats(clone, changes)

    block = clone.begin()
    while block.isValid():
        block_format = block.blockFormat()
        block_format.clearProperty(QTextFormat.Property.LineHeight)
        block_format.clearProperty(QTextFormat.Property.LineHeightType)
        QTextCursor(block).setBlockFormat(block_format)
        block = block.next()

    for table in _tables(clone.rootFrame()):
        fmt = table.format()
        fmt.clearProperty(QTextFormat.Property.FrameBorderBrush)
        fmt.clearProperty(QTextFormat.Property.TableBorderCollapse)
        table.setFormat(fmt)
        for row in range(table.rows()):
            for column in range(table.columns()):
                cell = table.cellAt(row, column)
                cell_format = cell.format()
                for prop in _CELL_PADDING_PROPS:
                    cell_format.clearProperty(prop)
                if cell_format.hasProperty(ORIGINAL_BG):
                    cell_format.clearBackground()
                    cell_format.clearProperty(ORIGINAL_BG)
                cell.setFormat(cell_format)
    return clone.toHtml()


def text_color_format(light: str | None, mode: str) -> QTextCharFormat:
    """글자색 지정. light가 None이면 기본 글자색으로 돌아간다."""
    fmt = QTextCharFormat()
    if light is None:
        fmt.setForeground(QColor(_ink(mode)))
        fmt.setProperty(ORIGINAL_FG, "")
        return fmt
    fmt.setForeground(QColor(display_text_color(light, mode)))
    fmt.setProperty(ORIGINAL_FG, light)
    return fmt


def highlight_format(light: str, mode: str) -> QTextCharFormat:
    """형광펜·배경색 지정. 목록에 없는 색은 글자색도 잘 보이는 쪽으로 칠한다 (16번)."""
    fmt = QTextCharFormat()
    if light.upper() in _HIGHLIGHT_PAIRS:
        fmt.setBackground(QColor(display_highlight(light, mode)))
        fmt.setProperty(ORIGINAL_BG, light)
        return fmt
    fmt.setBackground(QColor(light))
    fmt.setForeground(QColor(better_ink(light)))
    fmt.setProperty(ORIGINAL_FG, "")
    return fmt


def clear_highlight_format() -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setBackground(QBrush(Qt.GlobalColor.transparent))
    fmt.setProperty(ORIGINAL_BG, "")
    return fmt


def link_format(href: str, mode: str) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setAnchor(True)
    fmt.setAnchorHref(href)
    fmt.setForeground(QColor(link_color(mode)))
    fmt.setProperty(ORIGINAL_FG, "")
    fmt.setFontUnderline(True)
    return fmt


# ----- 다른 PC에서 아직 못 받은 그림 (docs/sync-design.md 3.5) -----
IMAGE_PENDING_TEXT = "그림을 받는 중이에요"
IMAGE_TOO_BIG_TEXT = "다른 PC의 그림 하나가 너무 커서 받지 못했어요"
too_big_images: set[str] = set()  # 다른 PC가 너무 커서 못 올린 그림 해시 (동기화가 채운다)


def _image_names(doc: QTextDocument) -> list[str]:
    """문서 HTML의 <img src>. 문서의 글 조각을 하나씩 훑지 않는다 — 앱이 켜져 있는 동안 메모 문서마다
    훑으면 창을 정리할 때 드물게 비정상 종료됐다(test_versions.py, 약 10%)."""
    import html
    import re

    return [html.unescape(m) for m in re.findall(r'<img\b[^>]*?\bsrc="([^"]+)"', doc.toHtml(), re.IGNORECASE)]


def placeholder_image(text: str, width: int = 440, height: int = 96) -> QImage:
    """그림 자리에 둘 회색 상자. 밝은·어두운 화면 모두에서 읽히게 반투명 회색만 쓴다."""
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QColor(128, 128, 128, 140))
    p.setBrush(QColor(128, 128, 128, 36))
    p.drawRoundedRect(1, 1, width - 2, height - 2, 8, 8)
    p.setPen(QColor(128, 128, 128))
    p.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return image


def fill_missing_images(doc: QTextDocument) -> int:
    """받을 자리(<images>/<sha>.png)인데 파일이 아직 없는 그림에 자리 표시를 넣는다.
    본문은 먼저 보이고, 그림이 오면 refresh_images가 바꿔 끼운다. 저장되는 HTML은 그대로다."""
    from sync import images

    count = 0
    for name in _image_names(doc):
        path = images.src_to_path(name)
        sha = images.named_sha(path)
        if sha and not path.exists():
            text = IMAGE_TOO_BIG_TEXT if sha in too_big_images else IMAGE_PENDING_TEXT
            doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(name), placeholder_image(text))
            count += 1
    return count


def refresh_images(doc: QTextDocument, arrived) -> bool:
    """방금 받은 그림 파일로 자리 표시를 바꾼다. 열려 있는 메모도 깨지지 않고 그 자리에 그려진다."""
    from sync import images

    wanted = {str(p.resolve()) for p in arrived}
    changed = False
    for name in set(_image_names(doc)):
        path = images.src_to_path(name)
        try:
            hit = str(path.resolve()) in wanted
        except OSError:
            continue
        if hit:
            image = QImage(str(path))
            if not image.isNull():
                doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(name), image)
                changed = True
    if changed:
        doc.markContentsDirty(0, doc.characterCount())
    return changed
