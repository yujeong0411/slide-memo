"""설정 창 (일반 / AI / 동기화 / 정보 탭)."""
from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QIcon
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import autostart
from ai_provider import (
    AI_KEY_ENABLED,
    AI_KEY_MODEL,
    AI_KEY_PROVIDER,
    AI_KEY_SHOW_PREVIEW,
    AI_KEY_USAGE_RESET,
    AI_KEY_USAGE_TOKENS,
    PROVIDERS,
    AIProvider,
    delete_api_key,
    load_api_key,
    save_api_key,
)
from database import MemoDatabase
from theme import apply as A
from theme import tokens as T
from theme.widgets import AppDialog, ThemedCombo, line, make_button, notify, role_label

_KEY_HELP_URLS: dict[str, str] = {
    "anthropic": "https://console.anthropic.com/",
    "openai": "https://platform.openai.com/api-keys",
    "gemini": "https://aistudio.google.com/apikey",
    "ollama": "https://ollama.com/download",
}

_COST_PER_1K: dict[str, float] = {
    "anthropic": 0.0008,
    "openai": 0.003,
    "gemini": 0.0,
    "ollama": 0.0,
}

_LABEL_WIDTH = 112


class _TestWorker(QThread):
    result_ready = pyqtSignal(bool, str)

    def __init__(self, provider: str, model: str, key: str | None) -> None:
        super().__init__()
        self._provider = provider
        self._model = model
        self._key = key

    def run(self) -> None:
        ai = AIProvider(self._provider, self._model, self._key)
        ok, msg = ai.test_connection()
        self.result_ready.emit(ok, msg)


def _form() -> QFormLayout:
    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setHorizontalSpacing(12)
    form.setVerticalSpacing(12)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    return form


def _add_row(form: QFormLayout, text: str, field) -> None:
    label = QLabel(text)
    label.setFixedWidth(_LABEL_WIDTH)
    form.addRow(label, field)


def _status(label: QLabel, text: str, error: bool = False) -> None:
    label.setProperty("state", "error" if error else "")
    A.repolish(label)
    label.setText(text)
    label.setVisible(bool(text))  # 비어 있을 때 자리를 차지하면 묶음 간격이 벌어진다


def _eye_button(edit: QLineEdit) -> QPushButton:
    button = make_button("", "icon")
    button.setCheckable(True)
    button.setToolTip("키 보이기 / 숨기기")

    def sync(shown: bool) -> None:
        edit.setEchoMode(QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password)
        icon = A.tinted_pixmap("eye-off.svg" if shown else "eye.svg", A.current()["fg_secondary"], 16)
        button.setIcon(QIcon(icon))

    button.toggled.connect(sync)
    sync(False)
    return button


