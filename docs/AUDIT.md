# ZonePick 项目审计与开发记录

## 当前项目状态

单区域 CLI 和 Web 保留。基准优先建设统一数据、四区空间合同与评测口径。本轮完成数据整理、B00 基础设施与 B01 四区场景合同的验收。正式数据生成及训练排在后续里程碑。

## 技术问题追踪

| 问题 | 当前处理与验证 |
| --- | --- |
| 资源路径与 CAVEMOVE 大包 | 按实测根目录配置，Python ZIP64 全包校验与暂存解压通过。 |
| 跨集合说话人泄漏 | 语料命名空间、路径/文件名一致性、任意两集合身份与录音互斥。真实语料复核见本轮时间线。 |
| 噪声通道丢失及 SNR 偏离 | 按录音分组，保留同步采样与裁剪。总叠加噪声在配置参考通道标定。 |
| 旧实验目录被清理 | 默认保留，显式临时模式只持有本次创建的目录。 |
| 算法输入污染与 MVDR 数值崩溃 | 每算法独立观测副本，Oracle 拒绝进入普通排名。几何 MVDR 保留迹比例加载，零能量频点使用导向权重，病态矩阵额外加载。 |
| CAVEMOVE 几何、虚拟参考、少 MIC 可辨识性 | 有待后续场景适配与验证。B01 两麦中轴对称性纳入测试。 |
| 正式训练及评测 | B05 验收后进入 B06。 |

## 重要技术决策

事件级混合先以 M0–M9 完成。同一事件再按物理通道 ID 选择布局，固定 FL/FR/RL/RR 顺序。实测阵列保留自身几何。第五人可标为未归属并保留在混合及所有区外干扰中。虚拟参考与统一对齐由后续 Pilot 和评测阶段验证。

## 历史开发时间线

### 2026-11-22｜旧项目代码审计（以首次提交日期定位）

#### 旧语音处理代码审计与复用计划

本次审计读取原 `audio-ml-learning` 工作树（旧本地路径已失效，仅作历史记录），以 ZonePick [产品需求文档](PRD.md)、[技术架构](ARCHITECTURE.md)和[开发环境](ENVIRONMENT.md)为依据。以下路径均相对旧仓库根目录。复用顺序为 v0.1-A 的候选计划，具体几何、参考语音和验收口径仍需评审。

##### 复用结论

优先复用经过验证的逐通道卷积、频域 DAS 权重与合成，以及可配置化的音频读取和 STFT/ISTFT。旧实验的 DAS 入口把已知目标 RIR 转成导向向量，属于 Oracle。ZonePick 的常规 DAS 应从用户选择的区域和阵列几何得到指向。测量场景可作为固定预设或独立回归样例。MVDR、空间特征与训练先保留为后续路线的参考。

##### 场景与 RIR

| 旧实现 | 已核实的接口与行为 | 复用判断 |
| --- | --- | --- |
| `learning/spatial_audio/scene.py` 的 `load_rir_pair`、`load_array_geometry` | 接收 SOFA 目录、阵列编号和通道数。RIR 读取绑定 dEchorate 指定房间、两处固定声源、六组阵列和特定文件名，检查原始 `Data.IR` 为 `[1,5,48000]`、48 kHz。保持 SOFA 通道顺序，取前 M 路，返回两份降采样至 16 kHz 的 `[M,L]` RIR，以及从原始前 960 点最大绝对值估计的 Mic 0 相对时延 `[M]`（秒）。几何函数另返回麦克风 `[M,3]` 和声源 `[2,3]` 米坐标。 | 仅作为测量数据适配器；早期峰是近似，不能保证为直达声。固定测点不可按用户任意坐标重新标注。 |
| `choose_different_speakers` | 接收路径列表和调用方 NumPy RNG，根据 `speaker/chapter/file` 层级返回两位不同说话人的文件路径。说话人排序，文件抽样受传入顺序影响。 | 只适用于对应语料布局。MVP 可直接在配置指定两段获准使用的音频。 |
| `load_speech_segment` | 输入路径、目标样本数和采样率（默认 16 kHz）。SoundFile 解码单声道，按有理比例重采样，从头截取或尾部补零，返回 float64 `[N]`。 | 可作为音频读取候选。明确校验请求采样率和长度，另行定义多通道读写。 |
| `convolve_rir` | 输入单声道 `[N]` 和 RIR `[M,L]`，逐路 FFT 线性卷积，取前 N 点得到 `[M,N]`，保持通道顺序。 | **直接复用候选**。现有测试确认截尾行为；如需要保留混响尾部，应在场景协议中确定。 |
| `build_speech_scene` | 默认种子 42、阵列 1、五路、16000 样本、0 dB 输入 SIR。默认读取 LibriSpeech `dev-clean` FLAC 和 dEchorate SOFA。先构造五路，通过 Mic 0 功率比缩放干扰，再截取前 1/2/3/5 路。返回 `mixture/target/interference [M,N]`、两份 RIR、目标 TDOA、真实坐标、路径、种子和缩放参数。 | 保留混合与参考生成思路。拆除固定目标身份、数据目录、阵列和参考通道假设，推理入口仅接受观测和可用空间条件。 |

`learning/common/paths.py` 默认相对旧仓库定位 `data/`，可由 `AUDIO_LEARNING_DATA` 覆盖。主要共享函数没有绑定个人绝对路径，实验入口仍依赖旧仓库结构、数据命名与 Python 导入路径。审计确认默认测量场景可读取。公开发布前仍需核实源码及每项语料、RIR 的使用和再分发权限，本次在旧仓库浅层未找到独立许可证文件。

