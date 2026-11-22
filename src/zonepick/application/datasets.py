"""从项目工作目录解析数据配置，并抽查本地格式。"""

import json
import os
from pathlib import Path

import soundfile as sf

from zonepick.simulation.dechorate import load_measurement
from zonepick.simulation import mcvampire


def read_mapping(path):
    """读取 JSON 语法的配置对象。"""
    with Path(path).open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"配置顶层必须为对象: {path}")
    return value


def dataset_paths(config=None):
    """显式配置优先，其次本地文件，最后使用示例和已有环境变量。"""
    local = Path("configs/local/datasets.yaml")
    selected = Path(config) if config else local
    use_defaults = config is None and not local.is_file()
    if use_defaults:
        selected = Path("configs/datasets.example.yaml")
    entries = read_mapping(selected)
    old_root = os.getenv("AUDIO_LEARNING_DATA")
    if use_defaults and old_root:
        entries["librispeech"]["path"] = str(Path(old_root) / "LibriSpeech")
        entries["dechorate"]["path"] = str(Path(old_root) / "dEchorate" / "rir")
    return {
        name: Path(os.path.expandvars(entry["path"])).expanduser()
        for name, entry in entries.items() if entry.get("enabled", True)
    }


def require_dataset(paths, name):
    """返回已启用且存在的数据目录。"""
    root = paths.get(name)
    if root is None or not root.is_dir():
        raise ValueError(f"数据集 {name} 不可用（目录 {root}），请检查 configs/local/datasets.yaml 或 --datasets")
    return root


def inspect_datasets(paths):
    """抽查一个实际音频或一组 SOFA，输出可用性及格式。"""
    report = {}
    for name in ("librispeech", "dechorate", "mcvampire", "cavemove"):
        root = paths.get(name)
        result = {"path": str(root) if root else None, "enabled": root is not None, "available": False}
        try:
            root = require_dataset(paths, name)
            if name == "dechorate":
                load_measurement(root, 1, [0, 1, 2, 3, 4])
                result.update(format="SOFA/HDF5", sample_rate=48000, channels=5)
            elif name == "mcvampire":
                mcvampire.load_measurement(root, [{"seat": 1, "azimuth": 0}], list(range(14)))
                result.update(sample="ir/ir_mouth_pos1_0.wav", format="WAV",
                              sample_rate=24000, channels=14)
            else:
                suffix = "*.flac" if name == "librispeech" else "*.wav"
                sample = next((p for p in root.rglob(suffix) if p.is_file()), None)
                if sample is None:
                    raise ValueError(f"未找到 {suffix} 样例")
                info = sf.info(sample)
                result.update(sample=str(sample.relative_to(root)), format=info.format,
                              sample_rate=info.samplerate, channels=info.channels)
                if not info.frames or (name == "librispeech" and
                                       (info.channels != 1 or info.samplerate != 16000)):
                    raise ValueError("样例音轨格式不符合预期")
                if name == "cavemove" and (info.channels != 8 or info.samplerate != 16000):
                    raise ValueError("CAVEMOVE 样例须为 16 kHz 八通道 WAV")
            result["available"] = True
        except (OSError, ValueError, RuntimeError, KeyError) as error:
            result["reason"] = str(error)
        report[name] = result
    return report
