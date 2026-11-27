# ZonePick 项目审计 · 2026-11-27

## 1. 项目基本信息

工作区为 `/root/zxw/ZonePick`，远程为 [zxw040906/ZonePick](https://github.com/zxw040906/ZonePick)，`pyproject.toml` 标记版本 0.1.0。当前实物是离线单区域拾音原型与小规模对比工作台。以下按证据使用“已实现且验证通过”“已实现但未验证”“仅有接口或文档规划”“尚未实现”。单元测试夹具通过与实测数据闭环通过分别注明。

## 2. Git 状态及认证修复结果

| 项目 | 检查结果 |
|---|---|
| Git / 分支 | Git 2.25.1，`main` 跟踪 `origin/main`，HTTPS fetch/push URL 为 `https://github.com/zxw040906/ZonePick.git` |
| 提交与远端 | `git rev-parse HEAD origin/main` 两者均为 `abdbac36d78a9d8cf9c46691665937a259eb99f2`，`git ls-remote origin refs/heads/main` 独立返回相同 SHA，领先/落后均为 0 |
| 提交身份 | 初次 `git var GIT_AUTHOR_IDENT` 报 `fatal: unable to auto-detect email address`。核对最近六次历史提交后，通过 `git config --local` 设置历史作者 `zxw040906` 及同一历史邮箱，作者和提交者检查均通过。配置只写入 `.git/config` |
| 本地配置 | `git config --local --list` 检查到标准 `core` 设置、`remote.origin.url/fetch`、`branch.main.remote/merge/vscode-merge-base` 以及修复后的 `user.name/email`。邮箱可在本机用 `git var GIT_AUTHOR_IDENT` 核对 |
| GitHub HTTPS | GitHub 页面返回 HTTP 200，公开分支可读。`GIT_TERMINAL_PROMPT=0 git push --dry-run origin HEAD:refs/heads/main` 返回 `fatal: could not read Username for 'https://github.com': terminal prompts disabled`，本终端的 HTTPS 写认证未验证通过。未发现已配置的 Git credential helper，`gh` 不在 PATH |
| SSH | `ssh -T` 非交互探测 GitHub 22 及官方 SSH 443 入口，两者在外层 8 秒超时（退出码 124），未取得握手或认证结果。SSH 连通性和密钥有效性分别待核实 |
| VS Code | 该终端无法确认本地 VS Code Accounts 与远端扩展宿主的登录状态。已登录扩展与当前终端可用的 Git 凭据是两项独立检查 |

**需用户授权的步骤。** 继续使用 HTTPS 时，可在实际执行 Git 的环境使用支持浏览器登录的 Git Credential Manager。由用户在 GitHub 浏览器页面确认正确账号及仓库访问。若该环境后来已有 GitHub CLI，用户可在对应终端运行 `gh auth login --hostname github.com --git-protocol https --web` 并在浏览器完成设备授权，用 `gh auth status` 查看状态。在仓库内可用 `git -c 'credential.helper=!gh auth git-credential' push --dry-run origin HEAD:refs/heads/main` 验证该次命令的认证。写权限确认后再由用户决定实际操作。VS Code Remote-SSH 用户应在远程窗口终端复核这一过程。此轮未安装认证工具。 [GitHub HTTPS 和 SSH](https://docs.github.com/en/get-started/git-basics/about-remote-repositories) · [GitHub 凭据管理](https://docs.github.com/en/get-started/git-basics/caching-your-github-credentials-in-git) · [gh auth login](https://cli.github.com/manual/gh_auth_login) · [VS Code Git 认证](https://code.visualstudio.com/docs/sourcecontrol/faq#_authentication)

| 现有暂存修改 | 相对 GitHub main 的实际差异 |
|---|---|
| `README.md` | 更新就绪数据说明和样例路径 |
| `configs/datasets.example.yaml` | 改用项目内语音目录，新增 AISHELL-3、DNS noise 和 DNS RIR，禁用未落地的实测数据 |
| `docs/DATASETS.md` | 更新表格路径和本机可用性，仍保留历史环境的下载和校验叙述 |
| `docs/LEGACY_CODE_AUDIT.md` | 更新数据相关说明 |
| `src/zonepick/workbench/noise.py` | 只替换两个默认噪声路径和行尾注释，筛选和解码逻辑未变 |

五个文件共 16 行新增、13 行删除，`git diff --cached --check` 通过。以上是与 DeepSeek 迁移叙述吻合的可观测差异，暂存内容无法确定作者或工具。首次状态另见未跟踪 `test.py`（605 字节）。后续复查该路径已不存在，本轮命令没有操作该文件，原因及归属未验证。五项暂存修改均保留。

`git ls-files data .vscode` 无输出。`git check-ignore -v` 证实 `/data/`（含两个链接及下载日志）、`/runs/`、`/outputs/`、`/configs/local/`、`.vscode/`、`.env`、`*.key`、`*.pem`、常见模型权重、WAV/FLAC/SOFA/ZIP 已受规则覆盖。受控目录外的 `*.tgz`、`*.tar.gz`、`*.h5`、`*.hdf5`、`*.npy`、`*.npz`、`credentials.json`、`.netrc` 未被测试规则匹配，第三方凭据文件也不能仅凭扩展名保证覆盖。审计未修改忽略规则。

## 3. 服务器与开发环境

| 检查项 | 实测 |
|---|---|
| Linux / CPU / 内存 | Ubuntu 20.04.6 LTS，AMD EPYC 7543，单路 32 物理核 / 64 逻辑 CPU，125 GiB RAM，测试时约 119 GiB available，8 GiB swap |
| 磁盘 | 项目位于 `/dev/sda1`，`df -h .` 见 7.3 TiB 总量、4.2 TiB 已用、2.8 TiB 可用 |
| GPU | 两张 RTX 3090，各 24,576 MiB。初检每卡 1 MiB、0% 利用率，`nvidia-smi` 未列运行进程 |
| NVIDIA / CUDA | 驱动 595.104.02，`nvidia-smi` 显示兼容 CUDA 13.2。PyTorch 编译 CUDA 11.8，运行可用。PATH 未找到 `nvcc` |
| Python / Conda | 当前 `base`，`/root/anaconda3/bin/python`，Python 3.11.7。`conda env list` 未列文档示例的 `pytorch` 环境 |
| 科研库 | NumPy 1.24.0、SciPy 1.11.4、SoundFile 0.12.1、h5py 3.9.0、PyTorch 2.4.0、torchaudio 2.4.0、pystoi 0.4.1、pesq 0.0.4、pytest 7.4.0。PyRoomAcoustics、TensorBoard 导入时报 `ModuleNotFoundError` |
| 声明冲突 | NumPy 满足声明。SciPy、SoundFile、h5py 低于 `pyproject.toml` 下限 1.13、0.13、3.14。源码经 `PYTHONPATH=src` 可运行，安装解析与新环境重建未验证 |
| CUDA / DDP | `torch.cuda.is_available()=True`，两张卡和 CPU 分别完成 4 元素求和，均得 4。Distributed 与 NCCL available 均 True，具备两卡 DDP 基础。未验证进程组、集合通信或真实训练 |

## 4. 数据集完整清单

`du -hL data` 显示本地数据与两个链接目标合计约 60 GiB。项目中数据路径均以 `/root/zxw/ZonePick/` 为绝对前缀。体积来自 `du -hL` 实际分配空间，语音目录体积含留存压缩包。音频时长按每个可读文件 `frames / samplerate` 累加，多通道每文件计一次。缺失数据的本地占用、文件数、时长、采样率、通道、作者所用划分均记为未验证，且本项目配置路径未发现目录、压缩包或链接。外部仅按项目链接或文档明确指向的依赖定位。

| 本机数据 / 版本 | 绝对路径、链接、占用与解压 | 实物统计 / 官方划分 | 空间及项目适配 |
|---|---|---|---|
| AISHELL-3 1.0，普通话 | `/root/zxw/ZonePick/data/raw/AISHELL3`，非链接约 44 GiB。留存 `data_aishell3.tgz`（19,057,141,777 B），已展开 `train/wav` 约 19 GiB、`test/wav` 约 6.7 GiB | 本地 train 63,262 WAV / 174 人，test 24,773 WAV / 214 人，合计 88,035 WAV / 218 人。按 `SSBxxxx` 父目录提取说话人，170 人跨官方命名的 train/test，同一说话人目录与文件名组合的交集为 0。现有目录划分无法满足说话人互斥。全量文件头实测 train 227,420.55 秒（63.17 h）、test 80,803.62 秒（22.45 h），合计 85.62 h。全部 44.1 kHz 单声道，0 头读取失败。每部分抽查 64 个为 PCM 16-bit | RIR、噪声类别、空间坐标 N/A，安静室内单声道录音。两边各抽一个文件经 `read_audio/speech_segment` 可正常读取并重采样，场景和检查 CLI 均未适配 AISHELL-3 |
| LibriSpeech OpenSLR SLR12 英语 clean 子集 | `/root/zxw/ZonePick/data/raw/LibriSpeech/LibriSpeech`，非链接。父目录含三个 `.tar.gz` 共约 6.6 GiB，解压约 7.0 GiB，合计约 14 GiB | 33,862 FLAC，111.38 h，全部 16 kHz 单声道，0 头读取失败。官方 `train-clean-100` 28,539 / 100.59 h / 251 人。`dev-clean` 2,703 / 5.39 h / 40 人。`test-clean` 2,620 / 5.40 h / 40 人。文件名前缀与说话人目录为 ID，三个官方子集共 331 人、两两无交集。其他官方子集未发现 | 类别、RIR、坐标 N/A。已适配，CLI 抽查和真实自由场闭环通过。[OpenSLR SLR12](https://www.openslr.org/12) |
| 标记为 DNS noise 的本地 17 类子集，正式来源及版本未验证 | 项目链接 `/root/zxw/ZonePick/data/raw/DNS_noise/noise_17class` → `/root/DNS-Challenge-master/noise`，约 2.5 GiB。在审计范围内未见对应压缩包，已存在实物 | 272 WAV / 22.67 h，均 16 kHz 单声道，0 头读取失败，17 类各 16 文件。说话人及 ID N/A，官方训练划分未验证 | RIR N/A，本地文件未附可用坐标。普通读音频通过，现有噪声入口适配失败，272 个文件均不匹配 UrbanSound8K 正则。同类 `ch01.wav` 到 `ch16.wav` 均为 300.004 s。如按每组同一录音计，仅约 85 分钟。目录名和分通道结构与官方 DEMAND 1.0 发布高度吻合，包含疑似真实私家车 `TCAR` 样例，实际文件来源、阵列配准与速度未通过校验确认。仓库命名不能证明其 DNS 版本。[DEMAND 官方发布](https://zenodo.org/records/1227121) · [Microsoft DNS 官方仓库](https://github.com/microsoft/DNS-Challenge) |
| 标记为 DNS RIR 2021 的本地八通道子集，正式来源及版本未验证 | 项目链接 `/root/zxw/ZonePick/data/raw/DNS_RIRS/rirs_8ch` → `/root/DNS_noise_2021/RIRS`，约 8.9 MiB。在审计范围内未见压缩包，已存在实物 | 36 WAV、累计 36.00 秒，每文件 1 秒，均 16 kHz 八通道，0 头读取失败。RT60 文件名范围 0.26–1.23 s。说话人、噪声分类 N/A，官方划分未验证 | 含 RIR，本目录只见 WAV，麦克风/声源对应坐标与车内来源未验证。通用 WAV 读取通过，场景无 DNS RIR 适配器 |

DNS 噪声目录类别（均带 `_16k` 后缀）为 `DKITCHEN`、`DLIVING`、`DWASHING`、`NFIELD`、`NPARK`、`NRIVER`、`OHALLWAY`、`OMEETING`、`OOFFICE`、`PCAFETER`、`PRESTO`、`SPSQUARE`、`PSTATION`、`STRAFFIC`、`TBUS`、`TCAR`、`TMETRO`。未见专用空调或风噪类别。

| 项目未落地的数据 | 项目路径和官方属性 | ZonePick 状态 |
|---|---|---|
| In-Car McVAMPIRE V1.0 | `/root/zxw/ZonePick/data/raw/McVAMPIRE/V1.0`，文档所指 `/root/zxw/shared-datasets/McVAMPIRE` 也不存在。官方为真实八座三排车内数据，14 麦、口部及扬声器 RIR、行驶噪声。代码期望 24 kHz 14 通道，`geometry.mat` 有麦克风和口部坐标。说话人 N/A（口部模拟器），官方训练划分未验证 | 固定测点 RIR 适配器夹具通过，实物读取未验证。车载场景和噪声样例无法运行。[Zenodo V1.0](https://zenodo.org/records/12806684) |
| CAVEMOVE（文档标 v4） | `/root/zxw/ZonePick/data/raw/CAVEMOVE`，文档所指 `/root/zxw/shared-datasets/CAVEMOVE` 不存在。官方含四车型、两种录制布置、车内静态 RIR、静止与行驶噪声、通风/空调条件。代码检查预期 16 kHz 八通道。可用精确三维坐标、说话人标签和官方训练划分未验证 | `inspect_datasets` 仅能抽查 WAV，无仿真适配器。历史文档的 1,430 WAV、MD5 及库存不可用作本机证据。[官方数据](https://zenodo.org/records/17404917) · [官方合成 API](https://github.com/SPL-FORTH-ICS/CAVEMOVE) |
| dEchorate | `/root/zxw/ZonePick/data/raw/dEchorate/rir`，示例固定 SOFA 测点。官方为室内实测 RIR，含源和麦克风三维坐标、早期反射标注。代码期望 48 kHz 五通道。本机 SOFA 版本未验证，官方训练划分未验证，说话人 N/A。非车内 | 固定房间两测点 SOFA 适配器夹具通过，实物无从验证。[作者仓库](https://github.com/Chutlhu/dEchorate) · [SOFA 发布目录](https://www.sofaconventions.org/data/database/dechorate/) |
| UrbanSound8K | 项目内未发现目录或链接，旧代码指向另一机器的路径。官方 8,732 个短片、10 类、10 folds，含空调、喇叭、怠速发动机等环境声。说话人、RIR、坐标 N/A。非专用真实车内阵列 | 仍实现按 UrbanSound8K 文件名提取类 ID 的枚举，当前默认根指向 DNS，实测失败。[数据主页](https://urbansounddataset.weebly.com/urbansound8k.html) |
| 独立驾驶噪声 | `/root/zxw/ZonePick/data/raw/driving_noise` 未见。代码期望文件名以速度数字和 `kph` 开头 | `list_noise_files(NoiseConfig(kinds=["driving"]))` 实测 `ValueError: 未找到行驶噪声` |

`data/cache`、`data/rir`、`data/split` 及 `data/scenes/{train,val,test}` 未见实际样本或 manifest。其余识别到的 `data/raw/dl_logs` 约 628 KiB，为下载和解压相关记录。未扫描其他项目目录。正式数据版本、原始来源与下载完整性须以校验清单为准，本轮未重读整包做哈希。

## 5. 当前代码架构

| 模块 | 已实现和验证边界 | 复用判断 |
|---|---|---|
| `main.py`、`src/zonepick/__main__.py` | 一键对比与 HTTP 服务闭环通过，CLI 提供 datasets/run/serve/compare/split。两种比较入口默认算法和噪声行为不同 | 保留编排思路，清理范围和默认值需收敛 |
| `application/datasets.py` | JSON 语法配置，本地优先，目录抽查。实际只检查 LibriSpeech、dEchorate、McVAMPIRE、CAVEMOVE | 可复用路径解析及抽查框架 |
| `application/__init__.py` | 双源仿真配置、录音模式、几何、直接 DAS 和原子写出。自由场实物及录音夹具验证 | 可复用通道顺序管理和结果写出 |
| `audio/__init__.py`、`simulation/`、`regions/` | SoundFile 音频 I/O、重采样、STFT、RIR、混音、二维圆成员判断。测试边界和阵列声道顺序 | 基础工具可复用，样本、参考和标签合同需扩展 |
| `algorithms/` | 注册表、`load()/enhance()` 和单区域输入接口。identity、DAS、MVDR 已运行。Oracle 有诊断类 | 传统基线和接口可复用，公平隔离需强化 |
| `workbench/` 与 `evaluation/` | 同输入比较、评分、汇总、分组划分通过样例或单测。噪声真实数据映射失败 | 评分基础和划分逻辑可复用，协议需完整化 |
| `web/server.py` / `static/index.html` | 标准库 HTTP 后端、单 HTML 页面、场景预览和音频/对比 API | 适合作为本机调试工具 |
| `tests/`、`configs/`、`docs/` | 40 项测试。四个预设。README 和 ARCHITECTURE/PRD/CHARTER 描述路线，DATASETS/ENVIRONMENT/LEGACY 含前环境信息 | 测试夹具和预设可复用。文档架构和数据状态以现有源码/文件为准 |

`training/`、混合模型、纯神经网络模型、数据加载训练循环、检查点读写和多卡训练代码均尚未实现。插件 `kind="hybrid"/"neural"` 和 `load()` 为扩展接口。旧项目审计里的 GCC-PHAT/TDOA→DOA 仅有文档引用，当前树无 DOA、GCC-PHAT、MUSIC、SRP-PHAT 实现和注册。几何预测到达时差已实现。

## 6. 已实现算法及验证结果

通过 `PYTHONPATH=src python -m zonepick compare --config configs/scenarios/free_field.json --algorithms das mvdr --output-root <临时目录>` 和基础应用入口，在现有 `free_field.json`、16 kHz、32,000 样本、5 通道、两条真实 LibriSpeech `dev-clean` 语音、关闭环境噪声的同一试验中，落盘混合为 `(32000,5)`，各算法、参考、独立目标/干扰为 `(32000,1)`，重新读取后全为 16 kHz 且有限。内存算法约定为 `[M,N] → [N]`。

| 算法 | 实现及状态 | SI-SDR / 提升 dB | SDR / SIR / SAR dB |
|---|---|---:|---:|
| identity | 参考通道透传，已验证 | −0.379 / 0.000 | −0.379 / −0.379 / 321.023 |
| DAS | `classical.enhance` 对区域中心与指向高度做几何相位对齐后等权平均，已验证，含多通道数和相位符号夹具 | 0.299 / +0.678 | 0.299 / 6.322 / 2.457 |
| MVDR (sample) | `MvdrAlgorithm.enhance` 默认全帧样本协方差，已验证 | 6.317 / +6.696 | 6.312 / 29.800 / 6.336 |
| MVDR (speech_absence) | 同场景启用默认 0.3 能量分位，已验证 | 6.388 / +6.767 | 本轮未记录 |
| Oracle | `oracle.py::OracleTarget` 可返回外部注入的 `_target`。默认未导入，完整受控注入及排名剔除尚未实现 | N/A | N/A |

CLI 单次 RTF 约为 identity 0.000005、DAS 0.0027、MVDR 0.0062，计时区间仅包含插件 `enhance`，数据读取、仿真、初始化和保存另计。

MVDR 的数学与实际命名如下。

- 令 `τ_m=(||p-r_m||−||p-r_ref||)/c`，几何导向 `d_m(f)=exp(−j2πfτ_m)`，在参考通道归一为 1。代码按频点求 `z=solve(R,d)`，`w=z/(dᴴz)`，输出 `wᴴX`，iSTFT 至原长。Nyquist 权重取实部会改变该频点的理论约束。
- `_noise_covariance` 估计 `R=Σ_t x_t x_tᴴ/T + α·tr(R_sample)/M·I`，默认 `α=0.01`。默认估计是含目标和所有干扰的混合协方差，低能量模式依据跨频和麦的总能量筛帧，少于两帧回退全帧。低能量与目标缺席的等价关系未经验证。导向只用区域几何、自由场时延和单位幅值。失配时协方差可能压制区内目标。
- 实现是几何 steering-vector 形式的 MVDR。README、`main.py`、`algorithms/mvdr.py` 称 Souden 2010。Souden PSD 形式是 `R_n⁻¹ R_s u / tr(R_n⁻¹ R_s)`。当前无目标 PSD `R_s`，无迹归一计算。在匹配的秩一目标 PSD 及参考归一约定下形式可以等价。静音输入实测 `numpy.linalg.LinAlgError: Singular matrix`，因为相对迹加载仍为零。 [TorchAudio SoudenMVDR 公式](https://docs.pytorch.org/audio/stable/generated/torchaudio.transforms.SoudenMVDR.html)
- 分数是单个演示片段结果。两输入源、无车内 RIR 与环境噪声的成绩无法代表四区多人与低麦数性能。

## 7. 仿真和数据生成能力

`simulation/__init__.py::free_field_rir` 用欧氏距离、线性两抽头分数延迟和 `1/r` 衰减建直达路径。`convolve` 通过 FFT 逐通道卷积并截为输入长度，尾响被截，缺少反射、散射、头部遮挡、车厢混响、设备响应和采样不同步。底层 `mix_sources` 能累加任意同维数源并保留 `[S,M,N]`，上层 `prepare_simulation` 限死恰好两个源，只读 LibriSpeech，场景固定 16 kHz。实测适配目前为 dEchorate 固定房型、两声源、五通道阵列，以及 McVAMPIRE 座位/方位选择和 `geometry.mat`，并将 RIR 重采样到 16 kHz。两适配器单测使用造出的格式夹具。

`regions.circle_members` 以二维欧氏距离含边界决定成员，不处理座椅语义、区域重叠、区域空占位或移动。`application.run` 和 `workbench.compare.prepare_scenario` 均要求区内恰好一人，并以 `components[~members, reference][0]` 只拿第一路区外干扰。仅取消双源入口检查会让多区外源丢失于参考、SIR 和导出。四区域同时输出、区域内多源求和、全量区外语音及噪声真值、批量生成/分片/缓存重用尚未实现。

`noise.py::inject_noise` 支持基于种子抽样、自由场随机方向卷积、相对目标标定与独立噪声分量。测试仅覆盖禁用及相关配置。DNS 迁移只改了路径，`list_noise_files` 仍使用旧 UrbanSound8K 文件名 `\d+-(\d+)-` 及 10 类编号，`dns_noise` 数据配置没有接入该函数。真实测试 `free_field` 开噪声触发 `ValueError: 未找到 UrbanSound8K 噪声`。驾驶噪声目录独立测试也触发 `ValueError`。`_noise_at_mics` 在 captured 分支前裁成首路，阵列多通道情况下会退回随机方向渲染，并且缺少实测通道映射。两通道夹具的第二路原为零，实测输出第二路有 795 个非零样本。SNR 对每份噪声按第 0 通道标定，目标用配置参考通道，叠加后无总 SNR 校正。场景的 seed 与噪声随机种子未统一。

## 8. 数据划分与公平评价机制

- `workbench/splits.py` 支持固定随机种子、按路径或组分配以及 JSON manifest 读写。默认组提取为相对路径第一串数字。以真实 LibriSpeech 根目录运行时，`train-clean-100/...` 的 251 人全部被合为键 `100`，实测只得 81 组，生成 train 57 组/32,251 条、val 12 组/792 条、test 12 组/819 条。通过 `python -m zonepick split --root data/raw/LibriSpeech/LibriSpeech --output <临时 manifest>` 复现相同条数。它还会重新分配官方 dev/test 的说话人。局部含数字的目录可能掩盖真实说话人 ID，按文件分配也可能造成跨集。AISHELL-3 官方命名的 train/test 实测已有 170 个共同说话人。相同路径的 manifest 可以覆盖，时间戳每次变化。零比例还可能被强制至少保留一组的逻辑覆盖。
- `assert_no_test_leak` 只比对给定字符串与 test 清单，已有单元测试。没有训练入口校验，也没有执行时绑定。无跨语言、噪声原始录音、车辆/路况、RIR 测量会话隔离实现。README 的“冻结”需要额外流程约束。演示引用官方 dev-clean，两条样例可用于功能验证。
- `compare` 只准备一次输入，`AlgorithmInput` 白名单含混合、采样率、阵列、参考索引和用户区域。正常插件的导向未用真值。冻结 dataclass 中的 NumPy 数组仍可原地修改，同进程插件共享它们，因此后续插件可受前一算法意外修改影响。Oracle 默认未注册，`compare` 并无按 `kind` 剔除逻辑。显式导入后调用当前普通入口会因无注入而失败。清单和导出的参考包含真值，供独立评测使用。
- `metrics.py` 的 SI-SDR、相对 identity 的 ΔSI-SDR、BSS-Eval 风格单干扰投影 SDR/SIR/SAR、RTF 和均值/总体标准差汇总已实现。其 SIR/SAR 中干扰参考只是一条区外语音，额外噪声进入残差。公式也存在近零残差给出极大 SAR 的现象，本轮 identity 约 321 dB。区域选择性仅为响应增益差函数，未建立工作台测量。STOI/PESQ 仅列可选指标，项目未调用。对空区域、同时多目标和全阵列统一参考的协议待定。
- `compare` manifest 记录场景、运行版本、部分噪声字段和指标，遗漏实际每算法参数、各输入内容校验、被抽取噪声片段与完整噪声配置。CLI `compare` 和 `main.py` 各自解析噪声开关。比较入口给插件空参数时不继承场景 `das` 的 FFT 或声速设定，传统 `run` 则会读取它们。比较实验需要明确记录这些差异。

## 9. 可视化功能

`web/server.py` 和 `web/static/index.html` 含预设选择、二维和三维几何、拖动圆形区域、波形/频谱、试听、指标与对比页面。自定义场景 JSON 可写回配置目录。网页常规运行 POST 调用单区域 DAS，比较页读取已有多算法产物。一键入口退出后自动清理。

`python main.py` 在 `127.0.0.1` 临时端口启动，GET `/`、`/api/scenarios`、`/api/preview/free_field`、`/api/compare` 均为 200。独立 handler 实测对比详情和 `mvdr.wav` 均 200，POST `/api/runs` 返回 201 并输出真实 DAS 指标。实际浏览器绘制、旋转、拖动和播放器交互未验收。

## 10. 与导师新要求之间的差距

| 目标 | 当前适配度 |
|---|---|
| 四区 FL/FR/RL/RR，对应区域保留幅度、抑制其余区域和噪声 | 当前每次只有一个几何圆和单路增强。区域标签、输出 `[4,N]`、四个目标构建、跨区串扰评价均待设计 |
| 四至五人同讲 | 本地中英两种独立语料均可选取多于五名说话人，底层卷积累加可复用。项目场景/API 限两人且一区一人，尚不可生成目标场景 |
| 8/6/4/3/2 MIC | `select_channels` 可按已有阵列选通道，不能替代物理位置相符的测量。8 麦为前后左右各 2。6 麦前排左右各 2、后排左右各 1。4 麦前后左右各 1。3 麦前排左右加后中。2 麦前后中轴。现有自由场为 5 麦直线，车内预设为另一种 14 麦测量阵列。尚无五套对应几何与同场可复核的 RIR |
| 真实混响与行驶、空调、风噪 | 本地未证实任何车内配准 RIR 或驾驶录音可用。本地疑似 DEMAND 的 TCAR 可作为候选车内噪声，分通道录音的同步、布置和工况仍需核实，现有工程未提供与目标布置的映射。通风、风噪专用样本及真实车内配置待核验 |
| 路线 A | identity、DAS、几何 MVDR 可做起点，尚无四区、多人、跨麦数真实基线 |
| 路线 B / C | 只有注册与推理接口，尚无掩码网络、纯 NN、训练、推理权重、数据集类或公平训练评估协议 |
| 规模化训练与复现 | 有语料、底层声学和基础划分工具，缺场景采样、批量生成、实测 RIR/噪声映射、版本化批次和自动泄漏检查 |

精确麦克风坐标、车厢几何、第五人标签、区域边界、多区域冲突策略、训练规模、交叉验证和模型架构均为待研究事项，本轮未定稿。

## 11. 已发现的 Bug 与科研风险

1. **高优先级 · 双源及真值语义。** `prepare_simulation`、`application.run`、`prepare_scenario` 的双源、区内一人、取第一路区外干扰限制阻塞主要科研任务。工作台还在校验 reference 索引前访问 components，坏索引可能先抛 `IndexError`。
2. **高优先级 · 噪声。** DNS 路径与旧 UrbanSound8K 分类规则不匹配。captured 提前降成单通道。参考通道与 SNR 标定不一致。详见第 7 节。
3. **高优先级 · MVDR 复现与稳定性。** 算法别名与 PSD 形式不匹配。静音实测奇异，贴近零功率、低秩矩阵、几何失配和混响有待覆盖。参数记录不足会影响复现。
4. **高优先级 · 退出清理。** `main.py` 向 `cleanup_generated` 同时传入当前运行目录和整个 `runs/compare`。若已有历史结果，默认退出会递归移除。函数也遍历项目的 `__pycache__` 和 `*.pyc`。本轮执行前确认 `runs/` 不存在。默认退出清理了本轮产物，并清除了项目预先存在的可重建字节码缓存。
5. **中优先级 · 网页测试与代理。** 原环境结果 36 passed / 4 failed。失败用例为 `test_compare_routes_list_detail_and_audio`、`test_post_runs_application_config_and_links_result`、`test_scenarios_and_preview_expose_geometry_and_region`、`test_unknown_scenario_and_bad_region_return_readable_error`。定位 `tests/test_zonepick.py::WebTests.request` 224/231 行，`urllib` 回环请求被代理处理，HTTP 错误体为空，`json.loads` 抛 `JSONDecodeError: Expecting value: line 1 column 1 (char 0)`。独立探测直接看到 HTTP 502。仅凭进程参数 `NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost` 复测为 **40 passed in 19.12s**。
6. **中优先级 · 环境与 Git 规则。** 实际版本低于声明，历史环境和数据描述混在当前部署文档。通用大文件和凭据文件的忽略覆盖存在空档。现有 CLI 的正确检查命令为 `python -m zonepick datasets`。`datasets-check` 会被 argparse 以 invalid choice 拒绝。

## 12. 可以直接复用的代码

- `audio` 的解码、重采样、STFT/iSTFT 与 FLOAT WAV 写出，`simulation` 的逐源逐麦卷积与分量累加，`application.select_channels` 的通道映射。
- `regions.circle_members` 可继续用于诊断区域。`AlgorithmInput` 可作为显式推理边界。identity、DAS、几何 MVDR 可用作小场景传统对照。
- `runtime_metadata`、`workbench.splits` 的种子/组分配基本逻辑、`evaluation` 的信号投影评分和 Web 产物检查入口。使用现有测试夹具继续验证通道顺序、几何和参考口径。

## 13. 后续建议检查和开发的事项

1. 先冻结数据来源、车内布置与通道映射证据，核对真实车辆 RIR、行驶/通风/风噪及许可证，并验证训练、验证和测试中的说话人、车型、会话及原始音轨分组。
2. 定义多人四区场景与标签合同、空区/多人同区处理、干声或参考麦声像的公平参考、五种配置配对比较条件。保持第五人归属、训练规模和验证方案开放。
3. 修通真实数据入口后建立数值基线，覆盖静音、零能量频点、强混响、阵列失配及多干扰。明确命名现有 MVDR，若比较 Souden 形式则记录目标和噪声 PSD 的估计方法与信息来源。将修正后的说话人分组在真实语料根目录上验证，避免使用演示 `dev-clean` 场景作为正式测试集。
4. 先统一产物清理范围、比较参数与数据哈希，再考虑批量生成和路线 B/C 训练接入，记录配置、提交、依赖、划分、权重、参考条件和聚合口径。

## 14. 本轮实际修改的文件

- `.git/config` 写入本仓库级别提交者姓名和邮箱。
- `docs/PROJECT_AUDIT_2026-11-27.md` 新增，未暂存。
- 轻量运行的临时产物已清理。首次 pytest 使用了系统默认临时目录，复测显式将 TMPDIR 指到仓库内。一键入口也移除了项目已有的可重建 Python 字节码缓存，详见第 11 节。科研源码、现有暂存内容、数据、依赖及远端分支保持原状态。本轮没有提交或推送。

## 15. 未完成或无法验证的事项

- GitHub HTTPS 写入需用户授权。SSH 探测超时。VS Code 本地与远程登录不能从当前终端判定。远端可读和提交身份均已验证。
- 当前没有真实车内场景、双语多人四区、五档实测阵列、混合/纯神经网络、训练及 DDP 集合通信闭环证据。实测 RIR 适配器只通过合成格式夹具。前端浏览器交互尚未实测。
- 原始数据归档完整性校验、DNS 子集的精确来源与版本、RIR 坐标配套及与车内条件的对应关系未验证。历史文档中的其他工作机数据可用性未归为当前机器事实。
