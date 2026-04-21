"""
Hand gesture controller — moves the overlay window via webcam.

Gestures:
  ☝️  Index finger only extended  → drag window in that direction
  ✌️  Index + middle both extended → finalize / lock position (hold 0.6s)
  ✊  Fist / no gesture            → idle

Landmark reference (MediaPipe):
  4  = thumb tip
  8  = index tip      ← primary control finger
  12 = middle tip     ← used for finalize gesture
  16 = ring tip
  20 = pinky tip
  6  = index PIP (second joint)
  10 = middle PIP
  14 = ring PIP
  18 = pinky PIP
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable

import cv2
import mediapipe as mp
import numpy as np

# ── Tuning ────────────────────────────────────────────────────────────────────
SENSITIVITY     = 2.8    # pixels of window movement per pixel of finger movement
SMOOTHING       = 0.35   # EMA alpha — lower = smoother but more lag
DEAD_ZONE       = 0.008  # minimum normalised delta before window moves
FINALIZE_SECS   = 0.6    # hold ✌️ this long to lock position
FPS_TARGET      = 30


class GestureController:
    """
    Runs in a background thread.
    Calls move_cb(dx, dy) to move the window.
    Calls finalize_cb() when ✌️ held long enough.
    """

    def __init__(
        self,
        move_cb: Callable[[int, int], None],
        finalize_cb: Callable[[], None],
        status_cb: Callable[[str], None] | None = None,
    ):
        self._move_cb     = move_cb
        self._finalize_cb = finalize_cb
        self._status_cb   = status_cb
        self._stop        = threading.Event()
        self._thread: threading.Thread | None = None

        # smoothed finger position (normalised 0-1)
        self._sx: float = 0.5
        self._sy: float = 0.5
        self._prev_sx: float | None = None
        self._prev_sy: float | None = None

        # finalize gesture timing
        self._finalize_start: float | None = None
        self._finalized = False

    # ── public API ────────────────────────────────────────────────────────

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def reset(self):
        """Call after window is moved to reset relative tracking."""
        self._prev_sx = None
        self._prev_sy = None
        self._finalize_start = None
        self._finalized = False

    # ── main loop ─────────────────────────────────────────────────────────

    def _run(self):
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            self._log("Gesture: no webcam found")
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, FPS_TARGET)

        mp_hands  = mp.solutions.hands
        hands_det = mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.6,
        )

        self._log("Gesture: webcam ready ✋")
        frame_delay = 1.0 / FPS_TARGET

        while not self._stop.is_set():
            t0 = time.monotonic()
            ok, frame = cap.read()
            if not ok:
                continue

            # flip so left/right is natural (mirror)
            frame = cv2.flip(frame, 1)
            rgb   = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res   = hands_det.process(rgb)

            if res.multi_hand_landmarks:
                lm = res.multi_hand_landmarks[0].landmark
                self._process(lm)
            else:
                # no hand visible — reset tracking
                self._prev_sx = None
                self._prev_sy = None
                self._finalize_start = None

            elapsed = time.monotonic() - t0
            wait    = frame_delay - elapsed
            if wait > 0:
                time.sleep(wait)

        cap.release()
        hands_det.close()
        self._log("Gesture: stopped")

    # ── gesture logic ─────────────────────────────────────────────────────

    def _process(self, lm):
        h = lm    # shorthand

        index_up  = self._finger_up(h, tip=8,  pip=6)
        middle_up = self._finger_up(h, tip=12, pip=10)
        ring_up   = self._finger_up(h, tip=16, pip=14)
        pinky_up  = self._finger_up(h, tip=20, pip=18)

        # ── ✌️ finalize: index + middle up, ring + pinky down ─────────────
        if index_up and middle_up and not ring_up and not pinky_up:
            if self._finalize_start is None:
                self._finalize_start = time.monotonic()
            elif time.monotonic() - self._finalize_start >= FINALIZE_SECS:
                if not self._finalized:
                    self._finalized = True
                    self._log("Gesture: ✌️  position locked")
                    self._finalize_cb()
            return   # no movement while finalising

        self._finalize_start = None
        self._finalized = False

        # ── ☝️ drag: only index finger up ─────────────────────────────────
        if index_up and not middle_up and not ring_up and not pinky_up:
            # raw normalised position of index tip
            raw_x = h[8].x
            raw_y = h[8].y

            # EMA smooth
            self._sx = SMOOTHING * raw_x + (1 - SMOOTHING) * self._sx
            self._sy = SMOOTHING * raw_y + (1 - SMOOTHING) * self._sy

            if self._prev_sx is not None:
                dx = self._sx - self._prev_sx
                dy = self._sy - self._prev_sy

                # dead zone — ignore micro-tremor
                if abs(dx) > DEAD_ZONE or abs(dy) > DEAD_ZONE:
                    # scale to pixels (assume 1080p reference height)
                    px = int(dx * 1080 * SENSITIVITY)
                    py = int(dy * 1080 * SENSITIVITY)
                    if px != 0 or py != 0:
                        self._move_cb(px, py)
                        self._log(f"Gesture: ☝️  moving ({px:+d}, {py:+d})")

            self._prev_sx = self._sx
            self._prev_sy = self._sy
        else:
            # hand visible but not dragging — reset relative tracking
            self._prev_sx = None
            self._prev_sy = None

    @staticmethod
    def _finger_up(lm, tip: int, pip: int) -> bool:
        """Returns True if fingertip is above (smaller y) its PIP joint."""
        return lm[tip].y < lm[pip].y

    def _log(self, msg: str):
        print(f"[ASE] {msg}")
        if self._status_cb:
            self._status_cb(msg.replace("Gesture: ", ""))
