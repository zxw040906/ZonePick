"""同时间轴参考信号上的 SI-SDR。"""

import numpy as np


def si_sdr(estimate, target):
    """计算去均值的 SI-SDR。静音或无有限定义时返回 None。"""
    estimate, target = np.asarray(estimate), np.asarray(target)
    if estimate.shape != target.shape or target.ndim != 1 or not target.size:
        raise ValueError("SI-SDR 需要同长非空单通道")
    estimate = estimate - estimate.mean()
    target = target - target.mean()
    power = np.dot(target, target)
    if power <= 0:
        return None
    projection = np.dot(estimate, target) / power * target
    error = estimate - projection
    numerator = np.dot(projection, projection)
    denominator = np.dot(error, error)
    if min(numerator, denominator) <= 0:
        return None
    return float(10 * (np.log10(numerator) - np.log10(denominator)))