##### 时频、阵列处理与评价

| 旧实现 | 已核实的接口与行为 | 复用判断 |
| --- | --- | --- |
| `learning/spatial_audio_nn/scene_utils.py` 的 `RIRPair`、`split_speakers`、`read_random_speech_segment` | `RIRPair` 保存两份 `[M,L]` 和参考通道相对时延 `[M]`（秒）。划分函数按 LibriSpeech 说话人 ID 返回两份排序路径列表，每侧至少两位说话人。随机裁剪接收已有 16 kHz 单声道、长度与 RNG，返回 float64 `[N]`，短片段补零。 | 后续训练可借鉴按说话人隔离和显式 RNG。MVP 用固定输入；时延及 RIR 留在仿真或 Oracle 路径。 |
| 同文件的 `stft_spectrum`、`istft_waveform` | 16 kHz、Hann 256 点、128 点帧移、零边界及末帧补齐，使用 SciPy 默认 spectrum 缩放。输入 `[N]` 或 `[M,N]`，输出 `[F,K]` 或 `[M,F,K]`，通常 `F=129`。逆变换接收单通道谱 `[F,K]`，末尾裁至请求长度。 | 可借鉴成对变换，显式传采样率、窗和长度；逆变换接口当前只承诺单通道。测试短于一窗、尾帧和同长度重建。 |
| `learning/speech_signal_processing/Frequency_Process/STFT.py`、`STFT_librosa.py` | 教学用分帧 FFT 和 librosa 绘图，读取示例文件、保留源采样率，运行流程与绘图相连。 | 保留作教学参考。首版使用已验证的 SciPy 变换路径。 |
| `learning/spatial_audio/spatial_utils.py` 的 `simulate_delay`、`build_spatial_source`、普通互相关与 GCC-PHAT 系列 | 延迟函数 `[N] -> [N]`，正值为延后，边界补零并支持分数采样；双麦构造堆叠原信号和延迟信号 `[2,N]`。估计器输入两条波形、最大采样延迟等参数，返回有符号采样延迟，`calc_estimate_tdoa` 可转换成秒或毫秒；`tdoa_to_doa` 按双麦几何输出角度。 | 可作为合成和符号检查参考。混合语音的主峰未必属于目标区域，定位不进入首版必需流程。 |
| 同文件的 `steering_vector`、`rir_steering_vectors` | 前者输入频率、以阵列法线为基准的角度、阵元索引和间距，返回 ULA 导向 `[M]`。后者用目标实测 RIR 的早期响应（默认 320 点）得到相对 Mic 0 的复数 `[F,M]`。 | ULA 实现仅用于满足其假设的线阵。首版可用各麦到区域代表点的几何延迟构造单位幅度导向；RIR 导向仅作 Oracle。 |
| 同文件的 `beamformer_weights`、`apply_beamformer` | 输入混合谱 `[M,F,K]` 与导向 `[F,M]`，返回 `[F,M]` 权重。DAS 取导向相位并除以导向幅值和，单位幅度时是等幅平均。应用时按通道共轭求和，输出 `[F,K]`。 | **直接复用候选**，沿用变换轴与共轭约定，限制常规入口可接受参数为观测和几何来源，验证参考通道、空维、有限值及分母。 |
| 同文件的 `estimate_spatial_covariance`、`mvdr_weights`、`masked_spatial_covariance` | 未中心化协方差 `[M,K] -> [M,M]`；MVDR 由协方差与 `[M]` 导向求 `[M]` 权重，加载由外层完成。掩码协方差输入 `[M,F,K]` 和非负功率权重 `[F,K]`，输出 `[F,M,M]`，低权重频点回退至混合协方差。 | 后续可复用。旧 `mvdr` 分支默认用纯干扰谱，`mvdr_mixture` 用混合谱；外部协方差及掩码是否属 Oracle 取决于来源。 |
| 同文件的 `evaluate_scene_beamformers`、`component_sir`，以及 `experiment.py` 与 `05_das.py` 至 `09_spatial_interference_mvdr.py` | 传统频域实验用 16 kHz、512 点窗及半窗重叠，得 `F=257`，参考为 Mic 0。导向来自目标 RIR。冻结权重应用于混合与独立分量，返回长度 N 波形及目标/干扰功率比。时域 MVDR 练习直接从目标和干扰的真实分量取协方差。 | 频域分量加性和固定权重评价思路可借鉴。旧入口均含 Oracle 条件，混合协方差分支也沿用真实 RIR 导向。时域单权重诊断不作为宽带基线。 |

`scene_utils.component_snr` 是带 EPS 的分量功率比，双静音会得到 0 dB。旧 `component_sir` 则拒绝零功率分量。`learning/speech_enhancement/audio_utils.py` 的 `calculate_snr` 基于参考与估计的误差，语义不同。首版应另行确认 SI-SDR 的对齐、参考和无效值策略。

##### 空间特征与学习实验

