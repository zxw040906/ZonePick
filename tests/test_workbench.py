"""公平评测工作台：插件接口、指标、噪声、划分与对比的单元测试。"""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from zonepick.algorithms import (
    AlgorithmInput, Region, algorithm_names, ensure_no_forbidden_fields, get_algorithm,
    registered_classes,
)
from zonepick.algorithms.base import FORBIDDEN_FIELDS
from zonepick.evaluation.metrics import (
    aggregate, delta_si_sdr, evaluate_all, rtf, sd_sir_sar,
)
from zonepick.evaluation import si_sdr
from zonepick.workbench.compare import apply_algorithm, evaluate, prepare_scenario
from zonepick.workbench.noise import NoiseConfig, list_noise_files, noise_config_from_hint
from zonepick.web.server import load_scenario, parse_custom_scenario, scenario_summary
from zonepick.workbench.splits import (
    SplitConfig, SplitManifest, assert_no_test_leak, build_split,
)


class AlgorithmInterfaceTests(unittest.TestCase):
    def test_whitelist_has_no_truth_fields(self):
        ensure_no_forbidden_fields()  # 不应抛错
        fields = set(AlgorithmInput.__dataclass_fields__)
        self.assertFalse(FORBIDDEN_FIELDS.intersection(fields))

    def test_registry_has_traditional_algorithms_not_oracle(self):
        names = algorithm_names()
        self.assertIn("das", names)
        self.assertIn("identity", names)
        self.assertNotIn("oracle_target", names)  # oracle 不默认注册
        self.assertEqual(registered_classes()["das"].kind, "classical")

    def test_region_steering_point_is_deterministic(self):
        region = Region(center=np.array([1.0, 2.0]), radius=0.5, steering_height=1.6)
        np.testing.assert_allclose(region.steering_point, [1.0, 2.0, 1.6])

    def test_identity_and_das_plugins(self):
        rng = np.random.default_rng(0)
        mixture = rng.normal(size=(3, 400))
        inp = AlgorithmInput(
            mixture=mixture, rate=16000,
            microphones=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float),
            reference_channel=1,
            region=Region(np.array([1.0, 0.0]), 0.5, 1.5),
        )
        identity = get_algorithm("identity")
        np.testing.assert_allclose(identity.enhance(inp), mixture[1])
        das = get_algorithm("das", n_fft=128)
        output = das.enhance(inp)
        self.assertEqual(output.shape, (400,))
        self.assertTrue(np.isfinite(output).all())


class MvdrTests(unittest.TestCase):
    def _input(self, mixture, region, mics=None, reference=0):
        return AlgorithmInput(
            mixture=mixture, rate=16000,
            microphones=mics if mics is not None else np.array(
                [[0, 0, 0], [0.05, 0, 0], [0.10, 0, 0], [0.15, 0, 0]], dtype=float),
            reference_channel=reference, region=region,
        )

    def test_registered_as_classical(self):
        self.assertIn("mvdr", algorithm_names())
        self.assertEqual(registered_classes()["mvdr"].kind, "classical")

    def test_output_shape_finite_and_deterministic(self):
        rng = np.random.default_rng(11)
        mixture = rng.normal(size=(4, 4000))
        inp = self._input(mixture, Region(np.array([0.075, 2.0]), 0.5, 1.0))
        first = get_algorithm("mvdr", n_fft=256).enhance(inp)
        second = get_algorithm("mvdr", n_fft=256).enhance(inp)
        self.assertEqual(first.shape, (4000,))
        self.assertTrue(np.isfinite(first).all())
        np.testing.assert_allclose(first, second, rtol=0, atol=0)

    def test_steering_comes_from_region_not_truth(self):
        # 相同混合与阵列，只改区域 → 输出必须不同（证明由用户区域而非真值导向）。
        rng = np.random.default_rng(12)
        mixture = rng.normal(size=(4, 4000))
        a = get_algorithm("mvdr", n_fft=256).enhance(
            self._input(mixture, Region(np.array([0.075, 2.0]), 0.5, 1.0)))
        b = get_algorithm("mvdr", n_fft=256).enhance(
            self._input(mixture, Region(np.array([2.0, 0.0]), 0.5, 1.0)))
        self.assertGreater(float(np.max(np.abs(a - b))), 1e-6)

    def test_invalid_params_rejected(self):
        with self.assertRaises(ValueError):
            get_algorithm("mvdr", diagonal_load=-1)
        with self.assertRaises(ValueError):
            get_algorithm("mvdr", n_fft=101)  # 奇数 FFT 窗非法
        with self.assertRaises(ValueError):
            get_algorithm("mvdr", cov_estimate="bogus")

    def test_suppresses_directional_interference(self):
        # 4 元线阵：目标在正侧方(broadside)，干扰在端射(endfire)。
        # MVDR 应在目标保持不变的情况下陷零端射干扰，SI-SDR 高于未处理基线。
        from zonepick.simulation import convolve, free_field_rir, mix_sources
        rng = np.random.default_rng(13)
        n = 8000
        mics = np.array([[0, 0, 0], [0.05, 0, 0], [0.10, 0, 0], [0.15, 0, 0]], dtype=float)
        target_pos = np.array([0.075, 2.0, 1.0])
        interferer_pos = np.array([3.0, 0.0, 1.0])
        target = rng.normal(size=n)
        interference = 3.0 * rng.normal(size=n)
        rirs = [free_field_rir(p, mics, 16000, 343.0) for p in (target_pos, interferer_pos)]
        mixture, components = mix_sources([target, interference], rirs, [1.0, 1.0])
        target_ref = components[0, 0]  # 参考通道 0 的独立目标分量
        region = Region(np.array([0.075, 2.0]), 0.5, 1.0)
        inp = self._input(mixture, region, mics=mics)
        baseline = mixture[0]
        enhanced = get_algorithm("mvdr", n_fft=512).enhance(inp)
        self.assertGreater(si_sdr(enhanced, target_ref), si_sdr(baseline, target_ref))


