# v1 设计笔记（WORLD 离线链）· 2026-10-06

## 结构：两个旋钮各管一半

```
voice_shift.py
  world_analyze(x, sr) -> (f0, sp, ap)      harvest + stonemask / cheaptrick / d4c
  移调：f0 *= 2**(pitch/12)                 只碰基频轨迹
  共振峰：sp 频轴按 2**(formant/12) 重采样    只碰频谱包络（bin 轴线性插值）
  world_synthesize(f0, sp, ap, sr)          StoneMask 合成
```

设计原则：**移调不改共振峰、共振峰不改音高**——这是"不是简单提高音调"的技术落点。
参数级隔离由 `tests/test_voice_shift.py::test_each_knob_only_touches_its_own_parameter`
用捕获式断言钉住（不是靠听）。

## 验证证据

### 1. 包络频轴缩放：确定性（无音频参与）

| formant | F1 区包络峰 | 倍率 | 理论 |
|---|---|---|---|
| +0 | 517 Hz | — | — |
| +2 | 581 Hz | ×1.124 | ×1.1222 |
| +4 | 646 Hz | ×1.249 | ×1.2599 |

bin 宽 21.5 Hz（22050 Hz / 513 bin），±1 bin 内即精确。

### 2. 移调量：同一时间窗自相关（`scripts/verify_pitch.py`）

源窗口 @10.75 s，155.2 Hz；成品取**同一 1 秒窗**（WORLD 保时长，同窗即同音素）：

| 后端 | semis | ratio | 理论 | 偏差 |
|---|---|---|---|---|
| world | +7 | 1.4959 | 1.4983 | −0.16% |
| world | +9 | 1.6810 | 1.6818 | −0.05% |
| world | +12 | 1.9974 | 2.0000 | −0.13% |
| pv | +9 | 1.6806 | 1.6818 | −0.07% |
| praat | +9 | 1.6846 | 1.6818 | +0.17% |

**两处测量陷阱（都踩过）**：
- WORLD harvest 的中位数口径在重合成语音上有 2–4% 系统偏低 → 不能当精度判据；
- 自相关核验必须**同一时间窗**：各文件各自挑"最周期的那一秒"会比到不同句子音高，得到假的 −9%。

### 3. 时长与电平

时长逐帧保持（22050 Hz / 5 ms 帧）；写盘走 0.99 峰值守卫，PCM_16 往返长度 ±1 采样。

### 4. 性能（本机 CPU）

WORLD 全片 43.84 s → 6.56 s（0.15× 实时），15 s 片段 ~2.3 s。离线够用，
实时（§4 下一步）要压块长与算力预算另算。

## 后端取舍

| backend | 移调 | 共振峰 | 备注 |
|---|---|---|---|
| `world` | 精确（±0.2%） | 独立、确定性可证 | 先手；离线质量最好 |
| `praat` | 精确（±0.2%，走 `Change gender` 的 `new_pitch_median`） | 走 `formant_shift_ratio` | PSOLA 路线 |

phase vocoder 后端已删（用户 2026-10-06 判定）：当时实测相位伪影、共振峰不可独立控、
电平 −33% rms；`librosa`/`resampy` 依赖随之卸载。

Praat 侧实现要点：`Change gender` 要绝对目标中位音高，所以先 `To Pitch` 取
`Get quantile ... 0.5 Hertz` 再乘比例；只给 formant 时 `new_pitch_median=0`（保持原音高）。

## 踩坑

- **"包络没动"不能用重新分析来测**：换了 f0 之后，cheaptrick 对稀疏谐波堆的包络估计必然变化
  （同一曲线被更稀疏的谐波采样），于是包络重心跟着动 ~1.5×。测试改成参数级捕获。
- 本机 shell：`curl -o /c/...` 静默不落盘（改 `C:/`）；`uv pip install --python env\Scripts\...`
  反斜杠被 bash 吃掉（改正斜杠）。

## 门禁

```bash
env/Scripts/python.exe -m ruff check .     # All checks passed!
env/Scripts/python.exe -m pytest -q        # 25 passed
```

## 参数面（用户 2026-10-06 判定）

| 参数 | 面 | 说明 |
|---|---|---|
| 后端 | `world` / `praat` | phase vocoder **已删**（相位伪影、共振峰不可独立控；librosa/resampy 卸载） |
| 移调 | **0 ~ 15 半音**，步进 0.5 | 目标域 +7~12（handoff §4），0 = 旁路 |
| 共振峰 | **0 ~ 3 半音**，步进 0.5 | +4 听感过头，出圈 |

- 范围是**产品契约**：CLI 越界 exit 2（`test_cli_enforces_ranges` 钉住），GUI 滑条读
  `voice_shift.PITCH_RANGE / FORMANT_RANGE / PARAM_STEP` 同一组常量。
- 库函数 `world_shift/praat_shift` 不设限（机制级可任意测，如包络测试用 4 半音）；
  范围只在 CLI/GUI 这层收口。
- `render_scan.py` 网格只取样范围内值：`FORMANTS=[0,2]`、`AB_BACKENDS=["praat"]`。

## 待办（用户听感，只定默认值）

试听集 `output/listen/`（14–29 s 窗口，15 s）：world 3×2 + praat 一 + 源片段，共 7 件。
选后端与定 pitch/formant **默认值**（范围已定死，不因此缩放）。

