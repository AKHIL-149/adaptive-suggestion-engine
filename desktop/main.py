"""
Adaptive Suggestion Engine — Desktop App
=========================================
Run: python3 -m desktop.main  (from project root)

Flow:
  1. Overlay opens → user picks context → session starts
  2. Mic captures audio continuously
  3. When someone finishes speaking (silence > 1.2s):
       a. Whisper transcribes the utterance
       b. Question detector checks if it's a question
       c. If yes → Ollama generates suggestions via API
       d. Suggestions appear in the overlay, ranked by your history
  4. User clicks "Use this" on a suggestion → marks it accepted
  5. User rates outcome 1–5 → learning loop updates patterns
"""
from __future__ import annotations

import sys
import threading
from PyQt6.QtWidgets import QApplication

from desktop.audio import AudioTranscriber
from desktop.responder import Session, is_question
from desktop.overlay import Overlay, Bridge


class App:
    def __init__(self):
        self._context = "Software Engineering Interview"
        self._session: Session | None = None
        self._last_transcript = ""
        self._bridge = Bridge()
        self._transcriber: AudioTranscriber | None = None

    # ── Session lifecycle ─────────────────────────────────────────────────

    def _start_session(self):
        self._session = Session(self._context)
        ok = self._session.start()
        status = "Backend connected ✓" if ok else "Offline mode (Ollama direct)"
        self._bridge.status_update.emit(status)

        self._transcriber = AudioTranscriber(
            model_size="tiny",
            on_utterance=self._on_utterance,
        )
        self._transcriber.start()
        self._bridge.status_update.emit("Listening…")

    def _on_context_change(self, ctx: str):
        self._context = ctx
        if self._session:
            # restart session with new context
            self._stop_session(score=0)
            self._start_session()

    # ── Audio → suggestion pipeline ───────────────────────────────────────

    def _on_utterance(self, text: str):
        """Called from background thread when Whisper finishes a segment."""
        self._last_transcript = text
        self._bridge.transcript_ready.emit(text)

        if is_question(text):
            self._bridge.status_update.emit("Thinking…")
            threading.Thread(
                target=self._fetch_suggestions,
                args=(text,),
                daemon=True,
            ).start()
        else:
            self._bridge.status_update.emit("Listening…")

    def _fetch_suggestions(self, prompt: str):
        if not self._session:
            return
        items = self._session.get_suggestions(prompt, n=3)
        self._bridge.suggestions_ready.emit(items)
        self._bridge.status_update.emit("Listening…")

    def _on_refresh(self):
        if self._last_transcript and self._session:
            self._bridge.status_update.emit("Thinking…")
            threading.Thread(
                target=self._fetch_suggestions,
                args=(self._last_transcript,),
                daemon=True,
            ).start()

    def _on_mark_used(self, suggestion_id: str):
        if self._session:
            threading.Thread(
                target=self._session.mark_used,
                args=(suggestion_id,),
                daemon=True,
            ).start()

    # ── Outcome + cleanup ─────────────────────────────────────────────────

    def _on_end_session(self):
        score = self._overlay.get_score()
        if score == 0:
            self._bridge.status_update.emit("Rate 1–5 first, then Submit.")
            return
        self._stop_session(score)

    def _stop_session(self, score: int):
        if self._transcriber:
            self._transcriber.stop()
            self._transcriber = None
        if self._session and score > 0:
            result = self._session.end(score)
            learned = result.get("learning", {}).get("learned", [])
            if learned:
                best = max(learned, key=lambda x: x["new_rate"])
                self._bridge.status_update.emit(
                    f"Learned: {best['type']} → {int(best['new_rate']*100)}% ✓"
                )
        self._session = None

    # ── Entry point ───────────────────────────────────────────────────────

    def run(self):
        qt_app = QApplication(sys.argv)
        qt_app.setStyle("Fusion")

        self._overlay = Overlay(
            bridge=self._bridge,
            on_context_change=self._on_context_change,
            on_refresh=self._on_refresh,
            on_end_session=self._on_end_session,
            on_mark_used=self._on_mark_used,
        )
        self._overlay.show()

        # Start session after UI is shown
        threading.Thread(target=self._start_session, daemon=True).start()

        sys.exit(qt_app.exec())


if __name__ == "__main__":
    App().run()
