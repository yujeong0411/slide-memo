"""단계별 캡처를 밝은/어두운 짝으로 묶은 검토용 그림을 만든다.

사용법: python tools/review_sheet.py step-2 real_60_settings 52_settings_ai_on ...
결과: docs/ui-audit-after/review/step-2-1.png, step-2-2.png (한 장에 4줄)
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
AFTER = ROOT / "docs" / "ui-audit-after"
FONT = ROOT / "assets" / "fonts" / "Pretendard-Medium.otf"

SHEET_WIDTH = 2000
MARGIN = 16
GAP = 16
CAPTION_SIZE = 24
CAPTION_HEIGHT = 40
ROW_GAP = 28
ROWS_PER_SHEET = 4
BACKGROUND = (154, 157, 165)  # 흰 창과 어두운 창이 둘 다 경계가 보이는 중간 회색
CAPTION_COLOR = (0, 0, 0)
CELL_WIDTH = (SHEET_WIDTH - 2 * MARGIN - GAP) // 2


def load_cell(path: Path) -> Image.Image:
    """반투명 캡처는 배경 위에 합성하고, 칸보다 넓을 때만 줄인다."""
    image = Image.open(path).convert("RGBA")
    if image.width > CELL_WIDTH:
        height = round(image.height * CELL_WIDTH / image.width)
        image = image.resize((CELL_WIDTH, height), Image.Resampling.LANCZOS)
    flat = Image.new("RGB", image.size, BACKGROUND)
    flat.paste(image, (0, 0), image)
    return flat


def build_sheet(folder: Path, names: list[str], font: ImageFont.FreeTypeFont) -> Image.Image:
    rows = [
        (name, load_cell(folder / f"{name}__light.png"), load_cell(folder / f"{name}__dark.png"))
        for name in names
    ]
    height = MARGIN + sum(
        CAPTION_HEIGHT + max(light.height, dark.height) + ROW_GAP for _, light, dark in rows
    )
    sheet = Image.new("RGB", (SHEET_WIDTH, height), BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    y = MARGIN
    for name, light, dark in rows:
        draw.text((MARGIN, y), name, font=font, fill=CAPTION_COLOR)
        y += CAPTION_HEIGHT
        sheet.paste(light, (MARGIN, y))
        sheet.paste(dark, (MARGIN + CELL_WIDTH + GAP, y))
        y += max(light.height, dark.height) + ROW_GAP
    return sheet


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    step, names = sys.argv[1], sys.argv[2:]
    folder = AFTER / step
    missing = [
        f"{name}__{mode}.png"
        for name in names
        for mode in ("light", "dark")
        if not (folder / f"{name}__{mode}.png").exists()
    ]
    if missing:
        print("캡처 파일이 없어요:", ", ".join(missing))
        return 1

    out = AFTER / "review"
    out.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(str(FONT), CAPTION_SIZE)
    for index in range(0, len(names), ROWS_PER_SHEET):
        number = index // ROWS_PER_SHEET + 1
        path = out / f"{step}-{number}.png"
        build_sheet(folder, names[index:index + ROWS_PER_SHEET], font).save(path)
        print(path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
