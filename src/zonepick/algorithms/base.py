"""算法插件接口：算法唯一可见的输入对象与注册表。

公平性设计要点：
1. AlgorithmInput 是 frozen 数据对象，字段集合就是"算法允许知道的信息"白名单。
   它不含真实声源位置、干净目标、干扰、理想掩码、SNR、种子或噪声配置。
   阵列几何和用户选的区域是公开先验，属于合法信息。
2. 类式接口 load()/enhance() 兼容传统 DSP 与需要权重的神经网络；
   神经网络插件 load() 加载模型、enhance() 做推理，无需改动应用层。
3. kind="oracle" 的插件可用真值做诊断，但必须显式打标，排除在正常排名之外。
4. 非 oracle 算法只能拿到 AlgorithmInput，配合防泄漏测试保证推理波形与真值无关。
"""

from dataclasses import dataclass
from typing import Any, Dict

import numpy as np

_REGISTRY: Dict[str, type] = {}


@dataclass(frozen=True)
class Region:
    """用户选择的区域（二维圆心 + 半径 + 指向高度），公开先验。"""

    center: np.ndarray  # [2]
    radius: float
    steering_height: float

    @property
    def steering_point(self) -> np.ndarray:
        """频域导向点 [3]，完全由用户区域确定性推出。"""
        return np.array([self.center[0], self.center[1], self.steering_height], dtype=float)


@dataclass(frozen=True)
class AlgorithmInput:
    """算法可见输入的白名单。禁止字段由结构测试守护。"""

    mixture: np.ndarray       # [M, N] 已对齐、已重采样的观测
    rate: int
    microphones: np.ndarray   # [M, 3] 阵列几何（公开先验）
    reference_channel: int
    region: Region            # 用户区域（公开先验）


FORBIDDEN_FIELDS = frozenset({
    "target", "interference", "sources", "source_positions", "ideal_mask",
    "snr", "noise", "seed", "members", "clean", "reference_audio",
})


class Algorithm:
    """算法插件基类；子类实现 load()/enhance()。"""

    name: str = ""
    kind: str = "classical"  # classical | hybrid | neural | oracle

    def load(self, **params) -> "Algorithm":
        """加载配置/权重并返回自身；无状态算法直接返回 self。"""
        return self

    def parameters(self) -> dict:
        """Return resolved run parameters for the experiment manifest."""
        return {}

    def enhance(self, inp: AlgorithmInput) -> np.ndarray:
        """从受限输入生成参考通道域单声道 [N]。"""
        raise NotImplementedError


def register(name: str, kind: str = "classical"):
    """注册算法插件类的装饰器。"""
    def decorate(cls):
        if not isinstance(name, str) or not name:
            raise ValueError("算法名须为非空字符串")
        if kind not in ("classical", "hybrid", "neural", "oracle"):
            raise ValueError(f"未知算法类型: {kind}")
        if name in _REGISTRY:
            raise ValueError(f"算法已注册: {name}")
        cls.name = name
        cls.kind = kind
        _REGISTRY[name] = cls
        return cls
    return decorate


def get_algorithm(name: str, **params) -> Algorithm:
    """按名称实例化并加载参数。"""
    if name not in _REGISTRY:
        raise ValueError(f"未知算法: {name}（已注册: {sorted(_REGISTRY)}）")
    instance = _REGISTRY[name]()
    return instance.load(**params)


def algorithm_names() -> list:
    """返回已注册算法名（排序）。"""
    return sorted(_REGISTRY)


def registered_classes() -> Dict[str, type]:
    """返回注册表副本，供防泄漏测试遍历。"""
    return dict(_REGISTRY)


def ensure_no_forbidden_fields() -> None:
    """结构防泄漏：AlgorithmInput 不得包含真值字段。"""
    leaked = FORBIDDEN_FIELDS.intersection(AlgorithmInput.__dataclass_fields__)
    if leaked:
        raise RuntimeError(f"AlgorithmInput 泄漏真值字段: {sorted(leaked)}")
