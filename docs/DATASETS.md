# ZonePick 数据集

## 存储与本地配置

从 ZonePick 项目根目录运行 CLI。数据配置中的相对路径也以该目录为基准，支持环境变量和 `~`。优先读取 `--datasets` 指定的文件，其次读取 `configs/local/datasets.yaml`。两者均未指定时，使用仓库内示例，且已有的 `AUDIO_LEARNING_DATA` 可以覆盖旧项目数据根目录。

```bash
mkdir -p configs/local
cp -n configs/datasets.example.yaml configs/local/datasets.yaml
conda run -n pytorch env PYTHONPATH=src python -m zonepick datasets
```

配置使用 YAML 兼容的 JSON 写法，可直接由 Python 标准库解析。每项配置使用 `path` 指定目录，并用 `enabled` 启用或禁用。检查命令抽查可读取的文件及其格式，CAVEMOVE 通过检查仅表示可读 WAV，尚无场景适配器。默认目录约定如下。

| 数据源 | 相对 ZonePick 的位置 | ZonePick 用途 |
| --- | --- | --- |
| LibriSpeech | `../audio-ml-learning/data/LibriSpeech` | 两位不同说话人的干语音 |
| dEchorate | `../audio-ml-learning/data/dEchorate/rir` | 固定测点的房间 RIR 闭环 |
| In-Car McVAMPIRE V1.0 | `../shared-datasets/McVAMPIRE/V1.0` | 固定口部位置与朝向的车内 RIR 闭环 |
| CAVEMOVE v4 | `../shared-datasets/CAVEMOVE` | 后续车内 RIR 与驾驶噪声场景 |

本地覆盖配置、数据和生成音频只在工作区外部或 Git 忽略目录存放。数据许可以记录中的署名及使用条件为准。即使数据可公开下载，本仓库也只提交配置示例、链接和自编写的适配代码。

## 复用旧项目数据

