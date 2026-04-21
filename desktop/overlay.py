"""
PyQt6 always-on-top transparent overlay — Cluely-style.

Role-aware UI:
  - INTERVIEWER label when a question is detected (other person speaking)
  - YOUR RESPONSE label when suggestions appear
  - Thin, semi-transparent like Cluely
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QFrame,
    QScrollArea, QSizePolicy,
)
from PyQt6.QtCore import Qt, QPoint, pyqtSignal, QObject
from PyQt6.QtGui import QColor

# ── Palette ───────────────────────────────────────────────────────────────────
BG        = "rgba(10, 10, 20, 210)"
SURFACE   = "rgba(15, 15, 25, 220)"
BORDER    = "#1e1e2e"
ACCENT    = "#6c63ff"
MUTED     = "#6b6b80"
SUCCESS   = "#22c55e"
TEXT      = "#e8e8f0"
WARN      = "#f59e0b"
INTER_CLR = "#60a5fa"   # blue  — interviewer / client / investor
USER_CLR  = "#a78bfa"   # purple — candidate / salesperson / founder

CONTEXTS = [
    "Software Engineering Interview",
    "Product Management Interview",
    "Sales Meeting",
    "Investor Pitch",
    "Performance Review",
    "General Meeting",
]

# Maps context → (other_role, user_role)
ROLE_MAP = {
    "Software Engineering Interview": ("INTERVIEWER", "YOUR RESPONSE"),
    "Product Management Interview":   ("INTERVIEWER", "YOUR RESPONSE"),
    "Sales Meeting":                  ("CLIENT",      "YOUR PITCH"),
    "Investor Pitch":                 ("INVESTOR",    "YOUR PITCH"),
    "Performance Review":             ("MANAGER",     "YOUR RESPONSE"),
    "General Meeting":                ("SPEAKER",     "YOUR RESPONSE"),
}


def _btn(text: str, bg: str = ACCENT, fg: str = "#fff") -> QPushButton:
    b = QPushButton(text)
    b.setStyleSheet(f"""
        QPushButton {{
            background: {bg}; color: {fg};
            border: none; border-radius: 6px;
            padding: 6px 14px; font-size: 12px; font-weight: 600;
        }}
        QPushButton:hover {{ background: {bg}; opacity: 0.85; }}
        QPushButton:disabled {{ background: {BORDER}; color: {MUTED}; }}
    """)
    return b


def _label(text: str, size: int = 12, color: str = TEXT, bold: bool = False) -> QLabel:
    lb = QLabel(text)
    lb.setStyleSheet(
        f"color: {color}; font-size: {size}px; font-weight: {'700' if bold else '400'};"
        " background: transparent;"
    )
    lb.setWordWrap(True)
    return lb


# ── Signal bridge ─────────────────────────────────────────────────────────────
class Bridge(QObject):
    transcript_ready  = pyqtSignal(str, bool)   # text, is_question
    suggestions_ready = pyqtSignal(list)
    status_update     = pyqtSignal(str)
    loading_start     = pyqtSignal()


# ── Suggestion card ───────────────────────────────────────────────────────────
class SuggestionCard(QFrame):
    used = pyqtSignal(str)

    def __init__(self, rank: int, item: dict):
        super().__init__()
        self._id = item.get("id", "")
        pct = int(item.get("predicted_success", 0.5) * 100)
        pct_color = SUCCESS if pct >= 60 else (WARN if pct >= 40 else MUTED)

        self.setStyleSheet(f"""
            QFrame {{
                background: rgba(20, 20, 35, 200);
                border: 1px solid {BORDER};
                border-radius: 8px;
            }}
        """)
        # expand vertically to fit content — never clip
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        # header row
        h = QHBoxLayout()
        rank_lbl = _label(f"#{rank}", 10, MUTED, bold=True)
        rank_lbl.setFixedWidth(24)
        h.addWidget(rank_lbl)
        h.addWidget(_label(item.get("angle", ""), 10, MUTED))
        h.addStretch()
        h.addWidget(_label(f"{pct}% match", 10, pct_color, bold=True))
        lay.addLayout(h)

        # full suggestion text — word wrap, no height limit
        text_lbl = QLabel(item.get("text", ""))
        text_lbl.setWordWrap(True)
        text_lbl.setStyleSheet(
            f"color: {TEXT}; font-size: 13px; background: transparent; line-height: 1.5;")
        text_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        text_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(text_lbl)

        # use button
        row = QHBoxLayout()
        row.addStretch()
        use = _btn("✓ Use this", SUCCESS)
        use.clicked.connect(self._use)
        row.addWidget(use)
        lay.addLayout(row)

    def _use(self):
        self.setStyleSheet(self.styleSheet().replace(BORDER, SUCCESS))
        self.used.emit(self._id)


# ── Main overlay ──────────────────────────────────────────────────────────────
class Overlay(QWidget):
    def __init__(self, bridge: Bridge, on_context_change, on_refresh,
                 on_end_session, on_mark_used):
        super().__init__()
        self._drag_pos: QPoint | None = None
        self._stars: list[QLabel] = []
        self._score = 0
        self._context = CONTEXTS[0]
        self._on_mark_used = on_mark_used

        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(460)
        self.setFixedHeight(560)   # stable fixed height — no jumping when suggestions load

        self._build(on_context_change, on_refresh, on_end_session)

        bridge.transcript_ready.connect(self._on_transcript)
        bridge.suggestions_ready.connect(self._on_suggestions)
        bridge.status_update.connect(self._on_status)
        bridge.loading_start.connect(self._on_loading)

    # ── Build UI ──────────────────────────────────────────────────────────

    def _build(self, on_ctx, on_refresh, on_end):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # outer container — thin, glassy
        self._container = QWidget()
        self._container.setStyleSheet(f"""
            QWidget#container {{
                background: {SURFACE};
                border: 1px solid {BORDER};
                border-radius: 14px;
            }}
        """)
        self._container.setObjectName("container")
        root.addWidget(self._container)

        main = QVBoxLayout(self._container)
        main.setContentsMargins(14, 10, 14, 14)
        main.setSpacing(10)

        # ── Title bar ─────────────────────────────────────────────────────
        tb = QHBoxLayout()
        self._dot = QLabel("●")
        self._dot.setStyleSheet(f"color: {MUTED}; font-size: 11px; background: transparent;")
        self._status_lbl = _label("Starting…", 11, MUTED)
        tb.addWidget(self._dot)
        tb.addWidget(self._status_lbl)
        tb.addStretch()

        self._ctx_combo = QComboBox()
        self._ctx_combo.addItems(CONTEXTS)
        self._ctx_combo.setStyleSheet(f"""
            QComboBox {{
                background: rgba(20,20,35,180); color: {TEXT};
                border: 1px solid {BORDER}; border-radius: 5px;
                padding: 3px 8px; font-size: 11px; min-width: 180px;
            }}
            QComboBox::drop-down {{ border: none; width: 16px; }}
            QComboBox QAbstractItemView {{
                background: #0d0d1a; color: {TEXT}; border: 1px solid {BORDER};
            }}
        """)
        self._ctx_combo.currentTextChanged.connect(self._ctx_changed(on_ctx))
        tb.addWidget(self._ctx_combo)

        x = QPushButton("×")
        x.setFixedSize(20, 20)
        x.setStyleSheet(f"background: transparent; color: {MUTED}; border: none; font-size: 15px; font-weight: bold;")
        x.clicked.connect(self.close)
        tb.addWidget(x)
        main.addLayout(tb)

        main.addWidget(self._divider())

        # ── Transcript ────────────────────────────────────────────────────
        self._speaker_lbl = _label("LISTENING…", 9, MUTED, bold=True)
        main.addWidget(self._speaker_lbl)

        self._transcript = _label("Speak — your mic is live.", 13, MUTED)
        self._transcript.setMinimumHeight(36)
        main.addWidget(self._transcript)

        main.addWidget(self._divider())

        # ── Suggestions ───────────────────────────────────────────────────
        sh = QHBoxLayout()
        self._sugg_title = _label("SUGGESTIONS", 9, ACCENT, bold=True)
        sh.addWidget(self._sugg_title)
        sh.addStretch()
        ref = _btn("⟳", "transparent", MUTED)
        ref.setFixedSize(28, 22)
        ref.clicked.connect(on_refresh)
        sh.addWidget(ref)
        main.addLayout(sh)

        # Scroll area — suggestions live inside here, fully readable
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(f"""
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: {BORDER}; width: 4px; border-radius: 2px;
            }}
            QScrollBar::handle:vertical {{
                background: {MUTED}; border-radius: 2px; min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)

        self._sugg_container = QWidget()
        self._sugg_container.setStyleSheet("background: transparent;")
        self._sugg_area = QVBoxLayout(self._sugg_container)
        self._sugg_area.setSpacing(8)
        self._sugg_area.setContentsMargins(0, 0, 4, 0)
        self._sugg_area.addStretch()

        self._scroll.setWidget(self._sugg_container)
        main.addWidget(self._scroll, stretch=1)   # takes all remaining vertical space

        main.addWidget(self._divider())

        # ── Outcome ───────────────────────────────────────────────────────
        out = QHBoxLayout()
        end = _btn("⏹ End", "#cc3333")
        end.clicked.connect(on_end)
        out.addWidget(end)
        out.addStretch()
        out.addWidget(_label("Rate:", 11, MUTED))

        for i in range(1, 6):
            s = QLabel("★")
            s.setStyleSheet(f"color: {BORDER}; font-size: 18px; background: transparent;")
            s.mousePressEvent = lambda _, v=i: self._rate(v)
            self._stars.append(s)
            out.addWidget(s)

        self._submit = _btn("Submit", ACCENT)
        self._submit.setEnabled(False)
        self._submit.clicked.connect(on_end)
        out.addWidget(self._submit)
        main.addLayout(out)

    def _ctx_changed(self, cb):
        def handler(text):
            self._context = text
            cb(text)
        return handler

    def _divider(self) -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet(f"background: {BORDER}; border: none;")
        f.setFixedHeight(1)
        return f

    # ── Slots ─────────────────────────────────────────────────────────────

    def _on_transcript(self, text: str, is_q: bool):
        other_role, _ = ROLE_MAP.get(self._context, ("SPEAKER", "YOUR RESPONSE"))
        if is_q:
            self._speaker_lbl.setStyleSheet(
                f"color: {INTER_CLR}; font-size: 9px; font-weight: 700; background: transparent;")
            self._speaker_lbl.setText(f"▶ {other_role}")
            self._transcript.setStyleSheet(
                f"color: {TEXT}; font-size: 13px; background: transparent;")
        else:
            self._speaker_lbl.setStyleSheet(
                f"color: {MUTED}; font-size: 9px; font-weight: 700; background: transparent;")
            self._speaker_lbl.setText("▶ YOU (heard)")
            self._transcript.setStyleSheet(
                f"color: {MUTED}; font-size: 13px; background: transparent;")
        self._transcript.setText(text)

    def _on_loading(self):
        _, user_role = ROLE_MAP.get(self._context, ("SPEAKER", "YOUR RESPONSE"))
        self._sugg_title.setText(f"SUGGESTIONS  ·  generating…")
        self._sugg_title.setStyleSheet(
            f"color: {WARN}; font-size: 9px; font-weight: 700; background: transparent;")
        self._clear_suggestions()
        loading = _label("⏳  Thinking — first suggestion in ~3s…", 12, WARN)
        self._sugg_area.insertWidget(0, loading)

    def _on_suggestions(self, items: list):
        _, user_role = ROLE_MAP.get(self._context, ("SPEAKER", "YOUR RESPONSE"))
        count = len(items)
        self._sugg_title.setText(f"{user_role}  ·  {count} suggestion{'s' if count != 1 else ''}")
        self._sugg_title.setStyleSheet(
            f"color: {SUCCESS}; font-size: 9px; font-weight: 700; background: transparent;")
        self._clear_suggestions()
        if not items:
            self._sugg_area.insertWidget(0, _label("No suggestions generated.", 12, MUTED))
        else:
            for i, item in enumerate(reversed(items[:3]), 1):
                card = SuggestionCard(len(items) - i + 1, item)
                card.used.connect(self._on_card_used)
                self._sugg_area.insertWidget(0, card)
        # scroll to top so user sees #1 first
        self._scroll.verticalScrollBar().setValue(0)

    def _on_card_used(self, sid: str):
        self._on_mark_used(sid)

    def _on_status(self, text: str):
        self._status_lbl.setText(text)
        live = text.lower() in ("listening…", "transcribing…", "thinking…")
        self._dot.setStyleSheet(
            f"color: {SUCCESS if live else MUTED}; font-size: 11px; background: transparent;")

    def _clear_suggestions(self):
        while self._sugg_area.count() > 1:   # keep the stretch at the end
            item = self._sugg_area.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _rate(self, v: int):
        self._score = v
        for i, s in enumerate(self._stars):
            s.setStyleSheet(
                f"color: {WARN if i < v else BORDER}; font-size: 18px; background: transparent;")
        self._submit.setEnabled(True)

    def get_score(self) -> int:
        return self._score

    # ── Drag ──────────────────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() == Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None