## 实时链与 GUI（v1，2026-10-06 真机实测）

- **架构**：WASAPI 跨设备双工被 PortAudio 拒（`-9993 Illegal combination of I/O devices`）
  → **双流 + 队列管线**：输入回调入队 → worker 线程用 2 块左上下文做 WORLD/PSOLA →
  输出回调出队（空 = 静音 + 欠载计数）。启动时**先预填 1 块再开输出流**；
  预填等待**不能持 `_out_lock`**（会和 worker 死锁——写完第一版就撞上，已修）。
- **设备事实**：`CABLE Input` 有 48 kHz 端点（#16）与 44.1 kHz 端点（#14）；麦阵列 48 kHz
  → 选 48k 端点同率直通，**不用重采样**。GUI 默认输出即自动落在 #16。
- **块耗时**（48 kHz，300 ms 窗）：WORLD 合成信号 67 ms / 真麦 68~70 ms；PSOLA ~8 ms。
  判据沿用 Seed-VC 线：**处理 ms < 块 ms**。100 ms 块下 WORLD 余量薄
  （4 s 冒烟 41 块欠载 2，其中 1 个是启动预填）——后备方案：切 praat（10× 快），
  或后续把块长做成 GUI 参数。
- **冒烟证据**：4 s 实链（麦 → WORLD → CABLE）blocks=41，process 68~70 < 100 ✓，
  error 空，peak in 0.03~0.08 / out 0.03~0.09；`screen.grabWindow` 截屏验版式；
  `实时变声.cmd`（单文件：路径自检 → `start` 拉起 pythonw，无 ps1 第二真相源）
  → pythonw（父+子双进程 = 重定向器正常）；
  改名 No_More_VFS 后复测，窗口标题 `NoMoreVFS`、Responding=True。
- **GUI 坑**：`FluentWindow.addSubInterface` 要求目标有非空 `objectName`（否则 ValueError）；
  `win.grab()` 截图顶部黑条是 backing store 假象，要 `screen.grabWindow(0, x, y, w, h)`
  抓真实屏幕区域；`.cmd` 必须 CRLF + 头部纯 ASCII（本项目启动器已单文件化，
  不再有 `.ps1`——两份文件 = 两个真相源，用户裁定"直接一个脚本"）；CJK 文件名在
  git-bash 下 `sed`/裸引用会 os error 2 → 用 Python 字节级处理。
- **响应式接线（2026-10-06 用户要求）**：
  - 滑条 `valueChanged` / 后端 `currentIndexChanged` → `Page._apply_params` →
    `engine.set_params`，worker 每块读一次 → **运行中即生效，不重启**；
  - 设备下拉每 `DEVICE_REFRESH_MS = 2500` 轮询 `realtime.list_devices()`：名单没变不重建，
    变了按**设备 id** 保选择（刷新不把用户选中的设备拽走）；
  - 每滑条一个「复原」→ `voice_shift.DEFAULT_PITCH / DEFAULT_FORMANT`（9.0 / 2.0，
    与范围同源常量）；按用户截图删掉大标题与顶部提示文案。
  - 设备下拉 `currentIndexChanged` → 运行中 = `_stop_engine` + `_start_engine`
    （停旧起新，参数现取）；`_rebuilding` 闸保证 2.5 s 自动刷新**永不**误触发重启；
  - 标题层：显示名 `NoMoreVFS`（无中文、无下划线——下划线只留给 GitHub 仓名）；
    FluentWindow.resizeEvent 硬编码 `titleBar.move(46,0)`（给导航留位，我们导航隐藏）
    → 覆盖 `resizeEvent` 归零，标题 x 64 → 18（贴左）；
  - 实机验证：拖滑条+换后端 `('world',9,2) → ('praat',12,1)`、复原回 `(9,2)`；
    运行中切输入设备 dev 0 → 1 引擎真重启，之后 21 块无错；单测 7 条
    （`tests/test_gui.py`，offscreen）。
- **设备热插拔与「刷新」按钮（2026-10-06 用户实测：插耳机列表不动）**：
  - 根因：`sounddevice` 在 **import 时 Pa_Initialize 一次**，PortAudio 设备表从此缓存，
    热插拔设备永不出现（源码 `sounddevice.py:2973` 模块级 `_initialize()`）。
  - 修法 = 强制重扫：`sd._terminate(); sd._initialize()`（计数 1→0→1 配平，
    实测重扫后 18 进 / 20 出稳定）。`list_devices(rescan=True)` 封装这条路径。
  - 设备卡右侧「刷新」按钮 = 停机强扫 → 重建下拉 →（若在运行）自动重启；
    2.5 s 定时器只在**待机**时强扫，运行中只查不扫——`Pa_Terminate` 会砸开流的流。
  - 冒烟：待机点按钮真强扫无恙；运行中点按钮引擎停-扫-起（新实例、之后 17 块无错）；
    单测 +3（强扫触发 / 运行中定时器不强扫不误重启 / 运行中按钮停-扫-起），共 25 条。
  - 按钮渲染验证：整窗截图附件会串图，最终用**像素探针**在 (992..1033) 量到 386 深色像素
    （与「复原」按钮同量级）定案。