class MetricsTests(unittest.TestCase):
    def test_si_sdr_perfect_and_delta(self):
        rng = np.random.default_rng(1)
        target = rng.normal(size=1000)
        perfect = target.copy()
        base = target + 0.5 * rng.normal(size=1000)
        # 完全相等时误差为 0，SI-SDR 定义上无有限值（返回 None）；加极小残差验证高值。
        near = target + 1e-8 * rng.normal(size=1000)
        self.assertGreater(si_sdr(near, target), 40)
        self.assertGreater(delta_si_sdr(near, target, base), 0)

    def test_sd_sir_sar_perfect(self):
        rng = np.random.default_rng(2)
        target = rng.normal(size=800)
        interference = rng.normal(size=800)
        estimate = target + 1e-8 * rng.normal(size=800)
        scores = sd_sir_sar(estimate, target, interference)
        self.assertGreater(scores["sdr_db"], 40)
        self.assertGreater(scores["sir_db"], 40)

    def test_rtf_and_aggregate(self):
        self.assertAlmostEqual(rtf(0.5, 2.0), 0.25)
        result = aggregate([1.0, 3.0, None])
        self.assertAlmostEqual(result["mean"], 2.0)
        self.assertEqual(result["count"], 2)

    def test_evaluate_all_keys(self):
        rng = np.random.default_rng(3)
        target = rng.normal(size=500)
        estimate = target + 0.1 * rng.normal(size=500)
        scores = evaluate_all(estimate, target, target + rng.normal(size=500),
                              rng.normal(size=500), 0.1, 500 / 16000)
        for key in ("si_sdr_db", "delta_si_sdr_db", "sdr_db", "sir_db", "sar_db", "rtf"):
            self.assertIn(key, scores)


class SplitTests(unittest.TestCase):
    def test_parameterized_group_disjoint_split(self):
        entries = [f"speaker{s}/session{i}.flac" for s in range(10) for i in range(5)]
        config = SplitConfig(train_ratio=0.6, val_ratio=0.2, test_ratio=0.2,
                             seed=7, strategy="group")
        manifest = build_split(entries, Path("/data"), config)
        train = set(manifest.paths_for("train"))
        test = set(manifest.paths_for("test"))
        self.assertTrue(train.isdisjoint(test))
        self.assertEqual(len(train) + len(manifest.paths_for("val")) + len(test), len(entries))
        self.assertGreater(len(train), 0)

    def test_manifest_roundtrip_and_leak_guard(self):
        entries = [f"spk{s}/a.flac" for s in range(6)]
        manifest = build_split(entries, Path("/data"), SplitConfig())
        with tempfile.TemporaryDirectory() as directory:
            path = manifest.write(Path(directory) / "manifest.json")
            restored = SplitManifest.read(path)
            self.assertEqual(manifest.splits, restored.splits)
        with self.assertRaises(AssertionError):
            assert_no_test_leak(manifest, manifest.paths_for("test"))

    def test_invalid_ratios_rejected(self):
        with self.assertRaises(ValueError):
            SplitConfig(train_ratio=0.9, val_ratio=0.2).validate()


class NoiseTests(unittest.TestCase):
    def test_disabled_noise_is_identity(self):
        rng = np.random.default_rng(4)
        mixture = rng.normal(size=(2, 128))
        target = mixture[0].copy()
        noisy, component = __import__(
            "zonepick.workbench.noise", fromlist=["inject_noise"]
        ).inject_noise(mixture, target, 16000,
                       np.array([[0, 0, 0], [1, 0, 0]], dtype=float),
                       NoiseConfig(enabled=False))
        np.testing.assert_allclose(noisy, mixture)
        self.assertFalse(component.any())


