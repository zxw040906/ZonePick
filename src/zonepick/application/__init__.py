"""连接场景生成、独立推理和评价。"""

from datetime import datetime, timezone
from importlib.metadata import version
import json
from pathlib import Path
from shutil import which
from subprocess import run as run_command
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from uuid import uuid4

import numpy as np

from zonepick.algorithms.classical import enhance
from zonepick.application.datasets import require_dataset
from zonepick.audio import read_audio, speech_segment, write_audio
from zonepick.evaluation import si_sdr
from zonepick.regions import circle_members
from zonepick.simulation import free_field_rir, mix_sources
from zonepick.simulation import dechorate, mcvampire


def runtime_metadata():
    """记录依赖版本和本地源码的版本状态。"""
    metadata = {
        "python": sys.version.split()[0],
        "packages": {name: version(name) for name in ("numpy", "scipy", "soundfile", "h5py")},
    }
    checkout = Path(__file__).resolve().parents[3]
    if (checkout / ".git").exists() and which("git"):
        git = ["git", "--no-optional-locks", "-C", str(checkout)]
        revision = run_command(git + ["rev-parse", "HEAD"], capture_output=True, text=True)
        status = run_command(git + ["status", "--porcelain"], capture_output=True, text=True)
        if revision.returncode == 0:
            metadata["git_head"] = revision.stdout.strip()
        if status.returncode == 0:
            metadata["git_dirty"] = bool(status.stdout)
    return metadata


def select_channels(config, count):
    """返回合法的物理通道索引，顺序由配置指定。"""
    channels = config.get("channels", list(range(count)))
    if not channels or any(type(i) is not int or not 0 <= i < count for i in channels):
        raise ValueError(f"通道索引须为 0–{count - 1} 范围内的整数")
    if len(set(channels)) != len(channels):
        raise ValueError("通道索引不可重复")
    return channels


def prepare_simulation(config, datasets, speed):
    """生成两路独立声源、观测及所选阵列坐标。"""
    rate = config["sample_rate"]
    if type(rate) is not int or rate != 16000:
        raise ValueError("首版场景配置仅支持 16000 Hz")
    length = config["samples"]
    if type(length) is not int or length <= 0:
        raise ValueError("samples 须为正整数")
    inputs = config["sources"]
    if len(inputs) != 2:
        raise ValueError("仿真需要恰好两个声源")
    gains = [source.get("gain", 1.0) for source in inputs]
    if not np.isfinite(gains).all() or min(gains) <= 0:
        raise ValueError("语音增益须为正有限值")
    backend = config["backend"]
    if backend in ("dechorate", "mcvampire"):
        if "microphones" in config or any("position" in source for source in inputs):
            raise ValueError("实测场景不能覆盖声源或阵列位置")
        root = require_dataset(datasets, backend)
        if backend == "dechorate":
            channels = select_channels(config, 5)
            responses, microphones, positions = dechorate.load_measurement(root, config["array_id"], channels)
        else:
            channels = select_channels(config, 14)
            responses, microphones, positions = mcvampire.load_measurement(root, inputs, channels)
    else:
        positions = np.asarray([source["position"] for source in inputs], dtype=float)
        microphones = np.asarray(config["microphones"], dtype=float)
        channels = select_channels(config, len(microphones))
        microphones = microphones[channels]
        responses = [free_field_rir(point, microphones, rate, speed) for point in positions]

    speech_root = require_dataset(datasets, "librispeech")
    speech = [
        speech_segment(speech_root / source["file"], rate, length, source.get("offset", 0))
        for source in inputs
    ]
    mixture, components = mix_sources(speech, responses, gains)
    return mixture, components, microphones, positions, channels


def resolve_geometry(config, datasets):
    """只解析麦克风与声源坐标，供网页预览画区域使用。

    与 prepare_simulation 共用同一位置解析口径，但跳过语音读取、RIR 卷积与混音，
    因此可在用户画区域之前快速拿到实测场景的真实几何。返回纯 Python 列表，便于
    JSON 序列化；该几何仅用于可视化，绝不作为算法输入。
    """
    backend = config["backend"]
    inputs = config["sources"]
    if backend in ("dechorate", "mcvampire"):
        if "microphones" in config or any("position" in source for source in inputs):
            raise ValueError("实测场景不能覆盖声源或阵列位置")
        root = require_dataset(datasets, backend)
        if backend == "dechorate":
            channels = select_channels(config, 5)
            _, microphones, positions = dechorate.load_measurement(root, config["array_id"], channels)
        else:
            channels = select_channels(config, 14)
            _, microphones, positions = mcvampire.load_measurement(root, inputs, channels)
    elif backend == "free_field":
        positions = np.asarray([source["position"] for source in inputs], dtype=float)
        microphones = np.asarray(config["microphones"], dtype=float)
        channels = select_channels(config, len(microphones))
        microphones = microphones[channels]
    elif backend == "recording":
        microphones = np.asarray(config["microphones"], dtype=float)
        channels = select_channels(config, len(microphones))
        microphones = microphones[channels]
        positions = np.empty((0, 3), dtype=float)
    else:
        raise ValueError(f"未知场景模式: {backend}")
    return np.asarray(microphones, dtype=float).tolist(), np.asarray(positions, dtype=float).tolist()


