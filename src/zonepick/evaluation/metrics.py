"""公平评价指标集合。

所有函数为零新依赖（numpy），输入均为单声道 [N]。
口径冻结：指标函数有独立单元测试（合成已知信号验证数值），避免评分口径漂移。
"""

import numpy as np

from zonepick.evaluation import si_sdr


def _vectors(estimate, target):
    e = np.asarray(estimate, dtype=float)
    t = np.asarray(target, dtype=float)
    if e.shape != t.shape or t.ndim != 1 or not t.size:
        raise ValueError("指标需要同长非空单通道")
    if not np.isfinite(e).all() or not np.isfinite(t).all():
        raise ValueError("指标输入须为有限值")
    return e, t


def _db(numerator, denominator):
    """返回 10log10(num/den)；定义不清时返回 None。"""
    if min(numerator, denominator) <= 0:
        return None
    return float(10 * (np.log10(numerator) - np.log10(denominator)))


def sd_sir_sar(estimate, target, interference):
    """BSS-Eval 风格分解：SDR / SIR / SAR（dB）。

    分解 e = s_target + e_interf + e_artif：
    - s_target：e 在目标方向上的投影；
    - e_interf：残差在（与目标正交化后的）干扰方向上的投影；
    - e_artif：剩余伪影。
    SDR 衡量总体失真，SIR 衡量残余干扰，SAR 衡量伪影/音乐噪声。
    """
    e, t = _vectors(estimate, target)
    i = np.asarray(interference, dtype=float)
    if i.shape != t.shape or not np.isfinite(i).all():
        raise ValueError("干扰参考须与目标同长且有限")
    power_t = np.dot(t, t)
    if power_t <= 0:
        return {"sdr_db": None, "sir_db": None, "sar_db": None}
    target_proj = (np.dot(e, t) / power_t) * t
    residual = e - target_proj
    # 将干扰正交化到目标子空间之外。
    interf_orth = i - (np.dot(i, t) / power_t) * t
    power_i = np.dot(interf_orth, interf_orth)
    if power_i <= 0:
        interf_proj = np.zeros_like(e)
    else:
        interf_proj = (np.dot(residual, interf_orth) / power_i) * interf_orth
    artif = residual - interf_proj
    p_target = np.dot(target_proj, target_proj)
    p_interf = np.dot(interf_proj, interf_proj)
    p_artif = np.dot(artif, artif)
    return {
        "sdr_db": _db(p_target, p_interf + p_artif),
        "sir_db": _db(p_target, p_interf),
        "sar_db": _db(p_target + p_interf, p_artif),
    }


def delta_si_sdr(estimate, target, baseline):
    """相对未增强基线的 SI-SDR 提升（dB）。"""
    out, base = si_sdr(estimate, target), si_sdr(baseline, target)
    if out is None or base is None:
        return None
    return out - base


def region_selectivity(target_response_db, interferer_response_db):
    """区域选择性（dB）：指向区内/区外的响应增益比。

    参数为算法对区内目标方向与区外干扰方向的响应增益（dB），
    由工作台用同一算法、把导向点分别指向两声源方向测得。
    """
    if target_response_db is None or interferer_response_db is None:
        return None
    return float(target_response_db - interferer_response_db)


def rtf(processing_seconds, audio_seconds):
    """实时因子：处理耗时 / 音频时长；小于 1 表示可实时。"""
    if not np.isfinite(processing_seconds) or not np.isfinite(audio_seconds) or audio_seconds <= 0:
        raise ValueError("RTF 需有限处理时长与正音频时长")
    return float(processing_seconds / audio_seconds)


def aggregate(values):
    """汇总一组数值：均值 ± 标准差（总体标准差），None 自动跳过。"""
    clean = [float(v) for v in values if v is not None and np.isfinite(v)]
    if not clean:
        return {"mean": None, "std": None, "count": 0}
    array = np.asarray(clean)
    return {"mean": float(array.mean()), "std": float(array.std()), "count": len(clean)}


def evaluate_all(estimate, target, baseline, interference, processing_seconds, audio_seconds):
    """计算单个算法的完整指标字典。"""
    e, t = _vectors(estimate, target)
    scores = {
        "si_sdr_db": si_sdr(e, t),
        "delta_si_sdr_db": delta_si_sdr(e, t, baseline),
    }
    scores.update(sd_sir_sar(e, t, interference))
    scores["rtf"] = rtf(processing_seconds, audio_seconds)
    return scores


OPTIONAL_METRICS = ("stoi", "pesq")
