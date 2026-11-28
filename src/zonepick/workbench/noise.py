"""按录音组织噪声，并在参考通道上标定叠加后的 SNR。"""

from dataclasses import dataclass, field, replace
from pathlib import Path
import re

import numpy as np
from scipy.signal import resample_poly

from zonepick.audio import read_audio
from zonepick.simulation import convolve, free_field_rir

# UrbanSound8K 官方 10 类；类目来自 metadata 的 classID。
URBAN_CLASSES = {
    "air_conditioner": 0, "car_horn": 1, "children_playing": 2, "dog_bark": 3,
    "drilling": 4, "engine_idling": 5, "gun_shot": 6, "jackhammer": 7,
    "siren": 8, "street_music": 9,
}


@dataclass
class NoiseConfig:
    """噪声配置；所有维度均可通过参数调节。"""

    kinds: list = field(default_factory=lambda: ["dns_noise", "driving"])
    urban_classes: list = field(default_factory=lambda: sorted(URBAN_CLASSES))
    urban_root: Path = None
    dns_root: Path = None
    driving_root: Path = None
    captured_channels: tuple = ()
    driving_speeds: list = field(default_factory=lambda: [0, 40, 80, 120])
    snr_db: tuple = (5.0, 20.0)          # 相对目标能量的信噪比范围（均匀分布）
    max_sources: int = 3                 # 每次注入最多叠加几个噪声源
    spatial: str = "diffuse"             # diffuse | captured
    seed: int = 0
    enabled: bool = False


def noise_config_from_hint(hint, override_enabled=None):
    """把场景中的 noise_hint 字典转成 NoiseConfig；未知字段忽略。

    override_enabled 显式给定时优先（例如命令行 --noise），否则用 hint.enabled。
    """
    hint = hint or {}
    allowed = {
        "kinds", "urban_classes", "urban_root", "driving_root", "driving_speeds",
        "snr_db", "max_sources", "spatial", "seed", "enabled", "dns_root", "captured_channels",
    }
    values = {key: value for key, value in hint.items() if key in allowed}
    if "urban_root" in values:
        values["urban_root"] = Path(values["urban_root"])
    if "driving_root" in values:
        values["driving_root"] = Path(values["driving_root"])
    if "snr_db" in values:
        values["snr_db"] = tuple(values["snr_db"])
    if override_enabled is not None:
        values["enabled"] = bool(override_enabled)
    return NoiseConfig(**values)


def _class_id(name):
    if isinstance(name, int):
        return name
    if name not in URBAN_CLASSES:
        raise ValueError(f"未知 UrbanSound8K 类别: {name}")
    return URBAN_CLASSES[name]


def list_noise_files(config):
    """列出候选噪声文件，按类型分组。"""
    groups = {}
    if "urban" in config.kinds:
        files = []
        for path in sorted(Path(config.urban_root or "data/raw/UrbanSound8K").rglob("*.wav")):
            match = re.match(r"\d+-(\d+)-", path.name)
            if match and int(match.group(1)) in [_class_id(c) for c in config.urban_classes]:
                files.append(path)
        if not files:
            raise ValueError(f"未找到 UrbanSound8K 噪声: {config.urban_root}")
        groups["urban"] = files
    if "driving" in config.kinds:
        files = [
            root for root in sorted(Path(config.driving_root or "data/raw/McVAMPIRE/driving_noise").glob("*.wav"))
            if _speed(root) in config.driving_speeds
        ]
        if not files:
            raise ValueError(f"未找到行驶噪声: {config.driving_root}")
        groups["driving"] = files
    if "dns_noise" in config.kinds:
        groups["dns_noise"] = list_local_recordings(config.dns_root or "data/raw/DNS_noise/noise_17class")
    if set(config.kinds) != set(groups):
        raise ValueError("Unknown noise source")
    return groups


def _speed(path):
    match = re.match(r"(\d+)kph", path.name)
    return int(match.group(1)) if match else None


@dataclass(frozen=True)
class LocalNoiseRecording:
    noise_recording_id: str
    paths: tuple
    channel_ids: tuple = tuple(f"ch{i:02d}" for i in range(1, 17))


def list_local_recordings(root):
    root = Path(root)
    channels = {}
    for path in sorted(root.rglob("ch*.wav")):
        if re.fullmatch(r"ch(?:0[1-9]|1[0-6])", path.stem):
            channels.setdefault(path.parent, {})[path.stem] = path
    recordings = []
    for directory, paths in channels.items():
        if len(paths) != 16:
            raise ValueError(f"Incomplete 16-channel noise recording: {directory}")
        recordings.append(LocalNoiseRecording(
            f"dns_noise:{directory.relative_to(root).as_posix()}",
            tuple(paths[key] for key in sorted(paths)),
        ))
    if not recordings:
        raise ValueError(f"No local 16-channel recordings: {root}")
    return recordings


def configure_noise(config, datasets, backend, channels):
    """由所选数据集解析目录，实测车厢复用同一测量通道编号。"""
    driving_root = datasets.get("mcvampire")
    measured_directory = Path(driving_root) / "driving_noise" if driving_root else None
    driving = config.driving_root or measured_directory
    captured = config.captured_channels
    known_mapping = (backend == "mcvampire" and config.kinds == ["driving"]
                     and measured_directory is not None and Path(driving).resolve() == measured_directory.resolve())
    if config.spatial == "captured" and known_mapping:
        if captured and tuple(captured) != tuple(channels):
            raise ValueError("Captured mapping does not match McVAMPIRE physical channels")
        captured = tuple(channels)
    elif config.spatial == "captured" and len(config.kinds) != 1:
        raise ValueError("Captured noise requires one explicitly mapped dataset")
    roots = {"dns_noise": config.dns_root or datasets.get("dns_noise"),
             "urban": config.urban_root or datasets.get("urbansound8k"), "driving": driving}
    for kind in config.kinds:
        if not roots.get(kind):
            raise ValueError(f"Configure an enabled dataset or an explicit noise directory for {kind}")
    return replace(
        config,
        dns_root=roots["dns_noise"],
        urban_root=roots["urban"],
        driving_root=driving,
        captured_channels=captured,
    )


