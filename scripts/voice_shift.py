#!/usr/bin/env python
"""Offline voice conversion: independent pitch shift + formant shift.

Backends:
  world  - WORLD vocoder (pyworld): f0 *= 2**(pitch/12), spectral envelope
           frequency axis warped by 2**(formant/12). Both knobs independent.
  praat  - Praat PSOLA (parselmouth): "Change gender" with target pitch median.

Parameter ranges are the product contract (2026-10-06):
  pitch   0..15 semitones (target domain +7..12, handoff §4)
  formant 0..3  semitones (+4 rejected by listening)
The CLI rejects out-of-range values; the GUI uses the same constants.
phase vocoder backend removed by user verdict (2026-10-06).
"""
from __future__ import annotations

import argparse

import numpy as np
import soundfile as sf

F0_FLOOR = 71.0   # ~ male low end; keeps WORLD fft_size reasonable
F0_CEIL = 800.0
FRAME_PERIOD = 5.0

# 可调范围：CLI 越界即拒；GUI 滑条用同一组常量（唯一事实来源）。
PITCH_RANGE = (0.0, 15.0)   # semitones，0 = 不移调
FORMANT_RANGE = (0.0, 3.0)  # semitones
PARAM_STEP = 0.5            # GUI 步进
# 默认档 = 已测 AB 档（handoff §6.1/§6.3）；GUI 滑条初值与"复原"按钮都读这里。
DEFAULT_PITCH = 9.0
DEFAULT_FORMANT = 2.0


def load_mono(path: str) -> tuple[np.ndarray, int]:
    x, sr = sf.read(path, dtype="float64", always_2d=False)
    if x.ndim > 1:
        x = x.mean(axis=1)
    return x, int(sr)


def write_wav(path: str, x: np.ndarray, sr: int) -> None:
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if peak > 0.99:
        x = x * (0.99 / peak)
    sf.write(path, x.astype(np.float32), sr, subtype="PCM_16")


def warped_envelope(sp: np.ndarray, ratio: float) -> np.ndarray:
    """Warp the spectral envelope's frequency axis by `ratio` (bin-axis interp)."""
    n_bins = sp.shape[1]
    idx = np.arange(n_bins, dtype=np.float64) / ratio
    np.clip(idx, 0.0, n_bins - 1.0, out=idx)
    i0 = np.floor(idx).astype(np.int64)
    i1 = np.minimum(i0 + 1, n_bins - 1)
    w = (idx - i0)[None, :]
    return sp[:, i0] * (1.0 - w) + sp[:, i1] * w


def world_analyze(x: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """WORLD analysis -> (f0, spectral envelope, aperiodicity)."""
    import pyworld as pw

    f0, t = pw.harvest(x, sr, f0_floor=F0_FLOOR, f0_ceil=F0_CEIL, frame_period=FRAME_PERIOD)
    f0 = pw.stonemask(x, f0, t, sr)
    sp = pw.cheaptrick(x, f0, t, sr, f0_floor=F0_FLOOR)
    ap = pw.d4c(x, f0, t, sr)
    return f0, sp, ap


def world_synthesize(f0: np.ndarray, sp: np.ndarray, ap: np.ndarray, sr: int) -> np.ndarray:
    import pyworld as pw

    y = pw.synthesize(f0, np.ascontiguousarray(sp), ap, sr, frame_period=FRAME_PERIOD)
    return np.asarray(y, dtype=np.float64)


def world_shift(x: np.ndarray, sr: int, semis: float, formant_semis: float) -> np.ndarray:
    f0, sp, ap = world_analyze(x, sr)
    f0 = f0 * (2.0 ** (semis / 12.0))
    if abs(formant_semis) > 1e-9:
        sp = warped_envelope(sp, 2.0 ** (formant_semis / 12.0))
    return world_synthesize(f0, sp, ap, sr)


def praat_shift(x: np.ndarray, sr: int, semis: float, formant_semis: float) -> np.ndarray:
    import parselmouth
    from parselmouth.praat import call

    snd = parselmouth.Sound(x.astype(np.float64), sampling_frequency=sr)
    ratio = 2.0 ** (semis / 12.0)

    if abs(formant_semis) > 1e-9:
        # Praat "Change gender" = PSOLA resynthesis with formant ratio
        # (formant_shift_ratio) and an absolute target pitch median.
        new_median = 0.0
        if abs(semis) > 1e-9:
            p = call(snd, "To Pitch", 0.0, max(F0_FLOOR, 75.0), F0_CEIL)
            med = call(p, "Get quantile", snd.xmin, snd.xmax, 0.5, "Hertz")
            if med and med == med:
                new_median = med * ratio
        res = call(snd, "Change gender", max(F0_FLOOR, 75.0), F0_CEIL,
                   2.0 ** (formant_semis / 12.0), new_median, 1.0, 1.0)
        return np.asarray(res.values[0], dtype=np.float64).squeeze()

    man = call(snd, "To Manipulation", 0.01, max(F0_FLOOR, 75.0), F0_CEIL)
    pt = call(man, "Extract pitch tier")
    call(pt, "Multiply frequencies", snd.xmin, snd.xmax, ratio)
    call([man, pt], "Replace pitch tier")
    res = call(man, "Get resynthesis (overlap-add)")
    return np.asarray(res.values[0], dtype=np.float64).squeeze()


BACKENDS = {"world": world_shift, "praat": praat_shift}


def _bounded(name: str, lo: float, hi: float):
    def check(value: str) -> float:
        try:
            x = float(value)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{name} must be a number, got {value!r}") from None
        if not lo <= x <= hi:
            raise argparse.ArgumentTypeError(
                f"{name} must be in [{lo:g}, {hi:g}] semitones, got {x:g}")
        return x

    return check


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--backend", choices=sorted(BACKENDS), default="world")
    ap.add_argument("--pitch", type=_bounded("pitch", *PITCH_RANGE), required=True,
                    help="pitch shift in semitones (0..15)")
    ap.add_argument("--formant", type=_bounded("formant", *FORMANT_RANGE), default=0.0,
                    help="formant shift in semitones (0..3)")
    args = ap.parse_args()

    x, sr = load_mono(args.src)
    y = BACKENDS[args.backend](x, sr, args.pitch, args.formant)
    write_wav(args.dst, y, sr)
    print(f"{args.backend} pitch={args.pitch:+g} formant={args.formant:+g} "
          f"in={len(x)/sr:.2f}s out={len(y)/sr:.2f}s -> {args.dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
