from __future__ import annotations

import sys
import threading
from PyQt6.QtWidgets import QApplication

from desktop.audio import AudioTranscriber
from desktop.responder import Session, is_question
from desktop.overlay import Overlay, Bridge
from desktop.gesture import GestureController


class App:
    def __init__(self):
        self._context = "Software Engineering Interview"
        self._session: Session | None = None
        self._last_transcript = ""
        self._bridge = Bridge()
        self._transcriber: AudioTranscriber | None = None
        self._gesture: GestureController | None = None

    def _start_session(self):
        self._session = Session(self._context)
        ok = self._session.start()
        self._bridge.status_update.emit("Backend ✓" if ok else "Offline (Ollama direct)")
        self._transcriber = AudioTranscriber(
            model_size="base",           # handles accents far better than tiny
            on_utterance=self._on_utterance,
            context=self._context,
        )
        self._transcriber.start()
        self._bridge.status_update.emit("Listening…")

    def _on_context_change(self, ctx: str):
        self._context = ctx
        if self._transcriber:
            self._transcriber.update_context(ctx)   # update prompt live, no restart needed
        if self._session:
            self._stop_audio()
            self._session = Session(self._context)
            self._session.start()
            self._start_audio()

    def _start_audio(self):
        self._transcriber = AudioTranscriber(
            model_size="base",
            on_utterance=self._on_utterance,
            context=self._context,
        )
        self._transcriber.start()
        self._bridge.status_update.emit("Listening…")

    def _stop_audio(self):
        if self._transcriber:
            self._transcriber.stop()
            self._transcriber = None

    # ── Core pipeline ─────────────────────────────────────────────────────

    def _on_utterance(self, text: str):
        """Called from Whisper background thread on completed utterance."""
        self._last_transcript = text
        iq = is_question(text)

        # update transcript with role label
        self._bridge.transcript_ready.emit(text, iq)

        if iq:
            # show loading spinner IMMEDIATELY — before Ollama responds
            self._bridge.loading_start.emit()
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
        # on_partial fires after each suggestion → UI updates progressively
        def on_partial(partial_items: list):
            self._bridge.suggestions_ready.emit(partial_items)

        items = self._session.get_suggestions(prompt, n=3, on_partial=on_partial)
        # final emit ensures UI is up to date even if backend returned all at once
        if items:
            self._bridge.suggestions_ready.emit(items)
        self._bridge.status_update.emit("Listening…")

    def _on_refresh(self):
        if self._last_transcript and self._session:
            self._bridge.loading_start.emit()
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

    def _start_gesture(self):
        """Start hand gesture controller in background."""
        self._gesture = GestureController(
            move_cb=lambda dx, dy: self._bridge.gesture_move.emit(dx, dy),
            finalize_cb=lambda: self._bridge.gesture_finalize.emit(),
            status_cb=lambda msg: self._bridge.status_update.emit(msg),
        )
        self._gesture.start()

    def _on_end_session(self):
        score = self._overlay.get_score()
        if score == 0:
            self._bridge.status_update.emit("Rate 1–5 first, then Submit.")
            return
        self._stop_audio()
        if self._session:
            result = self._session.end(score)
            learned = result.get("learning", {}).get("learned", [])
            if learned:
                best = max(learned, key=lambda x: x["new_rate"])
                self._bridge.status_update.emit(
                    f"Learned: {best['type']} → {int(best['new_rate']*100)}% ✓")
        self._session = None

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
        threading.Thread(target=self._start_session, daemon=True).start()
        self._start_gesture()
        sys.exit(qt_app.exec())


if __name__ == "__main__":
    App().run()
