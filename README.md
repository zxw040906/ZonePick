# ZonePick

ZonePick 是一个基于多麦克风阵列的目标区域语音增强与可视化仿真平台。项目以软件仿真为基础，计划支持用户配置声源、麦克风阵列和目标区域，并通过不同算法从多通道混合语音中提取目标区域语音。

## 核心功能规划

- 仿真多说话人声学场景，支持配置声源位置和麦克风阵列。
- 支持固定区域和自定义目标区域。
- 在统一输入和评价条件下比较传统阵列信号处理、神经网络与传统算法结合、纯神经网络三条路线。
- 通过网页配置和查看场景，试听处理前后的音频，查看波形、频谱和实验指标。
- 管理实验配置、模型版本和评价结果，支持复现与性能对比。

## 技术架构

项目拟采用 Python `src` 布局和模块化单体架构。音频、声学仿真与区域模块提供多通道观测和空间条件，三类算法通过统一接口输出增强语音。应用层组织仿真、推理与评价，供命令行和网页复用。训练模块负责数据加载、损失计算和模型检查点。详见[技术架构](docs/ARCHITECTURE.md)。

## 开发环境

本地使用 VS Code 连接 WSL2 Ubuntu，通过 Codex 协作开发。项目暂时沿用已有的 Conda `pytorch` 环境，使用 Python 3.9.25 和 PyTorch 2.0.1（CUDA build 11.8）。后续较大规模训练计划在学校 GPU 服务器上开展。详见[开发环境](docs/ENVIRONMENT.md)。

## 当前开发状态

v0.1-A 已提供 WSL2 CPU 命令行闭环，v0.1-B 已提供最小网页可视化。可以使用两段真实语音，生成自由场或固定测点 RIR 的多通道混合，按二维圆形区域执行频域 DAS，并保存 WAV、配置和 SI-SDR。支持 dEchorate 固定阵列与 McVAMPIRE 固定口部测点。网页可运行预设场景、修改区域圆心/半径/指向高度，查看二维位置图、波形、试听和 SI-SDR。CAVEMOVE 目前用于数据清点，场景适配留待后续。

## 运行 v0.1-A

从仓库根目录执行。使用已有 Conda `pytorch` 环境，通过 `PYTHONPATH=src` 运行，无需安装 ZonePick。配置查找及数据状态见[数据集](docs/DATASETS.md)。

```bash
conda run -n pytorch env PYTHONPATH=src python -m zonepick datasets
conda run -n pytorch python main.py                 # 一键：公平对比 + 网页 + 退出自动清理
conda run -n pytorch python main.py --noise --keep  # 含噪场景，并保留产物
conda run -n pytorch env PYTHONPATH=src python -m zonepick serve
conda run -n pytorch env PYTHONPATH=src python -m zonepick run --config configs/scenarios/free_field.json
conda run -n pytorch env PYTHONPATH=src python -m zonepick run --config configs/scenarios/dechorate.json
conda run -n pytorch env PYTHONPATH=src python -m zonepick run --config configs/scenarios/mcvampire.json
conda run -n pytorch env PYTHONPATH=src python -m unittest discover -s tests -v
```

- 可复制 `configs/datasets.example.yaml` 到 Git 忽略的 `configs/local/datasets.yaml`，按需修改路径。示例使用同级旧仓库和同级 `shared-datasets/`，也可用 `--datasets` 指定配置。
- `python main.py` 是推荐的一键入口：无需设置 `PYTHONPATH`，用预设场景准备一次（可选 `--noise` 多类型真实噪声），让 identity 与各 `--algorithms` 在同一份含噪输入上公平对比，随后在网页展示二维图、波形、多算法指标表与聆听对照；按 **Ctrl+C** 结束会删除本次产物与字节码缓存，加 `--keep` 可保留。可用 `--scenario` / `--port` 调整。
- `python -m zonepick serve` 默认在 `http://127.0.0.1:8000/` 启动网页，仅用标准库 `http.server`，可用 `--host` / `--port` / `--output-root` 调整。网页直接调用应用层 `run()`，与命令行结果共用同一套配置与产物结构；首版只提供预设场景和区域参数调整，不含频谱与完整场景编辑器。
- 场景使用 16 kHz，将声源水平投影到闭合圆。带参考模式目前要求恰好一个区内声源。`region.center` 和 `steering_height` 构成 DAS 指向，`channels` 同步选择波形与几何，`reference_channel` 指所选通道内的索引。固定配置使用明确的文件与裁剪位置，种子随配置保存，当前流程无需抽样。
- 输出位于 `runs/<run_id>/`，包含混合、未增强参考通道、增强音频和独立目标及干扰 WAV，以及 `scenario.json` 与 `metrics.json`。运行记录包含解析后的配置、依赖版本和本地源码版本状态。SI-SDR 以参考麦克风处的独立混响目标为参考，去均值后在同一时间轴比较。自由场采用直接传播与距离衰减，实测 RIR 只用于对应测点。
- 对已有多通道录音，可在 JSON 中设置 `"backend": "recording"`，并提供 `input_wav`、`sample_rate`、按 WAV 通道排列的 `microphones` 和同样的区域参数。无需数据集或逐源参考，SI-SDR 输出为 `null`。
- DAS 暂无定位、跟踪或混响补偿。指向误差、窗边缘和空间混响可能影响输出，单个场景的指标变化不能代表总体改进。

