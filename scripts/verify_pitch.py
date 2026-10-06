#!/usr/bin/env python
"""Same-window autocorrelation F0 check: does a render really sit at the requested pitch?

WORLD harvest medians drift 2-4% on resynthesized speech, so this uses FFT
autocorrelation on one fixed 1 s window (picked on the reference file) and
compares every render against the theoretical 2**(semitones/12) ratio.

Usage:
  python verify_pitch.py REF.wav FILE.wav:SEMITONES [FILE.wav:SEMITONES ...]
"""
from __future__ import annotations

import argparse

import numpy as np

import voice_shift as vs


def ac_f0(seg: np.ndarray, sr: int, lo: float = 70.0, hi: float = 600.0) -> tuple[float, float]:
    """Autocorrelation F0 (parabolic peak interpolation) and its peak height."""
    seg = seg - seg.mean()
    n = len(seg)
    nfft = 1 << int(np.ceil(np.log2(2 * n)))
    ac = np.fft.irfft(np.abs(np.fft.rfft(seg, nfft)) ** 2)[:n]
    ac /= ac[0]
    la, lb = int(sr / hi), int(sr / lo)
    lag = la + int(np.argmax(ac[la:lb]))
    y0, y1, y2 = ac[lag - 1], ac[lag], ac[lag + 1]
    frac = 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2)
    return float(sr / (lag + frac)), float(y1)


def pick_window(x: np.ndarray, sr: int) -> int:
    """Offset of the most periodic 1 s window with real energy."""
    n, step = sr, sr // 4
    def score(i: int) -> float:
        seg = x[i:i + n]
        return ac_f0(seg, sr)[1] if float(np.sqrt((seg ** 2).mean())) > 0.02 else 0.0
    return max(range(0, len(x) - n, step), key=score)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ref")
    ap.add_argument("renders", nargs="+", help="path.wav:SEMITONES")
    args = ap.parse_args()

    x, sr = vs.load_mono(args.ref)
    off = pick_window(x, sr)
    base, streak = ac_f0(x[off:off + sr], sr)
    print(f"ref {args.ref}: window @{off / sr:.2f}s f0={base:.1f} Hz ac={streak:.3f}")

    worst = 0.0
    for item in args.renders:
        path, semis = item.rsplit(":", 1)
        y, sr_y = vs.load_mono(path)
        f0, streak_y = ac_f0(y[off:off + sr_y], sr_y)
        expected = 2.0 ** (float(semis) / 12)
        dev = 100 * (f0 / base / expected - 1)
        worst = max(worst, abs(dev))
        print(f"  {path.rsplit('/', 1)[-1]:26s} semis={float(semis):+5.1f} "
              f"f0={f0:6.1f} ratio={f0 / base:.4f} target={expected:.4f} dev={dev:+.2f}%")
    print(f"worst deviation: {worst:.2f}%")
    return 0 if worst < 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