- `learning/spatial_audio_nn/13_spatial_feature_representation_exercise.py` 从混合谱计算相对 Mic 0 的 IPD 与 ILD，每个通道对输出 `[F,K]`，堆叠为 `[M-1,F,K]`。相位编码和 ILD 裁剪可作为后续特征设计参考，需固定通道对顺序、符号和静音规则。
- `15_target_condition_exercise.py` 至 `17_conditioned_mask_network_exercise.py` 中的条件沿用旧目标和干扰身份，监督掩码来自独立分量。`18_spatial_region_exercise.py` 读取真实声源与阵列位置，按到阵列中心的距离区分远近。几何坐标可供仿真标注和评价。目标身份、远近索引和真实声源位置均不得替代常规推理的区域条件。同一混合样本上拟合与再评估只能验证学习机制。
- `hybrid_nn_mvdr.py` 的实际路径用混合对数幅度 `[M,F,K]` 预测 Mic 0 的三类功率掩码 `[3,F,K]`，后续做目标掩码、WPE 和通道平均。它整批堆叠预生成数据，用 PyTorch MSE 训练。使用预测掩码与真实分量生成的理想掩码分别评价。训练和验证从 `dev-clean` 按说话人切分，测试用 `test-clean`，阵列按 1–4、5、6 分配。可参考其划分与冻结滤波器评价设计；首版无需训练或 WPE。
- `jointly_optimal_cbf.py` 直接把实测目标 TDOA 转成逐频导向用于处理，属于 Oracle 对照。`learning/speech_enhancement/dataset.py`、`train.py` 是单声道混合与干净标签的训练流程，可参考 DataLoader 和训练验证职责，输入缺少阵列与区域条件。

##### 推理边界与验收风险

- **区域指向**使用预先确定且可由用户配置的圆心与阵列坐标，候选方案按共同高度或明确投影约定求传播时延，以显式参考麦克风为零。记录指向来源、声速、单位和通道顺序。预设测试应至少包含目标偏离圆心的场景，确保推理未把真值位置自动替换为指向。
- **参考隔离**将场景配置中的逐源位置、RIR、独立语音和标签留在仿真、训练或评价路径。应用层独立传递混合波形、采样率、阵列和区域给 DAS。未增强输入使用同一参考通道。调整或移除参考时，保留同一观测和区域，验证推理波形不变。缺参考时报告指标不可用。
- **评价可比性**预先固定参考通道上的目标分量、对齐规则和裁剪长度。若计算分量 SIR，以同一组从允许输入得到的固定权重处理双方分量，避免分别估计权重或将重建残差混称干扰。输出 WAV 前统一检查增益、裁剪和量化，指标口径与试听产物应可追溯。
- **数据泄漏**后续训练记录语料、说话人、片段和 RIR/房间版本与划分，避免同一说话人或不同裁剪的同一录音跨集合。若主张泛化到未见房间，还需按房间隔离。测试集合不参与算法或区域参数选择。Oracle 与常规运行分别记录信息来源和结果。

##### 环境与验证证据

- 使用 WSL2 中已有的 Conda `pytorch`，实测 Python 3.9.25、PyTorch 2.0.1。NumPy 1.24.4、SciPy 1.13.1、SoundFile 0.13.1、h5py 3.14.0 和 tqdm 4.70.1 可导入，`nara_wpe.wpe` 亦可导入。NumPy/SciPy 首版路径不依赖 PyTorch GPU 或 Triton。
- 使用 `python -B` 在 CPU 运行旧仓库现有 10 项单元测试，全部通过。数值覆盖包括 RIR 截尾卷积、随机裁剪与 RNG 状态、STFT 往返、掩码协方差、固定波束权重及分量加性。
- 使用旧默认配置（阵列 1、种子 42、0 dB 输入 SIR）做一次只读 CPU 冒烟检查。混合与目标 RIR 均为 `[5,16000]`，研究 STFT 为 `[5,129,126]`，参考通道往返重建通过 `1e-12` 绝对容差检查（NumPy 默认相对容差）。旧 Oracle DAS 权重为 `[257,5]`，DAS、纯干扰协方差 MVDR 和混合协方差 MVDR 均返回长度 16000 的混合输出及有限 SIR。此检查只验证旧实验执行和形状。
- **待运行验证**包括区域几何 DAS 在合成延迟与偏心目标上的行为、参考通道变更、区域边界、无参考推理，以及写出 WAV 后的端到端重跑。未运行学习实验、GPU 路径或完整依赖矩阵，不能据此推断其性能。

##### v0.1-A 最小实现顺序

1. **固定候选输入契约**。两个静止说话人、五通道、16 kHz、二维区域。记录坐标单位、通道映射、参考麦克风和种子。固定测量预设只用对应测点，若首版需要移动声源则单独实现可配置的几何仿真路径。
2. **打通场景生成和区域标签**。读入两段获准发布或本地持有的语音，卷积并混合出 `[5,N]`。区域成员只用于仿真参考生成和场景校验，常规推理独立接收区域几何。确认空区域、多声源和边界行为。
3. **接入常规 DAS**。从圆心或评审选定的区域代表点求相对传播时延，构造逐频几何导向，使用成对 STFT/ISTFT 合成同长度波形。用已知延迟合成样例验证对齐方向、参考通道和单位响应。
4. **接入命令行与评价**。用同一混合信号保存未增强参考通道和增强 WAV、已解析场景、算法参数与指标。候选首项为 SI-SDR，待确认参考和有效性规则。日志保存运行标识、代码版本和指向来源。
5. **验收 CPU 闭环**。固定配置重跑，核对形状、长度、采样率、通道顺序和记录。独立测试无参考和偏心目标，记录耗时和内存。根据样例结果确认容差和后续性能目标。

### 2026-11-27｜服务器迁移与全面审计

