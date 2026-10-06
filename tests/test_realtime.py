"""Realtime engine invariants: block math, streaming pipeline, underrun contract."""
from __future__ import annotations

import threading
import time

import numpy as np

import realtime


def _engine(**kw) -> realtime.RealtimeEngine:
    defaults = dict(input_device=-1, output_device=-1, samplerate=22050, block_ms=100)
    defaults.update(kw)
    return realtime.RealtimeEngine(**defaults)


def test_block_samples_matches_block_ms():
    eng = _engine()
    assert eng.block_samples == 2205
    assert eng.stats.block_ms == 100.0


def test_align_tail_trims_and_pads_to_exact_length():
    trimmed = realtime.align_tail(np.arange(5000.0), 4800)
    assert len(trimmed) == 4800
    assert trimmed.dtype == np.float32
    np.testing.assert_allclose(trimmed, np.arange(5000.0)[-4800:])

    padded = realtime.align_tail(np.arange(4000.0), 4800)
    assert len(padded) == 4800
    np.testing.assert_allclose(padded[:4000], np.arange(4000.0))
    assert not padded[4000:].any()


def test_worker_pipeline_produces_aligned_blocks():
    """端到端（无音频设备）：注入原始块 -> DSP -> 输出队列长度与类型正确。"""
    eng = _engine(backend="praat", pitch=7.0, formant=0.0, context_blocks=2)
    worker = threading.Thread(target=eng._run, daemon=True)
    worker.start()
    try:
        tone = (0.3 * np.sin(2 * np.pi * 220 * np.arange(2205) / 22050)).astype(np.float32)
        for _ in range(4):
            eng._in_q.put(tone)
            time.sleep(0.05)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            with eng._out_lock:
                if eng._out:
                    break
            time.sleep(0.05)
        with eng._out_lock:
            assert eng._out, "worker never produced a block"
            block = eng._out[0]
        assert len(block) == eng.block_samples
        assert block.dtype == np.float32
        assert eng.stats.blocks >= 1
        assert eng.stats.error == ""
    finally:
        eng._stop.set()
        worker.join(timeout=2.0)
    assert not worker.is_alive()


def test_output_callback_counts_underruns_and_fills_channels():
    eng = _engine()
    outdata = np.zeros((eng.block_samples, 2), dtype=np.float32)

    eng._out_cb(outdata, eng.block_samples, None, None)  # empty queue -> silence
    assert eng.stats.underruns == 1
    assert not outdata.any()

    with eng._out_lock:
        eng._out.append(np.full(eng.block_samples, 0.5, dtype=np.float32))
    eng._out_cb(outdata, eng.block_samples, None, None)
    assert eng.stats.underruns == 1  # 没欠载就不该再加
    assert np.allclose(outdata[:, 0], 0.5)
    assert np.allclose(outdata[:, 1], 0.5)


def test_gui_module_imports():
    """import 级冒烟：qfluentwidgets 组件名与顶层副作用（不起 QApplication）。"""
    import gui  # noqa: F401
