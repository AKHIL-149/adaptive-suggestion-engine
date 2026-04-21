"""
PyQt6 always-on-top transparent overlay.

Layout:
  ┌──────────────────────────────────────┐
  │  ● LIVE   [Context ▼]   [_][×]       │  ← title bar (drag here)
  ├──────────────────────────────────────┤
  │  TRANSCRIPT                           │
  │  "Tell me about a time you..."        │
  ├──────────────────────────────────────┤
  │  SUGGESTIONS          [⟳ Refresh]    │
  │  ┌────────────────────────────────┐  │
  │  │ #1  ████████░░  82%            │  │
  │  │ "In my previous role..."       │  │
  │  │                  [✓ Use this]  │  │
  │  └────────────────────────────────┘  │
  ├──────────────────────────────────────┤
  │  [⏹ End]   ★☆☆☆☆  [Submit]          │
  └──────────────────────────────────────┘
"""
from __future__ import annotations

import threading
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QScrollArea, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt, QPoint, pyqtSignal, QObject
from PyQt6.QtGui import QColor, QPalette, QFont, QCursor

# ── Colour palette (matches web app) ─────────────────────────────────────────
BG          = "#0d0d14"
SURFACE     = "#13131a"
BORDER      = "#1e1e2e"
ACCENT      = "#6c63ff"
MUTED       = "#6b6b80"
SUCCESS     = "#22c55e"
TEXT        = "#e8e8f0"
WARN        = "#f59e0b"

CONTEXTS = [
    "Software Engineering Interview",
    "Product Management Interview",
    "Sales Meeting",
    "Investor Pitch",
    "Performance Review",
    "General Meeting",
]


def _btn(text: str, color: str = ACCENT, fg: str = "#ffffff") -> QPushButton:
    b = QPushButton(text)
    b.setStyleSheet(f"""
        QPushButton {{
            background: {color}; color: {fg};
            border: none; border-radius: 6px;
            padding: 6px 14px; font-size: 12px; font-weight: 600;
        }}
        QPushButton:hover {{ opacity: 0.8; }}
        QPushButton:disabled {{ background: {BORDER}; color: {MUTED}; }}
    """)
    return b


def _label(text: str, size: int = 12, color: str = TEXT, bold: bool = False) -> QLabel:
    lb = QLabel(text)
    lb.setStyleSheet(f"color: {color}; font-size: {size}px; font-weight: {'700' if bold else '400'};")
    lb.setWordWrap(True)
    return lb


# ── Signal bridge (thread → UI) ───────────────────────────────────────────────
class Bridge(QObject):
    transcript_ready  = pyqtSignal(str)
    suggestions_ready = pyqtSignal(list)
    status_update     = pyqtSignal(str)