class CleanupTests(unittest.TestCase):
    def test_cleanup_only_owns_current_temporary_run(self):
        from zonepick.workbench.cleanup import temporary_run

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = root / "runs" / "compare" / "prior-run"
            history.mkdir(parents=True)
            cache = root / "__pycache__"
            cache.mkdir()
            (history / "result.json").write_text("{}")
            with temporary_run(root) as current:
                (current / "artifact").write_text("temporary")
                (current / "history-link").symlink_to(history, target_is_directory=True)
            self.assertFalse(current.exists())
            self.assertTrue((history / "result.json").is_file())
            self.assertTrue(cache.is_dir())

    def test_cleanup_rejects_symlinked_run_root_and_replaced_directory(self):
        from zonepick.workbench.cleanup import temporary_run

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside"
            outside.mkdir()
            (root / "project").mkdir()
            (root / "project" / "runs").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symbolic link"):
                with temporary_run(root / "project"):
                    self.fail("unexpected temporary directory")
            with temporary_run(root) as current:
                current.rename(current.with_suffix(".moved"))
                current.symlink_to(outside, target_is_directory=True)
            self.assertTrue(outside.is_dir())
            self.assertTrue(current.is_symlink())


class CompareTests(unittest.TestCase):
    def test_prepare_apply_evaluate_on_synthetic_scenario(self):
        # 用最小可复现配置验证编排：两声源、预设区域、不做噪声。
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            speech = directory / "spk"
            speech.mkdir()
            rng = np.random.default_rng(5)
            for name in ("a.flac", "b.flac"):
                import soundfile as sf
                sf.write(speech / name, rng.normal(size=4000), 16000)
            config = {
                "backend": "free_field", "sample_rate": 16000, "samples": 2000,
                "microphones": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                "sources": [
                    {"file": "a.flac", "position": [3, 0, 1.5], "gain": 1.0},
                    {"file": "b.flac", "position": [-3, 0, 1.5], "gain": 1.0},
                ],
                "region": {"center": [3, 0], "radius": 0.5, "steering_height": 1.5},
                "reference_channel": 0,
            }
            datasets = {"librispeech": speech}
            bundle = prepare_scenario(config, datasets)
            self.assertEqual(bundle.mixture.shape, (3, 2000))
            self.assertIsNotNone(bundle.target)
            base, seconds = apply_algorithm(bundle, "identity")
            scores = evaluate(bundle, base, base, seconds)
            self.assertTrue(scores["reference_available"])
            self.assertIn("si_sdr_db", scores)


class ScenarioFeatureTests(unittest.TestCase):
    def test_all_presets_have_chinese_labels(self):
        for name in ("free_field", "dechorate", "mcvampire", "car"):
            summary = scenario_summary(name, load_scenario(name))
            self.assertTrue(summary.get("label"), f"{name} 缺少中文标签")
            self.assertTrue(any("\u4e00" <= ch <= "\u9fff" for ch in summary["label"]),
                            f"{name} 的标签不是中文")

    def test_car_scenario_has_driving_noise_hint(self):
        summary = scenario_summary("car", load_scenario("car"))
        hint = summary.get("noise_hint")
        self.assertTrue(hint and hint.get("enabled"))
        self.assertIn("driving", hint["kinds"])
        self.assertEqual(hint["spatial"], "captured")

    def test_noise_config_from_hint(self):
        cfg = noise_config_from_hint({"enabled": True, "kinds": ["driving"],
                                      "snr_db": [5, 20], "spatial": "captured"})
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.kinds, ["driving"])
        self.assertEqual(cfg.snr_db, (5, 20))
        self.assertEqual(cfg.spatial, "captured")
        # 显式覆盖优先。
        self.assertFalse(noise_config_from_hint({"enabled": True}, override_enabled=False).enabled)

    def test_parse_custom_scenario_whitelist_and_validation(self):
        name, config = parse_custom_scenario({
            "name": "my_car_1", "base": "car",
            "config": {"label": "我的车内场景", "region": {"center": [0, 0], "radius": 0.4,
                                                     "steering_height": 0.7}},
        })
        self.assertEqual(name, "my_car_1")
        self.assertEqual(config["label"], "我的车内场景")
        self.assertEqual(config["region"]["radius"], 0.4)
        self.assertNotIn("target_source_index", config)  # 真值字段不得写入
        with self.assertRaises(ValueError):
            parse_custom_scenario({"name": "bad", "base": "car",
                                   "config": {"region": {"center": [0, 0], "radius": -1,
                                                         "steering_height": 0.7}}})


if __name__ == "__main__":
    unittest.main()
