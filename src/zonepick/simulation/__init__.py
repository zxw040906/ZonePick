"""自由场传播和逐通道声学混合。"""

import numpy as np
from scipy.signal import fftconvolve


def distances(point, microphones):
    """返回源到各麦克风的距离，单位为米。"""
    point = np.asarray(point, dtype=float)
    microphones = np.asarray(microphones, dtype=float)
    if point.shape != (3,) or microphones.ndim != 2 or microphones.shape[1] != 3 or not len(microphones):
        raise ValueError("点和阵列坐标须为 [3] 与 [M,3]")
    result = np.linalg.norm(microphones - point, axis=1)
    if not np.isfinite(result).all():
        raise ValueError("坐标与距离须为有限值")
    return result


def propagation_seconds(point, microphones, sound_speed=343.0):
    """返回绝对传播时间，单位为秒。"""
    if not np.isfinite(sound_speed) or sound_speed <= 0:
        raise ValueError("声速须为正有限值")
    return distances(point, microphones) / sound_speed


def free_field_rir(point, microphones, rate, sound_speed):
    """生成带线性分数采样延迟和 1/r 衰减的自由场 RIR。"""
    samples = propagation_seconds(point, microphones, sound_speed) * rate
    meters = samples * sound_speed / rate
    if np.any(meters < 0.01):
        raise ValueError("自由场声源与麦克风须相距至少 0.01 米")
    start = np.floor(samples).astype(int)
    fraction = samples - start
    rir = np.zeros((len(start), int(start.max()) + 2))
    channels = np.arange(len(start))
    rir[channels, start] = (1 - fraction) / meters
    rir[channels, start + 1] = fraction / meters
    return rir


def convolve(speech, rir):
    """将单声道 [N] 与 RIR [M,L] 卷积，保留前 N 点。"""
    speech, rir = np.asarray(speech), np.asarray(rir)
    if speech.ndim != 1 or rir.ndim != 2 or not speech.size or not rir.size:
        raise ValueError("卷积需要非空的语音 [N] 和 RIR [M,L]")
    return fftconvolve(speech[None, :], rir, axes=-1)[:, :speech.size]


def mix_sources(speech, responses, gains):
    """返回混合 [M,N] 与按声源排列的分量 [S,M,N]。"""
    if not len(speech) or len(speech) != len(responses) or len(speech) != len(gains):
        raise ValueError("每个声源须有对应的语音、RIR 和增益")
    components = np.stack([
        gain * convolve(waveform, rir)
        for waveform, rir, gain in zip(speech, responses, gains)
    ])
    return components.sum(axis=0), components
