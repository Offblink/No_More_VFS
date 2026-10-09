# No_More_VFS

自己动手做的实时变声器：不手术、不插件、不黑盒——移调和共振峰两个旋钮归你控制，
把男声送进女声域，输出进会议/直播（走 VB-Cable）。

## 关于这个名字

VFS = Voice Feminization Surgery，嗓音女性化手术。

作者的手术效果不理想，于是有了这个项目：
不动声带，用移调 + 共振峰把声音送进女声域。

**如果你也在这条路上——你一直被看见。**

## VB-Cable：先把虚拟声卡装上

无论用本项目还是后面的 Seed-VC，声音都要经过一条"虚拟音频线"送进会议/直播软件。
[VB-Cable](https://vb-audio.com/Cable/) 是免费的虚拟声卡，装一次两条线共用。

**装**：官网下载 VB-Cable（Windows），按安装向导完成，装完建议重启一次。
装好后系统的播放/录音设备里会多出两个端点：

| 设备名 | 方向 | 谁连它 |
|---|---|---|
| **CABLE Input** | 声音**进**线（播放端） | 变声器的输出 → 选它 |
| **CABLE Output** | 声音**出**线（录制端） | 会议/直播软件的麦克风 → 选它 |

> 名字是相对"线缆"说的，最容易搞反：**自己的程序往 `CABLE Input` 里写，
> 对面的会议软件从 `CABLE Output` 里读。**

**三步接线（两条线通用）**

1. 变声器（本项目或 Seed-VC）输出设备选 `CABLE Input`；
2. 会议/直播软件的麦克风选 `CABLE Output`；
3. 想自己听到效果：`CABLE Output` → 右键属性 →「侦听此设备」→ 插耳机。

**验证装对了**：Windows「声音设置」里能看到上述两个端点；再开"录音机"，
录音设备选 `CABLE Output` 说句话 → 播放，能听到声音就通了。

常见坑：会议软件有时会在你插拔设备后失效——重新选一次麦克风；
系统"默认设备"保持你自己的耳机/麦不动，只在会议软件**内部**选 `CABLE Output`。

## 开始使用

首次在新机器上准备环境（Python 3.13）：

```bash
pip install -r requirements.txt
```

然后：

1. 双击 `实时变声.cmd`；
2. 「设备」卡：输出选 `CABLE Input`（默认已选），输入选你的麦；
   列表右侧的「**刷新**」按钮可随时重新扫描设备；
3. 调好参数 → 点「开始变声」；
4. 会议/直播软件里：麦克风选 `CABLE Output`（见上一节的接线）。

界面全是响应式的：

- **运行中直接调**：拖滑条、换后端、切设备，下一块立即生效，不用停了重开；
- 每个滑条带「复原」，一键回默认档（移调 9.0 / 共振峰 2.0 半音）；
- 插拔耳机等新设备：待机时每 2.5 s 自动扫出来，也可以点「刷新」立刻扫；
- 状态行看流畅度：**处理 ms < 块 ms = 跟得上 ✓**，欠载 > 0 表示偶尔会卡。

## 参数范围

| 参数 | 范围 | 步进 | 默认 |
|---|---|---|---|
| 移调 | 0 ~ 15 半音 | 0.5 | 9.0 |
| 共振峰 | 0 ~ 3 半音 | 0.5 | 2.0 |
| 后端 | `world`（WORLD）/ `praat`（PSOLA） | — | world |

- ♂→♀ 的移调通常落在 **+7~12 半音**，建议从 9 起步，一边听一边调；
- 共振峰加得越多越"女"，到 2 以上开始容易发假——按自己的耳朵定；
- 命令行同一套范围，越界直接拒绝。

**两个后端**

| 后端 | 特点 | 速度（100 ms 音频块的处理耗时） |
|---|---|---|
| `world` | WORLD 声码器，音高与共振峰分开处理，音质最好 | ≈68 ms，贴着实时线 |
| `praat` | Praat PSOLA，两个旋钮同样独立，音色质感不同 | ≈8 ms，余量最大 |

两个都留着，按听感换；`world` 卡顿（欠载变多）时切 `praat` 立竿见影。

## 想要更好的变声效果：Seed-VC 详细配置

本项目是"自己搓"的 DSP 链。想要效果更好的神经变声，用
[Seed-VC](https://github.com/Plachtaa/seed-vc)——零样本：一段 1~30 秒的参考音频即可换声，
不用训练。以下是从零到出声的完整流程。

### 1. 安装

```bash
git clone https://github.com/Plachtaa/seed-vc.git
cd seed-vc
# 官方建议 Python 3.10（Windows）
pip install -r requirements.txt
# 可选：Windows 上装 triton 以启用 --compile 给 v2 提速
pip install triton-windows==3.2.0.post13
```

权重**首次运行时自动从 HuggingFace 下载**。访问不了 HuggingFace 时，命令前加镜像：

```bash
# Windows CMD
set HF_ENDPOINT=https://hf-mirror.com
```

**下载卡住 / 镜像报错怎么办**
（日志刷 `MaxRetryError ... hf-mirror.com ... SSLError: EOF occurred in violation of protocol`）：

- 权重已在本地（跑过一次）→ 这只是镜像的 HEAD 探测在重试，不是缺文件。
  设 `set HF_HUB_OFFLINE=1` 再启动：跳过联网核验，实测 0.02 s 直接进加载。
- 权重确实没有 → `hf-mirror.com` 偶发 TLS 中断：换网络重试，或挂代理直连 HuggingFace，或预下载：

  ```bash
  hf download Plachta/Seed-VC DiT_uvit_tat_xlsr_ema.pth --cache-dir checkpoints
  ```

### 2. 实时变声（开会/直播用）

```bash
python real-time-gui.py
```

`--checkpoint-path` / `--config-path` 留空即可：自动下载默认的实时模型
**seed-uvit-tat-xlsr-tiny**（v1，25M，为实时设计）。GPU 强烈建议（官方原话）。

界面里：载入参考音频 → 选输出设备为 `CABLE Input` → 调参 → Start。
注意：**改参数会自动 Stop，改完要重新 Start**；参考音频只在 Start 那一刻载入。

**参数怎么设**

官方给出的推荐起点（RTX 3060 实测）：

| 扩散步数 | CFG | Max prompt | Block | Crossfade | 左右上下文 | 延迟 | 每块推理 |
|---|---|---|---|---|---|---|---|
| 10 | 0.7 | 3.0 s | 0.18 s | 0.04 s | 2.5 / 0.02 s | 430 ms | 150 ms |

更省算力的取向（更长的块、更少的步数）：扩散步数 1、CFG 1.0、block 0.36 s、
right 0.08 s → 延迟 ≈ 0.9 s，低配机器也能跑。

**流畅判据（官方口径）**：`Inference Time (ms) < Block Time (ms)`。
违反会卡 + 重复音——先加大 block、缩短 Max prompt，或换小一点的模型。

### 3. 离线转换（质量比实时高一档）

```bash
python inference_v2.py --source 你的声音.wav --target 参考.wav \
    --convert-style false --intelligibility-cfg-rate 0.7 --similarity-cfg-rate 0.7
```

- `--convert-style false`：语调节奏跟你的源、音色跟参考 = **复原你的语气**；
  设成 `true` 会照搬参考的语调，通常不要。
- 四声偶尔错时，把 `--intelligibility-cfg-rate` 提到 `0.85`。
- v2 模型（hubert-bsqvae-small）最能压住原说话人的痕迹；唱歌转换用
  `inference.py` + 44.1k 的 singing 模型。

### 4. 参考音频怎么挑（决定成败）

- 音量 rms ≥ 0.14，浊音率 ≥ 0.74，F0 落在 245~310 Hz（偏女声域）；
- 参考**开头 3 秒**决定一切——实时链只取开头 3 秒，挑最稳的一段；
- 干净、无背景乐、无混响；脏参考会让四声最先出错；
- 参考文件路径不要含中文（实时 GUI 会拒绝加载）。

### 5. 接线

和本项目完全一样：Seed-VC 输出选 `CABLE Input`，会议麦克风选 `CABLE Output`
（见 VB-Cable 一节），两条线随时互换。

## 三条路线怎么选（RVC / Seed-VC / 本项目）

| | RVC | Seed-VC | No_More_VFS（本项目） |
|---|---|---|---|
| 原理 | 神经·检索式，需要现成的目标声线模型 | 神经·零样本，一段参考音频即可用 | 纯 DSP：移调 + 共振峰（WORLD / PSOLA） |
| 准备 | 找/换声线模型（.pth 要先转 onnx） | 选好参考 wav 就完事 | 零素材，开窗即调 |
| 实测结论 | 两副常见声线都不过关：有的咬字糊，有的"很声优、不自然" | 实听效果好，离线 v2 再高一档 | 参数全透明，听感档位自定 |
| 可控性 | 黑盒，声线由模型决定 | 半黑盒：参考 + cfg 两组旋钮 | 全透明：移调/共振峰逐半音可调 |
| 算力 | CPU 可跑（慢），实时要 vc-rs + onnx | 需要 GPU | 纯 CPU（100 ms 块 / 处理 60~70 ms） |
| 实时延迟 | ≈1 s | ≈0.4~0.9 s | ≈0.3 s |

**怎么选**

- 直接要最好听 → **Seed-VC**（配置流程在上一节）。
- 找得到心仪声线模型、机器也强 → **RVC**；常见声线实测容易翻车，期待放低。
- 零素材、零 GPU、每个参数自己控、延迟最低 → **本项目**。
- 三条线出口都是 VB-Cable：会议端 `CABLE Output` 一套接线通用，随时互换。

## 命令行用法（不开界面）

```bash
# 单文件转换（范围与界面一致，越界拒绝）
python scripts/voice_shift.py 你的声音.wav 输出.wav --backend world --pitch 9 --formant 2

# 批量出对比试听（同一段音频 × 多组参数 + manifest）
python scripts/render_scan.py --source 你的声音.wav --outdir output/listen --start 14 --excerpt 15
```

## 目录

```
No_More_VFS\
├── 实时变声.cmd               双击入口（单文件，自检 + 拉起 GUI）
├── requirements.txt           运行依赖（pip install -r）
├── scripts\
│   ├── gui.py                界面（PySide6-Fluent-Widgets）
│   ├── realtime.py           实时引擎：采集 → DSP → 输出
│   ├── voice_shift.py        DSP 核（界面与命令行共用）
│   ├── render_scan.py        批量对比试听
│   ├── analyze_f0.py / verify_pitch.py   音高取证
├── tests\                    pytest
├── docs\V1_NOTES.md          设计与实测记录（维护者向）
└── output\listen\            试听说明与清单（wav 成品含真人嗓音，不随仓分发；可自行重生成）
```
