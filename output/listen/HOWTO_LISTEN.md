# 试听说明（v1 离线，2026-10-06）

> 注：wav 成品**不随仓分发**（真人嗓音）。克隆后跑
> `python scripts/render_scan.py --source 你的声音.wav --outdir output/listen --start 14 --excerpt 15`
> 即可重新生成同名文件，本文档与 `manifest.json` 逐字适用。

试音源：`user_live.wav` 的 14–29 s 窗口（该片浊音率最高，0.706）。
全部 22050 Hz / 16-bit，时长 15 s，严格逐帧对齐——**同一时间点可比**。

先听 `_source_excerpt.wav`（原始男声），再按下面顺序听。

## 参数范围（产品契约，CLI 与 GUI 同源）

| 参数 | 范围 | 步进 | 依据 |
|---|---|---|---|
| 移调 `--pitch` | **0 ~ 15 半音** | 0.5 | 目标域 ♂→♀ +7~12（handoff §4） |
| 共振峰 `--formant` | **0 ~ 3 半音** | 0.5 | +4 听感过头，出圈（2026-10-06） |

越界直接拒（`voice_shift.py --pitch 99` → exit 2）。常量在 `voice_shift.py`
的 `PITCH_RANGE` / `FORMANT_RANGE` / `PARAM_STEP`，GUI 滑条读同一组。

**已删后端**：phase vocoder（`pv`，2026-10-06 用户判定）——代码、试听件、依赖
（librosa/resampy）全部移除；现役后端 `world` / `praat`。

## 第一轮：后端对照（handoff §6.1）

同一档位（移调 +9 / 共振峰 +2 半音）两路：

| 文件 | 后端 | 说明 |
|---|---|---|
| `world_p9_fplus2.wav` | WORLD | 两旋钮独立、证据最硬（见 `docs\V1_NOTES.md`） |
| `ab_p9_fplus2_praat.wav` | Praat PSOLA | 移调走 `Change gender` 的目标中位音高 |

判据（§0）：咬字不糊 / 无机器人味 / 复原语气。

## 第二轮：档位取样（handoff §6.3）

文件名规则 `world_p<移调>_fplus<共振峰>.wav`，6 件：

- 移调：`p7` / `p9` / `p12`（半音）
- 共振峰：`fplus0` / `fplus2`（半音）

建议先固定 `fplus0` 扫移调（哪一档开始"变假"，§6.2 的 +7 vs +12 在这里听掉），
再固定选中的移调扫共振峰。范围内的任意值直接跑：

```bash
env/Scripts/python.exe scripts/voice_shift.py 输入.wav 输出.wav --backend world --pitch 8.5 --formant 1.5
```

## 数值对照（`manifest.md` / `manifest.json`，7 行全量）

| 文件 | F0 中位数 | 浊音率 | rms |
|---|---|---|---|
| _source_excerpt | 135.7 Hz | 0.706 | 0.0431 |
| world_p7_fplus0 | 197.7 | 0.741 | 0.0444 |
| world_p9_fplus0 | 218.4 | 0.782 | 0.0434 |
| world_p12_fplus0 | 265.2 | 0.724 | 0.0430 |
| ab_p9_fplus2_praat | 216.8 | 0.690 | 0.0407 |

（F0 中位数口径在重合成语音上有 2–4% 系统偏低，精确度以 `scripts/verify_pitch.py`
的同一时间窗自相关为准，偏差 ≤0.2%。）

## 听完可选（只定默认值，不缩范围）

1. 后端默认：WORLD 还是 Praat PSOLA。
2. 移调默认值（范围内任意，例 9）。
3. 共振峰默认值（0~3，例 2）。
