"""公平评测工作台的编排：准备一次 → 多算法推理 → 统一评分 → 对比。

核心公平性保证：
1. prepare_scenario 只做一次（仿真/噪声/RIR/混合固定），所有算法拿到逐样本相同的 mixture；
2. apply_algorithm 只把 AlgorithmInput 白名单交给算法，真值（目标/干扰/声源位置/噪声）不进入推理；
3. evaluate 对同一份参考计算所有指标；identity（未处理）作为统一基线；
4. 每次对比写出独立目录，含 manifest，记录数据路径、种子与算法参数，结果可复现。

本模块不修改 application.run 的任何行为，纯新增。
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from uuid import uuid4

import numpy as np

from zonepick.algorithms import AlgorithmInput, Region, get_algorithm
from zonepick.algorithms.base import ensure_no_forbidden_fields, registered_classes
from zonepick.application import prepare_simulation, runtime_metadata, select_channels
from zonepick.audio import read_audio, write_audio
from zonepick.evaluation import si_sdr
from zonepick.evaluation.metrics import aggregate, evaluate_all
from zonepick.regions import circle_members
from zonepick.workbench.noise import NoiseConfig, configure_noise, inject_noise


@dataclass
class ScenarioBundle:
    """一次准备得到的固定输入与私有真值。

    只有 mixture/rate/microphones/reference_channel/region 会进入 AlgorithmInput；
    target/interference/positions 等字段仅供评分，算法永远看不到。
    """

    mixture: np.ndarray
    rate: int
    microphones: np.ndarray
    reference_channel: int
    region: Region
    config: dict
    target: np.ndarray = None
    interference: np.ndarray = None
    positions: np.ndarray = None
    noise_component: np.ndarray = None
    channels: list = field(default_factory=list)
    resolved: dict = field(default_factory=dict)

    def public_input(self) -> AlgorithmInput:
        """构造算法唯一可见的输入（白名单）。"""
        return AlgorithmInput(
            mixture=self.mixture.copy(), rate=self.rate, microphones=self.microphones.copy(),
            reference_channel=self.reference_channel,
            region=Region(self.region.center.copy(), self.region.radius, self.region.steering_height),
        )


def prepare_scenario(config, datasets, noise_config=None, speed=None):
    """准备固定场景：仿真 + 可选噪声注入，返回 ScenarioBundle。"""
    ensure_no_forbidden_fields()
    backend = config["backend"]
    noise_config = noise_config or NoiseConfig()
    region_cfg = config["region"]
    region = Region(
        center=np.asarray(region_cfg["center"], dtype=float),
        radius=float(region_cfg["radius"]),
        steering_height=float(region_cfg["steering_height"]),
    )
    options = config.get("das", {})
    speed = speed if speed is not None else options.get("sound_speed", 343.0)
    reference = config.get("reference_channel", 0)
    resolved = dict(config)
    noise_metadata = {}

    def validate_reference(mixture):
        if type(reference) is not int or not 0 <= reference < len(mixture):
            raise ValueError("参考麦克风须为所选通道内的有效整数索引")

    if backend == "recording":
        mixture, actual_rate = read_audio(config["input_wav"])
        rate = config["sample_rate"]
        if rate != actual_rate:
            raise ValueError("输入 WAV 与配置采样率不一致")
        microphones = np.asarray(config["microphones"], dtype=float)
        if microphones.shape != (len(mixture), 3):
            raise ValueError("麦克风坐标须与输入音频逐路对应")
        channels = select_channels(config, len(mixture))
        mixture, microphones = mixture[channels], microphones[channels]
        validate_reference(mixture)
        circle_members(np.empty((0, 3)), region.center, region.radius)
        target = interference = positions = noise_component = None
    else:
        mixture, components, microphones, positions, channels = prepare_simulation(config, datasets, speed)
        validate_reference(mixture)
        members = circle_members(positions, region.center, region.radius)
        if members.sum() != 1:
            raise ValueError("带参考场景要求区域内恰好一个声源")
        target = components[members, reference][0]
        interference = components[~members, reference].sum(axis=0)
        resolved["resolved_source_positions"] = positions.tolist()
        resolved["target_source_index"] = int(np.flatnonzero(members)[0])
        dataset_names = ("librispeech", backend) if backend in ("dechorate", "mcvampire") else ("librispeech",)
        resolved["dataset_paths"] = {name: str(Path(datasets[name]).resolve()) for name in dataset_names if name in datasets}
        if noise_config.enabled:
            # 噪声相对"参考通道目标"设定 SNR，作为干扰注入；参考保持独立混响目标。
            mixture, noise_component = inject_noise(
                mixture, target, config["sample_rate"], microphones,
                configure_noise(noise_config, datasets, backend, channels),
                reference_channel=reference, metadata=noise_metadata)
        else:
            noise_component = np.zeros_like(mixture)

    resolved.update(
        channels=channels, reference_channel=reference,
        resolved_microphones=microphones.tolist(),
        steering_point=region.steering_point.tolist(),
        noise={"enabled": noise_config.enabled, "seed": noise_config.seed,
               "kinds": list(noise_config.kinds), "snr_range_db": list(noise_config.snr_db), **noise_metadata},
    )
    return ScenarioBundle(
        mixture=mixture, rate=config["sample_rate"], microphones=microphones,
        reference_channel=reference, region=region, config=config,
        target=target, interference=interference, positions=positions,
        noise_component=noise_component, channels=channels, resolved=resolved,
    )


def apply_algorithm(bundle, name, *, effective_params=None, **params):
    """对固定输入运行一个已注册算法，返回 (单声道估计, 处理秒数)。"""
    plugin = registered_classes().get(name)
    if plugin and plugin.kind == "oracle":
        raise ValueError(f"Oracle is restricted to diagnostic runs: {name}")
    algorithm = get_algorithm(name, **params)
    if effective_params is not None:
        effective_params.update(params)
        effective_params.update(algorithm.parameters())
    public = bundle.public_input()
    started = perf_counter()
    estimate = algorithm.enhance(public)
    seconds = perf_counter() - started
    estimate = np.asarray(estimate, dtype=float)
    if estimate.shape != (bundle.mixture.shape[1],):
        raise ValueError(f"{name} 输出须为 [N] 单声道，实际 {estimate.shape}")
    if not np.isfinite(estimate).all():
        raise ValueError(f"{name} 输出含非有限值")
    return estimate, seconds


def evaluate(bundle, estimate, baseline, seconds):
    """按统一参考评分；无参考（录音模式）返回最小指标集。"""
    audio_seconds = bundle.mixture.shape[1] / bundle.rate
    if bundle.target is None:
        return {"reference_available": False, "processing_seconds": seconds,
                "rtf": seconds / audio_seconds}
    scores = evaluate_all(
        estimate=estimate, target=bundle.target, baseline=baseline,
        interference=bundle.interference, processing_seconds=seconds,
        audio_seconds=audio_seconds,
    )
    scores["reference_available"] = True
    scores["input_si_sdr_db"] = si_sdr(baseline, bundle.target)
    scores["si_sdr_reference"] = "isolated_target_at_reference_mic"
    return scores


def compare(config, datasets, algorithms, output_root=Path("runs"),
            noise_config=None, name=None):
    """准备一次场景，对多个算法做公平对比，返回结果目录与汇总。

    algorithms: 算法名列表（字符串）或 {名称: 参数字典}；identity 自动作为基线加入。
    """
    if isinstance(algorithms, str):
        algorithms = [algorithms]
    if isinstance(algorithms, dict):
        algorithm_params = dict(algorithms)
    else:
        algorithm_params = {name: {} for name in algorithms}
    algorithm_params.setdefault("identity", {})

    for algorithm_name in algorithm_params:
        plugin = registered_classes().get(algorithm_name)
        if plugin and plugin.kind == "oracle":
            raise ValueError(f"Oracle is restricted to diagnostic runs: {algorithm_name}")
    bundle = prepare_scenario(config, datasets, noise_config)
    effective_params = {name: {} for name in algorithm_params}
    baseline, baseline_seconds = apply_algorithm(bundle, "identity", effective_params=effective_params["identity"],
                                                 **algorithm_params["identity"])
    baseline_scores = evaluate(bundle, baseline, baseline, baseline_seconds)

    results = {"identity": {"scores": baseline_scores, "estimate": baseline}}
    for algorithm_name, params in algorithm_params.items():
        if algorithm_name == "identity":
            continue
        estimate, seconds = apply_algorithm(bundle, algorithm_name,
                                            effective_params=effective_params[algorithm_name], **params)
        results[algorithm_name] = {
            "scores": evaluate(bundle, estimate, baseline, seconds),
            "estimate": estimate,
        }

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:12]
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    if name is not None and (Path(name).name != name or name in ("", ".", "..")):
        raise ValueError("Invalid run directory name")
    directory = output_root / (name or run_id)
    summary = {}
    with TemporaryDirectory(prefix=".pending-", dir=output_root) as temporary:
        staged = Path(temporary) / "result"
        staged.mkdir()
        for algorithm_name, payload in results.items():
            scores = payload["scores"]
            summary[algorithm_name] = scores
            write_audio(staged / f"{algorithm_name}.wav", payload["estimate"][None], bundle.rate)
            (staged / f"{algorithm_name}.metrics.json").write_text(
                json.dumps(scores, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                encoding="utf-8")
        write_audio(staged / "mixture.wav", bundle.mixture, bundle.rate)
        write_audio(staged / "reference_mic.wav", baseline[None], bundle.rate)
        if bundle.target is not None:
            write_audio(staged / "target.wav", bundle.target[None], bundle.rate)
            write_audio(staged / "interference.wav", bundle.interference[None], bundle.rate)
            if bundle.noise_component is not None and bundle.noise_component.any():
                write_audio(staged / "noise.wav", bundle.noise_component, bundle.rate)

        manifest = {
            "run_id": run_id, "scenario": bundle.resolved,
            "algorithms": sorted(summary), "algorithm_parameters": effective_params, "runtime": runtime_metadata(),
            "summary": summary,
        }
        (staged / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8")
        directory.mkdir()
        try:
            staged.rename(directory)
        except OSError:
            directory.rmdir()
            raise
    return directory, summary


def summarize_runs(run_directories, algorithm, metric="si_sdr_db"):
    """跨场景汇总某算法某指标（均值±标准差），便于横向比较。"""
    values = []
    for directory in run_directories:
        path = Path(directory) / f"{algorithm}.metrics.json"
        if not path.exists():
            continue
        score = json.loads(path.read_text(encoding="utf-8")).get(metric)
        if score is not None:
            values.append(score)
    return aggregate(values)
