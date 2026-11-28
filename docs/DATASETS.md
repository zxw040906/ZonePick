# ZonePick 数据集

从仓库根目录运行 `PYTHONPATH=src python -m zonepick datasets`。CLI 优先读 `--datasets` 指定文件，其次读 `configs/local/datasets.yaml`，最后读 [示例配置](../configs/datasets.example.yaml)。路径支持环境变量和 `~`。配置使用 YAML 兼容的 JSON 语法。CLI 分别报告路径是否存在、资源是否启用、已声明的解压与完整性状态、音频抽读、项目适配及目标阵列配准。归档级验证以此文档与本地验证记录为准。

## 资源与适配状态

| 资源 | 本地根目录 | 音频和适配 |
| --- | --- | --- |
| LibriSpeech | `data/raw/LibriSpeech/LibriSpeech` | 已展开。train-clean-100、dev-clean、test-clean 分别有 28,539、2,703、2,620 条 16 kHz 单声道 FLAC。331 名说话人。支持官方 clean 子集和自定义说话人互斥划分。 |
| AISHELL-3 | `data/raw/AISHELL3` | 已展开。原始 train/test 分别有 63,262/24,773 条 WAV，抽读格式为 44.1 kHz 单声道。218 名说话人，其中 170 名跨原始目录。正式划分按身份归并。 |
| 本地 DNS 噪声 | `data/raw/DNS_noise/noise_17class` | 保留公共软链接，272 个 16 kHz 单声道文件来自 17 组录音，每组 ch01–ch16；原始来源及版本待核实。仿真渲染标为自由场仿真。 |
| 本地 DNS RIR | `data/raw/DNS_RIRS/rirs_8ch` | 保留公共软链接，36 个 16 kHz 八通道 WAV；来源、通道对应和版本待核实。可读，目标阵列未配准。 |
| In-Car McVAMPIRE V1.0 | `data/raw/McVAMPIRE` | 已解压并验证归档，111 个文件。94 个 RIR 和 14 个行驶噪声 WAV 均为 24 kHz、14 通道。口部 RIR、驾驶噪声已接入测量布置，目标阵列未配准。 |
| CAVEMOVE v4 | `data/raw/CAVEMOVE/cavemove_dataset` | 已解压并逐成员验证，1438 个文件，1430 个 WAV 均为 16 kHz 八通道。完成音频探测与元数据检查，场景适配和目标阵列配准待做。 |
| dEchorate | `data/raw/dEchorate/rir` | 当前服务器缺失，默认禁用。已有固定测点 SOFA 适配器。原始五通道 48 kHz RIR 降至 16 kHz。 |

