"""Realtime voice chain: WASAPI mic -> DSP -> VB-Cable CABLE Input.

Two separate PortAudio streams + queue pipeline (WASAPI refuses cross-device
duplex, PortAudio error -9993): input callback pushes raw blocks, a worker
thread runs WORLD/PSOLA over a left-context window, output callback pops
processed blocks (silence + underrun counter when starved).

Streaming judgement (Seed-VC line criterion): mean process time must stay
below the block duration, otherwise the output queue drains -> underruns.
"""
from __future__ import annotations

import queue
import threading
import time
from collections import deque
from dataclasses import dataclass

import numpy as np

import voice_shift as vs

DEFAULT_SR = 48000
DEFAULT_BLOCK_MS = 100
DEFAULT_CONTEXT_BLOCKS = 2
MAX_PENDING = 16


@dataclass
class Stats:
    """Engine counters; GUI polls them (single Python object swap = coherent)."""

    blocks: int = 0
    process_ms: float = 0.0
    block_ms: float = 0.0
    underruns: int = 0
    peak_in: float = 0.0
    peak_out: float = 0.0
    error: str = ""


def align_tail(y: np.ndarray, n: int) -> np.ndarray:
    """Trim (or zero-pad) a synthesized window to exactly `n` output samples."""
    if len(y) >= n:
        return np.ascontiguousarray(y[-n:], dtype=np.float32)
    out = np.zeros(n, dtype=np.float32)
    out[: len(y)] = y
    return out


def list_devices(
    rescan: bool = False,
) -> tuple[list[tuple[int, str, float]], list[tuple[int, str, float]]]:
    """-> (inputs, outputs), each entry (index, name, default_samplerate).

    PortAudio builds its device table once at Pa_Initialize (sounddevice does
    that at import), so hot-plugged devices stay invisible until a forced
    re-scan: Pa_Terminate + Pa_Initialize. rescan=True does exactly that —
    NEVER call it while streams are open: terminate would break them.
    """
    import sounddevice as sd

    if rescan:
        sd._terminate()
        sd._initialize()
    devs = sd.query_devices()
    inputs = [(i, d["name"], float(d["default_samplerate"]))
              for i, d in enumerate(devs) if d["max_input_channels"] > 0]
    outputs = [(i, d["name"], float(d["default_samplerate"]))
               for i, d in enumerate(devs) if d["max_output_channels"] > 0]
    return inputs, outputs


class RealtimeEngine:
    """Block DSP between two sounddevice streams. No Qt in here (unit-testable)."""

    def __init__(
        self,
        input_device: int,
        output_device: int,
        samplerate: int = DEFAULT_SR,
        block_ms: int = DEFAULT_BLOCK_MS,
        context_blocks: int = DEFAULT_CONTEXT_BLOCKS,
        backend: str = "world",
        pitch: float = 9.0,
        formant: float = 2.0,
        error_cb=None,
    ) -> None:
        self.input_device = input_device
        self.output_device = output_device
        self.samplerate = samplerate
        self.block_samples = max(1, round(samplerate * block_ms / 1000))
        self.context_blocks = context_blocks
        self.block_ms = block_ms
        self.stats = Stats(block_ms=float(block_ms))
        self._params = (backend, float(pitch), float(formant))
        self._error_cb = error_cb
        self._stop = threading.Event()
        self._in_q: queue.Queue[np.ndarray] = queue.Queue()
        self._out: deque[np.ndarray] = deque()
        self._out_lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._in_stream = None
        self._out_stream = None

    # ---- params (GUI thread writes, worker reads per block) ----
    def set_params(self, backend: str, pitch: float, formant: float) -> None:
        self._params = (backend, float(pitch), float(formant))

    # ---- audio callbacks (PortAudio threads) ----
    def _in_cb(self, indata, frames, time_info, status) -> None:
        self._in_q.put(np.asarray(indata[:, 0], dtype=np.float32).copy())

    def _out_cb(self, outdata, frames, time_info, status) -> None:
        with self._out_lock:
            block = self._out.popleft() if self._out else None
        if block is None:
            outdata.fill(0)
            self.stats.underruns += 1
            return
        n = min(frames, len(block))
        outdata[:n, 0] = block[:n]
        if outdata.shape[1] > 1:
            outdata[:n, 1] = block[:n]
        if n < frames:
            outdata[n:].fill(0)

    # ---- worker ----
    def _run(self) -> None:
        history: list[np.ndarray] = []
        acc: list[np.ndarray] = []
        acc_len = 0
        while not self._stop.is_set():
            try:
                chunk = self._in_q.get(timeout=0.1)
            except queue.Empty:
                continue
            acc.append(chunk)
            acc_len += len(chunk)
            if acc_len < self.block_samples:
                continue
            block = np.concatenate(acc)[: self.block_samples]
            acc, acc_len = [], 0

            window = np.concatenate([*history, block]).astype(np.float64)
            backend, pitch, formant = self._params
            t0 = time.perf_counter()
            try:
                y = vs.BACKENDS[backend](window, self.samplerate, pitch, formant)
            except Exception as exc:  # engine must not die silently on one bad block
                self.stats.error = f"{type(exc).__name__}: {exc}"
                if self._error_cb:
                    self._error_cb(self.stats.error)
                y = np.zeros_like(window)
            elapsed = (time.perf_counter() - t0) * 1000

            with self._out_lock:
                if len(self._out) < MAX_PENDING:
                    self._out.append(align_tail(y, self.block_samples))
            history.append(block)
            if len(history) > self.context_blocks:
                history.pop(0)

            s = self.stats
            s.blocks += 1
            s.process_ms = 0.8 * s.process_ms + 0.2 * elapsed if s.blocks > 1 else elapsed
            s.peak_in = 0.9 * s.peak_in + 0.1 * float(np.abs(block).max())
            s.peak_out = 0.9 * s.peak_out + 0.1 * float(np.abs(y[-self.block_samples:]).max())

    # ---- lifecycle ----
    def start(self) -> None:
        import sounddevice as sd

        if self._worker and self._worker.is_alive():
            raise RuntimeError("engine already running")
        self._stop.clear()
        self.stats = Stats(block_ms=float(self.block_ms))

        self._in_stream = sd.InputStream(
            samplerate=self.samplerate, blocksize=self.block_samples,
            device=self.input_device, channels=1, dtype="float32",
            callback=self._in_cb)
        self._out_stream = sd.OutputStream(
            samplerate=self.samplerate, blocksize=self.block_samples,
            device=self.output_device, channels=2, dtype="float32",
            callback=self._out_cb)
        self._in_stream.start()
        self._worker = threading.Thread(target=self._run, name="dsp-worker", daemon=True)
        self._worker.start()
        # prefill one block so the output stream starts with data (no startup gap);
        # never hold _out_lock while waiting (the worker needs it to append)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            with self._out_lock:
                if self._out:
                    break
            time.sleep(0.01)
        self._out_stream.start()

    def stop(self) -> None:
        self._stop.set()
        for stream in (self._out_stream, self._in_stream):
            if stream:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
        if self._worker:
            self._worker.join(timeout=3.0)
        self._in_stream = self._out_stream = None
        self._worker = None
        with self._out_lock:
            self._out.clear()

    @property
    def running(self) -> bool:
        return bool(self._worker and self._worker.is_alive())