# ── Suggestion card widget ────────────────────────────────────────────────────
class SuggestionCard(QFrame):
    used = pyqtSignal(str)   # emits suggestion_id

    def __init__(self, rank: int, item: dict):
        super().__init__()
        self._id = item.get("id", "")
        pct = int(item.get("predicted_success", 0.5) * 100)

        self.setStyleSheet(f"""
            QFrame {{
                background: {BG}; border: 1px solid {BORDER};
                border-radius: 8px; padding: 10px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(10, 10, 10, 10)

        # header row
        header = QHBoxLayout()
        header.addWidget(_label(f"#{rank}", 11, MUTED, bold=True))
        header.addWidget(_label(item.get("angle", ""), 11, MUTED))
        header.addStretch()
        pct_color = SUCCESS if pct >= 60 else (WARN if pct >= 40 else MUTED)
        header.addWidget(_label(f"{pct}% success", 11, pct_color, bold=True))
        layout.addLayout(header)

        # suggestion text
        layout.addWidget(_label(item.get("text", ""), 13, TEXT))

        # use button
        row = QHBoxLayout()
        row.addStretch()
        use_btn = _btn("✓ Use this", SUCCESS)
        use_btn.clicked.connect(self._on_use)
        row.addWidget(use_btn)
        layout.addLayout(row)

    def _on_use(self):
        self.setStyleSheet(self.styleSheet().replace(BORDER, SUCCESS))
        self.used.emit(self._id)


# ── Main overlay window ───────────────────────────────────────────────────────
class Overlay(QWidget):
    def __init__(self, bridge: Bridge, on_context_change, on_refresh, on_end_session, on_mark_used):
        super().__init__()
        self._drag_pos: QPoint | None = None
        self.bridge = bridge
        self._stars: list[QLabel] = []
        self._selected_score = 0

        self.setWindowTitle("ASE")
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(420)
        self.setMinimumHeight(200)

        self._build_ui(on_context_change, on_refresh, on_end_session, on_mark_used)

        bridge.transcript_ready.connect(self._show_transcript)
        bridge.suggestions_ready.connect(self._show_suggestions)
        bridge.status_update.connect(self._show_status)

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self, on_context_change, on_refresh, on_end_session, on_mark_used):
        self._on_mark_used = on_mark_used
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        container = QWidget()
        container.setStyleSheet(f"""
            QWidget {{
                background: {SURFACE};
                border: 1px solid {BORDER};
                border-radius: 12px;
            }}
        """)
        root.addWidget(container)

        main = QVBoxLayout(container)
        main.setContentsMargins(16, 12, 16, 16)
        main.setSpacing(12)

        # ── Title bar ─────────────────────────────────────────────────────
        title_row = QHBoxLayout()

        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        title_row.addWidget(self._status_dot)

        self._status_label = _label("Ready", 11, MUTED)
        title_row.addWidget(self._status_label)
        title_row.addStretch()

        ctx = QComboBox()
        ctx.addItems(CONTEXTS)
        ctx.setStyleSheet(f"""
            QComboBox {{
                background: {BG}; color: {TEXT}; border: 1px solid {BORDER};
                border-radius: 5px; padding: 3px 8px; font-size: 11px;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER};
            }}
        """)
        ctx.currentTextChanged.connect(on_context_change)
        title_row.addWidget(ctx)

        close_btn = QPushButton("×")
        close_btn.setFixedSize(22, 22)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {MUTED}; border: none;
                font-size: 16px; font-weight: bold;
            }}
            QPushButton:hover {{ color: #ff5555; }}
        """)
        close_btn.clicked.connect(self.close)
        title_row.addWidget(close_btn)
        main.addLayout(title_row)

        # ── Divider ───────────────────────────────────────────────────────
        main.addWidget(self._divider())

        # ── Transcript section ────────────────────────────────────────────
        main.addWidget(_label("TRANSCRIPT", 10, ACCENT, bold=True))
        self._transcript = _label("Listening… speak to capture.", 13, MUTED)
        self._transcript.setMinimumHeight(40)
        main.addWidget(self._transcript)

        main.addWidget(self._divider())

        # ── Suggestions section ───────────────────────────────────────────
        s_header = QHBoxLayout()
        s_header.addWidget(_label("SUGGESTIONS", 10, ACCENT, bold=True))
        s_header.addStretch()
        refresh = _btn("⟳ Refresh", BG, MUTED)
        refresh.clicked.connect(on_refresh)
        s_header.addWidget(refresh)
        main.addLayout(s_header)

        self._suggestions_area = QVBoxLayout()
        self._suggestions_area.setSpacing(8)
        self._no_suggestions = _label("Suggestions will appear when a question is detected.", 12, MUTED)
        self._suggestions_area.addWidget(self._no_suggestions)
        main.addLayout(self._suggestions_area)

        main.addWidget(self._divider())

        # ── Outcome row ───────────────────────────────────────────────────
        outcome_row = QHBoxLayout()
        end_btn = _btn("⏹ End", "#ff5555")
        end_btn.clicked.connect(on_end_session)
        outcome_row.addWidget(end_btn)

        outcome_row.addStretch()
        outcome_row.addWidget(_label("Rate:", 11, MUTED))
        for i in range(1, 6):
            star = QLabel("★")
            star.setStyleSheet(f"color: {BORDER}; font-size: 18px; cursor: pointer;")
            star.mousePressEvent = lambda _, v=i: self._rate(v)
            self._stars.append(star)
            outcome_row.addWidget(star)

        self._submit_btn = _btn("Submit", ACCENT)
        self._submit_btn.setEnabled(False)
        self._submit_btn.clicked.connect(on_end_session)
        outcome_row.addWidget(self._submit_btn)
        main.addLayout(outcome_row)

    def _divider(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {BORDER}; background: {BORDER};")
        line.setFixedHeight(1)
        return line

    # ── Slots ─────────────────────────────────────────────────────────────

    def _show_transcript(self, text: str):
        self._transcript.setText(text)
        self._transcript.setStyleSheet(f"color: {TEXT}; font-size: 13px;")

    def _show_suggestions(self, items: list):
        # clear old cards
        while self._suggestions_area.count():
            w = self._suggestions_area.takeAt(0)
            if w.widget():
                w.widget().deleteLater()

        if not items:
            self._suggestions_area.addWidget(
                _label("No suggestions generated.", 12, MUTED))
            return

        for i, item in enumerate(items[:3], 1):
            card = SuggestionCard(i, item)
            card.used.connect(self._on_card_used)
            self._suggestions_area.addWidget(card)

        self.adjustSize()

    def _on_card_used(self, suggestion_id: str):
        self._on_mark_used(suggestion_id)

    def _show_status(self, text: str):
        self._status_label.setText(text)
        is_live = text.lower() in ("listening…", "transcribing…", "thinking…")
        self._status_dot.setStyleSheet(
            f"color: {SUCCESS if is_live else MUTED}; font-size: 12px;")

    def _rate(self, value: int):
        self._selected_score = value
        for i, star in enumerate(self._stars):
            star.setStyleSheet(
                f"color: {WARN if i < value else BORDER}; font-size: 18px;")
        self._submit_btn.setEnabled(True)

    def get_score(self) -> int:
        return self._selected_score

    # ── Draggable window ──────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