#### ZonePick 项目审计 · 2026-11-27

##### 1. 项目基本信息

工作区为 `ZonePick 仓库根目录`，远程为 [zxw040906/ZonePick](https://github.com/zxw040906/ZonePick)，`pyproject.toml` 标记版本 0.1.0。当前实物是离线单区域拾音原型与小规模对比工作台。以下按证据使用“已实现且验证通过”“已实现但未验证”“仅有接口或文档规划”“尚未实现”。单元测试夹具通过与实测数据闭环通过分别注明。

##### 2. Git 状态及认证修复结果

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

##### 3. 服务器与开发环境

| 检查项 | 实测 |
|---|---|
| Linux / CPU / 内存 | Ubuntu 20.04.6 LTS，AMD EPYC 7543，单路 32 物理核 / 64 逻辑 CPU，125 GiB RAM，测试时约 119 GiB available，8 GiB swap |
| 磁盘 | 项目位于 `/dev/sda1`，`df -h .` 见 7.3 TiB 总量、4.2 TiB 已用、2.8 TiB 可用 |
| GPU | 两张 RTX 3090，各 24,576 MiB。初检每卡 1 MiB、0% 利用率，`nvidia-smi` 未列运行进程 |
| NVIDIA / CUDA | 驱动 595.104.02，`nvidia-smi` 显示兼容 CUDA 13.2。PyTorch 编译 CUDA 11.8，运行可用。PATH 未找到 `nvcc` |
| Python / Conda | 当前 `base`，`Conda base 的 Python`，Python 3.11.7。`conda env list` 未列文档示例的 `pytorch` 环境 |
| 科研库 | NumPy 1.24.0、SciPy 1.11.4、SoundFile 0.12.1、h5py 3.9.0、PyTorch 2.4.0、torchaudio 2.4.0、pystoi 0.4.1、pesq 0.0.4、pytest 7.4.0。PyRoomAcoustics、TensorBoard 导入时报 `ModuleNotFoundError` |
| 声明冲突 | NumPy 满足声明。SciPy、SoundFile、h5py 低于 `pyproject.toml` 下限 1.13、0.13、3.14。源码经 `PYTHONPATH=src` 可运行，安装解析与新环境重建未验证 |
| CUDA / DDP | `torch.cuda.is_available()=True`，两张卡和 CPU 分别完成 4 元素求和，均得 4。Distributed 与 NCCL available 均 True，具备两卡 DDP 基础。未验证进程组、集合通信或真实训练 |

##### 4. 数据集完整清单

`du -hL data` 显示本地数据与两个链接目标合计约 60 GiB。项目中数据路径均以 `` 为绝对前缀。体积来自 `du -hL` 实际分配空间，语音目录体积含留存压缩包。音频时长按每个可读文件 `frames / samplerate` 累加，多通道每文件计一次。缺失数据的本地占用、文件数、时长、采样率、通道、作者所用划分均记为未验证，且本项目配置路径未发现目录、压缩包或链接。外部仅按项目链接或文档明确指向的依赖定位。

| 本机数据 / 版本 | 绝对路径、链接、占用与解压 | 实物统计 / 官方划分 | 空间及项目适配 |
|---|---|---|---|
| AISHELL-3 1.0，普通话 | `data/raw/AISHELL3`，非链接约 44 GiB。留存 `data_aishell3.tgz`（19,057,141,777 B），已展开 `train/wav` 约 19 GiB、`test/wav` 约 6.7 GiB | 本地 train 63,262 WAV / 174 人，test 24,773 WAV / 214 人，合计 88,035 WAV / 218 人。按 `SSBxxxx` 父目录提取说话人，170 人跨官方命名的 train/test，同一说话人目录与文件名组合的交集为 0。现有目录划分无法满足说话人互斥。全量文件头实测 train 227,420.55 秒（63.17 h）、test 80,803.62 秒（22.45 h），合计 85.62 h。全部 44.1 kHz 单声道，0 头读取失败。每部分抽查 64 个为 PCM 16-bit | RIR、噪声类别、空间坐标 N/A，安静室内单声道录音。两边各抽一个文件经 `read_audio/speech_segment` 可正常读取并重采样，场景和检查 CLI 均未适配 AISHELL-3 |
| LibriSpeech OpenSLR SLR12 英语 clean 子集 | `data/raw/LibriSpeech/LibriSpeech`，非链接。父目录含三个 `.tar.gz` 共约 6.6 GiB，解压约 7.0 GiB，合计约 14 GiB | 33,862 FLAC，111.38 h，全部 16 kHz 单声道，0 头读取失败。官方 `train-clean-100` 28,539 / 100.59 h / 251 人。`dev-clean` 2,703 / 5.39 h / 40 人。`test-clean` 2,620 / 5.40 h / 40 人。文件名前缀与说话人目录为 ID，三个官方子集共 331 人、两两无交集。其他官方子集未发现 | 类别、RIR、坐标 N/A。已适配，CLI 抽查和真实自由场闭环通过。[OpenSLR SLR12](https://www.openslr.org/12) |
| 标记为 DNS noise 的本地 17 类子集，正式来源及版本未验证 | 项目链接 `data/raw/DNS_noise/noise_17class` → `外部 DNS-Challenge-master/noise`，约 2.5 GiB。在审计范围内未见对应压缩包，已存在实物 | 272 WAV / 22.67 h，均 16 kHz 单声道，0 头读取失败，17 类各 16 文件。说话人及 ID N/A，官方训练划分未验证 | RIR N/A，本地文件未附可用坐标。普通读音频通过，现有噪声入口适配失败，272 个文件均不匹配 UrbanSound8K 正则。同类 `ch01.wav` 到 `ch16.wav` 均为 300.004 s。如按每组同一录音计，仅约 85 分钟。目录名和分通道结构与官方 DEMAND 1.0 发布高度吻合，包含疑似真实私家车 `TCAR` 样例，实际文件来源、阵列配准与速度未通过校验确认。仓库命名不能证明其 DNS 版本。[DEMAND 官方发布](https://zenodo.org/records/1227121) · [Microsoft DNS 官方仓库](https://github.com/microsoft/DNS-Challenge) |
| 标记为 DNS RIR 2021 的本地八通道子集，正式来源及版本未验证 | 项目链接 `data/raw/DNS_RIRS/rirs_8ch` → `外部 DNS_noise_2021/RIRS`，约 8.9 MiB。在审计范围内未见压缩包，已存在实物 | 36 WAV、累计 36.00 秒，每文件 1 秒，均 16 kHz 八通道，0 头读取失败。RT60 文件名范围 0.26–1.23 s。说话人、噪声分类 N/A，官方划分未验证 | 含 RIR，本目录只见 WAV，麦克风/声源对应坐标与车内来源未验证。通用 WAV 读取通过，场景无 DNS RIR 适配器 |

DNS 噪声目录类别（均带 `_16k` 后缀）为 `DKITCHEN`、`DLIVING`、`DWASHING`、`NFIELD`、`NPARK`、`NRIVER`、`OHALLWAY`、`OMEETING`、`OOFFICE`、`PCAFETER`、`PRESTO`、`SPSQUARE`、`PSTATION`、`STRAFFIC`、`TBUS`、`TCAR`、`TMETRO`。未见专用空调或风噪类别。

| 项目未落地的数据 | 项目路径和官方属性 | ZonePick 状态 |
|---|---|---|
| In-Car McVAMPIRE V1.0 | `data/raw/McVAMPIRE/V1.0`，文档所指 `旧共享数据目录/McVAMPIRE` 也不存在。官方为真实八座三排车内数据，14 麦、口部及扬声器 RIR、行驶噪声。代码期望 24 kHz 14 通道，`geometry.mat` 有麦克风和口部坐标。说话人 N/A（口部模拟器），官方训练划分未验证 | 固定测点 RIR 适配器夹具通过，实物读取未验证。车载场景和噪声样例无法运行。[Zenodo V1.0](https://zenodo.org/records/12806684) |
| CAVEMOVE（文档标 v4） | `data/raw/CAVEMOVE`，文档所指 `旧共享数据目录/CAVEMOVE` 不存在。官方含四车型、两种录制布置、车内静态 RIR、静止与行驶噪声、通风/空调条件。代码检查预期 16 kHz 八通道。可用精确三维坐标、说话人标签和官方训练划分未验证 | `inspect_datasets` 仅能抽查 WAV，无仿真适配器。历史文档的 1,430 WAV、MD5 及库存不可用作本机证据。[官方数据](https://zenodo.org/records/17404917) · [官方合成 API](https://github.com/SPL-FORTH-ICS/CAVEMOVE) |
| dEchorate | `data/raw/dEchorate/rir`，示例固定 SOFA 测点。官方为室内实测 RIR，含源和麦克风三维坐标、早期反射标注。代码期望 48 kHz 五通道。本机 SOFA 版本未验证，官方训练划分未验证，说话人 N/A。非车内 | 固定房间两测点 SOFA 适配器夹具通过，实物无从验证。[作者仓库](https://github.com/Chutlhu/dEchorate) · [SOFA 发布目录](https://www.sofaconventions.org/data/database/dechorate/) |
| UrbanSound8K | 项目内未发现目录或链接，旧代码指向另一机器的路径。官方 8,732 个短片、10 类、10 folds，含空调、喇叭、怠速发动机等环境声。说话人、RIR、坐标 N/A。非专用真实车内阵列 | 仍实现按 UrbanSound8K 文件名提取类 ID 的枚举，当前默认根指向 DNS，实测失败。[数据主页](https://urbansounddataset.weebly.com/urbansound8k.html) |
| 独立驾驶噪声 | `data/raw/driving_noise` 未见。代码期望文件名以速度数字和 `kph` 开头 | `list_noise_files(NoiseConfig(kinds=["driving"]))` 实测 `ValueError: 未找到行驶噪声` |

`data/cache`、`data/rir`、`data/split` 及 `data/scenes/{train,val,test}` 未见实际样本或 manifest。其余识别到的 `data/raw/dl_logs` 约 628 KiB，为下载和解压相关记录。未扫描其他项目目录。正式数据版本、原始来源与下载完整性须以校验清单为准，本轮未重读整包做哈希。

##### 5. 当前代码架构

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

##### 6. 已实现算法及验证结果

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

##### 7. 仿真和数据生成能力

`simulation/__init__.py::free_field_rir` 用欧氏距离、线性两抽头分数延迟和 `1/r` 衰减建直达路径。`convolve` 通过 FFT 逐通道卷积并截为输入长度，尾响被截，缺少反射、散射、头部遮挡、车厢混响、设备响应和采样不同步。底层 `mix_sources` 能累加任意同维数源并保留 `[S,M,N]`，上层 `prepare_simulation` 限死恰好两个源，只读 LibriSpeech，场景固定 16 kHz。实测适配目前为 dEchorate 固定房型、两声源、五通道阵列，以及 McVAMPIRE 座位/方位选择和 `geometry.mat`，并将 RIR 重采样到 16 kHz。两适配器单测使用造出的格式夹具。

`regions.circle_members` 以二维欧氏距离含边界决定成员，不处理座椅语义、区域重叠、区域空占位或移动。`application.run` 和 `workbench.compare.prepare_scenario` 均要求区内恰好一人，并以 `components[~members, reference][0]` 只拿第一路区外干扰。仅取消双源入口检查会让多区外源丢失于参考、SIR 和导出。四区域同时输出、区域内多源求和、全量区外语音及噪声真值、批量生成/分片/缓存重用尚未实现。

`noise.py::inject_noise` 支持基于种子抽样、自由场随机方向卷积、相对目标标定与独立噪声分量。测试仅覆盖禁用及相关配置。DNS 迁移只改了路径，`list_noise_files` 仍使用旧 UrbanSound8K 文件名 `\d+-(\d+)-` 及 10 类编号，`dns_noise` 数据配置没有接入该函数。真实测试 `free_field` 开噪声触发 `ValueError: 未找到 UrbanSound8K 噪声`。驾驶噪声目录独立测试也触发 `ValueError`。`_noise_at_mics` 在 captured 分支前裁成首路，阵列多通道情况下会退回随机方向渲染，并且缺少实测通道映射。两通道夹具的第二路原为零，实测输出第二路有 795 个非零样本。SNR 对每份噪声按第 0 通道标定，目标用配置参考通道，叠加后无总 SNR 校正。场景的 seed 与噪声随机种子未统一。

##### 8. 数据划分与公平评价机制

- `workbench/splits.py` 支持固定随机种子、按路径或组分配以及 JSON manifest 读写。默认组提取为相对路径第一串数字。以真实 LibriSpeech 根目录运行时，`train-clean-100/...` 的 251 人全部被合为键 `100`，实测只得 81 组，生成 train 57 组/32,251 条、val 12 组/792 条、test 12 组/819 条。通过 `python -m zonepick split --root data/raw/LibriSpeech/LibriSpeech --output <临时 manifest>` 复现相同条数。它还会重新分配官方 dev/test 的说话人。局部含数字的目录可能掩盖真实说话人 ID，按文件分配也可能造成跨集。AISHELL-3 官方命名的 train/test 实测已有 170 个共同说话人。相同路径的 manifest 可以覆盖，时间戳每次变化。零比例还可能被强制至少保留一组的逻辑覆盖。
- `assert_no_test_leak` 只比对给定字符串与 test 清单，已有单元测试。没有训练入口校验，也没有执行时绑定。无跨语言、噪声原始录音、车辆/路况、RIR 测量会话隔离实现。README 的“冻结”需要额外流程约束。演示引用官方 dev-clean，两条样例可用于功能验证。
- `compare` 只准备一次输入，`AlgorithmInput` 白名单含混合、采样率、阵列、参考索引和用户区域。正常插件的导向未用真值。冻结 dataclass 中的 NumPy 数组仍可原地修改，同进程插件共享它们，因此后续插件可受前一算法意外修改影响。Oracle 默认未注册，`compare` 并无按 `kind` 剔除逻辑。显式导入后调用当前普通入口会因无注入而失败。清单和导出的参考包含真值，供独立评测使用。
- `metrics.py` 的 SI-SDR、相对 identity 的 ΔSI-SDR、BSS-Eval 风格单干扰投影 SDR/SIR/SAR、RTF 和均值/总体标准差汇总已实现。其 SIR/SAR 中干扰参考只是一条区外语音，额外噪声进入残差。公式也存在近零残差给出极大 SAR 的现象，本轮 identity 约 321 dB。区域选择性仅为响应增益差函数，未建立工作台测量。STOI/PESQ 仅列可选指标，项目未调用。对空区域、同时多目标和全阵列统一参考的协议待定。
- `compare` manifest 记录场景、运行版本、部分噪声字段和指标，遗漏实际每算法参数、各输入内容校验、被抽取噪声片段与完整噪声配置。CLI `compare` 和 `main.py` 各自解析噪声开关。比较入口给插件空参数时不继承场景 `das` 的 FFT 或声速设定，传统 `run` 则会读取它们。比较实验需要明确记录这些差异。

##### 9. 可视化功能

`web/server.py` 和 `web/static/index.html` 含预设选择、二维和三维几何、拖动圆形区域、波形/频谱、试听、指标与对比页面。自定义场景 JSON 可写回配置目录。网页常规运行 POST 调用单区域 DAS，比较页读取已有多算法产物。一键入口退出后自动清理。

`python main.py` 在 `127.0.0.1` 临时端口启动，GET `/`、`/api/scenarios`、`/api/preview/free_field`、`/api/compare` 均为 200。独立 handler 实测对比详情和 `mvdr.wav` 均 200，POST `/api/runs` 返回 201 并输出真实 DAS 指标。实际浏览器绘制、旋转、拖动和播放器交互未验收。

##### 10. 与导师新要求之间的差距

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

##### 11. 已发现的 Bug 与科研风险

1. **高优先级 · 双源及真值语义。** `prepare_simulation`、`application.run`、`prepare_scenario` 的双源、区内一人、取第一路区外干扰限制阻塞主要科研任务。工作台还在校验 reference 索引前访问 components，坏索引可能先抛 `IndexError`。
2. **高优先级 · 噪声。** DNS 路径与旧 UrbanSound8K 分类规则不匹配。captured 提前降成单通道。参考通道与 SNR 标定不一致。详见第 7 节。
3. **高优先级 · MVDR 复现与稳定性。** 算法别名与 PSD 形式不匹配。静音实测奇异，贴近零功率、低秩矩阵、几何失配和混响有待覆盖。参数记录不足会影响复现。
4. **高优先级 · 退出清理。** `main.py` 向 `cleanup_generated` 同时传入当前运行目录和整个 `runs/compare`。若已有历史结果，默认退出会递归移除。函数也遍历项目的 `__pycache__` 和 `*.pyc`。本轮执行前确认 `runs/` 不存在。默认退出清理了本轮产物，并清除了项目预先存在的可重建字节码缓存。
5. **中优先级 · 网页测试与代理。** 原环境结果 36 passed / 4 failed。失败用例为 `test_compare_routes_list_detail_and_audio`、`test_post_runs_application_config_and_links_result`、`test_scenarios_and_preview_expose_geometry_and_region`、`test_unknown_scenario_and_bad_region_return_readable_error`。定位 `tests/test_zonepick.py::WebTests.request` 224/231 行，`urllib` 回环请求被代理处理，HTTP 错误体为空，`json.loads` 抛 `JSONDecodeError: Expecting value: line 1 column 1 (char 0)`。独立探测直接看到 HTTP 502。仅凭进程参数 `NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost` 复测为 **40 passed in 19.12s**。
6. **中优先级 · 环境与 Git 规则。** 实际版本低于声明，历史环境和数据描述混在当前部署文档。通用大文件和凭据文件的忽略覆盖存在空档。现有 CLI 的正确检查命令为 `python -m zonepick datasets`。`datasets-check` 会被 argparse 以 invalid choice 拒绝。

##### 12. 可以直接复用的代码

- `audio` 的解码、重采样、STFT/iSTFT 与 FLOAT WAV 写出，`simulation` 的逐源逐麦卷积与分量累加，`application.select_channels` 的通道映射。
- `regions.circle_members` 可继续用于诊断区域。`AlgorithmInput` 可作为显式推理边界。identity、DAS、几何 MVDR 可用作小场景传统对照。
- `runtime_metadata`、`workbench.splits` 的种子/组分配基本逻辑、`evaluation` 的信号投影评分和 Web 产物检查入口。使用现有测试夹具继续验证通道顺序、几何和参考口径。

##### 13. 后续建议检查和开发的事项

1. 先冻结数据来源、车内布置与通道映射证据，核对真实车辆 RIR、行驶/通风/风噪及许可证，并验证训练、验证和测试中的说话人、车型、会话及原始音轨分组。
2. 定义多人四区场景与标签合同、空区/多人同区处理、干声或参考麦声像的公平参考、五种配置配对比较条件。保持第五人归属、训练规模和验证方案开放。
3. 修通真实数据入口后建立数值基线，覆盖静音、零能量频点、强混响、阵列失配及多干扰。明确命名现有 MVDR，若比较 Souden 形式则记录目标和噪声 PSD 的估计方法与信息来源。将修正后的说话人分组在真实语料根目录上验证，避免使用演示 `dev-clean` 场景作为正式测试集。
4. 先统一产物清理范围、比较参数与数据哈希，再考虑批量生成和路线 B/C 训练接入，记录配置、提交、依赖、划分、权重、参考条件和聚合口径。

##### 14. 本轮实际修改的文件

- `.git/config` 写入本仓库级别提交者姓名和邮箱。
- `docs/PROJECT_AUDIT_2026-11-27.md` 新增，未暂存。
- 轻量运行的临时产物已清理。首次 pytest 使用了系统默认临时目录，复测显式将 TMPDIR 指到仓库内。一键入口也移除了项目已有的可重建 Python 字节码缓存，详见第 11 节。科研源码、现有暂存内容、数据、依赖及远端分支保持原状态。本轮没有提交或推送。

##### 15. 未完成或无法验证的事项

- GitHub HTTPS 写入需用户授权。SSH 探测超时。VS Code 本地与远程登录不能从当前终端判定。远端可读和提交身份均已验证。
- 当前没有真实车内场景、双语多人四区、五档实测阵列、混合/纯神经网络、训练及 DDP 集合通信闭环证据。实测 RIR 适配器只通过合成格式夹具。前端浏览器交互尚未实测。
- 原始数据归档完整性校验、DNS 子集的精确来源与版本、RIR 坐标配套及与车内条件的对应关系未验证。历史文档中的其他工作机数据可用性未归为当前机器事实。

### 2026-11-28｜数据资源整理与完整性验证

- 开始时工作区干净，本地与远端 `main` 同为 `9d7cd464e9484b95cfbbd9540c389bae9af71912`。复用现有数据和两个公共 DNS 软链接。环境见 [ENVIRONMENT.md](ENVIRONMENT.md)。
- CAVEMOVE 归档及说明与公布的 MD5 一致。Info-ZIP 6.00 报 3,318,804,110 extra bytes 和找不到中央目录，虽声明支持大文件与 ZIP64，仍未正确处理本包的 ZIP64 末尾偏移。现有 bsdtar 报 `Damaged Zip archive`。Python 3.10 `zipfile` 读出中央目录实际偏移 7,613,771,329、1483 成员及 8,695,241,895 展开字节。定位到 ZIP64 EOCD 与 locator 后通过全包 CRC，暂存解压并逐文件比较后发布。1438 个文件，1430 个 WAV 均可抽读，格式及分类见 [DATASETS.md](DATASETS.md)。
- McVAMPIRE 归档 111 个文件与解压实物逐字节一致。SoundFile 抽读 94 个 RIR 和 14 个噪声 WAV。SciPy 核对 MAT 结构，使用 LibriSpeech 短片段验证实测 RIR 卷积与同步多通道噪声。真实车厢预设完成 identity/DAS/MVDR 端到端对比。这一条短样例仅用于回归，旧两源指标不用于四区科研结论。
- LibriSpeech 实际 331 名说话人，官方 251/40/40，无共同身份。默认自定义划分 232/50/49 人，对应 23,613/5,251/4,998 条。AISHELL-3 实际 218 名，原始 train/test 共有 170 名。默认自定义划分 152/33/33 人，对应 61,771/13,369/12,895 条。内存划分与临时 CLI manifest 的统计一致，CLI 复写请求被拒绝。正式测试集尚未冻结。
- 本地噪声 17 组 272 路，RIR 36 个 WAV。两项公共数据的名称沿用本地标记，原始来源和登记版本继续待核实。
- 下载校验值、文件数量、有效根目录及各压缩包处置见 [DATASETS.md](DATASETS.md)。原始下载日志、PDF、说明和元数据保留。

- 逐个删除六份已验证的项目归档 `dev-clean.tar.gz`、`test-clean.tar.gz`、`In-Car_McVAMPIRE_V1.0.zip`、`cavemove_dataset.zip`、`train-clean-100.tar.gz`、`data_aishell3.tgz`。归档逻辑大小合计 33,999,159,516 B，释放已分配磁盘块 33,999,249,408 B（31.66 GiB，按删除前 `st_blocks × 512` 计算）。

### 2026-11-28｜B00 基础设施

对比工作台隔离每个算法的输入和监督真值。Oracle 由常规工作台拒绝运行。运行清单记录实际参数和噪声裁剪、通道、增益、种子与 SNR。几何导向矢量 MVDR 保留观测协方差和迹比例加载，零协方差频点用等权导向向量，病态矩阵用尺度归一后的有限额外加载。噪声归并到录音级并按参考通道标定总 SNR。常规运行使用唯一 ID 并保留，只有显式临时模式持有可清理目录。旧两源打分作为回归功能继续运行，统一四区评分遵循 [EVALUATION.md](EVALUATION.md)。

指定的 Planning with Files、Hindsight Coding Agent、Anti Defensive Writing 与 Shuorenhua 未在已安装 Skill 和仓库找到。复用本文件追踪状态与可重复步骤。Context7 核对了 SciPy `loadmat(simplify_cells=True)` 和 `resample_poly(axis=-1)`，实际执行版本为 1.15.3。

### 2026-11-28｜B01 四区空间建模

暂定车厢 1.6 × 2.8 × 1.4 m，x 左至右、y 前至后、z 底至顶。四区中线 x=0.8、y=1.4，线上点归右侧/后排。所有声源和麦克风在内域。统一配置供构建器、CLI 和 Web 数据接口使用。

| MIC 数 | 物理通道顺序 | 主观测 |
| ---: | --- | --- |
| 8 | M0 M1 M2 M3 M4 M5 M6 M7 | M0 |
| 6 | M0 M1 M2 M3 M4 M7 | M0 |
| 4 | M0 M3 M4 M7 | M0 |
| 3 | M0 M3 M8 | M0 |
| 2 | M9 M8 | M9 |

M9 与 M8 位于中轴，可观测到同一排左右镜像点的距离和传播时延相同。场景合同按固定区域求和，保留空区、同区多人、占用与语音活动及未归属声源。五布局共用主事件和场景 ID。公开推理对象只有观测与公开几何。跨 MIC 参考保留干净源、物理 MIC 参考和可选虚拟参考定义，虚拟点、延迟与主监督目标待验证。接口详见 [ARCHITECTURE.md](ARCHITECTURE.md)。

#### 验证结果

- 原始提交在 `zxw` 的 unittest 及隔离 pytest 中各通过 40 项。B00/B01 更新后，pytest 通过 59/59 项，包含真实 McVAMPIRE 短语音卷积、驾驶噪声及 CAVEMOVE 格式探测。最终一轮使用项目目录中的 pytest 与内存临时目录，11.57 s。
- 现有真实车厢预设 CLI 完成三种算法对比，配置与噪声信息保存于本地运行清单。正常五路输入的 MVDR 与历史实现最大绝对差为 `6.66e-16`，同时通过静音和无默认加载的秩亏 float32 用例。
- `main.py --temporary` 的本地 HTTP 冒烟测试覆盖几何和对比接口。停止后本次临时产物移除，运行前目录保持原状。测试另覆盖越界软链接及历史实验保护。
- 两份历史审计全文迁入此文件并按时间分段，移除不必要的服务器绝对路径。逐行核对 63 行与 173 行历史正文，下线原文件并检查全部项目文档的相对链接。

下一阶段 B02 实现车内声学仿真、RIR 生成和缓存，验证边界、传播时延、测量几何配准和虚拟参考的可行性。B05 的批量评测验收先于 B06。此轮保持小规模回归。
