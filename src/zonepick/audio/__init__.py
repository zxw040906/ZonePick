"""音频边界统一使用浮点波形 [M,N]。"""

import numpy as np
from scipy import signal
import soundfile as sf


def read_audio(path):
    """读取 WAV/FLAC，返回 [M,N] 和采样率。"""
    frames, rate = sf.read(path, always_2d=True, dtype="float64")
    if not frames.size or not np.isfinite(frames).all():
        raise ValueError(f"音频为空或包含非有限值: {path}")
    return frames.T, rate


def write_audio(path, waveform, rate):
    """写出浮点 WAV，保留幅度和通道顺序。"""
    waveform = np.asarray(waveform)
    if waveform.ndim != 2 or not waveform.size or not np.isfinite(waveform).all():
        raise ValueError("波形须为非空有限 [M,N]")
    sf.write(path, waveform.T, rate, subtype="FLOAT")


def speech_segment(path, rate, length, offset=0):
    """读取单声道片段，重采样后按输出采样点截取并补零。"""
    from math import gcd

    if type(offset) is not int or type(length) is not int or offset < 0 or length <= 0:
        raise ValueError("片段起点须为非负整数，片段长度须为正整数")
    waveform, original_rate = read_audio(path)
    if waveform.shape[0] != 1:
        raise ValueError(f"声源音频须为单声道: {path}")
    speech = waveform[0]
    if rate != original_rate:
        divisor = gcd(rate, original_rate)
        speech = signal.resample_poly(speech, rate // divisor, original_rate // divisor)
    speech = speech[offset:offset + length]
    if not speech.size:
        raise ValueError(f"片段起点超出语音长度: {path}")
    return np.pad(speech, (0, length - speech.size))


def analysis(waveform, rate, n_fft):
    """沿末轴计算带补零的单边 STFT。"""
    if type(n_fft) is not int or n_fft < 4 or n_fft % 2:
        raise ValueError("FFT 窗必须为不小于 4 的偶数")
    waveform = np.asarray(waveform)
    if waveform.shape[-1] == 0:
        raise ValueError("音频不能为空")
    if waveform.shape[-1] < n_fft:
        padding = [(0, 0)] * (waveform.ndim - 1) + [(0, n_fft - waveform.shape[-1])]
        waveform = np.pad(waveform, padding)
    frequencies, _, spectrum = signal.stft(
        waveform, fs=rate, nperseg=n_fft, noverlap=n_fft // 2, boundary="zeros", padded=True
    )
    return frequencies, spectrum


def synthesis(spectrum, rate, n_fft, length):
    """使用匹配的窗与边界设置还原波形并裁到原长度。"""
    _, waveform = signal.istft(
        spectrum, fs=rate, nperseg=n_fft, noverlap=n_fft // 2, boundary=True
    )
    return waveform[..., :length]
