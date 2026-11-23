"""未处理基线：原样输出参考通道，作为所有相对提升的零点。"""

import numpy as np

from zonepick.algorithms import Algorithm, AlgorithmInput, register


@register("identity", kind="classical")
class IdentityAlgorithm(Algorithm):
    def enhance(self, inp: AlgorithmInput) -> np.ndarray:
        return np.asarray(inp.mixture[inp.reference_channel], dtype=float).copy()