def _noise_at_mics(resource, kind, rate, length, microphones, config, rng):
    if isinstance(resource, LocalNoiseRecording):
        tracks = [read_audio(path) for path in resource.paths]
        original_rate = tracks[0][1]
        if any(track.shape != tracks[0][0].shape or track.shape[0] != 1
               or source_rate != original_rate for track, source_rate in tracks):
            raise ValueError("Local recording channels must have equal length, rate and one channel per file")
        waveform = np.concatenate([track for track, _ in tracks])
        recording_id = resource.noise_recording_id
        channels = resource.channel_ids
    else:
        waveform, original_rate = read_audio(resource)
        recording_id = f"{kind}:{resource.stem}"
        channels = tuple(range(len(waveform)))
    if config.spatial == "captured":
        indices = tuple(config.captured_channels)
        if (len(indices) != len(microphones) or any(type(i) is not int for i in indices)
                or len(set(indices)) != len(indices) or any(not 0 <= i < len(channels) for i in indices)):
            raise ValueError("Captured noise requires an explicit valid channel mapping")
    else:
        indices = (0,)
    from math import gcd
    divisor = gcd(original_rate, rate)
    samples = resample_poly(waveform[list(indices)], rate // divisor, original_rate // divisor, axis=-1)
    if not samples.shape[-1]:
        raise ValueError("Empty noise recording")
    repeats = max(1, int(np.ceil(length / samples.shape[-1])))
    repeated = np.tile(samples, (1, repeats))
    start = int(rng.integers(0, repeated.shape[-1] - length + 1))
    segment = repeated[:, start:start + length]
    origin = {"dns_noise": "unverified_local_collection", "driving": "McVAMPIRE",
              "urban": "UrbanSound8K"}[kind]
    metadata = {"noise_recording_id": recording_id, "origin": origin,
                "channel_ids": [channels[index] for index in indices],
                "start_resampled_sample": start, "sample_rate": rate, "source_sample_rate": original_rate,
                "source_frames": waveform.shape[-1], "repeats": repeats,
                "rendering": "measured_channels" if config.spatial == "captured" else "simulated_free_field"}
    if config.spatial == "captured":
        return segment, metadata
    angle = rng.uniform(0, 2 * np.pi)
    distance = rng.uniform(1.5, 4.0)
    point = np.array([
        microphones[:, 0].mean() + distance * np.cos(angle),
        microphones[:, 1].mean() + distance * np.sin(angle),
        rng.uniform(0.5, 2.0),
    ])
    metadata["render_position"] = point.tolist()
    return convolve(segment[0], free_field_rir(point, microphones, rate, 343.0)), metadata


def inject_noise(mixture, target, rate, microphones, config, *, reference_channel=0, metadata=None):
    """将总噪声相对给定参考语音标定，保留同步多通道。"""
    if not config.enabled:
        return mixture.copy(), np.zeros_like(mixture)
    mixture, target = np.asarray(mixture), np.asarray(target, dtype=float)
    microphones = np.asarray(microphones, dtype=float)
    if (mixture.ndim != 2 or microphones.shape != (len(mixture), 3) or not mixture.size
            or target.shape != (mixture.shape[1],)):
        raise ValueError("Expected [M,T] mixture, [M,3] microphones and [T] reference")
    if (config.spatial not in ("diffuse", "captured")
            or type(config.max_sources) is not int or config.max_sources < 1
            or type(reference_channel) is not int or not 0 <= reference_channel < len(mixture)):
        raise ValueError("Invalid noise configuration")
    low, high = config.snr_db
    if not np.isfinite([low, high]).all() or low > high:
        raise ValueError("Invalid noise SNR range")
    groups = list_noise_files(config)
    if not groups:
        raise ValueError("No noise sources configured")
    rng = np.random.default_rng(config.seed)
    target_power = np.dot(target, target)
    if not np.isfinite(target_power) or target_power <= 0:
        raise ValueError("Reference speech must have positive finite energy")
    noise = np.zeros_like(mixture, dtype=float)
    records = []
    kinds = list(groups)
    for _ in range(rng.integers(1, config.max_sources + 1)):
        kind = rng.choice(kinds)
        resources = groups[kind]
        resource = resources[rng.integers(len(resources))]
        rendered, record = _noise_at_mics(resource, kind, rate, mixture.shape[1], microphones, config, rng)
        noise += rendered
        records.append(record)
    snr = float(rng.uniform(low, high))
    power = np.dot(noise[reference_channel], noise[reference_channel])
    if not np.isfinite(power) or power <= 0:
        raise ValueError("Rendered noise must have positive finite reference energy")
    gain = float(np.sqrt(target_power / power * 10 ** (-snr / 10)))
    noise *= gain
    if metadata is not None:
        metadata.update(snr_db=snr, reference_channel=reference_channel,
                        reference_definition="provided_speech_at_reference_channel",
                        recordings=[dict(record, gain=gain) for record in records], seed=config.seed)
    return mixture + noise, noise