class SettingsDialog(QDialog):
    def __init__(self, db: MemoDatabase, parent: QWidget | None = None, *, tab: str = "") -> None:
        super().__init__(parent)
        self.db = db
        self._test_worker: _TestWorker | None = None
        self._original_key: str | None = None

        self.setWindowTitle("설정")
        self.setFixedWidth(500)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 12, 0, 0)
        root.setSpacing(0)

        tabs = QTabWidget()
        tabs.addTab(self._build_general_tab(), "일반")
        tabs.addTab(self._build_ai_tab(), "AI")
        from sync.settings_tab import SyncTab  # 동기화 탭은 따로 둔다 (설계 6장)

        self._sync_tab = SyncTab(db, getattr(parent, "sync", None), open_versions=getattr(parent, "_show_versions", None))
        tabs.addTab(self._sync_tab, "동기화")
        tabs.addTab(self._build_info_tab(), "정보")
        for index, asset in enumerate(("sliders-horizontal.svg", "sparkles.svg", "refresh-cw.svg", "info.svg")):
            tabs.setTabIcon(index, QIcon(A.tinted_pixmap(asset, A.current()["fg_secondary"], 16)))
        if tab == "sync":
            tabs.setCurrentWidget(self._sync_tab)
        root.addWidget(tabs)
        self._tabs = tabs

        # 일반·AI 탭은 [취소]·[저장하기], 바로 적용되는 동기화·정보 탭은 [닫기]만 (9장 38)
        root.addWidget(line())
        footer = QHBoxLayout()
        footer.setContentsMargins(24, 16, 24, 16)
        footer.setSpacing(8)
        footer.addStretch(1)
        self._cancel_btn = make_button("취소")
        self._cancel_btn.clicked.connect(self._discard)
        footer.addWidget(self._cancel_btn)
        self._save_btn = make_button("저장하기", "primary")
        self._save_btn.clicked.connect(self._save_and_accept)
        footer.addWidget(self._save_btn)
        self._close_btn = make_button("닫기")
        self._close_btn.clicked.connect(self.reject)
        footer.addWidget(self._close_btn)
        root.addLayout(footer)

        self._load_settings()
        self._initial = self._collect()
        tabs.currentChanged.connect(self._update_footer)
        self._update_footer()

    # ── 아래 단추와 저장하지 않은 변경 ──────────────────────────────
    _EDITABLE_TABS = (0, 1)  # 일반, AI

    def _update_footer(self) -> None:
        editable = self._tabs.currentIndex() in self._EDITABLE_TABS
        self._cancel_btn.setVisible(editable)
        self._save_btn.setVisible(editable)
        self._close_btn.setVisible(not editable)
        self._save_btn.setDefault(editable)
        self._close_btn.setDefault(not editable)

    def _collect(self) -> tuple:
        """저장하기가 저장하는 값들 (일반·AI 탭). 열었을 때와 다르면 저장하지 않은 변경이 있다."""
        return (
            self._theme_combo.currentData(), self._side_combo.currentData(),
            self._display_mode_combo.currentData(), self._tab_width_slider.value(),
            self._memo_tab_height_slider.value(), self._opacity_slider.value(),
            self._autostart_chk.isChecked(), self._ai_enabled_chk.isChecked(),
            self._provider_combo.currentData(), self._model_combo.currentData(),
            self._key_edit.text().strip(), self._preview_chk.isChecked(),
            self._recording_enabled_chk.isChecked(), self._recording_keep_chk.isChecked(),
            self._recording_max_spin.value(), self._whisper_key_edit.text().strip(),
        )

    def has_unsaved_changes(self) -> bool:
        return self._collect() != self._initial

    def _discard(self) -> None:
        """[취소]: 이번에 바꾼 것을 버리고 닫는다 (묻지 않는다)."""
        super().reject()

    def reject(self) -> None:
        """창 닫기·Esc·[닫기]. 저장하지 않은 변경이 있으면 먼저 묻는다."""
        if not self.has_unsaved_changes():
            super().reject()
            return
        ask = AppDialog("저장하지 않은 변경이 있어요", self)
        text = role_label("일반·AI 탭에서 바꾼 설정을 아직 저장하지 않았어요.", "description")
        text.setWordWrap(True)
        ask.body.addWidget(text)
        cancel = ask.add_button("취소")
        cancel.clicked.connect(ask.reject)
        discard = ask.add_button("저장하지 않고 닫기")
        discard.clicked.connect(lambda: ask.done(2))
        save = ask.add_button("저장하고 닫기", "primary")
        save.clicked.connect(lambda: ask.done(1))
        save.setDefault(True)
        result = ask.exec()
        if result == 1:
            self._save_and_accept()
        elif result == 2:
            super().reject()

    def _combo(self) -> QComboBox:
        return ThemedCombo()

    def _slider_row(self, low: int, high: int, page: int) -> tuple[QHBoxLayout, QSlider, QLabel]:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(low, high)
        slider.setSingleStep(1)
        slider.setPageStep(page)
        value = role_label("", "value")
        value.setFixedWidth(52)
        value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        A.set_tabular(value)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        row.addWidget(slider, 1)
        row.addWidget(value)
        return row, slider, value

    # ── 일반 탭 ──────────────────────────────────────────────────
    def _build_general_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)

        outer.addWidget(role_label("화면", "group"))
        screen_form = _form()
        self._theme_combo = self._combo()
        self._theme_combo.addItem("시스템 설정 따르기", "system")
        self._theme_combo.addItem("밝게", "light")
        self._theme_combo.addItem("어둡게", "dark")
        _add_row(screen_form, "화면 모드", self._theme_combo)
        self._side_combo = self._combo()
        self._side_combo.addItem("오른쪽 가장자리", 0)
        self._side_combo.addItem("왼쪽 가장자리", 1)
        _add_row(screen_form, "붙는 위치", self._side_combo)
        self._display_mode_combo = self._combo()
        self._display_mode_combo.addItem("숨기기 (트레이에만 표시)", "tray")
        self._display_mode_combo.addItem("표시 (트레이에는 숨기기)", "taskbar")
        self._display_mode_combo.addItem("작업 표시줄과 트레이 모두 표시", "both")
        _add_row(screen_form, "작업 표시줄", self._display_mode_combo)
        outer.addLayout(screen_form)

        outer.addSpacing(12)
        outer.addWidget(role_label("인덱스 탭", "group"))
        tab_form = _form()
        width_row, self._tab_width_slider, self._tab_width_lbl = self._slider_row(24, 100, 4)
        self._tab_width_slider.valueChanged.connect(
            lambda v: self._tab_width_lbl.setText(f"{v} px")
        )
        _add_row(tab_form, "탭 너비", width_row)
        height_row, self._memo_tab_height_slider, self._memo_tab_height_lbl = self._slider_row(60, 200, 10)
        self._memo_tab_height_slider.valueChanged.connect(
            lambda v: self._memo_tab_height_lbl.setText(f"{v} px")
        )
        _add_row(tab_form, "탭 높이", height_row)
        opacity_row, self._opacity_slider, self._opacity_lbl = self._slider_row(50, 100, 5)
        self._opacity_slider.valueChanged.connect(self._on_opacity_preview)
        _add_row(tab_form, "창 불투명도", opacity_row)
        outer.addLayout(tab_form)

        outer.addSpacing(12)
        outer.addWidget(role_label("동작", "group"))
        self._autostart_chk = QCheckBox("Windows를 켤 때 자동으로 실행")
        outer.addWidget(self._autostart_chk)
        if not autostart.is_supported():
            self._autostart_chk.setEnabled(False)
            outer.addWidget(role_label("이 운영체제에서는 쓸 수 없습니다.", "hint"))

        # 사용법 안내(말풍선 가이드) 다시 보기 — 창을 닫으면 처음부터 시작한다
        guide_row = QHBoxLayout()
        guide_btn = make_button("사용법 다시 보기")
        guide_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        guide_btn.clicked.connect(self._request_guide_restart)
        guide_row.addWidget(guide_btn)
        guide_row.addStretch(1)
        outer.addLayout(guide_row)

        outer.addStretch(1)
        return w

    def _request_guide_restart(self) -> None:
        """설정 창이 닫힌 뒤 메인 창이 가이드를 다시 시작한다 (여기선 표시만)."""
        self.restart_guide_requested = True
        self.accept()

    # ── AI 탭 ────────────────────────────────────────────────────
    def _key_row(self, edit: QLineEdit, placeholder: str, test_slot) -> tuple[QHBoxLayout, QPushButton, QPushButton]:
        edit.setEchoMode(QLineEdit.EchoMode.Password)
        edit.setPlaceholderText(placeholder)
        eye = _eye_button(edit)
        test = make_button("키 확인하기")
        test.clicked.connect(test_slot)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(edit, 1)
        row.addWidget(eye)
        row.addWidget(test)
        return row, eye, test

    def _build_ai_tab(self) -> QWidget:
        # 내용물이 길어서 탭 자체를 스크롤 영역으로 감싼다 — 다른 탭(일반/정보)의
        # 작은 높이에 맞춰 다이얼로그 전체 크기가 결정되도록.
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)

        self._ai_enabled_chk = QCheckBox("AI 기능 사용")
        outer.addWidget(self._ai_enabled_chk)

        # 나머지 AI 설정을 묶는 컨테이너 (토글로 한 번에 enable/disable)
        self._ai_body = QWidget()
        form = _form()
        self._ai_body.setLayout(form)

        self._provider_combo = self._combo()
        for pid, pinfo in PROVIDERS.items():
            self._provider_combo.addItem(pinfo["name"], pid)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        _add_row(form, "제공자", self._provider_combo)

        self._key_edit = QLineEdit()
        key_row, self._eye_btn, self._test_btn = self._key_row(self._key_edit, "API 키 입력", self._run_test)
        self._key_row_widget = QWidget()
        self._key_row_widget.setLayout(key_row)
        _add_row(form, "API 키", self._key_row_widget)

        self._key_help_lbl = role_label("", "hint")
        self._key_help_lbl.setOpenExternalLinks(False)
        self._key_help_lbl.linkActivated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        form.addRow("", self._key_help_lbl)

        self._model_combo = self._combo()
        _add_row(form, "모델", self._model_combo)
        outer.addWidget(self._ai_body)

        outer.addSpacing(12)
        outer.addWidget(role_label("이번 달 사용량", "group"))
        usage_row = QHBoxLayout()
        self._usage_lbl = QLabel("토큰: 0")
        A.set_tabular(self._usage_lbl)
        usage_row.addWidget(self._usage_lbl)
        usage_row.addStretch(1)
        reset_btn = make_button("통계 지우기")
        reset_btn.clicked.connect(self._reset_usage)
        usage_row.addWidget(reset_btn)
        outer.addLayout(usage_row)

        self._preview_chk = QCheckBox("AI 결과를 넣기 전에 미리 보기")
        outer.addWidget(self._preview_chk)

        self._test_result_lbl = role_label("", "hint")
        self._test_result_lbl.setWordWrap(True)
        self._test_result_lbl.hide()
        outer.addWidget(self._test_result_lbl)

        outer.addSpacing(12)
        outer.addWidget(role_label("음성 녹음 (Whisper)", "group"))
        self._recording_enabled_chk = QCheckBox("음성 녹음 기능 사용 (마이크 단추 켜기)")
        outer.addWidget(self._recording_enabled_chk)
        self._recording_keep_chk = QCheckBox("녹음 파일을 메모에 첨부")
        outer.addWidget(self._recording_keep_chk)

        rec_form = _form()
        self._recording_max_spin = QSpinBox()
        self._recording_max_spin.setRange(60, 600)
        self._recording_max_spin.setSingleStep(30)
        self._recording_max_spin.setValue(300)
        self._recording_max_spin.setFixedWidth(112)
        A.set_tabular(self._recording_max_spin)
        _add_row(rec_form, "최대 녹음 시간(초)", self._recording_max_spin)
        outer.addLayout(rec_form)

        # Whisper용 OpenAI 키. AI 제공자가 OpenAI면 keyring 항목이 같아서
        # 칸이 두 개면 서로 덮어쓴다 → 그때는 이 칸을 숨기고 안내만 띄운다.
        self._whisper_key_widget = QWidget()
        wk_col = QVBoxLayout(self._whisper_key_widget)
        wk_col.setContentsMargins(0, 0, 0, 0)
        wk_col.setSpacing(8)
        self._whisper_key_edit = QLineEdit()
        whisper_row, self._whisper_eye_btn, self._whisper_test_btn = self._key_row(
            self._whisper_key_edit, "Whisper용 OpenAI API 키", self._run_whisper_test
        )
        wk_col.addLayout(whisper_row)
        self._whisper_test_lbl = role_label("", "hint")
        self._whisper_test_lbl.setWordWrap(True)
        self._whisper_test_lbl.hide()
        wk_col.addWidget(self._whisper_test_lbl)
        whisper_key_help = role_label(
            '<a href="https://platform.openai.com/api-keys">OpenAI API 키 발급 페이지 →</a>', "hint"
        )
        whisper_key_help.setOpenExternalLinks(False)
        whisper_key_help.linkActivated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        wk_col.addWidget(whisper_key_help)
        outer.addWidget(self._whisper_key_widget)

        self._whisper_shared_lbl = role_label("AI 제공자가 OpenAI라서 위에 넣은 키를 그대로 써요.", "hint")
        self._whisper_shared_lbl.setWordWrap(True)
        outer.addWidget(self._whisper_shared_lbl)

        rec_note = role_label("Whisper API 비용은 분당 약 $0.006이에요. 마이크 권한이 필요해요.", "hint")
        rec_note.setWordWrap(True)
        outer.addWidget(rec_note)

        outer.addStretch(1)

        self._ai_enabled_chk.toggled.connect(self._ai_body.setEnabled)
        # QScrollArea로 감싸 다이얼로그 자체 높이가 길어지지 않도록
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(w)
        return scroll

    # ── 정보 탭 ──────────────────────────────────────────────────
    def _build_info_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)
        layout.addWidget(QLabel("<b>SlideMemo</b>"))
        from main import APP_VERSION
        layout.addWidget(QLabel(f"버전: {APP_VERSION}"))
        layout.addWidget(role_label("PyQt6로 만든 Windows 슬라이드 메모장", "description"))
        layout.addSpacing(8)
        copyright_lbl = role_label("© 2026 nursecoder<br>MIT License", "hint")
        copyright_lbl.setWordWrap(True)
        layout.addWidget(copyright_lbl)
        layout.addSpacing(8)
        db_lbl = role_label(f"데이터 위치: {self.db.db_path.parent}", "hint")
        db_lbl.setWordWrap(True)
        layout.addWidget(db_lbl)
        open_row = QHBoxLayout()
        open_btn = make_button("데이터 폴더 열기")
        open_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.db.db_path.parent)))
        )
        open_row.addWidget(open_btn)
        open_row.addStretch(1)
        layout.addLayout(open_row)
        layout.addStretch(1)
        return w

    def _on_opacity_preview(self, v: int) -> None:
        self._opacity_lbl.setText(f"{v}%")
        # 부모(메모 창)에 실시간 반영. 취소하면 main이 닫은 뒤 DB값으로 되돌림.
        p = self.parent()
        if p is not None:
            p.setWindowOpacity(v / 100.0)

    # ── 설정 로드 ─────────────────────────────────────────────────
    def _load_settings(self) -> None:
        # 일반
        theme_index = self._theme_combo.findData(self.db.get_setting_str(A.THEME_MODE_KEY, "system"))
        self._theme_combo.setCurrentIndex(max(0, theme_index))
        side = self.db.get_setting_int("side", 0)
        self._side_combo.setCurrentIndex(1 if side == 1 else 0)
        mode = self.db.get_setting_str("display_mode", "tray")
        if mode not in ("tray", "taskbar", "both"):
            mode = "tray"
        idx = self._display_mode_combo.findData(mode)
        self._display_mode_combo.setCurrentIndex(max(0, idx))

        # 인덱스 탭 설정 (값/범위는 main.py 상수와 동일)
        tab_w = max(24, min(self.db.get_setting_int("tab_width", T.TAB_WIDTH_DEFAULT), 100))
        self._tab_width_slider.setValue(tab_w)
        self._tab_width_lbl.setText(f"{tab_w} px")
        tab_h = max(60, min(self.db.get_setting_int("memo_tab_height", T.TAB_HEIGHT_DEFAULT), 200))
        self._memo_tab_height_slider.setValue(tab_h)
        self._memo_tab_height_lbl.setText(f"{tab_h} px")

        op = max(50, min(self.db.get_setting_int("window_opacity", 100), 100))
        self._opacity_slider.setValue(op)
        self._opacity_lbl.setText(f"{op}%")

        # 자동 실행: OS의 실제 등록 상태가 진실
        if autostart.is_supported():
            self._autostart_chk.setChecked(autostart.is_enabled())

        # AI
        enabled = self.db.get_setting_str(AI_KEY_ENABLED, "0") == "1"
        provider = self.db.get_setting_str(AI_KEY_PROVIDER, "anthropic")
        model = self.db.get_setting_str(AI_KEY_MODEL, "")
        show_preview = self.db.get_setting_str(AI_KEY_SHOW_PREVIEW, "0") == "1"
        tokens = int(self.db.get_setting_str(AI_KEY_USAGE_TOKENS, "0") or "0")

        # provider 콤보 (signal 차단 후 설정 → 직접 초기화)
        self._provider_combo.blockSignals(True)
        idx = self._provider_combo.findData(provider)
        self._provider_combo.setCurrentIndex(max(0, idx))
        self._provider_combo.blockSignals(False)

        # 모델/키/도움말 초기화
        self._apply_provider_ui(provider, model)

        self._ai_enabled_chk.setChecked(enabled)
        self._ai_body.setEnabled(enabled)
        self._preview_chk.setChecked(show_preview)

        # 음성 녹음 설정
        self._recording_enabled_chk.setChecked(
            self.db.get_setting_int("recording_enabled", 0) == 1
        )
        self._recording_keep_chk.setChecked(
            self.db.get_setting_int("recording_keep_audio", 0) == 1
        )
        max_s = self.db.get_setting_int("recording_max_seconds", 300)
        self._recording_max_spin.setValue(max(60, min(max_s, 600)))
        # Whisper용 OpenAI 키 (provider가 openai면 같은 항목을 공유)
        self._whisper_original_key = load_api_key("openai") or ""
        self._whisper_key_edit.setText(self._whisper_original_key)

        self._check_monthly_reset()
        tokens = int(self.db.get_setting_str(AI_KEY_USAGE_TOKENS, "0") or "0")
        self._update_usage_lbl(tokens, provider)

    def _apply_provider_ui(self, provider: str, current_model: str = "") -> None:
        """제공자에 맞게 키 필드/도움말/모델 콤보 갱신."""
        needs_key = PROVIDERS.get(provider, {}).get("needs_key", True)

        self._key_row_widget.setVisible(needs_key)
        self._key_help_lbl.setVisible(needs_key)

        # provider가 openai면 Whisper도 같은 keyring 항목을 쓴다.
        # 칸을 따로 두면 한쪽 저장이 다른 쪽을 덮어쓰므로 안내로 대체한다.
        shared_openai = provider == "openai"
        self._whisper_key_widget.setVisible(not shared_openai)
        self._whisper_shared_lbl.setVisible(shared_openai)

        if needs_key:
            url = _KEY_HELP_URLS.get(provider, "")
            self._key_help_lbl.setText(f'<a href="{url}">API 키 발급 페이지 →</a>')
            self._original_key = load_api_key(provider)
            self._key_edit.setText(self._original_key or "")
        else:
            self._original_key = None

        # 모델 콤보
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        models = PROVIDERS.get(provider, {}).get("models", [])
        for m in models:
            self._model_combo.addItem(m, m)
        # 이미 고른 모델이 목록에서 빠졌으면(구버전 ID 등) 항목으로 되살려 둔다.
        # 그냥 두면 콤보가 0번으로 떨어져 사용자가 고른 적 없는 모델로 조용히
        # 바뀐다 — 0번은 대개 가장 비싼 모델이라 요금까지 달라진다.
        if current_model and current_model not in models:
            self._model_combo.addItem(f"{current_model} (이전 버전)", current_model)
            models = models + [current_model]
        if current_model not in models:
            current_model = PROVIDERS.get(provider, {}).get("default_model", "")
        if current_model in models:
            self._model_combo.setCurrentIndex(models.index(current_model))
        self._model_combo.blockSignals(False)

    def _check_monthly_reset(self) -> None:
        stored_ym = self.db.get_setting_str(AI_KEY_USAGE_RESET, "")
        current_ym = datetime.now().strftime("%Y-%m")
        if stored_ym != current_ym:
            self.db.set_setting_str(AI_KEY_USAGE_TOKENS, "0")
            self.db.set_setting_str(AI_KEY_USAGE_RESET, current_ym)

    def _update_usage_lbl(self, tokens: int, provider: str) -> None:
        cost = tokens / 1000.0 * _COST_PER_1K.get(provider, 0.001)
        if cost > 0:
            self._usage_lbl.setText(f"토큰: {tokens:,}  (예상 비용: ${cost:.3f})")
        else:
            self._usage_lbl.setText(f"토큰: {tokens:,}")

    # ── 이벤트 핸들러 ─────────────────────────────────────────────
    def _on_provider_changed(self) -> None:
        provider = self._provider_combo.currentData()
        current_model = self._model_combo.currentData() or ""
        self._apply_provider_ui(provider, current_model)
        tokens = int(self.db.get_setting_str(AI_KEY_USAGE_TOKENS, "0") or "0")
        self._update_usage_lbl(tokens, provider)
        _status(self._test_result_lbl, "")

    def _run_test(self) -> None:
        if self._test_worker and self._test_worker.isRunning():
            return
        provider = self._provider_combo.currentData()
        model = self._model_combo.currentData() or ""
        key = self._key_edit.text().strip() or None

        self._test_btn.setEnabled(False)
        _status(self._test_result_lbl, "확인하는 중이에요")

        self._test_worker = _TestWorker(provider, model, key)
        self._test_worker.result_ready.connect(self._on_test_result)
        self._test_worker.start()

    def _on_test_result(self, ok: bool, msg: str) -> None:
        self._test_btn.setEnabled(True)
        _status(self._test_result_lbl, msg, error=not ok)

    def _run_whisper_test(self) -> None:
        key = self._whisper_key_edit.text().strip()
        if not key:
            _status(self._whisper_test_lbl, "키를 먼저 넣어 주세요.")
            return
        self._whisper_test_btn.setEnabled(False)
        _status(self._whisper_test_lbl, "확인하는 중이에요")
        try:
            from openai import OpenAI
            client = OpenAI(api_key=key)
            client.models.list()
            _status(self._whisper_test_lbl, "OpenAI 키가 정상이에요.")
        except Exception as e:
            _status(self._whisper_test_lbl, f"확인하지 못했어요: {type(e).__name__}: {e}", error=True)
        finally:
            self._whisper_test_btn.setEnabled(True)

    def _reset_usage(self) -> None:
        self.db.set_setting_str(AI_KEY_USAGE_TOKENS, "0")
        self.db.set_setting_str(AI_KEY_USAGE_RESET, datetime.now().strftime("%Y-%m"))
        provider = self._provider_combo.currentData()
        self._update_usage_lbl(0, provider)

    # ── 저장 ─────────────────────────────────────────────────────
    def _save_and_accept(self) -> None:
        provider = self._provider_combo.currentData()
        model = (
            self._model_combo.currentData()
            or PROVIDERS.get(provider, {}).get("default_model", "")
        )

        # API 키 — 변경된 경우만 keyring 갱신
        if PROVIDERS.get(provider, {}).get("needs_key"):
            new_key = self._key_edit.text().strip()
            if new_key != (self._original_key or ""):
                delete_api_key(provider)      # 비웠으면 지우고 끝
                if new_key:
                    save_api_key(provider, new_key)

        self.db.set_setting_str(
            AI_KEY_ENABLED, "1" if self._ai_enabled_chk.isChecked() else "0"
        )
        self.db.set_setting_str(AI_KEY_PROVIDER, provider)
        self.db.set_setting_str(AI_KEY_MODEL, model)
        self.db.set_setting_str(
            AI_KEY_SHOW_PREVIEW, "1" if self._preview_chk.isChecked() else "0"
        )
        self.db.set_setting_str(A.THEME_MODE_KEY, self._theme_combo.currentData())
        self.db.set_setting_int("side", self._side_combo.currentData())
        self.db.set_setting_str(
            "display_mode", self._display_mode_combo.currentData() or "tray"
        )

        # 인덱스 탭 설정
        self.db.set_setting_int("tab_width", self._tab_width_slider.value())
        self.db.set_setting_int(
            "memo_tab_height", self._memo_tab_height_slider.value()
        )
        self.db.set_setting_int("window_opacity", self._opacity_slider.value())

        # 자동 실행: 현재 OS 상태와 다르면 set_enabled 호출, 실패하면 알림
        if autostart.is_supported():
            want = self._autostart_chk.isChecked()
            current = autostart.is_enabled()
            if want != current:
                ok, msg = autostart.set_enabled(want)
                if not ok:
                    notify(self, "자동 실행을 바꾸지 못했어요", msg, warning=True)

        # 음성 녹음
        self.db.set_setting_int(
            "recording_enabled",
            1 if self._recording_enabled_chk.isChecked() else 0,
        )
        self.db.set_setting_int(
            "recording_keep_audio",
            1 if self._recording_keep_chk.isChecked() else 0,
        )
        self.db.set_setting_int(
            "recording_max_seconds", self._recording_max_spin.value()
        )
        # Whisper 키 — 변경됐을 때만 keyring 갱신.
        # provider가 openai면 같은 항목이라 위 블록이 이미 처리했다 (덮어쓰기 방지).
        whisper_key = self._whisper_key_edit.text().strip()
        if provider != "openai" and whisper_key != self._whisper_original_key:
            if self._whisper_original_key:
                delete_api_key("openai")
            if whisper_key:
                save_api_key("openai", whisper_key)

        self.accept()
