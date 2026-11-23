"""真实感空间噪声注入（多类型、可复现、与语音源无关）。

噪声来源：
- UrbanSound8K：10 类环境音（街道、咖啡厅、车流、儿童、狗吠、空调、引擎……）；
- McVAMPIRE driving_noise：0/30/.../150 kph 车内行驶噪声，14 通道。

支持两种注入方式：
- diffuse：多个随机方向经自由场 RIR 卷积后叠加，形成空间扩散噪声；
- captured：McVAMPIRE 多通道实测噪声直接按参考通道对齐叠加。

噪声真值单独保存为分量，可从 SI-SDR 参考口径中排除（参考=独立混响目标）。
"""

from dataclasses import dataclass, field
from pathlib import Path
import re

import numpy as np
from scipy.signal import resample_poly

from zonepick.audio import read_audio
from zonepick.simulation import convolve, free_field_rir

DEFAULT_URBAN_ROOT = Path("/home/zxw/python_code/project/audio-ml-learning/data/UrbanSound8K/audio")
DEFAULT_DRIVING_ROOT = Path("/home/zxw/python_code/project/shared-datasets/McVAMPIRE/V1.0/driving_noise")

# UrbanSound8K 官方 10 类；类目来自 metadata 的 classID。
URBAN_CLASSES = {
    "air_conditioner": 0, "car_horn": 1, "children_playing": 2, "dog_bark": 3,
    "drilling": 4, "engine_idling": 5, "gun_shot": 6, "jackhammer": 7,
    "siren": 8, "street_music": 9,
}


@dataclass
class NoiseConfig:
    """噪声配置；所有维度均可通过参数调节。"""

    kinds: list = field(default_factory=lambda: ["urban", "driving"])
    urban_classes: list = field(default_factory=lambda: sorted(URBAN_CLASSES))
    urban_root: Path = DEFAULT_URBAN_ROOT
    driving_root: Path = DEFAULT_DRIVING_ROOT
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
        "snr_db", "max_sources", "spatial", "seed", "enabled",
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
        for path in sorted(Path(config.urban_root).rglob("*.wav")):
            match = re.match(r"\d+-(\d+)-", path.name)
            if match and int(match.group(1)) in [_class_id(c) for c in config.urban_classes]:
                files.append(path)
        if not files:
            raise ValueError(f"未找到 UrbanSound8K 噪声: {config.urban_root}")
        groups["urban"] = files
    if "driving" in config.kinds:
        files = [
            root for root in sorted(Path(config.driving_root).glob("*.wav"))
            if _speed(root) in config.driving_speeds
        ]
        if not files:
            raise ValueError(f"未找到行驶噪声: {config.driving_root}")
        groups["driving"] = files
    return groups


def _speed(path):
    match = re.match(r"(\d+)kph", path.name)
    return int(match.group(1)) if match else None


def _resample(waveform, src_rate, dst_rate):
    if src_rate == dst_rate:
        return waveform
    from math import gcd
    divisor = gcd(src_rate, dst_rate)
    return resample_poly(waveform, dst_rate // divisor, src_rate // divisor)


def _noise_at_mics(path, rate, length, microphones, spatial, rng, sound_speed=343.0):
    """把一个噪声文件渲染成 [M, length] 的多通道噪声。"""
    waveform, original_rate = read_audio(path)
    if waveform.shape[0] != 1:
        waveform = waveform[:1]  # driving_noise 为 14 通道，取第一路作空间扩散源
    source = _resample(waveform[0], original_rate, rate)
    if len(source) < length:
        source = np.tile(source, int(np.ceil(length / len(source))))
    start = int(rng.integers(0, max(1, len(source) - length)))
    segment = source[start:start + length]
    if len(segment) < length:
        segment = np.pad(segment, (0, length - len(segment)))
    if spatial == "captured" and waveform.shape[0] >= microphones.shape[0]:
        captured = np.stack([_resample(waveform[m], original_rate, rate)[start:start + length]
                             for m in range(microphones.shape[0])])
        return captured
    # 随机方向 + 自由场 RIR，形成空间扩散噪声（不以声源真值为方向）。
    angle = rng.uniform(0, 2 * np.pi)
    distance = rng.uniform(1.5, 4.0)
    point = np.array([
        microphones[:, 0].mean() + distance * np.cos(angle),
        microphones[:, 1].mean() + distance * np.sin(angle),
        float(rng.uniform(0.5, 2.0)),
    ])
    rir = free_field_rir(point, microphones, rate, sound_speed)
    return convolve(segment, rir)


def inject_noise(mixture, target, rate, microphones, config):
    """按 SNR 叠加多类型真实噪声，返回 (带噪混合, 噪声分量 [M,N])。

    target 为目标在参考通道的分量，用于确定噪声能量；噪声分量单独保存，
    使 SI-SDR 参考始终是"独立混响目标"，噪声作为干扰而非目标的一部分。
    """
    if not config.enabled:
        zeros = np.zeros_like(mixture)
        return mixture.copy(), zeros
    groups = list_noise_files(config)
    rng = np.random.default_rng(config.seed)
    length = mixture.shape[1]
    noise = np.zeros_like(mixture)
    target_power = np.dot(target, target)
    if target_power <= 0:
        raise ValueError("目标能量为零，无法确定噪声 SNR")
    sources = int(rng.integers(1, config.max_sources + 1))
    kinds = list(groups)
    for _ in range(sources):
        kind = kinds[int(rng.integers(0, len(kinds)))]
        path = groups[kind][int(rng.integers(0, len(groups[kind])))]
        rendered = _noise_at_mics(path, rate, length, microphones, config.spatial, rng)
        # 归一化：按目标参考通道能量与指定 SNR 决定该源增益。
        desired_power = target_power / (len(groups) * 10 ** (float(
            config.snr_db[0] + rng.uniform(0, config.snr_db[1] - config.snr_db[0])
        ) / 10))
        current = np.dot(rendered[0], rendered[0])
        if current > 0:
            noise += rendered * np.sqrt(desired_power / current)
    return mixture + noise, noise
