"""频域几何 DAS：适配为公平评测工作台的第一个传统算法插件。"""

import numpy as np

from zonepick.algorithms import Algorithm, AlgorithmInput, register
from zonepick.algorithms.classical import enhance as das_enhance


@register("das", kind="classical")
class DasAlgorithm(Algorithm):
    """已有 DAS 的插件包装；算法本体一行未改。"""

    def load(self, **params):
        self.n_fft = params.get("n_fft", 512)
        self.sound_speed = params.get("sound_speed", 343.0)
        if type(self.n_fft) is not int or self.n_fft < 4 or self.n_fft % 2:
            raise ValueError("n_fft 须为不小于 4 的偶数")
        if not np.isfinite(self.sound_speed) or self.sound_speed <= 0:
            raise ValueError("sound_speed 须为正有限值")
        return self

    def parameters(self):
        return {"n_fft": self.n_fft, "sound_speed": self.sound_speed}

    def enhance(self, inp: AlgorithmInput) -> np.ndarray:
        return das_enhance(
            inp.mixture, inp.rate, inp.microphones, inp.region.steering_point,
            inp.reference_channel, self.n_fft, self.sound_speed,
        )
