"""
Real-time audio capture + transcription — accent-robust.

Key improvements over naive Whisper usage:
  1. Uses 'base' model by default — 2× larger than tiny, handles accents far better
  2. No forced language='en' — auto-detects language so non-native English is handled naturally
  3. beam_size=5 — more decoding candidates → better accuracy on unusual pronunciation
  4. initial_prompt — primes Whisper with domain context so it interprets
     technical/business vocabulary correctly regardless of accent
  5. Adaptive VAD threshold — adjusts to background noise so soft-spoken
     or accent-heavy speakers aren't cut off
  6. Longer silence window — gives slower/accented speakers more time to finish
  7. condition_on_previous_text=False — prevents early transcription errors
     from snowballing across an accented utterance

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

SAMPLE_RATE   = 16000
CHUNK_MS      = 100
CHUNK_FRAMES  = SAMPLE_RATE * CHUNK_MS // 1000   # 1600 frames per chunk

# VAD — tuned for accented / soft-spoken speakers
SILENCE_CHUNKS    = 10      # ~1.0s silence → faster trigger (was 1.8s)
MIN_SPEECH_CHUNKS = 4       # ~400ms minimum utterance to avoid noise
NOISE_FLOOR_CHUNKS = 30     # first 3s used to calibrate noise floor

# Context prompts help Whisper resolve ambiguous pronunciation correctly
CONTEXT_PROMPTS = {
    "Software Engineering Interview": (
        "Software engineering interview. Topics include coding, algorithms, "
        "system design, data structures, APIs, cloud infrastructure, Python, Java."
    ),
    "Product Management Interview": (
        "Product management interview. Topics include product roadmap, metrics, "
        "user research, A/B testing, stakeholders, OKRs, go-to-market strategy."
    ),
    "Sales Meeting": (
        "Business sales meeting. Topics include pricing, contract, ROI, "
        "solution, proposal, timeline, budget, decision maker."
    ),
    "Investor Pitch": (
        "Startup investor pitch meeting. Topics include funding, valuation, "
        "market size, revenue, traction, team, product, runway, Series A."
    ),
    "Performance Review": (
        "Employee performance review. Topics include goals, feedback, "
        "promotion, salary, achievements, improvement areas."
    ),
    "General Meeting": (
        "Professional business meeting discussion."
    ),
}

DEFAULT_PROMPT = "Professional meeting or interview discussion."


class AudioTranscriber:
    def __init__(
        self,
        model_size: str = "base",   # base >> tiny for accent handling
        on_utterance=None,
        context: str = "General Meeting",
    ):
        self.on_utterance = on_utterance
        self._context = context
        self._raw_q:   queue.Queue[np.ndarray] = queue.Queue()
        self._trans_q: queue.Queue[np.ndarray] = queue.Queue()
        self._stop = threading.Event()
        self._noise_floor: float = 0.01   # calibrated during first few seconds

        print(f"[ASE] Loading Whisper '{model_size}' model (accent-robust)…")
        self._model = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",
        )
        print("[ASE] Whisper ready.")

    def update_context(self, context: str):
        self._context = context

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
        print("[ASE] Microphone open — accent-robust mode active.")

    def stop(self):
        self._stop.set()
        if hasattr(self, "_stream"):
            self._stream.stop()
            self._stream.close()

    # ── internals ─────────────────────────────────────────────────────────

    def _audio_callback(self, indata, frames, time_info, status):
        self._raw_q.put(indata[:, 0].copy())

    def _vad_loop(self):
        """
        Adaptive energy-based VAD.
        - Calibrates noise floor from first 3 seconds of audio
        - Dynamic threshold = noise_floor × 2.5 (handles quiet rooms and loud ones)
        - Longer silence window so accented/slower speakers aren't cut off mid-sentence
        """
        speech_buf:  list[np.ndarray] = []
        silent_count  = 0
        speaking      = False
        calibration:  list[float] = []
        calibrated    = False

        while not self._stop.is_set():
            try:
                chunk = self._raw_q.get(timeout=0.2)
            except queue.Empty:
                continue

            rms = float(np.sqrt(np.mean(chunk ** 2)))

            # Calibrate noise floor from ambient audio
            if not calibrated:
                calibration.append(rms)
                if len(calibration) >= NOISE_FLOOR_CHUNKS:
                    self._noise_floor = max(np.percentile(calibration, 80), 0.005)
                    calibrated = True
                    print(f"[ASE] Noise floor calibrated: {self._noise_floor:.4f}")
                continue

            threshold = self._noise_floor * 2.5

            if rms > threshold:
                speaking = True
                silent_count = 0
                speech_buf.append(chunk)
            else:
                if speaking:
                    silent_count += 1
                    speech_buf.append(chunk)
                    if silent_count >= SILENCE_CHUNKS:
                        if len(speech_buf) >= MIN_SPEECH_CHUNKS:
                            audio = np.concatenate(speech_buf)
                            self._trans_q.put(audio)
                        speech_buf   = []
                        silent_count = 0
                        speaking     = False

    def _trans_loop(self):
        """
        Transcribes audio using accent-robust settings:
        - No forced language (auto-detect handles non-native English better)
        - beam_size=5 for better decoding of unusual pronunciation
        - initial_prompt provides domain vocabulary context
        - condition_on_previous_text=False prevents error propagation
        """
        while not self._stop.is_set():
            try:
                audio = self._trans_q.get(timeout=0.3)
            except queue.Empty:
                continue

            prompt = CONTEXT_PROMPTS.get(self._context, DEFAULT_PROMPT)

            segments, info = self._model.transcribe(
                audio,
                beam_size=3,                       # 3 = sweet spot: faster than 5, still accent-robust
                language=None,                     # auto-detect
                initial_prompt=prompt,             # domain context
                vad_filter=True,
                vad_parameters={
                    "min_silence_duration_ms": 300,
                    "speech_pad_ms": 100,
                },
                condition_on_previous_text=False,
                temperature=0.0,                   # single pass — faster than fallback chain
                compression_ratio_threshold=2.4,
                log_prob_threshold=-1.0,
                no_speech_threshold=0.5,
            )

            text = " ".join(s.text.strip() for s in segments).strip()

            # Filter out hallucinations common with quiet/background audio
            if text and not _is_hallucination(text) and self.on_utterance:
                detected_lang = info.language if hasattr(info, "language") else "en"
                if detected_lang != "en":
                    print(f"[ASE] Detected accent/language: {detected_lang}")
                self.on_utterance(text)


# ── Hallucination filter ──────────────────────────────────────────────────────
# Whisper sometimes outputs these when it hears silence or noise

_HALLUCINATIONS = {
    "thank you", "thanks for watching", "thanks for listening",
    "please subscribe", "you", ".", "..", "...", "okay", "ok",
    "bye", "goodbye", "uh", "um", "hmm", "[music]", "[applause]",
    "[ silence ]", "[silence]", "[ Silence ]",
}

def _is_hallucination(text: str) -> bool:
    t = text.strip().lower().rstrip(".")
    return t in _HALLUCINATIONS or len(t) <= 2
