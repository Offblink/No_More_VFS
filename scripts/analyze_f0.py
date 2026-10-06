#!/usr/bin/env python
"""F0 / loudness / voicing evidence for one or more wav files (WORLD harvest)."""
from __future__ import annotations

import sys

import numpy as np
import pyworld as pw
import soundfile as sf


def stats(path: str) -> dict:
    x, sr = sf.read(path, dtype="float64", always_2d=False)
    if x.ndim > 1:
        x = x.mean(axis=1)
    f0, t = pw.harvest(x, sr, f0_floor=71.0, f0_ceil=800.0, frame_period=5.0)
    f0 = pw.stonemask(x, f0, t, sr)
    voiced = f0[f0 > 0]
    rms = float(np.sqrt(np.mean(x ** 2)))
    return {
        "file": path,
        "dur_s": round(len(x) / sr, 2),
        "rms": round(rms, 4),
        "voiced_ratio": round(len(voiced) / max(len(f0), 1), 3),
        "f0_median": round(float(np.median(voiced)), 1) if len(voiced) else None,
        "f0_p10": round(float(np.percentile(voiced, 10)), 1) if len(voiced) else None,
        "f0_p90": round(float(np.percentile(voiced, 90)), 1) if len(voiced) else None,
    }


def main() -> int:
    for path in sys.argv[1:]:
        s = stats(path)
        print(f"{s['file']}\n  dur={s['dur_s']}s rms={s['rms']} voiced={s['voiced_ratio']} "
              f"F0 med={s['f0_median']} p10={s['f0_p10']} p90={s['f0_p90']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