本地 WSL2 CPU 冒烟实验复用了同两段 2 秒 LibriSpeech 音频。下表为仓库预设的单次结果，车内预设用实测 RIR 合成混合语音。

| 预设 | 通道数 | 参考麦克风 SI-SDR（dB） | DAS SI-SDR（dB） |
| --- | --- | --- | --- |
| 自由场 | 5 | −0.38 | 0.30 |
| dEchorate | 5 | −1.31 | −1.15 |
| McVAMPIRE | 14 | 10.23 | −3.12 |

## 项目文档

- [项目章程](docs/PROJECT_CHARTER.md)
- [产品需求文档](docs/PRD.md)
- [技术架构](docs/ARCHITECTURE.md)
- [开发环境](docs/ENVIRONMENT.md)
- [数据集](docs/DATASETS.md)
- [旧代码审计](docs/LEGACY_CODE_AUDIT.md)

## 公平评测工作台（实验性）

工作台把"造输入、隔离真值、统一评分、多算法对比"固定下来，便于只改算法就做公平比较：

- **插件接口**：`zonepick.algorithms` 提供类式 `Algorithm.load()/enhance()` 接口。算法只能看到 `AlgorithmInput`（多通道混合、采样率、公开阵列几何、用户区域），看不到真实声源位置、干净目标、干扰或理想掩码，结构测试守护白名单。已注册 `das`（频域几何 DAS）、`mvdr`（Souden/Benesty/Affes, IEEE TASLP 2010, DOI 10.1109/TASL.2009.2025790 统计型 MVDR：区域指向 + 从混合估计噪声协方差求权，可配 n_fft/diagonal_load/cov_estimate=sample 或 speech_absence；python main.py 默认对比 das 与 mvdr）和 `identity`（未处理基线）；纯神经网络可用同一接口预留 `load()` 加载权重、`enhance()` 推理。Oracle 诊断插件需显式导入并打 `kind="oracle"`，不参与正常排名。
- **丰富指标**：每次对比输出 SI-SDR、相对未处理基线的 ΔSI-SDR、BSS 风格 SDR/SIR/SAR、实时因子 RTF，以及可选 STOI/PESQ 接口（需另装依赖）。指标函数有独立单元测试锁定口径。
- **真实复杂噪声**：`NoiseConfig` 支持 UrbanSound8K 十类环境音与 McVAMPIRE 多车速行驶噪声，多类型、多源、按 SNR 设定能量、空间扩散/实测两种注入模式，全程固定种子可复现。噪声作为干扰注入，参考始终是参考麦克风处的独立混响目标。
- **参数化数据划分**：`python -m zonepick split --root <数据根> --output <manifest.json> --train-ratio ... --val-ratio ... --test-ratio ... --seed ...` 生成按说话人/会话分组隔离的 train/val/test 冻结 manifest，比例与种子都是参数，测试条目不进入训练命名空间。

```bash
conda run -n pytorch env PYTHONPATH=src python -m zonepick compare \
  --config configs/scenarios/free_field.json --algorithms das --noise \
  --output-root runs/compare
conda run -n pytorch env PYTHONPATH=src python -m zonepick split \
  --root /home/zxw/python_code/project/audio-ml-learning/data/LibriSpeech \
  --output runs/splits/librispeech.json --train-ratio 0.7 --val-ratio 0.15 --test-ratio 0.15
```

`compare` 只准备一次场景，让所有算法处理逐样本相同的混合，再统一评分；每个算法的结果、指标和含数据路径/种子的 manifest 写入独立目录。注意：评测用的说话人与场景应通过划分 manifest 与神经网络训练集隔离，避免评价不公平。

## 后续计划

1. 扩大 v0.1-A 的固定场景验证，确认评价口径和验收条件。
2. 在统一输入与公平评价下扩充传统算法基线，并预留神经网络插件接口。
3. ~~接入网页场景交互、音频试听和结果可视化。~~（v0.1-B 已实现最小版本）
4. 用参数化划分与多类型噪声场景集做可复现的对照实验和消融分析。
