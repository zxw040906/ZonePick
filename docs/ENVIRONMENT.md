# ZonePick 开发环境

## 已验证的本地环境

2026-11-22 在本地 WSL2 复核。当前检查终端激活的是 Conda `base`，默认 `python` 为 3.13.9。以下项目解释器、软件包及 PyTorch 检测结果均通过 `conda run -n pytorch` 获取。GPU 驱动信息来自 WSL2 内的 `nvidia-smi`。

| 项目 | 实测结果 |
| --- | --- |
| 系统 | Ubuntu 26.04 LTS，WSL2 |
| 开发工具 | VS Code 1.138.0，Conda 25.11.1，Git 2.53.0 |
| 项目环境 | 已有 Conda `pytorch` |
| Python | 3.9.25 |
| PyTorch | 2.0.1 |
| PyTorch CUDA build | 11.8 |
| `torch.cuda.is_available()` | `True` |
| `torch.backends.cudnn.version()` | 8700 |
| GPU | NVIDIA GeForce RTX 3050 Ti Laptop GPU |
| 显存 | 4 GiB（`nvidia-smi` 显示 4096 MiB） |
| 驱动报告的 CUDA 支持版本 | 13.4 |

`torch.version.cuda` 表示 PyTorch 的构建版本。`nvidia-smi` 显示驱动报告的 CUDA 支持版本。本次终端的 PATH 未找到 `nvcc`，独立 CUDA Toolkit 安装情况仍待核实。

## 已确认的软件包

| 软件包 | 版本 |
| --- | --- |
| h5py | 3.14.0 |
| numpy | 1.24.4 |
| scipy | 1.13.1 |
| soundfile | 0.13.1 |
| torch | 2.0.1 |
| nara_wpe | 0.0.11 |
| tqdm | 4.70.1 |

上表是现有环境中已核实的部分包。ZonePick 的直接依赖、训练和网页的可选依赖及锁定策略随实现确认。

本次 `pip check` 再次报告 Triton 2.0.0 缺少 `cmake` 和 `lit`。此问题与 CUDA 可用性检查的结果分别记录，涉及 Triton 的实际工作流尚待验证。

## 开发方式与环境决策

在 VS Code 中通过 WSL 打开仓库，选择 Conda `pytorch` 的 Python 解释器，在 WSL 终端执行项目命令，并使用 Codex 协作开发。终端可以显式执行 `conda activate pytorch`，也可以保持当前环境并使用 `conda run -n pytorch`。Codex 云端可用于协作，正式运行和验证以本地 WSL2 及后续学校 GPU 服务器为准。

现阶段继续使用已有环境，保留当前 Python、PyTorch 和 CUDA 版本。现有版本已通过导入和 GPU 可用性检查，可以用于早期开发和小规模验证。遇到可复现的兼容问题、确需不兼容的新依赖，或学校服务器的软硬件条件要求迁移时，再评估独立环境。迁移前记录现有版本与结果，在候选环境核对依赖、GPU、基础音频流程及适用的推理和检查点兼容性，保留可回退的运行配置。

学校 GPU 服务器预计承担较大规模训练和批量实验。GPU 型号、驱动、可用的环境与调度方式、数据存储和访问条件均需在上机前核实。

## 验证命令

在 WSL 终端运行以下只读检查。首先确认终端的当前环境，再显式指定项目环境复核。

```bash
uname -r
cat /etc/os-release
printf '%s\n' "${CONDA_DEFAULT_ENV:-未激活}"
command -v python
python --version
conda --version
code --version
git --version
nvidia-smi
command -v nvcc
```

```bash
conda run -n pytorch python -B - <<'PY'
import sys
from importlib.metadata import version

import torch

print(sys.executable, sys.version)
for package in ("h5py", "numpy", "scipy", "soundfile", "torch", "nara_wpe", "tqdm", "triton"):
    print(package, version(package))
print("PyTorch:", torch.__version__)
print("CUDA build:", torch.version.cuda)
print("CUDA available:", torch.cuda.is_available())
print("cuDNN:", torch.backends.cudnn.version())
for index in range(torch.cuda.device_count()):
    gpu = torch.cuda.get_device_properties(index)
    print(gpu.name, gpu.total_memory, "bytes")
PY

conda run -n pytorch python -B -m pip check
```

核对 `sys.executable` 是否指向 `pytorch`，再比较版本和设备输出。`pip check` 当前预期会显式报告上述 Triton 依赖缺项，记录新增异常供后续排查。
