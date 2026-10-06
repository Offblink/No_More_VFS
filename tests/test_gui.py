"""GUI 响应式接线：滑条/后端实时生效、复原按钮、设备列表刷新保选择。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QApplication

import gui
import realtime
import voice_shift as vs

IN_A = [(1, "Mic A", 48000.0), (25, "Mic B", 48000.0)]
OUT_A = [(16, "CABLE Input (VB-Audio Virtual Cable)", 48000.0),
         (5, "Speakers", 44100.0)]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def make_page(monkeypatch) -> gui.Page:
    monkeypatch.setattr(realtime, "list_devices",
                        lambda rescan=False: (list(IN_A), list(OUT_A)))
    return gui.Page()


def test_slider_change_applies_params_live(app, monkeypatch):
    """滑条拖动 -> 立即写进 engine（运行中下一块生效，无需重启）。"""
    page = make_page(monkeypatch)
    page.engine = Mock()
    page.pitch_slider.setValue(round(12.0 / vs.PARAM_STEP))
    page.engine.set_params.assert_called_with(
        "world", 12.0, vs.DEFAULT_FORMANT)
    page.formant_slider.setValue(round(0.0 / vs.PARAM_STEP))
    page.engine.set_params.assert_called_with(
        "world", 12.0, 0.0)


def test_backend_change_applies_live(app, monkeypatch):
    """换后端也要响应式。"""
    page = make_page(monkeypatch)
    page.engine = Mock()
    page.backend_box.setCurrentIndex(1)  # praat
    page.engine.set_params.assert_called_with(
        "praat", vs.DEFAULT_PITCH, vs.DEFAULT_FORMANT)


def test_reset_button_restores_defaults(app, monkeypatch):
    page = make_page(monkeypatch)
    page.pitch_slider.setValue(page.pitch_slider.minimum())
    page.formant_slider.setValue(page.formant_slider.maximum())
    page.pitch_reset.click()
    page.formant_reset.click()
    assert page._slider_value(page.pitch_slider) == vs.DEFAULT_PITCH
    assert page._slider_value(page.formant_slider) == vs.DEFAULT_FORMANT
    assert page.pitch_label.text() == f"移调 {vs.DEFAULT_PITCH:.1f} 半音"


def test_device_timer_active_and_refresh_preserves_selection(app, monkeypatch):
    page = make_page(monkeypatch)
    assert page._device_timer.isActive()
    assert page._device_timer.interval() == gui.DEVICE_REFRESH_MS

    page.in_box.setCurrentIndex(1)               # Mic B (#25)
    page.refresh_devices()                        # 同名单 -> 不重建
    assert page.in_box.currentIndex() == 1

    new_in = IN_A + [(27, "Mic C", 48000.0)]
    monkeypatch.setattr(realtime, "list_devices",
                        lambda rescan=False: (list(new_in), list(OUT_A)))
    page.refresh_devices()                        # 名单变了 -> 重建
    assert len(page._inputs) == 3
    assert page.in_box.currentIndex() == 1        # 仍选中 #25（按设备 id 保选择）
    assert "Mic B" in page.in_box.currentText()


def _fake_engine_cls():
    class FakeEngine:
        instances: list = []

        def __init__(self, **kw):
            self.kw = kw
            self._running = False
            FakeEngine.instances.append(self)

        @property
        def running(self):
            return self._running

        def start(self):
            self._running = True

        def stop(self):
            self._running = False

        def set_params(self, *args):
            pass

    return FakeEngine


def test_device_switch_restarts_running_engine(app, monkeypatch):
    """设备切换响应式：运行中切输入设备 = 停旧引擎、按新设备起新引擎。"""
    page = make_page(monkeypatch)
    fake = _fake_engine_cls()
    monkeypatch.setattr(realtime, "RealtimeEngine", fake)

    page.toggle()                                  # 起第一台
    assert len(fake.instances) == 1 and fake.instances[0].running

    page.in_box.setCurrentIndex(1)                 # 用户切到 Mic B (#25)
    assert len(fake.instances) == 2
    assert not fake.instances[0].running            # 旧的停了
    assert fake.instances[1].running
    assert fake.instances[1].kw["input_device"] == 25


def test_device_refresh_never_restarts_running_engine(app, monkeypatch):
    """2.5 s 定时刷新撞上运行中：只是重建下拉，绝不能拽着引擎重启。"""
    page = make_page(monkeypatch)
    fake = _fake_engine_cls()
    monkeypatch.setattr(realtime, "RealtimeEngine", fake)
    page.toggle()

    monkeypatch.setattr(realtime, "list_devices",
                        lambda rescan=False: (list(IN_A) + [(27, "Mic C", 48000.0)],
                                              list(OUT_A)))
    page.refresh_devices()

    assert len(fake.instances) == 1
    assert fake.instances[0].running


def test_window_title_plain_ascii(app, monkeypatch):
    """显示名层：无中文、无下划线（下划线留给 GitHub 仓名）。"""
    monkeypatch.setattr(realtime, "list_devices",
                        lambda rescan=False: (list(IN_A), list(OUT_A)))
    win = gui.Window()
    assert win.windowTitle() == "NoMoreVFS"


def _recording_devices(calls: list):
    def fake(rescan=False):
        calls.append(rescan)
        return list(IN_A), list(OUT_A)

    return fake


def test_manual_refresh_forces_rescan_when_idle(app, monkeypatch):
    """刷新按钮：待机也必须走强制重扫（热插拔就靠它）。"""
    page = make_page(monkeypatch)
    calls: list = []
    monkeypatch.setattr(realtime, "list_devices", _recording_devices(calls))
    page.refresh_btn.click()
    assert calls == [True]


def test_auto_refresh_skips_rescan_while_running(app, monkeypatch):
    """2.5 s 定时器撞上运行中：只查不重扫（Pa_Terminate 会砸流），且不重启引擎。"""
    page = make_page(monkeypatch)
    fake = _fake_engine_cls()
    monkeypatch.setattr(realtime, "RealtimeEngine", fake)
    page.toggle()

    calls: list = []
    monkeypatch.setattr(realtime, "list_devices", _recording_devices(calls))
    page.refresh_devices()                      # 定时器路径（rescan=None）
    assert calls == [False]
    assert len(fake.instances) == 1
    assert fake.instances[0].running


def test_manual_refresh_while_running_restarts_engine(app, monkeypatch):
    """运行中点刷新：停机重扫再起（短重启一次），重扫必须发生。"""
    page = make_page(monkeypatch)
    fake = _fake_engine_cls()
    monkeypatch.setattr(realtime, "RealtimeEngine", fake)
    page.toggle()

    calls: list = []
    monkeypatch.setattr(realtime, "list_devices", _recording_devices(calls))
    page.refresh_btn.click()
    assert calls == [True]
    assert len(fake.instances) == 2
    assert not fake.instances[0].running
    assert fake.instances[1].running
