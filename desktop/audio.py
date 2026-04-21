"""
Real-time audio capture + transcription.

Pipeline:
  sounddevice callback → raw_q (16kHz float32 chunks)
  → VAD thread accumulates speech frames
  → When silence detected after speech → transcribe_q
  → Whisper thread transcribes → emits via on_utterance callback
"""
from __future__ import annotations

import threading
import queue
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

SAMPLE_RATE = 16000
CHUNK_MS    = 100                        # process in 100ms chunks
CHUNK_FRAMES = SAMPLE_RATE * CHUNK_MS // 1000   # 1600 frames

SPEECH_THRESHOLD  = 0.015   # RMS energy threshold
SILENCE_CHUNKS    = 12      # ~1.2 seconds of silence → utterance done
MIN_SPEECH_CHUNKS = 5       # ignore very short noise bursts


class AudioTranscriber:
    def __init__(self, model_size: str = "tiny", on_utterance=None):
        """
        on_utterance(text: str) called from a background thread whenever
        a complete utterance is transcribed.
        """
        self.on_utterance = on_utterance
        self._raw_q: queue.Queue[np.ndarray] = queue.Queue()
        self._trans_q: queue.Queue[np.ndarray] = queue.Queue()
        self._stop = threading.Event()

        print(f"[ASE] Loading Whisper '{model_size}' model…")
        self._model = WhisperModel(model_size, device="cpu", compute_type="int8")
        print("[ASE] Whisper ready.")

    # ── public API ────────────────────────────────────────────────────────

    def start(self):
        self._stop.clear()
        threading.Thread(target=self._vad_loop,   daemon=True).start()
        threading.Thread(target=self._trans_loop, daemon=True).start()
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=CHUNK_FRAMES,
            callback=self._audio_callback,
        )
        self._stream.start()
        print("[ASE] Microphone open.")

    def stop(self):
        self._stop.set()
        if hasattr(self, "_stream"):
            self._stream.stop()
            self._stream.close()

    # ── internals ─────────────────────────────────────────────────────────

    def _audio_callback(self, indata, frames, time_info, status):
        self._raw_q.put(indata[:, 0].copy())   # mono

    def _vad_loop(self):
        """
        Simple energy-based VAD.
        Accumulates speech frames; once silence is detected after speech,
        pushes the accumulated audio to the transcription queue.
        """
        speech_buf: list[np.ndarray] = []
        silent_count = 0
        speaking = False

        while not self._stop.is_set():
            try:
                chunk = self._raw_q.get(timeout=0.2)
            except queue.Empty:
                continue

            rms = float(np.sqrt(np.mean(chunk ** 2)))

            if rms > SPEECH_THRESHOLD:
                speaking = True
                silent_count = 0
                speech_buf.append(chunk)
            else:
                if speaking:
                    silent_count += 1
                    speech_buf.append(chunk)   # keep trailing silence for context
                    if silent_count >= SILENCE_CHUNKS:
                        if len(speech_buf) >= MIN_SPEECH_CHUNKS:
                            audio = np.concatenate(speech_buf)
                            self._trans_q.put(audio)
                        speech_buf = []
                        silent_count = 0
                        speaking = False

    def _trans_loop(self):
        """Transcribes audio blobs from _trans_q."""
        while not self._stop.is_set():
            try:
                audio = self._trans_q.get(timeout=0.3)
            except queue.Empty:
                continue

            segments, _ = self._model.transcribe(
                audio,
                beam_size=1,
                language="en",
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300},
            )
            text = " ".join(s.text.strip() for s in segments).strip()
            if text and self.on_utterance:
                self.on_utterance(text)
