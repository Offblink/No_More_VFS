"""No_More_VFS realtime GUI: PySide6-Fluent single-page window over RealtimeEngine.

Responsive wiring (2026-10-06):
  slider / backend change -> Page._apply_params -> engine.set_params (takes
      effect on the next block, no restart needed)
  device comboboxes      -> rebuilt by a DEVICE_REFRESH_MS poll; selection is
      preserved by device index so a refresh never yanks the user's choice
  "复原" per slider      -> back to voice_shift.DEFAULT_PITCH / DEFAULT_FORMANT
Ranges AND defaults come from voice_shift (single source of truth).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QHBoxLayout, QSlider, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    FluentIcon,
    FluentWindow,
    InfoBar,
    InfoBarPosition,
    NavigationItemPosition,
    PrimaryPushButton,
    PushButton,
    SimpleCardWidget,
    Slider,
    StrongBodyLabel,
)

import realtime
import voice_shift as vs

DEVICE_REFRESH_MS = 2500


def _default_output_idx(outputs: list[tuple[int, str, float]]) -> int:
    """Prefer the 48 kHz CABLE Input endpoint; else first CABLE; else first."""
    for pos, (_, name, sr) in enumerate(outputs):
        if "cable input" in name.lower() and sr >= 48000:
            return pos
    for pos, (_, name, _) in enumerate(outputs):
        if "cable input" in name.lower():
            return pos
    return 0


class Page(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.engine: realtime.RealtimeEngine | None = None
        self._toast = None
        self._last_error = ""
        self._inputs: list[tuple[int, str, float]] = []
        self._outputs: list[tuple[int, str, float]] = []
        self._sig = None
        self._rebuilding = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 24)
        lay.setSpacing(12)

        # --- params card ---
        params = SimpleCardWidget()
        pl = QVBoxLayout(params)
        pl.setContentsMargins(16, 12, 16, 12)
        pl.setSpacing(8)
        pl.addWidget(StrongBodyLabel("参数"))

        row = QHBoxLayout()
        row.addWidget(BodyLabel("后端"))
        self.backend_box = ComboBox()
        self.backend_box.addItems(["world", "praat"])
        self.backend_box.setMaximumWidth(180)
        row.addWidget(self.backend_box, 1)
        pl.addLayout(row)

        self.pitch_slider = self._make_slider(vs.PITCH_RANGE)
        row = QHBoxLayout()
        row.addWidget(BodyLabel("移调（半音）"))
        row.addStretch(1)
        self.pitch_reset = PushButton("复原")
        self.pitch_reset.setFixedWidth(76)
        row.addWidget(self.pitch_reset)
        pl.addLayout(row)
        pl.addWidget(self.pitch_slider)
        self.pitch_label = CaptionLabel("")
        pl.addWidget(self.pitch_label)

        self.formant_slider = self._make_slider(vs.FORMANT_RANGE)
        row = QHBoxLayout()
        row.addWidget(BodyLabel("共振峰（半音）"))
        row.addStretch(1)
        self.formant_reset = PushButton("复原")
        self.formant_reset.setFixedWidth(76)
        row.addWidget(self.formant_reset)
        pl.addLayout(row)
        pl.addWidget(self.formant_slider)
        self.formant_label = CaptionLabel("")
        pl.addWidget(self.formant_label)
        lay.addWidget(params)

        # --- devices card ---
        devices = SimpleCardWidget()
        dl = QVBoxLayout(devices)
        dl.setContentsMargins(16, 12, 16, 12)
        dl.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(StrongBodyLabel("设备"))
        head.addStretch(1)
        self.refresh_btn = PushButton("刷新")
        self.refresh_btn.setFixedWidth(76)
        head.addWidget(self.refresh_btn)
        dl.addLayout(head)
        row = QHBoxLayout()
        row.addWidget(BodyLabel("输入（麦）"))
        self.in_box = ComboBox()
        row.addWidget(self.in_box, 1)
        dl.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(BodyLabel("输出（变声出口）"))
        self.out_box = ComboBox()
        row.addWidget(self.out_box, 1)
        dl.addLayout(row)
        lay.addWidget(devices)

        # --- run row ---
        row = QHBoxLayout()
        self.start_btn = PrimaryPushButton("开始变声")
        self.start_btn.clicked.connect(self.toggle)
        row.addWidget(self.start_btn)
        self.status_label = CaptionLabel("待机")
        self.status_label.setWordWrap(True)
        row.addWidget(self.status_label, 1)
        lay.addLayout(row)
        lay.addStretch(1)

        # defaults = tested AB setting (voice_shift.DEFAULT_*), not range-min
        self.pitch_slider.setValue(round(vs.DEFAULT_PITCH / vs.PARAM_STEP))
        self.formant_slider.setValue(round(vs.DEFAULT_FORMANT / vs.PARAM_STEP))

        # responsive wiring
        self.backend_box.currentIndexChanged.connect(self._apply_params)
        for slider in (self.pitch_slider, self.formant_slider):
            slider.valueChanged.connect(self._refresh_labels)
            slider.valueChanged.connect(self._apply_params)
        self.pitch_reset.clicked.connect(self._reset_pitch)
        self.formant_reset.clicked.connect(self._reset_formant)
        self.in_box.currentIndexChanged.connect(self._on_device_changed)
        self.out_box.currentIndexChanged.connect(self._on_device_changed)
        self.refresh_btn.clicked.connect(self._manual_refresh)
        self._refresh_labels()

        self.refresh_devices()
        self._apply_params()

        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(300)
        self._stats_timer.timeout.connect(self._poll_stats)
        self._stats_timer.start()

        self._device_timer = QTimer(self)
        self._device_timer.setInterval(DEVICE_REFRESH_MS)
        self._device_timer.timeout.connect(self.refresh_devices)
        self._device_timer.start()

    # ---- helpers ----
    @staticmethod
    def _make_slider(rng: tuple[float, float]) -> Slider:
        step = vs.PARAM_STEP
        s = Slider(Qt.Horizontal)
        s.setRange(round(rng[0] / step), round(rng[1] / step))
        return s

    @staticmethod
    def _slider_value(slider: QSlider) -> float:
        return slider.value() * vs.PARAM_STEP

    def _refresh_labels(self) -> None:
        self.pitch_label.setText(f"移调 {self._slider_value(self.pitch_slider):.1f} 半音")
        self.formant_label.setText(f"共振峰 {self._slider_value(self.formant_slider):.1f} 半音")

    def _reset_pitch(self) -> None:
        self.pitch_slider.setValue(round(vs.DEFAULT_PITCH / vs.PARAM_STEP))

    def _reset_formant(self) -> None:
        self.formant_slider.setValue(round(vs.DEFAULT_FORMANT / vs.PARAM_STEP))

    @staticmethod
    def _selected_dev(devices: list[tuple[int, str, float]], box: ComboBox) -> int | None:
        i = box.currentIndex()
        return devices[i][0] if 0 <= i < len(devices) else None

    def refresh_devices(self, rescan: bool | None = None) -> None:
        """Poll/button handler: rebuild only when the device set actually changed.

        rescan=None (2.5 s timer): force a PortAudio re-scan only while idle —
        a running engine owns the device table (Pa_Terminate would break its
        streams). The refresh button always passes rescan=True (it stops the
        engine first, see _manual_refresh).
        """
        if rescan is None:
            rescan = not (self.engine and self.engine.running)
        inputs, outputs = realtime.list_devices(rescan=rescan)
        sig = (tuple(inputs), tuple(outputs))
        if sig == self._sig:
            return
        in_sel = self._selected_dev(self._inputs, self.in_box)
        out_sel = self._selected_dev(self._outputs, self.out_box)
        self._inputs, self._outputs, self._sig = inputs, outputs, sig

        self._rebuilding = True  # 刷新期的 index 变化不是用户操作，不许触发重启
        try:
            self.in_box.clear()
            self.in_box.addItems([f"{name} (#{idx})" for idx, name, _ in self._inputs])
            pos = next((i for i, (idx, _, _) in enumerate(self._inputs) if idx == in_sel), 0)
            if self._inputs:
                self.in_box.setCurrentIndex(min(pos, len(self._inputs) - 1))

            self.out_box.clear()
            self.out_box.addItems([f"{name} (#{idx})" for idx, name, _ in self._outputs])
            pos = next((i for i, (idx, _, _) in enumerate(self._outputs) if idx == out_sel),
                       _default_output_idx(self._outputs))
            if self._outputs:
                self.out_box.setCurrentIndex(min(pos, len(self._outputs) - 1))
        finally:
            self._rebuilding = False

    def _manual_refresh(self) -> None:
        """刷新按钮：停机强制重扫（热插拔检测）→ 重建下拉；运行中会短重启一次。"""
        was_running = bool(self.engine and self.engine.running)
        if was_running:
            self._stop_engine()
        self.refresh_devices(rescan=True)
        if was_running:
            self._start_engine()

    def _apply_params(self) -> None:
        if self.engine:
            self.engine.set_params(
                self.backend_box.currentText(),
                self._slider_value(self.pitch_slider),
                self._slider_value(self.formant_slider),
            )

    # ---- run ----
    def toggle(self) -> None:
        if self.engine and self.engine.running:
            self._stop_engine()
        else:
            self._start_engine()

    def _stop_engine(self) -> None:
        if self.engine:
            self.engine.stop()
        self.engine = None
        self.start_btn.setText("开始变声")
        self.status_label.setText("已停止")

    def _start_engine(self) -> None:
        try:
            in_idx = self._inputs[self.in_box.currentIndex()][0]
            out_idx = self._outputs[self.out_box.currentIndex()][0]
            self.engine = realtime.RealtimeEngine(
                input_device=in_idx,
                output_device=out_idx,
                backend=self.backend_box.currentText(),
                pitch=self._slider_value(self.pitch_slider),
                formant=self._slider_value(self.formant_slider),
                error_cb=lambda msg: QTimer.singleShot(0, lambda: self._show_error(msg)),
            )
            self.engine.start()
        except Exception as exc:
            self.engine = None
            self._show_error(f"{type(exc).__name__}: {exc}")
            return
        self.start_btn.setText("停止")
        self.status_label.setText("运行中…")

    def _restart_engine(self) -> None:
        """设备切换响应式：运行中换设备 = 停旧起新（参数从界面现取）。"""
        self._stop_engine()
        self._start_engine()

    def _on_device_changed(self, _index: int = -1) -> None:
        if self._rebuilding:
            return
        if self.engine and self.engine.running:
            self._restart_engine()

    def _show_error(self, msg: str) -> None:
        if msg == self._last_error:
            return
        self._last_error = msg
        self._toast = InfoBar.error(
            "处理出错", msg, parent=self, duration=5000,
            position=InfoBarPosition.TOP)

    def _poll_stats(self) -> None:
        if not (self.engine and self.engine.running):
            return
        s = self.engine.stats
        if s.error:
            self._show_error(s.error)
            return
        verdict = "跟得上 ✓" if s.process_ms < s.block_ms else "跟不上（会卡）✗"
        self.status_label.setText(
            f"块 {s.block_ms:.0f} ms | 处理 {s.process_ms:.1f} ms {verdict} | "
            f"块数 {s.blocks} | 欠载 {s.underruns} | "
            f"电平 in {s.peak_in:.2f} / out {s.peak_out:.2f}")


class Window(FluentWindow):
    def __init__(self) -> None:
        super().__init__()
        # 显示名层：无中文、无下划线（下划线只留给 GitHub 仓名 No_More_VFS）
        self.setWindowTitle("NoMoreVFS")
        self.resize(760, 640)
        self.page = Page()
        self.page.setObjectName("voicePage")
        self.addSubInterface(self.page, FluentIcon.MICROPHONE, "变声",
                             NavigationItemPosition.TOP)
        self.navigationInterface.hide()

    def resizeEvent(self, e) -> None:
        # FluentWindow.resizeEvent 硬编码 titleBar.move(46, 0)（给导航区留位）；
        # 导航已隐藏，标题从窗口最左开始。
        super().resizeEvent(e)
        self.titleBar.move(0, 0)
        self.titleBar.resize(self.width(), self.titleBar.height())


def main() -> int:
    app = QApplication(sys.argv)
    win = Window()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
