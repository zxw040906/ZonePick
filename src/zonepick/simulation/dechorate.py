"""dEchorate 固定测点适配器。"""

from pathlib import Path

import h5py
import numpy as np
from scipy.signal import resample_poly


def load_measurement(root, array_id, channels):
    """读取两个固定测点的 16 kHz RIR 与匹配的坐标。"""
    if not 1 <= array_id <= 6:
        raise ValueError("dEchorate 阵列编号须为 1–6")
    first = (array_id - 1) * 5 + 1
    responses, sources = [], []
    microphones = None
    for source_id in (1, 2):
        path = Path(root) / (
            f"dEchorate_room000000_src{source_id}_arr{array_id}_mics{first}-{first + 4}.sofa"
        )
        with h5py.File(path, "r") as measurement:
            rate = np.asarray(measurement["Data.SamplingRate"]).flat[0]
            ir = np.asarray(measurement["Data.IR"])
            coords = np.asarray(measurement["ReceiverPosition"]).squeeze()
            source = np.asarray(measurement["SourcePosition"]).squeeze()
        if rate != 48000 or ir.shape != (1, 5, 48000) or coords.shape != (5, 3) or source.shape != (3,):
            raise ValueError(f"dEchorate 测量格式不符合固定预设: {path}")
        if microphones is not None and not np.allclose(microphones, coords):
            raise ValueError("两份实测 RIR 的麦克风坐标或顺序不一致")
        microphones = coords
        responses.append(resample_poly(ir[0, channels], 1, 3, axis=-1))
        sources.append(source)
    return responses, microphones[channels], np.stack(sources)
