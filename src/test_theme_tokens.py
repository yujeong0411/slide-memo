# ponytail: 3장 기준 self-check. run: python src/test_theme_tokens.py
from theme import memo_tokens as M
from theme import tokens as T

MODES = ("light", "dark")
CUSTOM_SAMPLES = ["#E07A5F", "#000000", "#FFFFFF", "#808080", "#FFFF00", "#0000FF", "#00FF00", "#2F3650"]


def demo():
    assert set(T.LIGHT) == set(T.DARK), "밝은/어두운 토큰 이름이 달라요"

    # 문서 끝 '확인한 대비' 표 (허용 오차 0.02)
    table = [
        ("fg", "bg_canvas", 16.86, 14.13), ("fg", "bg_raised", 16.86, 11.58),
        ("fg_secondary", "bg_canvas", 7.96, 7.93), ("fg_secondary", "bg_sunken", 7.30, 8.87),
        ("fg_hint", "bg_canvas", 4.54, 6.13), ("fg_hint", "bg_raised", 4.54, 5.02),
        ("line_control", "bg_canvas", 3.71, 4.21), ("line_control", "bg_raised", 3.71, 3.45),
        ("line_control", "bg_sunken", 3.40, 4.71),
        ("accent_text", "bg_canvas", 6.41, 7.13), ("accent_text", "bg_raised", 6.41, 5.84),
        ("on_accent", "accent", 6.41, 5.50), ("accent", "bg_canvas", 6.41, 4.81),
        ("accent_strong", "accent_weak", 7.44, 5.86),
        ("danger", "bg_canvas", 7.13, 6.11), ("danger", "bg_raised", 7.13, 5.01),
        ("danger", "danger_weak", 6.10, 6.11), ("fg_secondary", "bg_muted", 6.68, 5.00),
    ]
    for fg, bg, light, dark in table:
        for tokens, want in ((T.LIGHT, light), (T.DARK, dark)):
            got = M.contrast(tokens[fg], tokens[bg])
            assert abs(got - want) <= 0.02, (fg, bg, got, want)
    assert abs(M.contrast(T.WHITE, T.LIGHT["danger_fill"]) - 7.13) <= 0.02
    assert abs(M.contrast(T.WHITE, T.LIGHT["contrast"]) - 13.02) <= 0.02
    assert abs(M.contrast(T.WHITE, T.DARK["contrast"]) - 6.29) <= 0.02
    assert abs(M.contrast(T.HIGHLIGHT_FG, T.LIGHT["highlight"]) - 12.87) <= 0.02
    assert abs(M.contrast(T.SELECTION_FG, T.SELECTION_BG) - 6.41) <= 0.02

    # 3.0 프리셋: 띠 4.1 이상, 면 위 글자 12 이상
    assert len(T.MEMO_PRESETS) == 8 and T.DEFAULT_MEMO_COLOR in T.MEMO_PRESETS
    for key in T.MEMO_PRESETS:
        for mode in MODES:
            t = M.memo_tokens(key, mode)
            assert M.contrast(t["memo_band"], t["memo_face"]) >= 4.1, (key, mode)
            assert M.contrast(t["memo_fg"], t["memo_face"]) >= 12, (key, mode)
            assert M.contrast(t["memo_fg_secondary"], t["memo_face"]) >= 7, (key, mode)
        assert M.memo_tokens(key, "light")["memo_fg"] == T.INK_DARK
        assert M.memo_tokens(key, "dark")["memo_fg"] == T.WHITE
        assert M.memo_tokens(key, "dark")["memo_face"] == T.DARK_MEMO_FACE

    # 3.2 기준: 프리셋과 직접 만든 색 모두
    for color in list(T.MEMO_PRESETS) + CUSTOM_SAMPLES:
        for mode in MODES:
            t = M.memo_tokens(color, mode)
            assert M.contrast(t["memo_fg"], t["memo_face"]) >= 12, (color, mode)
            assert M.contrast(t["memo_fg_secondary"], t["memo_face"]) >= 4.5, (color, mode)
            assert M.contrast(t["memo_hint"], t["memo_field"]) >= 4.5, (color, mode)
            assert M.contrast(t["memo_border"], t["memo_face"]) >= 3, (color, mode)
            assert M.contrast(t["memo_border"], t["memo_field"]) >= 3, (color, mode)
            assert M.contrast(t["memo_band"], t["memo_face"]) >= 3, (color, mode)
            assert M.contrast(t["memo_link"], t["memo_face"]) >= 4.5, (color, mode)
            assert all(v.startswith("#") and len(v) == 7 for v in t.values()), (color, mode)

    # 3.0.1 예시
    assert M.custom_tones("#E07A5F") == ("#FFF2EE", "#D26E53", "#E07A5F")

    # 비율 보정: 낮은 시작값에서 기준을 넘을 때까지 오른다
    raised = M.solve_ratio(T.INK_DARK, "#FFFFFF", 0.10, 4.5)
    assert M.contrast(raised, "#FFFFFF") >= 4.5
    assert M.solve_ratio(T.INK_DARK, "#FFFFFF", 0.76, 4.5) == M.mix(T.INK_DARK, "#FFFFFF", 0.76)

    # 링크가 4.5에 못 미치면 먹색으로 대체
    assert M.memo_tokens("gray", "light")["memo_link"] == T.MEMO_LINK_ON_LIGHT
    assert M.memo_tokens("gray", "dark")["memo_link"] == T.MEMO_LINK_ON_DARK
    original_link = T.MEMO_LINK_ON_LIGHT
    T.MEMO_LINK_ON_LIGHT = T.LIGHT["line"]  # 일부러 대비가 낮은 색
    try:
        assert M.memo_tokens("gray", "light")["memo_link"] == T.INK_DARK
    finally:
        T.MEMO_LINK_ON_LIGHT = original_link

    # 9장 9: 글자색·형광펜 대비
    faces = [p[1] for p in T.MEMO_PRESETS.values()]
    assert len(T.TEXT_COLORS) == 10 and len(T.HIGHLIGHTS) == 5
    for name, light, dark in T.TEXT_COLORS:
        for face in faces:
            assert M.contrast(light, face) >= 4.5, (name, light, face, M.contrast(light, face))
        assert M.contrast(dark, T.DARK_MEMO_FACE) >= 4.5, (name, dark, M.contrast(dark, T.DARK_MEMO_FACE))
    for name, light, dark in T.HIGHLIGHTS:
        assert M.contrast(T.INK_DARK, light) >= 7, (name, light, M.contrast(T.INK_DARK, light))
        assert M.contrast(T.WHITE, dark) >= 7, (name, dark, M.contrast(T.WHITE, dark))

    # 저장값은 신뢰 경계: 깨진 색과 모드는 QSS로 흘러가지 않는다
    for bad in ("garbage", "#12345", "#GGGGGG", "red;}", ""):
        try:
            M.memo_tokens(bad, "light")
        except ValueError:
            continue
        raise AssertionError(f"거부되지 않음: {bad!r}")
    try:
        M.memo_tokens("gray", "sepia")
    except ValueError:
        pass
    else:
        raise AssertionError("잘못된 모드가 통과함")

    print("theme tokens OK")


if __name__ == "__main__":
    demo()
