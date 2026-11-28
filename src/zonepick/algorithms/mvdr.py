"""几何导向矢量 MVDR，协方差从观测估计。"""

import numpy as np

from zonepick.algorithms import Algorithm, AlgorithmInput, register
from zonepick.algorithms.classical import relative_delays
from zonepick.audio import analysis, synthesis


@register("mvdr", kind="classical")
class MvdrAlgorithm(Algorithm):
    """几何导向矢量 MVDR。"""

    def load(self, **params):
        self.n_fft = params.get("n_fft", 512)
        self.sound_speed = params.get("sound_speed", 343.0)
        self.diagonal_load = float(params.get("diagonal_load", 1e-2))
        self.cov_estimate = params.get("cov_estimate", "sample")
        self.noise_frame_quantile = float(params.get("noise_frame_quantile", 0.3))

        if type(self.n_fft) is not int or self.n_fft < 4 or self.n_fft % 2:
            raise ValueError("n_fft 须为不小于 4 的偶数")
        if not np.isfinite(self.sound_speed) or self.sound_speed <= 0:
            raise ValueError("sound_speed 须为正有限值")
        if not np.isfinite(self.diagonal_load) or self.diagonal_load < 0:
            raise ValueError("diagonal_load 须为非负有限值")
        if self.cov_estimate not in ("sample", "speech_absence"):
            raise ValueError("cov_estimate 须为 sample 或 speech_absence")
        if not 0.0 < self.noise_frame_quantile < 1.0:
            raise ValueError("noise_frame_quantile 须在 (0,1) 内")
        return self

    def parameters(self):
        return {key: getattr(self, key) for key in ("n_fft", "sound_speed", "diagonal_load",
                                                   "cov_estimate", "noise_frame_quantile")}

    def _noise_covariance(self, spectrum, frames):
        """从观测 STFT [M,F,T] 估计逐频协方差 [F,M,M]。

        spectrum[m,f,t]；默认全帧样本协方差，speech_absence 模式用低能量帧。
        """
        mics, freqs, _ = spectrum.shape
        selected = frames
        if self.cov_estimate == "speech_absence":
            power = np.sum(np.abs(spectrum) ** 2, axis=(0, 1))  # [T]
            threshold = np.quantile(power, self.noise_frame_quantile)
            selected = np.flatnonzero(power <= threshold)
            if selected.size < 2:
                selected = frames
        x = np.transpose(spectrum[:, :, selected], (1, 0, 2))  # [F,M,T']
        covariance = np.einsum("fmt,fnt->fmn", x, x.conj()) / selected.size
        # 对角加载：按每频平均功率比例，避免奇异矩阵。
        loading = self.diagonal_load * np.trace(covariance, axis1=1, axis2=2) / mics
        diagonal = np.arange(mics)
        covariance[:, diagonal, diagonal] += loading[:, None]
        return covariance

    def enhance(self, inp: AlgorithmInput) -> np.ndarray:
        mixture = np.asarray(inp.mixture, dtype=float)
        if mixture.ndim != 2 or not mixture.size or not np.isfinite(mixture).all():
            raise ValueError("混合音频须为非空有限 [M,N]")
        mics = np.asarray(inp.microphones, dtype=float)
        if mics.ndim != 2 or mics.shape[1] != 3 or mics.shape[0] != mixture.shape[0]:
            raise ValueError("麦克风坐标须与音频通道逐路对应 [M,3]")
        if type(inp.reference_channel) is not int or not 0 <= inp.reference_channel < mixture.shape[0]:
            raise ValueError("参考麦克风索引越界")

        # 导向矢量只来自用户区域（公开先验）+ 阵列几何，不使用真实声源位置。
        delays = relative_delays(inp.region.steering_point, mics,
                                 inp.reference_channel, self.sound_speed)
        frequencies, spectrum = analysis(mixture, inp.rate, self.n_fft)
        steering = np.exp(-2j * np.pi * frequencies[:, None] * delays[None, :])  # [F,M]

        covariance = self._noise_covariance(spectrum, np.arange(spectrum.shape[2]))

        # 逐频求解 w = Phi^{-1} d / (d^H Phi^{-1} d)，等价 w^H x。
        weights = np.empty_like(steering)
        for f in range(len(frequencies)):
            matrix = covariance[f]
            scale = np.max(np.abs(matrix))
            if scale == 0:
                weights[f] = steering[f] / len(mics)
                continue
            matrix = matrix / scale
            if np.linalg.cond(matrix) > 1e10:
                matrix += 1e-8 * np.eye(len(mics))
            inv_phi_d = np.linalg.solve(matrix, steering[f])
            weights[f] = inv_phi_d / np.vdot(steering[f], inv_phi_d)
        # 实值信号的 Nyquist 点只支持实权重。
        weights[-1] = weights[-1].real

        output = np.einsum("fm,mft->ft", weights.conj(), spectrum)
        return synthesis(output, inp.rate, self.n_fft, mixture.shape[-1])
