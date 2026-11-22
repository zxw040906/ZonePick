"""使用阵列几何与区域代表点的频域 DAS。"""

import numpy as np

from zonepick.audio import analysis, synthesis
from zonepick.simulation import propagation_seconds


def relative_delays(point, microphones, reference, sound_speed=343.0):
    """计算相对于参考麦克风的延迟，晚到达为正。"""
    arrival = propagation_seconds(point, microphones, sound_speed)
    if not 0 <= reference < len(arrival):
        raise ValueError("参考麦克风索引越界")
    return arrival - arrival[reference]


def das_weights(frequencies, delays):
    """从含 Nyquist 点的单边 FFT 频率 [F] 和秒延迟 [M] 生成权重 [F,M]。"""
    steering = np.exp(-2j * np.pi * frequencies[:, None] * delays[None, :])
    weights = steering / delays.size
    # 实值信号的 Nyquist 点只支持实权重。
    weights[-1] = weights[-1].real
    return weights


def enhance(mixture, rate, microphones, point, reference, n_fft=512, sound_speed=343.0):
    """从混合观测和用户指定代表点生成单通道 [N]。"""
    mixture = np.asarray(mixture)
    if mixture.ndim != 2 or not mixture.size or not np.isfinite(mixture).all():
        raise ValueError("混合音频须为非空有限 [M,N]")
    delays = relative_delays(point, microphones, reference, sound_speed)
    if len(delays) != mixture.shape[0]:
        raise ValueError("麦克风坐标数与音频通道数不一致")
    frequencies, spectrum = analysis(mixture, rate, n_fft)
    weights = das_weights(frequencies, delays)
    output = np.einsum("fm,mft->ft", weights.conj(), spectrum)
    return synthesis(output, rate, n_fft, mixture.shape[-1])
