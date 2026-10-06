"""DSP 核心不变量：两个旋钮互不干扰，移位量精确，范围守住，时长与电平不失控。"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import voice_shift as vs

SR = 22050


def harmonic_tone(freq: float = 200.0, dur: float = 1.0, n_harm: int = 12):
    """类浊音测试信号：谐波堆（1/k 幅度衰减），没有共振峰结构。"""
    t = np.arange(int(dur * SR)) / SR
    x = sum(np.sin(2 * np.pi * freq * k * t) / k for k in range(1, n_harm + 1))
    return (0.3 * x / np.max(np.abs(x))).astype(np.float64)


def analyzed_f0_median(x: np.ndarray) -> float:
    f0, _, _ = vs.world_analyze(x, SR)
    voiced = f0[f0 > 0]
    assert voiced.size, "no voiced frames in test signal"
    return float(np.median(voiced))


def envelope_centroid(sp: np.ndarray) -> float:
    n_bins = sp.shape[1]
    freqs = np.arange(n_bins) * (SR / 2.0) / (n_bins - 1)
    return float((sp * freqs).sum() / sp.sum())


def test_warped_envelope_scales_frequency_axis_up_and_down():
    n_bins, peak_bin = 513, 120
    sp = np.exp(-0.5 * ((np.arange(n_bins) - peak_bin) / 3.0) ** 2)[None, :]

    up = vs.warped_envelope(sp, 2.0 ** (2 / 12))[0]
    assert abs(int(np.argmax(up)) - round(peak_bin * 2.0 ** (2 / 12))) <= 1

    down = vs.warped_envelope(sp, 2.0 ** (-3 / 12))[0]
    assert int(np.argmax(down)) < peak_bin
    assert abs(int(np.argmax(down)) - round(peak_bin * 2.0 ** (-3 / 12))) <= 1

    assert np.allclose(vs.warped_envelope(sp, 1.0), sp, atol=1e-12)
    assert np.isfinite(vs.warped_envelope(sp, 0.1)).all()  # 压低时不能出 NaN


@pytest.mark.parametrize("semis", [7.0, -7.0])
def test_world_shift_moves_f0_by_requested_semitones(semis):
    x = harmonic_tone()
    y = vs.world_shift(x, SR, semis, 0.0)
    ratio = analyzed_f0_median(y) / analyzed_f0_median(x)
    assert abs(ratio - 2.0 ** (semis / 12)) < 0.02
    assert abs(len(y) / SR - len(x) / SR) < 0.02


def test_each_knob_only_touches_its_own_parameter(monkeypatch):
    """确定性：共振峰旋钮不得改 f0，移调旋钮不得改包络（免得两者互相污染）。"""
    x = harmonic_tone()
    f0_in, sp_in, _ = vs.world_analyze(x, SR)
    seen: dict[str, np.ndarray] = {}

    def fake_synth(f0, sp, ap, sr):
        seen["f0"], seen["sp"] = f0.copy(), sp.copy()
        return np.zeros(64)

    monkeypatch.setattr(vs, "world_synthesize", fake_synth)

    vs.world_shift(x, SR, 9.0, 0.0)
    assert np.allclose(seen["sp"], sp_in)
    assert np.allclose(seen["f0"], f0_in * 2.0 ** (9 / 12))

    vs.world_shift(x, SR, 0.0, 4.0)
    assert np.allclose(seen["f0"], f0_in)
    assert not np.allclose(seen["sp"], sp_in)
    assert np.all(seen["sp"] >= 0)


def test_formant_knob_lifts_envelope_in_rendered_audio():
    """机制侧证据：共振峰旋钮（此处 4 半音，库函数不设限）让成品包络重心上移。"""
    x = harmonic_tone()
    _, sp_in, _ = vs.world_analyze(x, SR)
    y = vs.world_shift(x, SR, 0.0, 4.0)
    _, sp_out, _ = vs.world_analyze(y, SR)
    assert envelope_centroid(sp_out) / envelope_centroid(sp_in) > 1.12


def test_pitch_range_bounds():
    check = vs._bounded("pitch", *vs.PITCH_RANGE)
    assert check("0") == 0.0
    assert check("15") == 15.0
    for bad in ("-0.5", "15.5", "99", "abc"):
        with pytest.raises(argparse.ArgumentTypeError):
            check(bad)


def test_formant_range_excludes_four():
    """fplus4 已被听感否掉（2026-10-06）：CLI 上界必须 < 4 半音。"""
    check = vs._bounded("formant", *vs.FORMANT_RANGE)
    assert vs.FORMANT_RANGE[1] < 4.0
    assert check("3") == 3.0
    for bad in ("4", "-1"):
        with pytest.raises(argparse.ArgumentTypeError):
            check(bad)


def test_cli_enforces_ranges(tmp_path):
    """接线级：真跑 CLI，越界 exit 2 并报范围（不是静默截断）。"""
    script = Path(vs.__file__).resolve()
    proc = subprocess.run(
        [sys.executable, str(script), "missing.wav", str(tmp_path / "x.wav"),
         "--pitch", "99"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2
    assert "must be in" in proc.stderr


def test_write_wav_applies_peak_guard_and_roundtrips(tmp_path):
    x = harmonic_tone(freq=300.0)
    loud = x * (2.0 / np.max(np.abs(x)))
    path = tmp_path / "loud.wav"
    vs.write_wav(str(path), loud, SR)

    y, sr = vs.load_mono(str(path))
    assert sr == SR
    assert abs(len(y) - len(x)) <= 1
    assert float(np.max(np.abs(y))) <= 1.0


def test_praat_backend_shifts_pitch_and_preserves_duration():
    x = harmonic_tone(dur=1.0)
    y = vs.praat_shift(x, SR, 9.0, 2.0)
    assert abs(len(y) / SR - 1.0) < 0.05
    ratio = analyzed_f0_median(y) / analyzed_f0_median(x)
    assert abs(ratio - 2.0 ** (9 / 12)) < 0.06