def run(config, datasets, output_root=Path("runs")):
    """执行带参考仿真或仅观测推理，将结果写入独立运行目录。"""
    started = perf_counter()
    backend = config["backend"]
    if backend not in ("free_field", "dechorate", "mcvampire", "recording"):
        raise ValueError(f"未知场景模式: {backend}")
    options = config.get("das", {})
    speed = options.get("sound_speed", 343.0)
    n_fft = options.get("n_fft", 512)
    region = config["region"]
    point = [*region["center"], region["steering_height"]]
    rate = config["sample_rate"]
    if type(rate) is not int or rate <= 0:
        raise ValueError("采样率须为正整数")
    reference = config.get("reference_channel", 0)
    target = interference = None
    resolved = dict(config)
    if backend == "recording":
        mixture, actual_rate = read_audio(config["input_wav"])
        if rate != actual_rate:
            raise ValueError("输入 WAV 与配置采样率不一致")
        microphones = np.asarray(config["microphones"], dtype=float)
        if microphones.shape != (len(mixture), 3):
            raise ValueError("麦克风坐标须与输入音频逐路对应")
        channels = select_channels(config, len(mixture))
        mixture, microphones = mixture[channels], microphones[channels]
        circle_members(np.empty((0, 3)), region["center"], region["radius"])
    else:
        mixture, components, microphones, positions, channels = prepare_simulation(config, datasets, speed)
        members = circle_members(positions, region["center"], region["radius"])
        if members.sum() != 1:
            raise ValueError("首版带参考场景要求区域内恰好一个声源")
        resolved["resolved_source_positions"] = positions.tolist()

    if type(reference) is not int or not 0 <= reference < len(mixture):
        raise ValueError("参考麦克风须为所选通道内的有效整数索引")
    if backend != "recording":
        target = components[members, reference][0]
        interference = components[~members, reference][0]
        resolved["target_source_index"] = int(np.flatnonzero(members)[0])
        dataset_names = ("librispeech",) if backend == "free_field" else ("librispeech", backend)
        resolved["dataset_paths"] = {
            name: str(Path(datasets[name]).resolve()) for name in dataset_names
        }
    processing_start = perf_counter()
    enhanced = enhance(mixture, rate, microphones, point, reference, n_fft, speed)
    processing_seconds = perf_counter() - processing_start
    original = mixture[reference]
    scores = {
        "input_si_sdr_db": si_sdr(original, target) if target is not None else None,
        "output_si_sdr_db": si_sdr(enhanced, target) if target is not None else None,
        "reference_available": target is not None,
        "processing_seconds": processing_seconds,
        "setup_and_processing_seconds": perf_counter() - started,
        "steering_source": "user_region_center_and_height",
        "si_sdr_reference": "isolated_target_at_reference_mic" if target is not None else None,
    }

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:12]
    resolved.update(
        channels=channels, reference_channel=reference, resolved_microphones=microphones.tolist(),
        das={"n_fft": n_fft, "sound_speed": speed}, steering_point=point, run_id=run_id,
        runtime=runtime_metadata(),
    )
    outputs = {
        "mixture.wav": mixture, "reference_mic.wav": original[None], "enhanced.wav": enhanced[None],
    }
    if target is not None:
        outputs.update({"target.wav": target[None], "interference.wav": interference[None]})
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    directory = output_root / run_id
    with TemporaryDirectory(prefix=".pending-", dir=output_root) as temporary:
        staging = Path(temporary) / "result"
        staging.mkdir()
        for filename, waveform in outputs.items():
            write_audio(staging / filename, waveform, rate)
        for filename, payload in (("scenario.json", resolved), ("metrics.json", scores)):
            serialized = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
            (staging / filename).write_text(serialized + "\n", encoding="utf-8")
        staging.rename(directory)
    return directory, scores