LibriSpeech 采用 CC BY 4.0，AISHELL-3 采用 Apache 2.0。项目只使用干源及身份分组，正式发布遵循各资源许可。dEchorate 本地 SOFA 镜像的版本与再分发条款仍待复核。 [LibriSpeech 官方下载](https://www.openslr.org/12) · [LibriSpeech 论文](https://doi.org/10.1109/ICASSP.2015.7178964) · [AISHELL-3 官方下载](https://www.openslr.org/93) · [dEchorate SOFA 镜像](https://sofacoustics.org/data/database/dechorate/) · [dEchorate HDF5](https://zenodo.org/records/6576203)

### McVAMPIRE

SciPy 读出 `mic (14,1)`、`mouth (8,1)` 和 `ls (6,1)`。麦克风 `pos` 和口部 `centerpos` 为三维点。各口部还记录 `orientations_XYZ [11,3]` 和 `orientations_AzEl [11,2]`。88 个口部 RIR 长 2040 点，另有 6 个车载扬声器 RIR。历史检查发现说明中一处通道数和实物不同，以 WAV/MAT 的 14 路为准。口部适配器沿朝向从中心前移约 7 cm 定义近似声学参考点，并同步选择 RIR 和噪声的物理通道。真实阵列数据保留原几何。 [官方归档及引用](https://zenodo.org/records/12806684)

### CAVEMOVE

数据覆盖 Alfa Romeo 146 Ti、Honda CR-V、Smart forfour、Volkswagen Golf。WAV 含 176 个 RIR、22 个车载音响 IR、402 个受控噪声、66 个通风样本、764 个非受控条件样本。每个 WAV 都读取了首段样本，1254 个是 24 位 PCM，176 个是浮点。

保留的 36 页 `dataset_documentation.pdf` 为 14,945,213 字节，MD5 `a76e68b81c8ea7c042b89c111f157040`。文档给出分布式布置（前六后两）、半径 5 cm 的八麦圆阵、通道编号及各车型测点示意。Alfa Romeo 此归档只有分布式布置。车型 `info.json` 的字段是 make、model、version、year。`info.mat` 读出 MATLAB MCOS 车型对象。当前检查未找到足以完成配准的统一三维麦克风和声源坐标。 [CAVEMOVE 归档与文档](https://zenodo.org/records/17404917) · [发布方代码](https://github.com/SPL-FORTH-ICS/CAVEMOVE)

## 归档校验及本地处置

ZIP 经全包 CRC、解压大小及逐字节对比。TAR.GZ/TGZ 经完整流读取、gzip 尾部校验和逐文件字节或 SHA-256 对比。只有项目内拥有独立目录项的归档可以按授权删除。文件数包括归档内的元数据，多个 LibriSpeech 分卷有共享说明文件。明细与删除规模见 [AUDIT.md](AUDIT.md)。

<!-- archive-verification -->

| 归档 | 文件字节 | MD5 | 解压根目录 | 实际文件数 | 校验及处置 |
| --- | ---: | --- | --- | ---: | --- |
| [data_aishell3.tgz](https://www.openslr.org/93) | 19,057,141,777 | `6833e9dcb47709d4e153e2f669e5ddc8` | `data/raw/AISHELL3` | 88,042 | 验证通过，归档已删除 |
| [train-clean-100.tar.gz](https://www.openslr.org/12) | 6,387,309,499 | `2a93770f6d5c6c964bc36631d331a522` | `data/raw/LibriSpeech/LibriSpeech` | 29,129 | 验证通过，归档已删除 |
| [dev-clean.tar.gz](https://www.openslr.org/12) | 337,926,286 | `42e2234ba48799c1f50f24a7926300a1` | `data/raw/LibriSpeech/LibriSpeech` | 2,805 | 验证通过，归档已删除 |
| [test-clean.tar.gz](https://www.openslr.org/12) | 346,663,984 | `32fa31d27d2e1cad72775fee3f4849a9` | `data/raw/LibriSpeech/LibriSpeech` | 2,712 | 验证通过，归档已删除 |
| [In-Car_McVAMPIRE_V1.0.zip](https://zenodo.org/records/12806684) | 256,172,199 | `187b2d91cb8a3b0ea0ae397a3de8afe0` | `data/raw/McVAMPIRE` | 111 | 验证通过，归档已删除 |
| [cavemove_dataset.zip](https://zenodo.org/records/17404917) | 7,613,945,771 | `dec31a69f02a304a2b55b6b4db665c5e` | `data/raw/CAVEMOVE/cavemove_dataset` | 1,438 | 验证通过，归档已删除 |

<!-- /archive-verification -->

## Benchmark 候选协议

Smoke 100 场景、Pilot 1,000 场景、Small 10,000 场景、Benchmark-v1 60,000 场景。正式候选划分为 Train 50,000、Val 5,000、Test 5,000，初始候选为 16 kHz、6 秒。Pilot 验证规模、时长和分片音频编码后再冻结。覆盖中文、英文及混语，抽样复杂噪声、混响、源位和语音重叠率。

先按说话人、原始录音和必要的测量/噪声会话划分资源，再生成场景。相同事件派生的五种 MIC 布局共用同一 scene_id 与 split。用 Manifest 追踪源文件、裁剪和生成版本，用 RIR 缓存标记仿真及实测来源。只有具有明确物理对应关系的实测声学素材可以作为目标阵列的实测素材。各参考音频的约定见 [EVALUATION.md](EVALUATION.md)。