**LibriSpeech** 为 OpenSLR SLR12 的英文朗读语料，许可为 CC BY 4.0。已有 `dev-clean`（2703 个 FLAC）及 `test-clean`（2620 个 FLAC），按说话人和章节组织。已核对 5323 个文件头，均为 16 kHz 单声道。这些语音提供干源，不含阵列或空间标注。示例指定两个不同说话人的片段，直接读取已有文件。引用 Panayotov 等人的 ICASSP 2015 论文，论文 DOI 为 `10.1109/ICASSP.2015.7178964`。 [OpenSLR SLR12 官方页](https://www.openslr.org/12) [论文 DOI](https://doi.org/10.1109/ICASSP.2015.7178964)

**dEchorate** 已有 SOFA 镜像的 12 个固定测量文件，覆盖 `room000000`、两个声源与六个阵列，另有 `dEchorate_annotations.h5`。原始 RIR 为 48 kHz、五通道，带测量声源和接收器三维坐标。适配器将 RIR 降至 16 kHz，按配置同时选择音频通道与麦克风坐标。区域可变，测点保持原值。当前子集足以验证固定测点的区域拾音，未重复下载。引用 Di Carlo 等人的 dEchorate 论文。关联 Zenodo HDF5 2.0 记录 DOI 为 `10.5281/zenodo.6576203`，标注 CC BY 4.0。本地 SOFA 文件的单独版本与再分发条款仍待核实。 [SOFA 数据镜像](https://sofacoustics.org/data/database/dechorate/) [数据与论文引用](https://zenodo.org/records/6576203)

## In-Car McVAMPIRE V1.0

Müller 与 Wolff（Cerence，2024），DOI `10.5281/zenodo.12806684`，Zenodo 标注 CC BY 4.0。官方 `In-Car_McVAMPIRE_V1.0.zip` 为 256,172,199 字节，存于 `../shared-datasets/McVAMPIRE/`。已核对 MD5 `187b2d91cb8a3b0ea0ae397a3de8afe0`，检查 ZIP 路径和文件类型后解压到 `V1.0/`，共 432,183,916 字节。 [官方数据与引用](https://zenodo.org/records/12806684)

- `ir/` 有 94 个 WAV，其中 88 个口部 RIR（8 个位置，每个 11 种朝向）和 6 个扬声器 RIR。口部 RIR 长 2040 点。`driving_noise/` 有 14 个行驶噪声 WAV。全部 108 个 WAV 的头信息均为 24 kHz、14 通道、PCM 24 位。
- `geometry.mat` 可用 SciPy 读取，包含 14 支麦克风、8 个口部中心及其朝向、6 个车载扬声器。包内还附有布置图和说明 PDF。按 88 个口部 RIR 的早期相对峰值与几何预测匹配，观测通道顺序与 MAT 麦克风顺序一致。包内说明有一处写作 32 支，适配器以实际 WAV 和 MAT 的 14 支为准。
- 首版只读取指定座位和朝向的口部 RIR，按官方说明用中心沿朝向前移约 7 cm 得到近似声学参考点，随后将 RIR 重采样至 16 kHz。此坐标用于仿真评价标签。常规 DAS 仍由配置中的区域圆心和高度指向。车载扬声器和驾驶噪声已清点，尚未接入混合流程。

## CAVEMOVE v4

FORTH Institute of Computer Science、Stefanakis、Kalaitzakis、Symiakakis 与 Pavlidi，DOI `10.5281/zenodo.17404917`，Zenodo 标注 CC BY 4.0。已从 Zenodo 下载 `dataset_documentation.pdf`（14,945,213 字节），校验 MD5 `a76e68b81c8ea7c042b89c111f157040`。官方说明记录 16 kHz、八通道 WAV，含静态 RIR 及驾驶、环境与通风等噪声，麦克风布置随车型和配置变化。 [官方数据与引用](https://zenodo.org/records/17404917)

完整包 `cavemove_dataset.zip` 为 7,613,945,771 字节，官方 MD5 为 `dec31a69f02a304a2b55b6b4db665c5e`。从官方服务器读得 ZIP 目录共 1483 项，展开 8,695,241,895 字节。下载前可用空间约 982 GB，压缩包及展开内容合计约 16.31 GB，满足操作完成后至少剩余 10 GB 的条件。

压缩包已下载至 `../shared-datasets/CAVEMOVE/`，MD5 与官方值一致。通过路径、条目类型、展开容量和解压 CRC 检查后发布至 `v4/cavemove_dataset/`，共享磁盘剩余约 965 GB。

- 解压实物包含 Alfa Romeo 146、Honda CR-V、Smart forfour 和 Volkswagen Golf。各车型按 `array/` 或 `distributed/` 组织，并附 `info.json` 和 `info.mat`。所查的 JSON 记录车型信息，未提供三维阵列坐标。
- 检查了 1430 个 WAV 的头信息，均为 16 kHz、八通道。其中 1254 个为 PCM 24 位、176 个为浮点 WAV。按目录统计有 176 个 `IRs`、22 个 `radio_IRs`、402 个 `noise`、66 个 `ventilation` 和 764 个 `uncontrolled_conditions`。已用 SoundFile 解码一个 RIR 和一个噪声样例，各读取 512 帧。


现有 SoundFile 可读取标准多通道 WAV，SciPy 可执行卷积。官方 Python API 固定 NumPy 2.0.2 和 SciPy 1.14.1，其中 SciPy 1.14.1 要求 Python ≥3.10。编码实现前仍需结合车型编号、麦克风布置及文档核实通道映射和可用几何。本轮保留官方 API 链接，后续适配可优先使用现有读音频接口。 [官方 API 与依赖文件](https://github.com/SPL-FORTH-ICS/CAVEMOVE/blob/HEAD/pyhton/source/requirements.txt) [SciPy 1.14.1 发布元数据](https://pypi.org/project/scipy/1.14.1/)

## 官方下载与校验

从对应 Zenodo 记录的 Files 下载，先写入 `.part`，确认文件大小和 MD5 后再改为正式文件名。解压前检查 ZIP 条目路径、特殊文件类型和预计展开容量，并在共享目录内的临时目录完成解压后再发布。两份旧项目数据直接读取，另行下载仅适用于确实缺失的文件。
