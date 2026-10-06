#!/usr/bin/env python
"""Render the listening set: parameter grid per backend + A/B across backends.

Example:
  python render_scan.py --source "C:/Users/Blinvo/Documents/seedvc-audio/user_live.wav" \
      --outdir output/listen --excerpt 12
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import voice_shift as vs

BACKENDS = ["world", "praat"]
PITCHES = [7, 9, 12]
# 产品范围 voice_shift.PITCH_RANGE / FORMANT_RANGE（0~15 / 0~3 半音）；
# fplus4 出圈（用户 2026-10-06 听感判定），网格只取样 range 内的值。
FORMANTS = [0, 2]
AB_SETTING = (9, 2)  # backend comparison setting
AB_BACKENDS = ["praat"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--outdir", default="output/listen")
    ap.add_argument("--excerpt", type=float, default=0.0,
                    help="seconds to keep (0 = whole file)")
    ap.add_argument("--start", type=float, default=0.0, help="start offset in seconds")
    ap.add_argument("--world-only", action="store_true")
    args = ap.parse_args()

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)

    x, sr = vs.load_mono(args.source)
    if args.excerpt and args.excerpt > 0:
        lo = int(args.start * sr)
        x = x[lo: lo + int(args.excerpt * sr)]
    src_cut = out / "_source_excerpt.wav"
    vs.write_wav(str(src_cut), x, sr)

    rows = []
    for p in PITCHES:
        for f in FORMANTS:
            name = f"world_p{p}_f{f:+d}.wav".replace("+", "plus").replace("-", "minus")
            y = vs.world_shift(x, sr, p, f)
            vs.write_wav(str(out / name), y, sr)
            rows.append({"file": name, "backend": "world", "pitch": p, "formant": f})

    if not args.world_only:
        for b in AB_BACKENDS:
            name = f"ab_p{AB_SETTING[0]}_f{AB_SETTING[1]:+d}_{b}.wav".replace("+", "plus")
            y = vs.BACKENDS[b](x, sr, AB_SETTING[0], AB_SETTING[1])
            vs.write_wav(str(out / name), y, sr)
            rows.append({"file": name, "backend": b,
                         "pitch": AB_SETTING[0], "formant": AB_SETTING[1]})

    # F0 evidence for every rendered file
    import analyze_f0
    for r in rows:
        r.update({k: v for k, v in analyze_f0.stats(str(out / r["file"])).items()
                  if k in ("f0_median", "f0_p10", "f0_p90", "voiced_ratio", "rms")})

    with (out / "manifest.json").open("w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)

    lines = ["| file | backend | pitch | formant | F0 med | voiced | rms |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['file']} | {r['backend']} | {r['pitch']:+d} | {r['formant']:+d} | "
                     f"{r['f0_median']} | {r['voiced_ratio']} | {r['rms']} |")
    (out / "manifest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
