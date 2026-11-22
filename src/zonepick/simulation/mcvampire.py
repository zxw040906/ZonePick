"""In-Car McVAMPIRE V1.0 固定口部测点适配器。"""

from pathlib import Path

import numpy as np
from scipy.io import loadmat
from scipy.signal import resample_poly

from zonepick.audio import read_audio


def load_measurement(root, selections, channels):
    """读取口部测点的 16 kHz RIR、麦克风坐标和近似声学参考点。"""
    root = Path(root)
    geometry = loadmat(root / "geometry.mat", simplify_cells=True)
    microphones = np.asarray([mic["pos"] for mic in geometry["mic"]], dtype=float)
    mouths = geometry["mouth"]
    if microphones.shape != (14, 3) or len(mouths) != 8 or not np.isfinite(microphones).all():
        raise ValueError("McVAMPIRE V1.0 几何须包含 14 支麦克风和 8 个口部中心")

    responses, positions = [], []
    for selection in selections:
        seat, azimuth = selection["seat"], selection["azimuth"]
        if type(seat) is not int or not 1 <= seat <= 8 or type(azimuth) is not int:
            raise ValueError("McVAMPIRE 座位须为 1–8，朝向须为测量中的整数度数")
        mouth = mouths[seat - 1]
        center = np.asarray(mouth["centerpos"], dtype=float)
        directions = np.asarray(mouth["orientations_XYZ"], dtype=float)
        angles = np.asarray(mouth["orientations_AzEl"])
        if center.shape != (3,) or directions.shape != (11, 3) or angles.shape != (11, 2):
            raise ValueError("McVAMPIRE 口部坐标或朝向元数据维度异常")
        matches = np.flatnonzero((angles[:, 0] == azimuth) & (angles[:, 1] == 0))
        if len(matches) != 1:
            raise ValueError(f"McVAMPIRE 座位 {seat} 无唯一的 {azimuth}° 实测朝向")
        direction = directions[matches[0]]
        if not np.isfinite(center).all() or not np.isclose(np.linalg.norm(direction), 1):
            raise ValueError("McVAMPIRE 口部坐标或朝向无效")
        waveform, rate = read_audio(root / "ir" / f"ir_mouth_pos{seat}_{azimuth}.wav")
        if rate != 24000 or waveform.shape != (14, 2040):
            raise ValueError("McVAMPIRE V1.0 口部 RIR 须为 24 kHz、14 通道、2040 点")
        responses.append(resample_poly(waveform[channels], 2, 3, axis=-1))
        positions.append(center + 0.07 * direction)
    return responses, microphones[channels], np.stack(positions)
