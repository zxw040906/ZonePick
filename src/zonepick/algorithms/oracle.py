"""Oracle 诊断插件（可选导入）：使用真值做上界诊断，明确打标、排除排名。"""

import numpy as np

from zonepick.algorithms import Algorithm, AlgorithmInput, register
from zonepick.algorithms.base import FORBIDDEN_FIELDS


@register("oracle_target", kind="oracle")
class OracleTarget(Algorithm):
    """直接输出参考麦克风处的独立目标——理论 SI-SDR 上界，仅供诊断。"""

    def enhance(self, inp: AlgorithmInput) -> np.ndarray:
        # Oracle 通过外部注入的真值工作；普通 AlgorithmInput 不含这些字段。
        target = getattr(self, "_target", None)
        if target is None:
            raise RuntimeError("Oracle 插件只能由评测工作台注入真值后使用")
        return np.asarray(target, dtype=float)


# Oracle 插件声明：允许工作台通过受控通道注入真值字段，但算法注册类型为 oracle。
ORACLE_ALLOWED_FIELDS = FORBIDDEN_FIELDS
